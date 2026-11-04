"""CBSL (Central Bank of Sri Lanka) data extractor.

Crawls CBSL statistical table pages + homepage Sinhala/English indicator
widgets, downloads/caches all Excel spreadsheets, and extracts all time-series
into structured categories matching the LankaEconomy.lk navigation.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

from .excel_parser import parse_workbook, table_unit
from .periods import parse_period

CBSL_BASE = "https://www.cbsl.gov.lk"

CBSL_INDEX_PAGES = [
    ("Real Sector – National Accounts", "/en/statistics/statistical-tables/real-sector/national-accounts"),
    ("Real Sector – Prices, Wages & Employment", "/en/statistics/statistical-tables/real-sector/prices-wages-employment"),
    ("Real Sector – Production Indicators", "/en/statistics/statistical-tables/real-sector/production-indicators"),
    ("Monetary Sector", "/en/statistics/statistical-tables/monetary-sector"),
    ("External Sector", "/en/statistics/statistical-tables/external-sector"),
    ("Fiscal Sector", "/en/statistics/statistical-tables/fiscal-sector"),
    ("Financial Sector", "/en/statistics/statistical-tables/financial-sector"),
    ("Exchange Rates", "/en/rates-and-indicators/exchange-rates"),
]

# Map every CBSL table filename prefix -> (nav_category, clean_title, unit_override, featured_rank)
# Nav categories match the LankaEconomy.lk header tabs:
#   - "Sri Lanka Economy" (GDP, National Accounts, Fiscal, Labour)
#   - "Business" (Industrial Production, Agriculture, Housing, Tourism, Remittances)
#   - "Banking & Finance" (Monetary Survey, Interest Rates, CBSL & Bank Assets, Soundness)
#   - "Markets" (Exchange Rates, CSE Inflows, T-Bill & T-Bond Auctions, REER)
#   - "Trade & Industry" (Exports, Imports, Trade Indices, BOP, External Debt, Reserves, IIP)
#   - "Money & Prices" (CCPI, NCPI, Wage Rate Indices, Reserve Money & Velocity)
TABLE_CATALOG = [
    # --- Money & Prices ---
    ("CCPI_and_CCPI_CORE", "Money & Prices", "Colombo Consumer Price Index (CCPI & Core)", "Index (2021=100) / %", 1),
    ("NCPI_and_NCPI_CORE", "Money & Prices", "National Consumer Price Index (NCPI & Core)", "Index (2021=100) / %", 2),
    ("wage_rate_indices", "Money & Prices", "Wage Rate Indices (Public & Informal Private)", "Index", 15),
    ("table4.11", "Money & Prices", "Reserve Money, Multiplier & Velocity (Monthly)", "Rs. Million", 18),
    ("table4.10", "Money & Prices", "Reserve Money, Multiplier & Velocity (Annual)", "Rs. Million", 35),

    # --- Markets ---
    ("IF_Buying_Selling_Exchange_Rates", "Markets", "Daily Buying & Selling Exchange Rates (Commercial Banks)", "LKR per Foreign Currency", 3),
    ("IF_Monthly_Average_Exchange_Rates", "Markets", "Monthly Average Exchange Rates (LKR)", "LKR per Foreign Currency", 4),
    ("IF_End_of_the_Month_Exchange_Rates", "Markets", "End of Month Exchange Rates (LKR)", "LKR per Foreign Currency", 22),
    ("IF_REER", "Markets", "Nominal & Real Effective Exchange Rate Indices (NEER / REER)", "Index (2017=100)", 14),
    ("table2.14.3", "Markets", "Colombo Stock Exchange (CSE) Foreign Inflows & Outflows", "USD Million", 11),
    ("table2.14.4", "Markets", "Treasury Bills & Bonds Foreign Inflows", "USD Million", 24),
    ("Treasury_Bill_Auctions", "Markets", "Treasury Bill Auctions (Primary Market Weekly)", "Rs. Million", 16),
    ("Treasury_Bond_Auctions", "Markets", "Treasury Bond Auctions", "Rs. Million", 28),

    # --- Banking & Finance ---
    ("table4.04", "Banking & Finance", "Interest Rates – Policy, T-Bills, Deposit & Lending (Monthly)", "% per annum", 5),
    ("table4.03", "Banking & Finance", "Interest Rates – Policy, T-Bills & Lending (Annual)", "% per annum", 30),
    ("table4.02", "Banking & Finance", "Monetary Survey – M0, M1, M2, M2b & Private Credit (Monthly)", "Rs. Million", 7),
    ("table4.01", "Banking & Finance", "Monetary Survey – Broad Money & Credit (Annual)", "Rs. Million", 31),
    ("table4.06", "Banking & Finance", "Assets & Liabilities of the Central Bank (Monthly)", "Rs. Million", 21),
    ("table4.05", "Banking & Finance", "Assets & Liabilities of the Central Bank (Annual)", "Rs. Million", 38),
    ("table4.08", "Banking & Finance", "Assets & Liabilities of Commercial Banks (Monthly)", "Rs. Million", 23),
    ("table4.07", "Banking & Finance", "Assets & Liabilities of Commercial Banks (Annual)", "Rs. Million", 39),
    ("Table1.0_", "Banking & Finance", "Banking Sector Financial Soundness Indicators (2022–Latest)", "% / Ratio", 12),
    ("Table2.0_", "Banking & Finance", "Banking Sector Assets, Liabilities & Capital (2022–Latest)", "Rs. Million", 25),
    ("Table3.0_", "Banking & Finance", "Banking Sector Earnings & Profitability (2022–Latest)", "Rs. Million", 26),
    ("Table4.0_", "Banking & Finance", "Distribution of Banking Outlets by District", "Number of Outlets", 45),
    ("table1.00_", "Banking & Finance", "Banking Sector Soundness Indicators (Historical 2008–2021)", "% / Ratio", 50),
    ("table2.00_", "Banking & Finance", "Banking Sector Assets & Liabilities (Historical 2008–2021)", "Rs. Million", 51),
    ("table3.00_", "Banking & Finance", "Banking Sector Earnings & Profits (Historical 2008–2021)", "Rs. Million", 52),
    ("table4.00_", "Banking & Finance", "Banking Industry Annual Statistics (1998–2021)", "Rs. Million", 53),
    ("quarterly_financial_information_lfc", "Banking & Finance", "Licensed Finance Companies – Financial Performance (2023–Latest)", "Rs. Million", 32),
    ("table5.06", "Banking & Finance", "Finance Companies – Soundness Indicators (2013–2023)", "% / Ratio", 54),
    ("table5.07", "Banking & Finance", "Finance Companies – Assets & Liabilities (2013–2023)", "Rs. Million", 55),
    ("table5.08", "Banking & Finance", "Finance Companies – Earnings & Profits (2013–2023)", "Rs. Million", 56),
    ("table5.09", "Banking & Finance", "Finance Companies – Branch Network by Province", "Branches", 57),
    ("table4.09", "Banking & Finance", "Assets & Liabilities of Finance Companies (1990–2010)", "Rs. Million", 58),

    # --- Sri Lanka Economy (Macro, GDP, Fiscal, Labour) ---
    ("GDP_by_Industrial_Origin_at_Constant", "Sri Lanka Economy", "Real GDP by Industrial Origin (Constant 2015 Prices)", "Rs. Million", 6),
    ("GDP_by_Industrial_Origin_at_Current", "Sri Lanka Economy", "Nominal GDP by Industrial Origin (Current Market Prices)", "Rs. Million", 17),
    ("Aggregate_Demand_at_Constant", "Sri Lanka Economy", "Real Aggregate Demand – Consumption, Investment & Net Exports", "Rs. Million", 19),
    ("Aggregate_Demand_at_Current", "Sri Lanka Economy", "Nominal Aggregate Demand (Current Market Prices)", "Rs. Million", 33),
    ("Income_Components_of_GDP_at_Constant", "Sri Lanka Economy", "Income Components of GDP (Constant 2015 Prices)", "Rs. Million", 40),
    ("Income_Components_of_GDP_at_Current", "Sri Lanka Economy", "Income Components of GDP (Current Market Prices)", "Rs. Million", 41),
    ("PGDP_Current_Market_Price", "Sri Lanka Economy", "Provincial GDP by Industrial Sector", "Rs. Million", 27),
    ("household_population", "Sri Lanka Economy", "Labour Force, Employment & Unemployment Rate", "'000 Persons / %", 10),
    ("Employed_population", "Sri Lanka Economy", "Employment by Sector (Public, Private, Self-Employed)", "Persons", 29),
    ("table3.01", "Sri Lanka Economy", "Government Fiscal Operations – Revenue, Expenditure & Deficit", "Rs. Million / % of GDP", 8),
    ("table3.02", "Sri Lanka Economy", "Government Revenue – Tax & Non-Tax Classification", "Rs. Million", 20),
    ("table3.03", "Sri Lanka Economy", "Government Expenditure – Functional Classification", "Rs. Million", 42),
    ("table3.04", "Sri Lanka Economy", "Government Expenditure – Economic Classification", "Rs. Million", 43),
    ("table3.05", "Sri Lanka Economy", "Central Government Outstanding Debt (Domestic & Foreign)", "Rs. Million", 9),

    # --- Trade & Industry ---
    ("table2.02", "Trade & Industry", "Merchandise Exports by Commodity (Monthly)", "USD Mn / Rs. Mn", 13),
    ("table2.01", "Trade & Industry", "Merchandise Exports by Commodity (Annual)", "USD Mn / Rs. Mn", 34),
    ("table2.04", "Trade & Industry", "Merchandise Imports by Commodity (Monthly)", "USD Mn / Rs. Mn", 14),
    ("table2.03", "Trade & Industry", "Merchandise Imports by Commodity (Annual)", "USD Mn / Rs. Mn", 36),
    ("table2.06", "Trade & Industry", "Trade Indices – Export & Import Volume, Unit Value & Terms of Trade (Monthly)", "Index (2010=100)", 37),
    ("table2.05", "Trade & Industry", "Trade Indices – Value, Volume & Unit Value (Annual)", "Index", 49),
    ("monthly_current_account_balance", "Trade & Industry", "Monthly Current Account Balance (Goods, Services, Income)", "USD Million", 15),
    ("table2.10", "Trade & Industry", "Balance of Payments – BPM6 Standard Presentation (Quarterly)", "USD Million", 19),
    ("table2.09", "Trade & Industry", "Balance of Payments – BPM6 Standard Presentation (Annual)", "USD Million", 44),
    ("table2.08", "Trade & Industry", "Balance of Payments – BPM5 Historical (Quarterly)", "USD Million", 60),
    ("table2.07", "Trade & Industry", "Balance of Payments – BPM5 Historical (Annual)", "USD Million", 61),
    ("table2.15.2", "Trade & Industry", "Official Reserve Assets & Foreign Currency Liquidity (Monthly)", "USD Million", 7),
    ("table2.12", "Trade & Industry", "Outstanding External Debt & Banking Sector Liabilities (Quarterly)", "USD Million", 16),
    ("table2.11", "Trade & Industry", "International Investment Position – IIP Assets & Liabilities (Quarterly)", "USD Million", 28),
    ("table2.16.1", "Trade & Industry", "Monthly Services Sector Trade (IT/BPO, Transport, Travel)", "USD Million", 23),
    ("table2.14.6", "Trade & Industry", "Government Long-Term Foreign Loan Disbursements", "USD Million", 46),
    ("table2.14.7", "Trade & Industry", "Government Foreign Grants", "USD Million", 47),

    # --- Business (Tourism, Remittances, Production, Agriculture, Construction) ---
    ("table2.14.1", "Business", "Earnings from Tourism", "USD Million", 8),
    ("table2.14.2", "Business", "Workers' Remittances Inflows (Monthly)", "USD Million", 9),
    ("workers_remittance_inflows_by_country", "Business", "Workers' Remittance Inflows by Source Country (Quarterly)", "USD Million", 21),
    ("table1.04_2", "Business", "Index of Industrial Production – IIP (2015=100)", "Index (2015=100)", 12),
    ("table1.04_1", "Business", "Factory Industry Production Index (Historical 2010=100)", "Index (2010=100)", 59),
    ("table1.01", "Business", "Agriculture Data Bulletin – Paddy, Tea, Rubber, Coconut, Fish & Milk", "MT / Rs. per kg", 13),
    ("table1.06", "Business", "Greater Colombo Housing Approval Index (Quarterly)", "Index (1995=100)", 25),
    ("table1.07", "Business", "Greater Colombo Housing Approval Index (Annual)", "Index (1995=100)", 48),
    ("statistics_on_sri_lanka_bureau", "Business", "Foreign Employment (SLBFE) Departures by Month", "Persons", 31),
    ("passport_issuance", "Business", "Passport Issuance by Department of Immigration", "Passports", 45),
]


def _match_catalog(filename: str):
    for prefix, cat, title, unit, rank in TABLE_CATALOG:
        if filename.startswith(prefix):
            return cat, title, unit, rank
    return "Sri Lanka Economy", filename.rsplit(".", 1)[0].replace("_", " "), "", 80


def _pick_latest_files(cache_dir: Path) -> list[Path]:
    """When two dated versions of the same table exist, keep only the newest."""
    files = sorted(p for p in cache_dir.glob("*.xls*") if not p.name.startswith("."))
    groups: dict[str, Path] = {}
    for p in files:
        stem = re.sub(r"_\d{6,8}(?:_[a-z])?\.(xlsx?)$", r".\1", p.name, flags=re.I)
        if stem not in groups or p.name > groups[stem].name:
            groups[stem] = p
    return sorted(groups.values())


def parse_cbsl_homepage_widgets(cache_root: Path) -> dict:
    """Extract live snapshot & mini-charts from CBSL Sinhala/English homepage widgets."""
    widgets = {}

    # 1. Quarterly Real GDP Growth from gdpchart-small.html
    gdp_f = cache_root / "gdpchart-small.html"
    if gdp_f.exists():
        t = gdp_f.read_text(errors="ignore")
        cats = re.findall(r"'((?:Q[1-4])\s*\d{2})'", t)
        m = re.search(r"name:\s*'GDP Growth'\s*,\s*data:\s*\[([^\]]+)\]", t)
        if cats and m:
            vals = [float(x) for x in m.group(1).split(",") if x.strip()]
            pts = []
            for c, v in zip(cats, vals):
                per = parse_period(c)
                if per:
                    pts.append([per[0], v])
            widgets["gdp_growth_q"] = {
                "title": "Real GDP Growth Rate (Quarterly YoY)",
                "unit": "% YoY",
                "freq": "Q",
                "source": "CBSL / DCS Homepage Indicator (cbsl.gov.lk/si)",
                "data": pts,
            }

    # 2. Inflation CCPI & NCPI from inflationchart-small.html
    inf_f = cache_root / "inflationchart-small.html"
    if inf_f.exists():
        t = inf_f.read_text(errors="ignore")
        cm = re.search(r"categories:\s*\[([^\]]+)\]", t)
        cats = re.findall(r"'([^']+)'", cm.group(1)) if cm else []
        pers = [parse_period(c)[0] for c in cats if parse_period(c)]
        series = {}
        for sm in re.finditer(r"name:\s*'([^']+)'\s*,\s*data:\s*\[([^\]]+)\]", t):
            nm = sm.group(1)
            vals = [float(x) for x in sm.group(2).split(",") if x.strip()]
            key = "CCPI YoY %" if "CCPI" in nm else "NCPI YoY %"
            series[key] = [[p, v] for p, v in zip(pers, vals)]
        if series:
            widgets["inflation_headline"] = series

    # 3. Unemployment by gender from unempchart-small.html
    un_f = cache_root / "unempchart-small.html"
    if un_f.exists():
        t = un_f.read_text(errors="ignore")
        cm = re.search(r"categories:\s*\[([^\]]+)\]", t)
        years = re.findall(r"\b(20\d\d)\b", cm.group(1)) if cm else []
        series = {}
        for sm in re.finditer(r"name:\s*'([^']+)'\s*,\s*data:\s*\[([^\]]+)\]", t):
            vals = [float(x) for x in sm.group(2).split(",") if x.strip()]
            series[sm.group(1)] = [[y, v] for y, v in zip(years, vals)]
        if series:
            widgets["unemployment_gender"] = series

    # 4. Sinhala rate window (ratewindowsi.html)
    rw_f = cache_root / "ratewindowsi.html"
    if rw_f.exists():
        t = rw_f.read_text(errors="ignore")
        nums = [float(x) for x in re.findall(r"(?<![0-9.])(\d{1,3}\.\d{2,4})(?![0-9.])", t)]
        # Order in ratewindowsi.php: [20.0063 (line-height), CCPI%, OPR%, TT_Buy, TT_Sell]
        rates = [n for n in nums if abs(n - 20.0063) > 1e-3]
        if len(rates) >= 4:
            widgets["live_window_si"] = {
                "ccpi_yoy_pct": rates[0],
                "opr_pct": rates[1],
                "usd_tt_buying": rates[2],
                "usd_tt_selling": rates[3],
                "labels_si": {
                    "inflation": "උද්ධමනය (කො.පා.මි.ද)",
                    "opr": "එක්දින ප්‍රතිපත්ති පොලී අනුපාතිකය",
                    "fx": "විනිමය අනුපාත ඇ.ඩො/රු (TT මිලදී ගැනීම / විකිණීම)",
                },
            }
    return widgets


def refresh_cbsl_cache(cache_root: Path, timeout: int = 35) -> dict:
    """Download updated indicator widgets and any new spreadsheets from cbsl.gov.lk."""
    cbsl_dir = cache_root / "cbsl"
    cbsl_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; LankaEconomyDashboard/1.0)"}
    downloaded = 0
    errors = []

    for w in ("gdpchart-small", "inflationchart-small", "ratewindowsi", "unempchart-small"):
        url = f"{CBSL_BASE}/cbsl_custom/param/{w}.php"
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.ok and len(r.text) > 200:
                (cache_root / f"{w}.html").write_text(r.text, encoding="utf-8")
                downloaded += 1
        except Exception as e:
            errors.append(f"{w}: {e}")

    sheet_urls = set()
    for _, path in CBSL_INDEX_PAGES:
        url = urljoin(CBSL_BASE, path)
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if not r.ok:
                continue
            for m in re.findall(r'href="([^"]+\.xlsx?)"', r.text, re.I):
                sheet_urls.add(urljoin(CBSL_BASE, html.unescape(m)))
        except Exception as e:
            errors.append(f"{path}: {e}")

    for u in sorted(sheet_urls):
        fname = u.split("/")[-1]
        dest = cbsl_dir / fname
        if dest.exists() and dest.stat().st_size > 500:
            continue
        try:
            r = requests.get(u, headers=headers, timeout=timeout)
            if r.ok and len(r.content) > 500:
                dest.write_bytes(r.content)
                downloaded += 1
        except Exception as e:
            errors.append(f"{fname}: {e}")

    return {"downloaded": downloaded, "discovered_urls": len(sheet_urls), "errors": errors[:10]}


def build_cbsl_dataset(cache_root: Path) -> dict:
    """Parse all cached CBSL files and return structured JSON for the dashboard."""
    cbsl_dir = cache_root / "cbsl"
    files = _pick_latest_files(cbsl_dir)
    tables = []
    total_series = 0
    total_points = 0

    for path in files:
        cat, title, unit_override, rank = _match_catalog(path.name)
        series_list = parse_workbook(path)
        if not series_list:
            continue
        unit = unit_override or table_unit(path)
        table_id = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
        table_id = re.sub(r"_\d{6,8}(?:_[a-z])?$", "", table_id)

        cleaned_series = []
        for idx, s in enumerate(series_list):
            pts = [[k, round(v, 4) if isinstance(v, float) else v] for k, v in s["data"] if v is not None]
            if len(pts) < 3:
                continue
            sid = f"{table_id}__{idx}"
            cleaned_series.append({
                "id": sid,
                "name": s["name"],
                "freq": s["freq"],
                "start": pts[0][0],
                "end": pts[-1][0],
                "last": pts[-1][1],
                "prev": pts[-2][1] if len(pts) > 1 else None,
                "count": len(pts),
                "data": pts,
            })
            total_points += len(pts)

        if not cleaned_series:
            continue
        total_series += len(cleaned_series)
        freqs = sorted({s["freq"] for s in cleaned_series})
        tables.append({
            "id": table_id,
            "file": path.name,
            "category": cat,
            "title": title,
            "unit": unit,
            "rank": rank,
            "frequencies": freqs,
            "start": min(s["start"] for s in cleaned_series),
            "end": max(s["end"] for s in cleaned_series),
            "series_count": len(cleaned_series),
            "series": cleaned_series,
        })

    # Inject CBSL homepage quarterly GDP growth & gender unemployment as dedicated tables
    widgets = parse_cbsl_homepage_widgets(cache_root)
    if "gdp_growth_q" in widgets:
        w = widgets["gdp_growth_q"]
        pts = w["data"]
        tables.append({
            "id": "cbsl_quarterly_gdp_growth",
            "file": "gdpchart-small.php",
            "category": "Sri Lanka Economy",
            "title": "Quarterly Real GDP Growth Rate",
            "unit": "% YoY",
            "rank": 2,
            "frequencies": ["Q"],
            "start": pts[0][0],
            "end": pts[-1][0],
            "series_count": 1,
            "series": [{
                "id": "cbsl_quarterly_gdp_growth__0",
                "name": "Real GDP Growth (% YoY)",
                "freq": "Q",
                "start": pts[0][0],
                "end": pts[-1][0],
                "last": pts[-1][1],
                "prev": pts[-2][1] if len(pts) > 1 else None,
                "count": len(pts),
                "data": pts,
            }],
        })
        total_series += 1
        total_points += len(pts)

    if "unemployment_gender" in widgets:
        ug = widgets["unemployment_gender"]
        s_list = []
        for idx, (nm, pts) in enumerate(ug.items()):
            s_list.append({
                "id": f"cbsl_unemployment_gender__{idx}",
                "name": f"Unemployment Rate – {nm}",
                "freq": "A",
                "start": pts[0][0],
                "end": pts[-1][0],
                "last": pts[-1][1],
                "prev": pts[-2][1] if len(pts) > 1 else None,
                "count": len(pts),
                "data": pts,
            })
            total_points += len(pts)
        if s_list:
            tables.append({
                "id": "cbsl_unemployment_gender",
                "file": "unempchart-small.php",
                "category": "Sri Lanka Economy",
                "title": "Unemployment Rate by Gender (Total, Male, Female)",
                "unit": "% of Labour Force",
                "rank": 11,
                "frequencies": ["A"],
                "start": s_list[0]["start"],
                "end": s_list[0]["end"],
                "series_count": len(s_list),
                "series": s_list,
            })
            total_series += len(s_list)

    tables.sort(key=lambda t: (t["rank"], t["title"]))
    return {
        "source": "Central Bank of Sri Lanka (https://www.cbsl.gov.lk/si & Statistical Tables)",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "stats": {
            "tables": len(tables),
            "series": total_series,
            "data_points": total_points,
        },
        "widgets": widgets,
        "tables": tables,
    }

