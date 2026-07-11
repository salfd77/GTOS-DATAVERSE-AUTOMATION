#!/usr/bin/env bash
# GTOS: pull latest scripts from main, then verify + export CSVs (read-only).
# Linux / WSL / macOS. Mirrors the PowerShell one-liner flow.
#
#   bash pull-and-run.sh            # pull + provision + verify/export
#   SEED=1 bash pull-and-run.sh     # also seed demo data if tables are empty
set -euo pipefail

RAW="https://raw.githubusercontent.com/salfd77/GTOS-DATAVERSE-AUTOMATION/main"
HERE="$(pwd)"
PY="${PYTHON:-python3}"

fetch() { # $1 = filename
  echo "[pull] $1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$RAW/$1" -o "$HERE/$1"
  else
    wget -qO "$HERE/$1" "$RAW/$1"
  fi
}

# 1) .env (once) - only the environment URL is required.
if [ ! -f .env ]; then
  echo "DATAVERSE_URL=https://org331e3f60.crm.dynamics.com" > .env
  echo "[ok] .env created"
fi

# 2) Pull latest files (defeats the stale local-folder problem).
for f in schema.json provision_gtos_dataverse.py seed_gtos_demo.py verify_gtos_data.py requirements.txt; do
  fetch "$f"
done

# 3) Dependencies (safe to re-run).
"$PY" -m pip install -r requirements.txt

# 4) Ensure columns/relationships exist (adds gtos_DetectedOn if missing). Device-code sign-in.
"$PY" provision_gtos_dataverse.py --interactive

# 5) Optional: seed demo data only when asked (SEED=1). Undo later with --purge.
if [ "${SEED:-0}" = "1" ]; then
  "$PY" seed_gtos_demo.py --interactive --owner tarek.20160862@buc.edu.eg
fi

# 6) Read-only verify + export the 6 CSVs for Power BI.
"$PY" verify_gtos_data.py --interactive

echo
echo "==== done ===="
echo "CSVs are in: $HERE/reporting_export"
echo "Build the model automatically:  pwsh ./build_pbip.ps1  (or open in Power BI Desktop)"
echo "Manual guide: docs/reporting/powerbi-desktop-from-csv.md"
