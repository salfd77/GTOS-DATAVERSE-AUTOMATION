# Build the GTOS dashboards in Power BI Desktop (from CSV)

No Fabric capacity required. This uses the CSVs produced by `verify_gtos_data.py`
(`reporting_export/`) so you can build the four dashboards entirely offline/desktop.

> When you later get Fabric, swap the CSV source for the live "Link to Fabric"
> source (`build-steps.md`); the model, measures and RLS carry over unchanged.

## 0. Produce the data
```bash
python verify_gtos_data.py --interactive
# -> writes reporting_export/gtos_states.csv, gtos_knowledges.csv,
#    gtos_governances.csv, gtos_transformations.csv, gtos_audits.csv, gtos_findings.csv
```

## 1. Load the six CSVs
1. Power BI Desktop → **Home → Get data → Text/CSV**.
2. Import all six files from `reporting_export/`. In **Transform Data**, confirm:
   - `gtos_detectedon`, `gtos_occurredon` → **Date/Time** type.
   - `gtos_accepted`, `gtos_verified` → **True/False**.
   - severity/status/stage columns stay **Text** (they already hold labels).
3. Close & Apply.

## 2. Relationships (Model view)
Create these (Many → One; the `_..._value` column is the foreign key):

| From (many) | Column | To (one) | Column |
|-------------|--------|----------|--------|
| `gtos_findings` | `_gtos_transformation_value` | `gtos_transformations` | `gtos_name`* |
| `gtos_transformations` | `_gtos_inputstate_value` | `gtos_states` | `gtos_name`* |
| `gtos_transformations` | `_gtos_outputstate_value` | `gtos_states` | `gtos_name`* |
| `gtos_audits` | `_gtos_governance_value` | `gtos_governances` | `gtos_name`* |
| `gtos_knowledges` | `_gtos_relatedstate_value` | `gtos_states` | `gtos_name`* |

\* The CSV export writes the **display name** into the `_..._value` column (via
FormattedValue), so relate it to `gtos_name`. Set the two Transformation→State
relationships so only one is active (Power BI allows a single active path); use
`USERELATIONSHIP` in a measure for the inactive one if you need both.

## 3. Date table
`New table` →
```dax
Date = CALENDAR ( DATE(2026,1,1), DATE(2026,12,31) )
```
Mark it as a date table. Relate `Date[Date]` to `gtos_findings[gtos_detectedon]`
(active) and to `gtos_audits[gtos_occurredon]` (inactive; use `USERELATIONSHIP`).

## 4. Measures
Paste from `measures.dax`. Because the CSV keeps choice **labels** as text, the
label-based filters in those measures (e.g. `gtos_severity = "Blocker"`) work as-is.

## 5. Report pages
| Page | Visuals |
|------|---------|
| **Findings** | Card `[Open Findings]`, `[Blocker Findings Open]`; bar by `gtos_severity`; table by owner/retest; line `[Findings Detected (period)]` over `Date` |
| **Audit trail** | Table of `gtos_audits` sorted by `gtos_occurredon`; slicer by governance record; card `[Last Audit]` |
| **State lifecycle** | Donut of `gtos_state[gtos_status]`; bar by `gtos_lifecyclestage` |
| **Transformation coverage** | Card `[Transformation Verify Rate]`; S1→S2 funnel/flow |

## 6. Row-Level Security
Apply the roles in `rls-roles.md`. In this tenant `gtos_ownership` / `gtos_owner`
are stored as **UPN**, so use `= USERPRINCIPALNAME()` directly (no bridge table).
Validate with **View as role** before sharing.

## 7. Refresh
Re-run `verify_gtos_data.py --interactive` to refresh the CSVs, then **Refresh** in
Power BI Desktop. (Scheduling refresh in the Service requires a gateway for local
files — the Fabric link path in `build-steps.md` avoids that.)

## Sanity check with current demo data
With the 11 seeded records you should see: **Open Findings = 1** (F3 not accepted),
severity split **Blocker/Major/Minor = 1/1/1**, two audit events, and the
Transformation flow **S1 - Draft Charter → S2 - Verified Charter [Verified]**.
