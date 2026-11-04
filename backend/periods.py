"""Parse the many period/date label styles used in CBSL spreadsheets.

Every parser returns a tuple ``(key, freq)`` where ``freq`` is one of
``A`` (annual), ``Q`` (quarterly), ``M`` (monthly) or ``D`` (daily) and
``key`` is a sortable ISO-like string that Plotly understands as a date:

* annual    -> ``"2024"``
* quarterly -> ``"2024-04"`` (first month of the quarter)
* monthly   -> ``"2024-05"``
* daily     -> ``"2024-05-17"``
"""
from __future__ import annotations

import datetime as _dt
import re

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\b"
)
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_YEAR4 = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")

# words that may appear around a period label without changing its meaning
_FILLER = {
    "", "end", "of", "the", "month", "year", "as", "at", "p", "r", "e", "f",
    "provisional", "revised", "estimate", "est", "prov", "ended", "week",
    "total", "annual", "-", "to", "date", "cal", "calendar", "and", "for",
    "period", "averages", "average", "avg", "upto", "up", "q", "qtr", "st",
    "nd", "rd", "th", "quarter", "in",
}


def _clean(text: str) -> str:
    s = str(text).replace("\n", " ").replace("\xa0", " ")
    s = _PAREN.sub(" ", s)
    s = s.replace("*", " ").replace("’", "'").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def year_of(value) -> int | None:
    """Return a year if the cell clearly holds a year, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.year
    if isinstance(value, (int, float)):
        if float(value).is_integer() and 1950 <= value <= 2100:
            return int(value)
        return None
    s = _clean(value)
    m = re.fullmatch(r"(?:end\s*(?:of\s*)?)?(19[5-9]\d|20\d\d)(?:\s*(?:annual|year|total|p|r|e))?", s)
    return int(m.group(1)) if m else None


def _leftover_ok(s: str) -> bool:
    words = re.split(r"[\s\-/,.']+", s)
    return all(w in _FILLER for w in words)


def _q(year: int, q: int) -> tuple[str, str]:
    return f"{year:04d}-{(q - 1) * 3 + 1:02d}", "Q"


def parse_period(value, ctx_year: int | None = None):
    """Parse a period label. ``ctx_year`` supplies the year when the label
    only carries a month or quarter (e.g. ``"February"`` under ``1986``)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, _dt.datetime):
        if 1950 <= value.year <= 2100:
            return value.strftime("%Y-%m-%d"), "D"
        return None
    if isinstance(value, _dt.date):
        return value.isoformat(), "D"
    if isinstance(value, (int, float)):
        y = year_of(value)
        return (f"{y}", "A") if y else None

    s = _clean(value)
    if not s or len(s) > 40:
        return None

    # --- ISO / numeric dates -------------------------------------------
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s.*)?", s)
    if m:
        try:
            return _dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat(), "D"
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        try:
            return _dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat(), "D"
        except ValueError:
            return None
    m = re.search(r"(?:^|\bending\s+)(\d{1,2})(?:st|nd|rd|th)?[-\s]+([a-z]{3,9})\.?[-\s,]*(\d{2}|\d{4})$", s)
    if m and m[2] in MONTHS:
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        try:
            return _dt.date(y, MONTHS[m[2]], int(m[1])).isoformat(), "D"
        except ValueError:
            return None

    # fiscal-year style 2023/24 -> skip (ambiguous)
    if re.fullmatch(r"\d{4}\s*/\s*\d{2,4}", s):
        return None

    # --- quarters --------------------------------------------------------
    pats = [
        (r"(\d{4})\s*[-,]?\s*(?:q|quarter|qtr)\.?\s*([1-4])\b", 1, 2),
        (r"(\d{4})\s*[-,]?\s*([1-4])\s*(?:st|nd|rd|th)?\s*(?:q|qtr|quarter)\b", 1, 2),
        (r"\b(?:q|qtr)\.?\s*([1-4])\s*[-,']?\s*(\d{4}|\d{2})\b", 2, 1),
        (r"\b([1-4])\s*(?:st|nd|rd|th)?\s*(?:q|qtr|quarter)\.?\s*[-,']?\s*(\d{4})\b", 2, 1),
        (r"\bquarter\s*([1-4])\s*[-,']?\s*(\d{4})\b", 2, 1),
    ]
    for pat, yi, qi in pats:
        m = re.search(pat, s)
        if m:
            y = m.group(yi)
            y = int(y) + (2000 if len(y) == 2 else 0)
            rest = s[: m.start()] + " " + s[m.end():]
            if _leftover_ok(rest.strip()):
                return _q(y, int(m.group(qi)))
    m = re.fullmatch(r"(?:q|qtr)\.?\s*([1-4])|([1-4])\s*(?:st|nd|rd|th)?\s*(?:q|qtr|quarter)|quarter\s*([1-4])", s)
    if m and ctx_year:
        q = int(next(g for g in m.groups() if g))
        return _q(ctx_year, q)

    # --- months ----------------------------------------------------------
    m = _MONTH_RE.search(s)
    if m:
        mon = MONTHS[m.group(1).rstrip(".")]
        rest = s[: m.start()] + " " + s[m.end():]
        y = None
        ym = _YEAR4.search(rest)
        if ym:
            y = int(ym.group(1))
            rest = rest[: ym.start()] + " " + rest[ym.end():]
        else:
            y2 = re.search(r"(?:^|[\s\-'/])(\d{2})\s*$", rest)
            if y2:
                y = 2000 + int(y2.group(1)) if int(y2.group(1)) < 60 else 1900 + int(y2.group(1))
                rest = rest[: y2.start()]
        if y is None:
            y = ctx_year
        if y and _leftover_ok(rest.strip()):
            return f"{y:04d}-{mon:02d}", "M"
        return None

    # --- years -----------------------------------------------------------
    y = year_of(s)
    if y:
        return f"{y}", "A"
    m = _YEAR4.search(s)
    if m and _leftover_ok((s[: m.start()] + " " + s[m.end():]).strip()):
        return f"{int(m.group(1))}", "A"
    return None


def is_bare_month(value) -> int | None:
    """Month number if the label is only a month name (no year)."""
    if not isinstance(value, str):
        return None
    s = _clean(value)
    m = _MONTH_RE.fullmatch(s)
    return MONTHS[m.group(1).rstrip(".")] if m else None

