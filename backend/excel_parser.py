"""Generic CBSL spreadsheet -> time-series extractor.

CBSL publishes dozens of differently laid-out Excel tables.  Instead of
hand-writing a parser for each one, this module detects the layout:

* **row layout**    – periods run down the rows (e.g. ``1986 | January``)
  and every numeric column becomes a series;
* **column layout** – periods run across a header row (e.g. ``2020 Q1``)
  and every labelled row becomes a series;
* **matrix layout** – months down the rows and years across the columns
  (e.g. tourism earnings), which is stitched into one monthly series.

Series with mixed frequencies (quarterly + annual columns) are split.
"""
from __future__ import annotations

import datetime as _dt
import re
from collections import OrderedDict
from pathlib import Path

from .periods import is_bare_month, parse_period, year_of

MAX_HEADER_ROWS = 8
_NA = {"", "-", "--", "...", "..", "n.a.", "na", "n/a", "nil", "x", "—", "–", "n.a", "*"}


# ---------------------------------------------------------------------------
# workbook loading
# ---------------------------------------------------------------------------
def _fill_merged(grid, ranges):
    for r0, r1, c0, c1 in ranges:  # inclusive-exclusive, zero based
        if r0 >= len(grid):
            continue
        v = grid[r0][c0] if c0 < len(grid[r0]) else None
        if v is None:
            continue
        for r in range(r0, min(r1, len(grid))):
            row = grid[r]
            for c in range(c0, min(c1, len(row))):
                if r == r0 and c == c0:
                    continue
                if row[c] is None:
                    row[c] = v


def load_workbook_grids(path: Path):
    """Yield ``(sheet_name, grid)`` with merged cells filled."""
    path = Path(path)
    if path.suffix.lower() == ".xls":
        import xlrd

        try:
            book = xlrd.open_workbook(str(path), formatting_info=True)
        except Exception:  # some files refuse formatting_info
            book = xlrd.open_workbook(str(path))
        for sh in book.sheets():
            if getattr(sh, "visibility", 0):
                continue
            grid = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_EMPTY or cell.ctype == xlrd.XL_CELL_BLANK:
                        v = None
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            v = xlrd.xldate_as_datetime(v, book.datemode)
                        except Exception:
                            v = None
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        v = None
                    row.append(v)
                grid.append(row)
            _fill_merged(grid, [(a, b, c, d) for a, b, c, d in getattr(sh, "merged_cells", [])])
            yield sh.name, _trim(grid)
        return

    import openpyxl
    import warnings

    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(str(path), data_only=True)
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        ranges = []
        for mr in ws.merged_cells.ranges:
            ranges.append((mr.min_row - 1, mr.max_row, mr.min_col - 1, mr.max_col))
        _fill_merged(grid, ranges)
        yield ws.title, _trim(grid)


