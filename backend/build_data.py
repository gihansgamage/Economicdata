"""Build pre-compiled JSON data bundles and summary highlights for the dashboard.

Creates:
* ``data/summary.json``   – KPI cards, ticker items, sidebar sparklines, catalog metadata
* ``data/cbsl_data.json`` – All 79 CBSL statistical tables & 3,000+ Sri Lanka series
* ``data/imf_data.json``  – All 43 IMF global indicators across 230+ countries & groups
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .cbsl_scraper import build_cbsl_dataset, refresh_cbsl_cache
from .imf_client import build_imf_dataset, fetch_imf_cache


def _find_series(tables: list[dict], table_prefix: str, name_substr: str, freq: str | None = None):
    for t in tables:
        if table_prefix.lower() in t["id"].lower() or table_prefix.lower() in t["file"].lower():
            for s in t["series"]:
                if freq and s["freq"] != freq:
                    continue
                if name_substr.lower() in s["name"].lower():
                    return t, s
    return None, None


def _build_highlights(cbsl: dict, imf: dict) -> dict:
    """Create curated KPI cards, sidebar series, and ticker items for both modes."""
    tables = cbsl["tables"]
    widgets = cbsl.get("widgets", {})

    # --- Helper to grab last, prev, delta, period, sparkline ---
    def _card(title, subtitle, unit, pts, source, color="#0b63b8", is_pct=False, decimals=2):
        if not pts:
            return None
        pts_recent = pts[-24:]
        last_p, last_v = pts[-1]
        prev_p, prev_v = pts[-2] if len(pts) > 1 else (last_p, last_v)
        diff = last_v - prev_v if (last_v is not None and prev_v is not None) else 0.0
        pct = (diff / abs(prev_v) * 100.0) if prev_v else 0.0
        return {
            "title": title,
            "subtitle": subtitle,
            "unit": unit,
            "period": last_p,
            "prev_period": prev_p,
            "value": round(last_v, decimals),
            "prev": round(prev_v, decimals),
            "change": round(diff, decimals),
            "change_pct": round(pct, 2),
            "is_pct": is_pct,
            "decimals": decimals,
            "color": color,
            "source": source,
            "sparkline": [[p, round(v, decimals)] for p, v in pts_recent],
        }

    lk_kpis = []

    # 1. Colombo CPI Inflation YoY
    _, s_ccpi = _find_series(tables, "ccpi", "Year-on-Year % Change – CCPI", "M")
    if s_ccpi:
        lk_kpis.append(_card(
            "Colombo CPI Inflation (YoY)",
            "CCPI Headline (2021=100)",
            "%",
            s_ccpi["data"],
            "CBSL / DCS",
            "#0b63b8",
            is_pct=True,
            decimals=1,
        ))

    # 2. National CPI Inflation YoY
    _, s_ncpi = _find_series(tables, "ncpi", "Year-on-Year % Change – NCPI", "M")
    if s_ncpi:
        lk_kpis.append(_card(
            "National CPI Inflation (YoY)",
            "NCPI Headline (2021=100)",
            "%",
            s_ncpi["data"],
            "CBSL / DCS",
            "#0b63b8",
            is_pct=True,
            decimals=1,
        ))

    # 3. Quarterly Real GDP Growth
    _, s_gdpq = _find_series(tables, "cbsl_quarterly_gdp_growth", "Real GDP Growth", "Q")
    if s_gdpq:
        lk_kpis.append(_card(
            "Real GDP Growth (Quarterly)",
            "Year-on-Year % Change",
            "%",
            s_gdpq["data"],
            "CBSL / DCS",
            "#2e9a14",
            is_pct=True,
            decimals=1,
        ))

    # 4. Overnight Policy Rate / SDFR
    _, s_opr = _find_series(tables, "table4_04", "Overnight Policy Rate", "M")
    if s_opr:
        lk_kpis.append(_card(
            "Overnight Policy Rate (OPR)",
            "Monetary Policy Rate",
            "%",
            s_opr["data"],
            "CBSL",
            "#0b63b8",
            is_pct=True,
            decimals=2,
        ))

    # 5. USD / LKR Exchange Rate (Monthly Average or Daily Selling)
    _, s_usd_d = _find_series(tables, "if_buying_selling", "United States – Selling – USD", "D")
    _, s_usd_m = _find_series(tables, "if_monthly_average", "USD", "M")
    if s_usd_d:
        lk_kpis.append(_card(
            "USD / LKR (TT Selling)",
            "Commercial Banks Daily Rate",
            "LKR",
            s_usd_d["data"][-60:],
            "CBSL",
            "#0b63b8",
            decimals=2,
        ))
    elif s_usd_m:
        lk_kpis.append(_card(
            "USD / LKR Exchange Rate",
            "Monthly Average Spot Rate",
            "LKR",
            s_usd_m["data"],
            "CBSL",
            "#0b63b8",
            decimals=2,
        ))

    # 6. Official Reserve Assets
    _, s_res = _find_series(tables, "table2_15_2", "Official Reserve Assets", "M")
    if s_res:
        lk_kpis.append(_card(
            "Gross Official Reserves",
            "Total Reserve Assets",
            "USD Mn",
            s_res["data"],
            "CBSL",
            "#2e9a14",
            decimals=0,
        ))

    # 7. Workers' Remittances (Monthly)
    _, s_rem = _find_series(tables, "table2_14_2", "Workers' Remittances", "M")
    if s_rem:
        lk_kpis.append(_card(
            "Workers' Remittances",
            "Monthly Inflows",
            "USD Mn",
            s_rem["data"],
            "CBSL",
            "#2e9a14",
            decimals=1,
        ))

    # 8. Earnings from Tourism (Monthly)
    _, s_tour = _find_series(tables, "table2_14_1", "Earnings from Tourism", "M")
    if s_tour:
        lk_kpis.append(_card(
            "Tourism Earnings",
            "Monthly Foreign Exchange Inflows",
            "USD Mn",
            s_tour["data"],
            "CBSL / SLTDA",
            "#0b63b8",
            decimals=1,
        ))

    # 9. Merchandise Exports (Monthly USD)
    _, s_exp = _find_series(tables, "table2_02", "In USD 2007-2026 – Total exports", "M")
    if s_exp:
        lk_kpis.append(_card(
            "Merchandise Exports",
            "Monthly Total Exports",
            "USD Mn",
            s_exp["data"],
            "CBSL / Customs",
            "#2e9a14",
            decimals=1,
        ))

    # 10. Merchandise Imports (Monthly USD)
    _, s_imp = _find_series(tables, "table2_04", "In USD 2007-2026 – Total imports", "M")
    if s_imp:
        lk_kpis.append(_card(
            "Merchandise Imports",
            "Monthly Total Imports",
            "USD Mn",
            s_imp["data"],
            "CBSL / Customs",
            "#d97706",
            decimals=1,
        ))

    # --- Global KPIs from IMF WEO ---
    imf_by_id = {ind["id"]: ind for ind in imf["indicators"]}
    cur_year = str(_dt.date.today().year)

    def _imf_series_upto(code: str, entity: str, max_yr: str = cur_year):
        ind = imf_by_id.get(code)
        if not ind:
            return []
        vals = ind["values"]
        pts = vals.get(entity, [])
        if not pts and entity == "WEOWORLD":
            for fallback in ("WEOWORLD", "FAD_WORLD", "FADGDWORLD", "BOPWORLD", "CFWORLD", "ARAWORLD"):
                if vals.get(fallback):
                    pts = vals[fallback]
                    break
        filtered = [p for p in pts if p[0] <= max_yr]
        return filtered or pts

    wd_kpis = []
    for code, ent, title, sub, unit, col, is_p, dec in [
        ("NGDP_RPCH", "WEOWORLD", "World Real GDP Growth", "Global Aggregate", "%", "#2e9a14", True, 1),
        ("PCPIPCH", "WEOWORLD", "Global Headline Inflation", "World Average Consumer Prices", "%", "#0b63b8", True, 1),
        ("NGDP_RPCH", "ADVEC", "Advanced Economies Growth", "Real GDP YoY Change", "%", "#0b63b8", True, 1),
        ("NGDP_RPCH", "OEMDC", "Emerging & Developing Growth", "Real GDP YoY Change", "%", "#2e9a14", True, 1),
        ("NGDP_RPCH", "DA", "Developing Asia GDP Growth", "Real GDP YoY Change", "%", "#2e9a14", True, 1),
        ("GGXWDG_NGDP", "WEOWORLD", "Global General Govt Debt", "Share of World GDP", "% of GDP", "#d97706", True, 1),
        ("NGDP_RPCH", "LKA", "Sri Lanka Real GDP Growth", "Annual % Change", "%", "#0b63b8", True, 1),
        ("PCPIPCH", "LKA", "Sri Lanka Inflation Rate", "Annual Average CPI Change", "%", "#0b63b8", True, 1),
        ("GGXWDG_NGDP", "LKA", "Sri Lanka Gross Govt Debt", "Share of GDP", "% of GDP", "#d97706", True, 1),
        ("BCA_NGDPD", "LKA", "Sri Lanka Current Account", "Percent of GDP", "% of GDP", "#2e9a14", True, 1),
    ]:
        pts = _imf_series_upto(code, ent)
        if pts:
            wd_kpis.append(_card(title, sub, unit, pts, "IMF WEO (Oct 2026)", col, is_pct=is_p, decimals=dec))

    # --- Sidebar cards (matching the XML template's #g-fx, #g-sl, #g-gl) ---
    usd_buy = _find_series(tables, "if_buying_selling", "United States – Buying – USD", "D")[1]
    usd_sell = _find_series(tables, "if_buying_selling", "United States – Selling – USD", "D")[1]
    sidebar = {
        "fx_daily": {
            "buying": usd_buy["data"][-30:] if usd_buy else [],
            "selling": usd_sell["data"][-30:] if usd_sell else [],
            "monthly_usd": s_usd_m["data"][-36:] if s_usd_m else [],
        },
        "sl_inflation": s_ccpi["data"][-14:] if s_ccpi else [],
        "sl_ncpi": s_ncpi["data"][-14:] if s_ncpi else [],
        "sl_gdp_q": s_gdpq["data"][-14:] if s_gdpq else [],
        "gl_inflation": _imf_series_upto("PCPIPCH", "WEOWORLD", "2028")[-14:],
        "gl_gdp": _imf_series_upto("NGDP_RPCH", "WEOWORLD", "2028")[-14:],
        "cbsl_live_si": widgets.get("live_window_si", {}),
    }

    # --- Live ticker items ---
    ticker_lk = []
    for k in lk_kpis:
        if not k:
            continue
        arrow = "▲" if k["change"] >= 0 else "▼"
        val_s = f"{k['value']:.{k['decimals']}f}{k['unit'] if k['is_pct'] else ' ' + k['unit']}"
        ticker_lk.append({
            "label": k["title"],
            "value": val_s.strip(),
            "change": f"{arrow} {abs(k['change']):.{k['decimals']}f} ({k['period']})",
            "up": k["change"] >= 0,
        })

    ticker_wd = []
    for k in wd_kpis:
        if not k:
            continue
        arrow = "▲" if k["change"] >= 0 else "▼"
        val_s = f"{k['value']:.{k['decimals']}f}{k['unit'] if k['unit'] == '%' else ' ' + k['unit']}"
        ticker_wd.append({
            "label": k["title"],
            "value": val_s.strip(),
            "change": f"{arrow} {abs(k['change']):.{k['decimals']}f} ({k['period']})",
            "up": k["change"] >= 0,
        })

    return {
        "lk_kpis": [k for k in lk_kpis if k],
        "wd_kpis": [k for k in wd_kpis if k],
        "sidebar": sidebar,
        "ticker_lk": ticker_lk,
        "ticker_wd": ticker_wd,
    }


def _downsample_long_daily(cbsl: dict, max_daily_points: int = 1500):
    """Keep full daily history for the last ~6 years + weekly prior so JSON stays fast on GitHub Pages."""
    for t in cbsl["tables"]:
        for s in t["series"]:
            if s["freq"] == "D" and len(s["data"]) > max_daily_points:
                pts = s["data"]
                recent = pts[-1000:]  # ~4 years of every single trading day
                older = pts[:-1000:5]  # weekly before that
                s["data"] = older + recent
                s["count"] = len(s["data"])


def build_all_data(root_dir: Path, refresh_remote: bool = False) -> dict:
    """Build all JSON files under ``root_dir / 'data'`` and return summary stats."""
    cache_root = root_dir / "cache"
    data_dir = root_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    refresh_log = {}
    if refresh_remote:
        refresh_log["cbsl"] = refresh_cbsl_cache(cache_root)
        refresh_log["imf"] = fetch_imf_cache(cache_root, force=False)
    elif not (cache_root / "imf" / "NGDP_RPCH.json").exists():
        refresh_log["imf"] = fetch_imf_cache(cache_root, force=False)

    cbsl = build_cbsl_dataset(cache_root)
    imf = build_imf_dataset(cache_root)
    highlights = _build_highlights(cbsl, imf)
    _downsample_long_daily(cbsl)

    summary = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "sources": {
            "sri_lanka": cbsl["source"],
            "global": imf["source"],
        },
        "stats": {
            "cbsl": cbsl["stats"],
            "imf": imf["stats"],
        },
        "highlights": highlights,
        "refresh_log": refresh_log,
    }

    (data_dir / "summary.json").write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    (data_dir / "cbsl_data.json").write_text(json.dumps(cbsl, separators=(",", ":")), encoding="utf-8")
    (data_dir / "imf_data.json").write_text(json.dumps(imf, separators=(",", ":")), encoding="utf-8")
    return summary


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    res = build_all_data(root, refresh_remote=False)
    print("Built datasets:", json.dumps(res["stats"], indent=2))
