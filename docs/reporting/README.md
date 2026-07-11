# GTOS Reporting Kit (Fabric + Power BI)

Paste-ready assets that implement the `skills/gtos-reporting-fabric-powerbi` skill
over the six provisioned GTOS tables. **Read-only layer** — nothing here writes back
to the operational Dataverse tables.

## Contents
| File | Purpose |
|------|---------|
| `build-steps.md` | End-to-end, click-by-click build (Link to Fabric -> model -> RLS -> reports) |
| `powerbi-desktop-from-csv.md` | Build the same dashboards in Power BI Desktop from exported CSVs (no Fabric needed) |
| `build_pbip.ps1` | **Auto-generate** a Power BI Project (PBIP/TMDL) from the CSVs — 6 tables + 5 relationships + measures, ready to open in Desktop |
| `pull-and-run.sh` | Linux/WSL one-shot: pull latest scripts -> provision -> verify -> export CSVs |
| `measures.dax` | Copy/paste DAX measures for the findings/audit/state/transformation dashboards |
| `rls-roles.md` | Row-Level Security role definitions tied to GTOS governance ownership |
| `demo-data.md` | How to seed sample data so the dashboards render (uses `seed_gtos_demo.py`) |

## Three paths to the same dashboards
- **With Fabric** (`build-steps.md`): Dataverse -> Link to Microsoft Fabric (zero-ETL) -> Power BI semantic model + RLS -> dashboards.
- **Without Fabric, manual** (`powerbi-desktop-from-csv.md`): `verify_gtos_data.py` -> CSVs -> Power BI Desktop -> same model, measures, RLS.
- **Without Fabric, automatic** (`build_pbip.ps1`): `verify_gtos_data.py` -> CSVs -> `pwsh ./build_pbip.ps1` -> open the generated `GTOS.pbip` (model + relationships + measures already wired; just drag fields).

## Prerequisites
- The six `gtos_*` tables + 5 relationships exist (they do — provisioned & verified).
- The `gtos_DetectedOn` column exists on Finding (run `provision_gtos_dataverse.py --interactive` once).
- (Recommended) Seed demo data so visuals aren't empty — see `demo-data.md`.
- For the Fabric path: a Microsoft Fabric capacity/trial + Power BI on the same tenant.
- For `build_pbip.ps1`: PowerShell + Power BI Desktop with PBIP save format (default since 2024). If your build can't open PBIP, use `powerbi-desktop-from-csv.md`.
