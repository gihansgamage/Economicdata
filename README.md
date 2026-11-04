# LankaEconomy.lk — Sri Lanka & Global Economic Data Dashboard

Interactive macroeconomic dashboard for **Sri Lanka** and **Global** economies with adjustable time periods, multi-series/country comparisons, YoY% / Indexed transformations, CSV export, and a Python backend + GitHub Pages static publishing pipeline.

## Data Sources
1. **Sri Lanka Economy — Central Bank of Sri Lanka (CBSL)** (`https://www.cbsl.gov.lk/si` & Statistical Tables):
   - **79 Statistical Tables · 4,500+ Series · 344,000+ Data Points** across:
     - **Money & Prices:** Colombo CPI (CCPI & Core), National CPI (NCPI & Core), Public & Informal Private Wage Rate Indices, Reserve Money & Velocity.
     - **Sri Lanka Economy:** Real & Nominal GDP by Industrial Origin (Constant 2015 & Current Prices), Quarterly Real GDP Growth, Aggregate Demand, Income Components of GDP, Provincial GDP, Labour Force, Employment & Unemployment by Gender, Government Fiscal Operations (Revenue, Expenditure, Deficit, Domestic & Foreign Debt).
     - **Banking & Finance:** Monetary Survey ($M_0, M_1, M_2, M_{2b}$, Private Credit), Policy Interest Rates (OPR, SDFR, SLFR, T-Bill Yields), CBSL & Commercial Bank Balance Sheets, Financial Soundness Indicators (CAR, Tier-1, NPLs, ROE), Licensed Finance Companies.
     - **Markets:** Daily Commercial Bank Buying/Selling Exchange Rates (2005–Latest), Monthly Average & End-of-Month Exchange Rates (1986–Latest), NEER/REER, CSE Foreign Inflows, Treasury Bill & Bond Auctions.
     - **Trade & Industry:** Monthly & Annual Merchandise Exports and Imports by Commodity, Trade Indices, Balance of Payments (BPM6), Monthly Current Account, Official Reserve Assets (RDT), External Debt & IIP, Services Trade.
     - **Business:** Tourism Earnings, Workers' Remittances (Monthly & Quarterly by Country), Index of Industrial Production (IIP), Agriculture Data Bulletin, Greater Colombo Housing Approvals, Foreign Employment (SLBFE) & Passport Issuance.
2. **Global Economy — International Monetary Fund (IMF)** (`https://www.imf.org/en/home` DataMapper API):
   - **41 Global Indicators · 398 Countries, Regions & Analytical Groups · 6,890 Series · 228,000+ Data Points** from the World Economic Outlook (WEO), Fiscal Monitor (FM), Global Debt Database (GDD), Capital Flows (CF), Export Diversification & Quality (SPRLU), Financial Openness (CL), Reserve Adequacy (ARA), and AI Preparedness Index (AIPI).

## Running the Python Backend Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# (Optional) Re-build / refresh data from CBSL & IMF
python -m backend.build_data

# Start the Flask backend server on http://127.0.0.1:5050
python app.py
```

## Publishing Through GitHub
- Pre-compiled data bundles (`data/summary.json`, `data/cbsl_data.json`, `data/imf_data.json`) are committed in [`data/`](data/) so the dashboard works out-of-the-box on **GitHub Pages** (`index.html`) as well as on any Python PaaS (Render, Railway, Fly.io, Heroku) via `gunicorn app:app`.
- The included GitHub Actions workflow (`.github/workflows/deploy.yml`) automatically runs the Python extractor on a schedule and deploys the updated dashboard to GitHub Pages.