def _trim(grid):
    grid = [list(r) for r in grid]
    for row in grid:
        for i, v in enumerate(row):
            if isinstance(v, str) and not v.strip():
                row[i] = None
    while grid and all(v is None for v in grid[-1]):
        grid.pop()
    width = 0
    for row in grid:
        for i in range(len(row) - 1, -1, -1):
            if row[i] is not None:
                width = max(width, i + 1)
                break
    return [r[:width] + [None] * (width - len(r[:width])) for r in grid]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def to_num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if f != f or abs(f) == float("inf") else f
    if isinstance(v, (_dt.date, _dt.datetime)):
        return None
    s = str(v).strip().replace(",", "").replace("\xa0", "")
    s = re.sub(r"(\s*\([a-zivx]{1,4}\))+$", "", s, flags=re.I)  # trailing footnote markers
    if s.lower() in _NA:
        return None
    if re.fullmatch(r"\(\s*-?\d+(\.\d+)?\s*\)", s):  # accounting negative
        s = "-" + s.strip("() ")
    try:
        return float(s)
    except ValueError:
        return None


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).replace("\n", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _is_label(v) -> bool:
    return isinstance(v, str) and to_num(v) is None and len(v.strip()) > 0


_UNIT_ONLY = re.compile(
    r"^\(?\s*(rs\.?|us\$|usd|lkr|sri lanka rupees|rupees)?\s*('?\s*(mn|million|bn|billion|000|thousand)s?)?\.?\s*\)?$|"
    r"^\(.*\)$|^(rs|us\$|usd)\.?\s*(mn|million|bn|billion)\.?$|^in\s+(usd|rs\.?|lkr)\b.*$",
    re.I,
)


def _despace(s: str) -> str:
    """'A S S E T S' -> 'Assets'."""
    return re.sub(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b", lambda m: m.group(0).replace(" ", "").title(), s)


def _clean_name(parts, drop=()):
    out = []
    drop_l = {d.lower() for d in drop}
    for p in parts:
        p = _text(p)
        p = re.sub(r"\s*\((?:[a-z]{1,2}|\d{1,2})\)\s*", " ", p)  # footnote refs
        p = re.sub(r"^table\s*[\d.]+\s*:?\s*", "", p, flags=re.I)
        p = _despace(re.sub(r"\s+", " ", p)).strip(" :-–")
        if not p or to_num(p) is not None or p.lower() in drop_l:
            continue
        if _UNIT_ONLY.match(p) and len(parts) > 1:
            continue
        if re.match(r"^\d+(\.\d+)+\s*($|\D)", p):  # "4.02" or "4.04 Interest Rates ..."
            continue
        if out and p.lower() == out[-1].lower():
            continue
        out.append(p)
    return " – ".join(out)


def _titles(grid):
    """Long text cells in the top rows – treated as table titles, not series names."""
    t = set()
    for row in grid[:3]:
        labs = [v for v in row if isinstance(v, str) and len(v.strip()) > 20]
        if labs and len(set(labs)) == 1:
            t.add(_text(labs[0]))
            t.add(_clean_name([labs[0]]))
    return t


# ---------------------------------------------------------------------------
# layout detection
# ---------------------------------------------------------------------------
def _row_periods(grid, w):
    """Periods for each row when the first ``w`` columns are labels."""
    ctx = None
    res = []
    for row in grid:
        lab = row[:w]
        per = None
        texts = []
        for v in lab:
            if isinstance(v, (_dt.datetime, _dt.date)):
                per = parse_period(v)
                break
            y = year_of(v) if not isinstance(v, str) or re.fullmatch(r"\s*\d{4}\s*", v or "") else None
            if y:
                ctx = y
                texts.append(str(y))
            elif isinstance(v, str):
                texts.append(v)
        if per is None and texts:
            joined = " ".join(texts)
            if len(joined) <= 40:
                per = parse_period(joined, ctx)
                if per and per[1] == "A":
                    ctx = int(per[0])
                elif per and per[1] in "QM":
                    ctx = int(per[0][:4])
        has_num = any(to_num(v) is not None for v in row[w:])
        res.append(per if (per and has_num) else None)
    return res


def detect_row_layout(grid):
    if not grid:
        return None
    best = None
    ncols = len(grid[0])
    for w in range(1, min(4, ncols - 1) + 1):
        pers = _row_periods(grid, w)
        n = sum(1 for p in pers if p)
        if best is None or n > best[0]:
            best = (n, w, pers)
    if not best or best[0] < 3:
        return None
    return best


def _header_periods(grid, r):
    """Parse period labels across row ``r`` (using rows above for years)."""
    row = grid[r]
    ctx = None
    out = {}
    for c, v in enumerate(row):
        if v is None:
            continue
        # year context from up to two rows above in the same column
        up = None
        for rr in (r - 1, r - 2):
            if rr >= 0 and c < len(grid[rr]):
                up = year_of(grid[rr][c]) or up
                if up:
                    break
        y = year_of(v)
        if y and up is None:
            ctx = y
        p = parse_period(v, up or ctx)
        if p is None and up and isinstance(v, str):
            p = parse_period(f"{up} {v}")
        if p:
            out[c] = p
            if p[1] in "QM":
                ctx = int(p[0][:4])
    return out


def detect_header_rows(grid):
    """Return {row_index: {col: period}} for rows that look like period headers."""
    heads = {}
    for r in range(len(grid)):
        hp = _header_periods(grid, r)
        if len(hp) < 3:
            continue
        # must be followed by numeric data in those columns
        cols = list(hp)
        nums = 0
        for rr in range(r + 1, min(r + 12, len(grid))):
            nums += sum(1 for c in cols if to_num(grid[rr][c]) is not None)
        # header cells themselves should not be mostly plain data
        if nums >= len(cols):
            heads[r] = hp
    return heads


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------
class _Acc:
    """Accumulates (name -> freq -> {date: value})."""

    def __init__(self):
        self.series: "OrderedDict[str, dict]" = OrderedDict()

    def add(self, name, per, val):
        if val is None or per is None or not name:
            return
        key, freq = per
        d = self.series.setdefault(name, {}).setdefault(freq, {})
        d.setdefault(key, val)


def _header_names(grid, top, bottom, ncols, first_col):
    """Build column names from header rows [top, bottom)."""
    rows = [grid[r] for r in range(top, bottom)]
    # forward-fill upper header rows to the right when a sub-header exists
    filled = [list(r) for r in rows]
    for i in range(len(filled) - 1):
        last = None
        for c in range(first_col, ncols):
            v = filled[i][c]
            has_below = any(filled[j][c] is not None for j in range(i + 1, len(filled)))
            if v is not None and not isinstance(v, (int, float)):
                last = v
            elif v is None and last is not None and has_below:
                filled[i][c] = last
            else:
                last = None if v is not None else last
    names = {}
    titles = _titles(grid)
    for c in range(first_col, ncols):
        parts = [r[c] for r in filled if isinstance(r[c], str)]
        names[c] = _clean_name(parts, titles)
    return names


def _extract_rows(grid, w, pers, acc, prefix=""):
    ncols = len(grid[0])
    data_rows = [i for i, p in enumerate(pers) if p]
    if not data_rows:
        return
    # group data rows into blocks separated by >4 non-data rows
    blocks, cur = [], [data_rows[0]]
    for i in data_rows[1:]:
        if i - cur[-1] > 4:
            blocks.append(cur)
            cur = [i]
        else:
            cur.append(i)
    blocks.append(cur)
    prev_end = -1
    for bi, blk in enumerate(blocks):
        top = max(prev_end + 1, blk[0] - MAX_HEADER_ROWS)
        names = _header_names(grid, top, blk[0], ncols, w)
        block_title = ""
        if len(blocks) > 1:
            for r in range(blk[0] - 1, top - 1, -1):
                labs = [v for v in grid[r][:w + 1] if _is_label(v)]
                if labs and all(grid[r][c] is None for c in range(w + 1, ncols)):
                    block_title = _clean_name([labs[0]], _titles(grid))
                    break
        used = {}
        for c in range(w, ncols):
            nm = names.get(c) or f"Column {c - w + 1}"
            if block_title:
                nm = f"{block_title} – {nm}"
            if prefix:
                nm = f"{prefix} – {nm}"
            used[nm] = used.get(nm, 0) + 1
            if used[nm] > 1:
                nm = f"{nm} ({used[nm]})"
            for r in blk:
                acc.add(nm, pers[r], to_num(grid[r][c]))
        prev_end = blk[-1]


def _extract_columns(grid, heads, acc, prefix=""):
    ncols = len(grid[0])
    hrows = sorted(heads)
    for hi, hr in enumerate(hrows):
        end = hrows[hi + 1] if hi + 1 < len(hrows) else len(grid)
        hp = heads[hr]
        first_pc = min(hp)
        all_a = all(p[1] == "A" for p in hp.values())
        section = ""
        seen = {}
        # matrix layout? (bare months as row labels under year columns)
        matrix = _is_matrix(grid, hr, end, hp)
        mat_name = None
        if not prefix:
            first = next((v for row in grid[:hr] for v in row if _is_label(v)), "")
            prefix_m = _clean_name([first])
        else:
            prefix_m = prefix
        for r in range(hr + 1, end):
            row = grid[r]
            labs = [v for v in row[:first_pc] if _is_label(v)]
            nums = [c for c in hp if to_num(row[c]) is not None]
            if matrix:
                mon = next((is_bare_month(v) for v in row[:first_pc] if is_bare_month(v)), None)
                if mon and nums:
                    nm = mat_name or _clean_name([prefix_m, section]) or prefix_m or "Value"
                    mat_name = nm
                    for c in nums:
                        y = int(hp[c][0])
                        acc.add(nm, (f"{y:04d}-{mon:02d}", "M"), to_num(row[c]))
                elif labs and not nums:
                    section = _text(labs[-1])
                    mat_name = None
                elif labs and nums:  # e.g. a "Total" row -> annual series
                    nm = _clean_name([prefix_m, section, labs[-1]])
                    for c in nums:
                        acc.add(nm, hp[c], to_num(row[c]))
                continue
            if not labs:
                continue
            label = _clean_name(labs[-2:] if len(labs) > 1 and len(_text(labs[-1])) < 4 else labs[-1:])
            if not nums:
                section = label
                continue
            nm = label
            key = nm.lower()
            if key in seen and section:
                nm = f"{section} – {label}"
            if nm.lower() in seen:
                seen[nm.lower()] += 1
                nm = f"{nm} ({seen[nm.lower()]})"
            seen[nm.lower()] = seen.get(nm.lower(), 1)
            seen.setdefault(key, 1)
            full = f"{prefix} – {nm}" if prefix else nm
            sub_r = hr + 1 if hr + 1 < end else None
            sub_cols = (
                {c: _text(grid[sub_r][c]) for c in hp
                 if grid[sub_r][c] is not None and _is_label(grid[sub_r][c])}
                if sub_r is not None else {}
            )
            use_sub = len(set(hp.values())) < len(hp) and len(sub_cols) >= len(hp) // 2
            for c in nums:
                s_name = f"{full} – {sub_cols[c]}" if (use_sub and c in sub_cols) else full
                acc.add(s_name, hp[c], to_num(row[c]))


_FREQ_NAME = {"A": "Annual", "Q": "Quarterly", "M": "Monthly", "D": "Daily"}


def _normalise_daily(points):
    """Daily points that are really month/quarter/year ends -> coarser freq."""
    keys = sorted(points)
    if len(keys) < 3:
        return points, "D"
    ds = [_dt.date.fromisoformat(k) for k in keys]
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    med = gaps[len(gaps) // 2]
    if 27 <= med <= 32:
        return {f"{d.year:04d}-{d.month:02d}": points[k] for k, d in zip(keys, ds)}, "M"
    if 85 <= med <= 95:
        return {f"{d.year:04d}-{((d.month - 1) // 3) * 3 + 1:02d}": points[k] for k, d in zip(keys, ds)}, "Q"
    if 360 <= med <= 370:
        return {f"{d.year}": points[k] for k, d in zip(keys, ds)}, "A"
    return points, "D"


def _is_matrix(grid, hr, end, hp):
    if not all(p[1] == "A" for p in hp.values()):
        return False
    first_pc = min(hp)
    month_rows = [r for r in range(hr + 1, min(end, hr + 20))
                  if any(is_bare_month(v) for v in grid[r][:first_pc])]
    return len(month_rows) >= 6


def _parse_rdt_archive(path: Path):
    """Parse Reserve Data Template archive where each sheet is one month."""
    import xml.etree.ElementTree as ET
    import zipfile

    z = zipfile.ZipFile(str(path))
    ss = ["".join(si.itertext()) for si in ET.fromstring(z.read("xl/sharedStrings.xml")) if si.tag.endswith("}si")]
    rels = {
        el.attrib["Id"]: "xl/" + el.attrib["Target"]
        for el in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        if "worksheet" in el.attrib.get("Type", "")
    }
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    items = [
        ("Official Reserve Assets", r"official\s+reserve\s+assets"),
        ("Foreign Currency Reserves", r"foreign\s+currency\s+reserves"),
        ("Securities", r"\(a\)\s*securities"),
        ("Total Currency and Deposits", r"total\s+currency\s+and\s+deposits"),
        ("IMF Reserve Position", r"(?:imf\s+reserve\s+position|reserve\s+position\s+in\s+the\s+imf)"),
        ("SDRs", r"\bsdrs\b"),
        ("Gold Reserves", r"\bgold\b"),
        ("Other Reserve Assets", r"other\s+reserve\s+assets"),
    ]
    series = {name: {} for name, _ in items}
    for el in wb.iter():
        if not el.tag.endswith("sheet"):
            continue
        per = parse_period(el.attrib.get("name", ""))
        if not per or per[1] != "M":
            continue
        rid = next((v for k, v in el.attrib.items() if k.endswith("id")), None)
        if not rid or rid not in rels:
            continue
        root = ET.fromstring(z.read(rels[rid]))
        for row in root.iter():
            if not row.tag.endswith("}row") or int(row.attrib.get("r", 0)) > 26:
                continue
            vals = []
            for c in row:
                v = next((x.text for x in c if x.tag.endswith("}v")), None)
                if v is not None:
                    vals.append(ss[int(v)].strip() if c.attrib.get("t") == "s" else v)
            if len(vals) < 2:
                continue
            num = to_num(vals[-1])
            if num is None:
                continue
            lab = vals[0].replace("\xa0", " ")
            for name, pat in items:
                if per[0] not in series[name] and re.search(pat, lab, re.I):
                    series[name][per[0]] = num
                    break
    return [
        {"name": name, "freq": "M", "sheet": "RDT", "data": sorted(pts.items())}
        for name, pts in series.items() if len(pts) >= 3
    ]


def _extract_stacked_years(grid, acc):
    """Handle tables like PGDP where year headers sit in col 0 above sector rows."""
    ncols = len(grid[0])
    col_names = {}
    for r in range(min(5, len(grid))):
        labs = {c: _clean_name([grid[r][c]]) for c in range(1, ncols) if _is_label(grid[r][c])}
        if len(labs) >= 3:
            col_names = labs
            break
    if not col_names:
        return
    cur_year = None
    for row in grid:
        y = year_of(row[0])
        if y and all(to_num(v) is None for v in row[1:]):
            cur_year = y
            continue
        if cur_year and _is_label(row[0]):
            rname = _clean_name([row[0]])
            for c, cname in col_names.items():
                if c < len(row) and to_num(row[c]) is not None:
                    acc.add(f"{cname} – {rname}", (f"{cur_year}", "A"), to_num(row[c]))
def _sheet_prefix(sheet: str, multi: bool) -> str:
    if not multi or re.fullmatch(r"(sheet|table)\s*\d*", sheet.strip(), re.I):
        return ""
    s = re.sub(r"^\s*\d+(\.\d+)*\s*", "", sheet).strip(" -–")
    return s


def parse_workbook(path: Path):
    """Return a list of series dicts ``{name, freq, sheet, data}``."""
    out = []
    try:
        sheets = list(load_workbook_grids(path))
    except Exception:
        return _parse_rdt_archive(path)
    multi = len(sheets) > 1
    max_year = _dt.date.today().year + 1
    for sheet, grid in sheets:
        if len(grid) < 3 or not grid[0]:
            continue
        if re.search(r"hs\s*code|index page|contents|notes?$", sheet, re.I):
            continue
        prefix = _sheet_prefix(sheet, multi)
        acc = _Acc()
        row_layout = detect_row_layout(grid)
        heads = detect_header_rows(grid)
        n_row = row_layout[0] if row_layout else 0
        n_col = max((len(h) for h in heads.values()), default=0)
        has_matrix = any(_is_matrix(grid, hr, len(grid), hp) for hr, hp in heads.items())
        if row_layout and n_row >= n_col and not has_matrix:
            _extract_rows(grid, row_layout[1], row_layout[2], acc, prefix)
        elif heads:
            _extract_columns(grid, heads, acc, prefix)
        else:
            _extract_stacked_years(grid, acc)
        for name, by_freq in acc.series.items():
            merged: dict[str, dict] = {}
            for freq, pts in by_freq.items():
                if freq == "D":
                    pts, freq = _normalise_daily(pts)
                tgt = merged.setdefault(freq, {})
                for k, v in pts.items():
                    if v is not None:
                        tgt[k] = v
            for freq, pts in list(merged.items()):
                if any(int(k[:4]) > max_year for k in pts):
                    merged.pop(freq)
                    continue
                vals = list(pts.values())
                if len(vals) < 3 or all(v == 0 for v in vals):
                    merged.pop(freq)
            for freq, pts in merged.items():
                nm = name if len(merged) == 1 else f"{name} ({_FREQ_NAME[freq]})"
                out.append({"name": nm, "freq": freq, "sheet": sheet, "data": sorted(pts.items())})
    # make names unique inside the workbook
    seen = {}
    for s in out:
        k = s["name"].lower()
        if k in seen:
            seen[k] += 1
            s["name"] = f"{s['name']} [{seen[k]}]"
        else:
            seen[k] = 1
    return out


def table_unit(path: Path) -> str:
    """Best-effort unit string from the top rows of the first sheet."""
    pat = re.compile(r"(rs\.?\s*(mn|million|bn|billion)|us\$|usd|lkr|rupees|per\s*cent|percent|%|index|million|billion|\bmn\b|\bbn\b|metric|tonnes|kg|number)", re.I)
    try:
        sheet, grid = next(iter(load_workbook_grids(path)))
    except Exception:
        return "USD Mn" if "2.15" in str(path) else ""
    for row in grid[:8]:
        for v in row:
            if isinstance(v, str) and len(v) < 90 and pat.search(v) and ("(" in v or len(v) < 40):
                m = re.search(r"\(([^()]*" + pat.pattern + r"[^()]*)\)", v, re.I)
                return _text(m.group(1) if m else v)
    return ""
