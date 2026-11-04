#!/usr/bin/env bash
# Auto-sync Sri Lanka (CBSL) & Global (IMF) economic data and push to GitHub.
set -euo pipefail

cd /Users/gihansanjaya/Applications/Economicdata

echo "[$(date -Iseconds)] Starting economic data refresh..."
/Users/gihansanjaya/Applications/Economicdata/.venv/bin/python -c \
  "from pathlib import Path; from backend.build_data import build_all_data; build_all_data(Path('.'), refresh_remote=True)"

# Stage any updated data or code changes and push to GitHub
git add data/*.json
if ! git diff --staged --quiet; then
  git commit -m "chore(data): auto-sync economic data ($(date '+%Y-%m-%d %H:%M'))"
  git push origin main
  echo "[$(date -Iseconds)] Pushed updated economic data to GitHub."
else
  echo "[$(date -Iseconds)] Data is already up to date."
fi

