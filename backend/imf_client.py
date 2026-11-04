"""IMF DataMapper API client & global macroeconomic dataset builder.

Extracts indicators across World Economic Outlook (WEO), Fiscal Monitor (FM),
Global Debt Database (GDD), Capital Flows (CF), Export Diversification (SPRLU),
Financial Openness (CL), Reserve Adequacy (ARA), Gender (GD), and AI
Preparedness Index (AIPI) from https://www.imf.org/external/datamapper/api/v1/.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import requests

IMF_API = "https://www.imf.org/external/datamapper/api/v1"

# Map IMF indicator code -> (nav_category, clean_label, unit_override, rank)
# Nav categories match LankaEconomy.lk World navigation:
#   - "Global Economy" (GDP Growth, Nominal/PPP GDP, Per Capita, Unemployment, Population, AI Index)
#   - "Money & Prices" (Headline CPI Inflation, End-of-Period CPI, PPP Conversion)
#   - "Banking & Finance" (Fiscal Balance, Govt Debt, Revenue, Expenditure, Private/HH/Corp Debt)
#   - "Trade & Industry" (Current Account, Reserves Adequacy, Export Diversification & Quality)
#   - "Markets" (FDI, Portfolio & Capital Flows, Financial Openness Indices, Bond Yields)
#   - "Business" (Corporate Debt, Innovation, Digital Infrastructure, Human Capital)
IMF_INDICATORS = [
    # --- Global Economy ---
    ("NGDP_RPCH", "Global Economy", "Real GDP Growth Rate", "Annual % change", 1),
    ("NGDPD", "Global Economy", "GDP, Current Prices (USD)", "USD Billions", 2),
    ("NGDPDPC", "Global Economy", "GDP per Capita, Current Prices (USD)", "USD per capita", 3),
    ("PPPGDP", "Global Economy", "GDP based on Purchasing Power Parity (PPP)", "Intl$ Billions", 4),
    ("PPPPC", "Global Economy", "GDP per Capita, PPP", "Intl$ per capita", 5),
    ("PPPSH", "Global Economy", "Share of World GDP (PPP)", "% of World", 6),
    ("LUR", "Global Economy", "Unemployment Rate", "% of Total Labor Force", 7),
    ("LP", "Global Economy", "Population", "Millions of people", 8),

    # --- Money & Prices ---
    ("PCPIPCH", "Money & Prices", "Inflation Rate, Average Consumer Prices", "Annual % change", 1),
    ("PCPIEPCH", "Money & Prices", "Inflation Rate, End of Period Consumer Prices", "Annual % change", 2),
    ("PPPEX", "Money & Prices", "Implied PPP Conversion Rate", "LCU per Intl$", 5),

    # --- Banking & Finance (Fiscal Monitor, WEO Fiscal, Global Debt Database) ---
    ("GGXWDG_NGDP", "Banking & Finance", "General Government Gross Debt (WEO)", "% of GDP", 1),
    ("GGXCNL_NGDP", "Banking & Finance", "General Government Net Lending / Borrowing (Fiscal Balance)", "% of GDP", 2),
    ("GGR_G01_GDP_PT", "Banking & Finance", "General Government Revenue (Fiscal Monitor)", "% of GDP", 3),
    ("G_X_G01_GDP_PT", "Banking & Finance", "General Government Expenditure (Fiscal Monitor)", "% of GDP", 4),
    ("GGXONLB_G01_GDP_PT", "Banking & Finance", "Primary Fiscal Balance (Fiscal Monitor)", "% of GDP", 5),
    ("GGXWDN_G01_GDP_PT", "Banking & Finance", "General Government Net Debt (Fiscal Monitor)", "% of GDP", 6),
    ("ie", "Banking & Finance", "Interest Paid on Public Debt", "% of GDP", 7),
    ("CG_DEBT_GDP", "Banking & Finance", "Central Government Debt (Global Debt Database)", "% of GDP", 8),
    ("Privatedebt_all", "Banking & Finance", "Total Private Sector Debt (All Instruments)", "% of GDP", 9),
    ("HH_ALL", "Banking & Finance", "Household Debt (All Instruments)", "% of GDP", 10),

    # --- Trade & Industry (External Sector, Reserves, Export Diversification) ---
    ("BCA_NGDPD", "Trade & Industry", "Current Account Balance (% of GDP)", "% of GDP", 1),
    ("BCA", "Trade & Industry", "Current Account Balance (USD Billions)", "USD Billions", 2),
    ("Reserves_M", "Trade & Industry", "International Reserves in Months of Imports", "Months of Imports", 3),
    ("Reserves_ARA", "Trade & Industry", "Ratio of Official Reserves to ARA Metric", "Ratio", 4),
    ("Reserves_STD", "Trade & Industry", "Official Reserves to Short-Term External Debt", "Ratio", 5),
    ("Reserves_M2", "Trade & Industry", "Official Reserves to Broad Money (M2)", "Ratio", 6),
    ("total_theil", "Trade & Industry", "Export Diversification Index (Theil)", "Index (Lower = More Diversified)", 7),
    ("SITC1_total", "Trade & Industry", "Export Quality Index", "Index", 8),

    # --- Markets (Capital Flows, Bond Yields, Financial Market Openness) ---
    ("DirectIn", "Markets", "Foreign Direct Investment (FDI) Inflows", "USD Millions", 1),
    ("DirectAbroad", "Markets", "Direct Investment Abroad (FDI Outflows)", "USD Millions", 2),
    ("Portfl", "Markets", "Portfolio Investment Inflows (Liabilities)", "USD Millions", 3),
    ("EquityL", "Markets", "Foreign Equity Securities Inflows", "USD Millions", 4),
    ("DebtL", "Markets", "Foreign Debt Securities Inflows", "USD Millions", 5),
    ("rltir", "Markets", "Real Long-Term Government Bond Yield", "% per annum", 6),
    ("FM_ka", "Markets", "Financial Market Openness Index", "Index (0 to 1)", 7),
    ("ka_new", "Markets", "Overall Capital Account Openness Index", "Index (0 to 1)", 8),

    # --- Business (Corporate Debt, AI Preparedness, Innovation, Infrastructure) ---
    ("NFC_ALL", "Business", "Nonfinancial Corporate Debt", "% of GDP", 1),
    ("AI_PI", "Business", "AI Preparedness Index (Overall)", "Index (0 to 1)", 2),
    ("DI", "Business", "Digital Infrastructure Score", "Index", 3),
    ("IEI", "Business", "Innovation & Economic Integration Score", "Index", 4),
    ("HCLMP", "Business", "Human Capital & Labor Market Policies Score", "Index", 5),
    ("GDI_TC", "Business", "Gender Development Index (Time-Consistent)", "Index", 6),
]

# Highlighted economies and analytical groups shown at top of country selector
FEATURED_ENTITIES = [
    ("LKA", "Sri Lanka"),
    ("WEOWORLD", "World"),
    ("ADVEC", "Advanced Economies"),
    ("OEMDC", "Emerging Market & Developing Economies"),
    ("DA", "Emerging & Developing Asia"),
    ("SAQ", "South Asia"),
    ("APQ", "Asia and Pacific"),
    ("MAE", "Major Advanced Economies (G7)"),
    ("EURO", "Euro Area"),
    ("EU", "European Union"),
    ("AS5", "ASEAN-5"),
    ("MENA", "Middle East & North Africa"),
    ("USA", "United States"),
    ("CHN", "China"),
    ("IND", "India"),
    ("JPN", "Japan"),
    ("DEU", "Germany"),
    ("GBR", "United Kingdom"),
    ("FRA", "France"),
    ("SGP", "Singapore"),
    ("MYS", "Malaysia"),
    ("THA", "Thailand"),
    ("IDN", "Indonesia"),
    ("VNM", "Vietnam"),
    ("PHL", "Philippines"),
    ("BGD", "Bangladesh"),
    ("PAK", "Pakistan"),
    ("MDV", "Maldives"),
    ("NPL", "Nepal"),
    ("ARE", "United Arab Emirates"),
    ("SAU", "Saudi Arabia"),
    ("QAT", "Qatar"),
    ("KWT", "Kuwait"),
    ("AUS", "Australia"),
    ("CAN", "Canada"),
    ("KOR", "Korea, Republic of"),
    ("BRA", "Brazil"),
    ("ZAF", "South Africa"),
]


def fetch_imf_cache(cache_root: Path, force: bool = False, timeout: int = 35) -> dict:
    """Download metadata + indicator JSONs from IMF DataMapper API into cache/imf/."""
    imf_dir = cache_root / "imf"
    imf_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; LankaEconomyDashboard/1.0)"}
    downloaded = 0
    errors = []

    for endpoint in ("indicators", "countries", "regions", "groups"):
        dest = imf_dir / f"meta_{endpoint}.json"
        if dest.exists() and dest.stat().st_size > 200 and not force:
            continue
        try:
            r = requests.get(f"{IMF_API}/{endpoint}", headers=headers, timeout=timeout)
            if r.ok:
                dest.write_text(r.text, encoding="utf-8")
                downloaded += 1
        except Exception as e:
            errors.append(f"{endpoint}: {e}")

    for code, *_ in IMF_INDICATORS:
        dest = imf_dir / f"{code}.json"
        if dest.exists() and dest.stat().st_size > 200 and not force:
            continue
        try:
            r = requests.get(f"{IMF_API}/{code}", headers=headers, timeout=timeout)
            if r.ok and "values" in r.text:
                dest.write_text(r.text, encoding="utf-8")
                downloaded += 1
        except Exception as e:
            errors.append(f"{code}: {e}")

    return {"downloaded": downloaded, "indicators": len(IMF_INDICATORS), "errors": errors[:10]}


def build_imf_dataset(cache_root: Path) -> dict:
    """Build compact, rich IMF global + Sri Lanka dataset from cached JSON files."""
    imf_dir = cache_root / "imf"

    entities: dict[str, dict] = {}
    for kind, fname in (("country", "meta_countries.json"), ("region", "meta_regions.json"), ("group", "meta_groups.json")):
        p = imf_dir / fname
        if not p.exists():
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        top_key = next((k for k in ("countries", "regions", "groups") if k in raw), None)
        if not top_key:
            continue
        for code, info in raw[top_key].items():
            label = (info.get("label") or code).strip()
            if label:
                entities[code] = {"code": code, "name": label, "type": kind}

    # Ensure World and featured entities have clean labels
    for code, name in FEATURED_ENTITIES:
        if code not in entities:
            entities[code] = {"code": code, "name": name, "type": "group" if len(code) != 3 or code in ("WLD", "AS5") else "country"}
        else:
            entities[code]["featured"] = True

    meta_ind = {}
    mi_path = imf_dir / "meta_indicators.json"
    if mi_path.exists():
        meta_ind = json.loads(mi_path.read_text(encoding="utf-8")).get("indicators", {})

    indicators_out = []
    total_series = 0
    total_points = 0

    for code, cat, title, unit_override, rank in IMF_INDICATORS:
        f = imf_dir / f"{code}.json"
        if not f.exists():
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        values_map = payload.get("values", {}).get(code, {})
        if not values_map:
            continue
        m = meta_ind.get(code, {})
        unit = unit_override or m.get("unit") or ""
        desc = (m.get("description") or "").strip()
        dataset = m.get("dataset") or "WEO"
        source = m.get("source") or f"IMF ({dataset})"

        series_by_entity = {}
        all_years = set()
        for ent_code, yr_dict in values_map.items():
            if not isinstance(yr_dict, dict):
                continue
            pts = []
            for yr, val in sorted(yr_dict.items()):
                if val is None:
                    continue
                try:
                    fv = round(float(val), 3)
                except (ValueError, TypeError):
                    continue
                pts.append([str(yr), fv])
                all_years.add(str(yr))
            if pts:
                series_by_entity[ent_code] = pts
                total_series += 1
                total_points += len(pts)

        if not series_by_entity:
            continue
        sorted_yrs = sorted(all_years)
        indicators_out.append({
            "id": code,
            "category": cat,
            "title": title,
            "unit": unit,
            "dataset": dataset,
            "source": source,
            "description": desc,
            "rank": rank,
            "start": sorted_yrs[0],
            "end": sorted_yrs[-1],
            "entity_count": len(series_by_entity),
            "values": series_by_entity,
        })

    indicators_out.sort(key=lambda x: (x["rank"], x["title"]))

    # Build ordered entity list (featured first, then alphabetical)
    featured_codes = [c for c, _ in FEATURED_ENTITIES]
    featured_set = set(featured_codes)
    entity_list = []
    for c, nm in FEATURED_ENTITIES:
        e = entities.get(c, {"code": c, "name": nm, "type": "country"})
        entity_list.append({**e, "name": nm, "featured": True})
    for c, e in sorted(entities.items(), key=lambda kv: kv[1]["name"]):
        if c not in featured_set:
            entity_list.append({**e, "featured": False})

    return {
        "source": "International Monetary Fund – IMF DataMapper API (https://www.imf.org/en/home)",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "stats": {
            "indicators": len(indicators_out),
            "entities": len(entity_list),
            "series": total_series,
            "data_points": total_points,
        },
        "entities": entity_list,
        "indicators": indicators_out,
    }
