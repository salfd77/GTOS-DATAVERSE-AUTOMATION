# GTOS Reporting Kit (Fabric + Power BI)

Paste-ready assets that implement the `skills/gtos-reporting-fabric-powerbi` skill
over the six provisioned GTOS tables. **Read-only layer** — nothing here writes back
to the operational Dataverse tables.

## Contents
| File | Purpose |
|------|---------|
| `build-steps.md` | End-to-end, click-by-click build (Link to Fabric -> model -> RLS -> reports) |
| `powerbi-desktop-from-csv.md` | Build the same dashboards in Power BI Desktop from exported CSVs (no Fabric needed) |
| `measures.dax` | Copy/paste DAX measures for the findings/audit/state/transformation dashboards |
| `rls-roles.md` | Row-Level Security role definitions tied to GTOS governance ownership |
| `demo-data.md` | How to seed sample data so the dashboards render (uses `seed_gtos_demo.py`) |

## Two paths to the same dashboards
- **With Fabric** (`build-steps.md`): Dataverse -> Link to Microsoft Fabric (zero-ETL) -> Power BI semantic model + RLS -> dashboards.
- **Without Fabric** (`powerbi-desktop-from-csv.md`): `verify_gtos_data.py` -> CSVs -> Power BI Desktop -> same model, measures, RLS.

## Prerequisites
- The six `gtos_*` tables + 5 relationships exist (they do — provisioned & verified).
- The `gtos_DetectedOn` column exists on Finding (run `provision_gtos_dataverse.py --interactive` once).
- (Recommended) Seed demo data so visuals aren't empty — see `demo-data.md`.
- For the Fabric path: a Microsoft Fabric capacity/trial + Power BI on the same tenant.
