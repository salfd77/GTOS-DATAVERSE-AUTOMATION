# Build steps — GTOS dashboards on Fabric + Power BI

Follow top to bottom. Each step is a single, concrete action.

## A. Link Dataverse to Fabric (zero-ETL)
1. Open **make.powerapps.com** and select environment **`org331e3f60`** (Sovereign_Sandbox_v1).
2. Left nav -> **Analyze** (or **Data**) -> **Link to Microsoft Fabric**.
3. Select the six tables: `gtos_state`, `gtos_knowledge`, `gtos_transformation`,
   `gtos_governance`, `gtos_audit`, `gtos_finding`.
4. Confirm. Dataverse mirrors them into **OneLake** automatically and keeps them in sync.
   - *Fallback (if the button is unavailable):* create a **Lakehouse** in a Fabric
     workspace -> **Get data -> New shortcut -> Dataverse** -> pick the environment
     and the six `gtos_*` tables.

## B. Open the semantic model
5. In the Fabric workspace created by step 3, open the **default semantic model**
   (or create a new Power BI semantic model over the Lakehouse SQL endpoint).

## C. Star schema (facts vs dimensions)
6. Set table roles:
   - **Facts:** `gtos_finding`, `gtos_audit`.
   - **Dimensions:** `gtos_state`, `gtos_governance`, `gtos_transformation`, `gtos_knowledge`.
7. Verify the 5 native relationships came across (do **not** hand-create keys):
   - `gtos_finding` -> `gtos_transformation`
   - `gtos_transformation` -> `gtos_state` (Input **and** Output)
   - `gtos_audit` -> `gtos_governance`
   - `gtos_knowledge` -> `gtos_state`
8. Add a **Date** dimension and mark it as a date table. Relate it to
   `gtos_finding[gtos_detectedon]` and `gtos_audit[gtos_occurredon]` for time intelligence.

## D. Measures
9. Create the measures from `measures.dax` (copy each block into a new measure).

## E. Row-Level Security
10. Apply the roles from `rls-roles.md`. Validate each with **View as role** before publishing.

## F. Reports
11. Build four pages:
    - **Findings** — open findings by severity/owner/retest; findings over time (uses `gtos_detectedon`).
    - **Audit trail** — chronological `gtos_audit`, filterable by governance record.
    - **State lifecycle** — distribution of lifecycle stage & status.
    - **Transformation coverage** — input->output funnel, evidence-met rate.
12. **Publish** to the workspace. Share least-privilege; rely on RLS for row filtering.

## G. Verify (checklist)
- [ ] Six tables + 5 relationships present in the model.
- [ ] Date table marked; related to `gtos_detectedon` / `gtos_occurredon`.
- [ ] Measures created and returning values.
- [ ] At least one RLS role validated with View as role.
- [ ] Four report pages render on live data.
- [ ] No write-back path; workspace shared least-privilege.
