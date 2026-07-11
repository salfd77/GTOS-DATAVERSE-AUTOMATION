# GTOS Reporting Kit (Fabric + Power BI)

Paste-ready assets that implement the `skills/gtos-reporting-fabric-powerbi` skill
over the six provisioned GTOS tables. **Read-only layer** — nothing here writes back
to the operational Dataverse tables.

## Contents
| File | Purpose |
|------|---------|
| `build-steps.md` | End-to-end, click-by-click build (Link to Fabric -> model -> RLS -> reports) |
| `measures.dax` | Copy/paste DAX measures for the findings/audit/state/transformation dashboards |
| `rls-roles.md` | Row-Level Security role definitions tied to GTOS governance ownership |

## The path in one line
`Dataverse (org331e3f60) -> Link to Microsoft Fabric (zero-ETL) -> Power BI star-schema semantic model + RLS -> dashboards.`

## Prerequisites
- The six `gtos_*` tables + 5 relationships exist (they do — provisioned & verified).
- For the findings timeline, the `gtos_DetectedOn` column exists (added in this PR's
  `schema.json`; run `provision_gtos_dataverse.py --interactive` once to apply it).
- A Microsoft Fabric capacity/trial and Power BI access on the same tenant.
