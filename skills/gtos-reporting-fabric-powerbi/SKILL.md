---
name: gtos-reporting-fabric-powerbi
version: 1.0.0
description: >
  Build the GTOS reporting/analytics layer on top of the six provisioned GTOS
  Dataverse tables using Microsoft Fabric + Power BI. Turns gtos_state,
  gtos_knowledge, gtos_transformation, gtos_governance, gtos_audit and
  gtos_finding into live governance/audit/findings dashboards with row-level
  security — without copying data out of Dataverse.
triggers:
  - gtos report
  - gtos dashboard
  - gtos power bi
  - gtos fabric
  - gtos analytics
  - link gtos to fabric
---

# GTOS Reporting on Fabric + Power BI

## 1. When to use this
Use this **after** `provision_gtos_dataverse.py` has created the six GTOS tables
(state, knowledge, transformation, governance, audit, finding), their columns and
the five relationships. This skill covers the *read/analytics* side only — it never
writes to the operational Dataverse tables. If the tables do not exist yet, run the
provisioning skill first.

## 2. The golden path (recommended architecture)
```
GTOS Dataverse (6 tables, 5 relationships)
        │
        │  zero-ETL, no data copy
        ▼
Microsoft Fabric OneLake
   • Option A (preferred):  Dataverse "Link to Microsoft Fabric"
       - Native, auto-mirrors the tables into OneLake, keeps them in sync.
   • Option B:  Fabric Lakehouse + a Dataverse **shortcut**
       - Virtual link into an existing Lakehouse if you already have one.
        ▼
Power BI Semantic Model  (import/DirectLake; Star Schema)
   • Facts:      gtos_finding, gtos_audit          (event/measure grain)
   • Dimensions: gtos_state, gtos_governance,
                 gtos_transformation, gtos_knowledge
   • Row-Level Security tied to gtos_governance ownership/authority scope
        ▼
Reports / Dashboards
   • Open findings by severity + owner + retest status
   • Audit trail (append-only) — actor / action / occurredOn
   • State lifecycle — stage & status distribution
   • Transformation throughput — input→output with evidence coverage
```

**Why Option A first:** Dataverse's native *Link to Microsoft Fabric* mirrors tables
into OneLake with no pipelines, no ETL, and no extra copy to maintain. It is the
lowest-effort, lowest-drift path and keeps the deterministic GTOS core authoritative.

## 3. One-time setup
1. In **make.powerapps.com** → your environment (`org331e3f60`) → **Analyze → Link to
   Microsoft Fabric**. Select the six `gtos_*` tables. This creates a Fabric workspace
   item that mirrors them into OneLake.
   - *Fallback (Option B):* create a Lakehouse in a Fabric workspace → **Get data →
     New shortcut → Dataverse** → pick the environment and the `gtos_*` tables.
2. In the Fabric workspace, open the auto-generated **default semantic model** (or
   create a new one over the Lakehouse SQL endpoint).
3. Build a **star schema** (see §4) and add **RLS** roles (see §5).
4. Build reports (see §6) and **publish** to the Fabric/Power BI workspace.

## 4. Star-schema modeling (map GTOS to facts & dimensions)
| GTOS table | Role | Grain | Key relationships |
|------------|------|-------|-------------------|
| `gtos_finding` | **Fact** | one row per finding | → `gtos_transformation` |
| `gtos_audit` | **Fact** | one row per audit event | → `gtos_governance` |
| `gtos_transformation` | Dimension | one row per transformation | → `gtos_state` (Input, Output) |
| `gtos_state` | Dimension | one row per state node | — |
| `gtos_governance` | Dimension | one row per authority record | — |
| `gtos_knowledge` | Dimension | one row per knowledge item | → `gtos_state` (Related) |

Guidance:
- Keep the five Dataverse relationships as the model relationships — do **not**
  re-derive keys by hand; the lookup columns already exist.
- Mark date columns (`gtos_occurredon`) as a Date table / mark-as-date for time
  intelligence.
- Prefer **DirectLake** storage mode for freshness at scale; fall back to Import for
  small volumes or complex transforms.

## 5. Row-Level Security (ties to GTOS governance)
GTOS already carries authority/ownership in `gtos_governance`
(`gtos_authorityscope`, `gtos_ownership`, `gtos_approvedby`). Reuse it:
- Create RLS roles that filter facts through their governance/ownership relationship
  so a viewer sees only records within their authority scope.
- Example DAX filter on the governance dimension:
  `[gtos_ownership] = USERPRINCIPALNAME()` (adapt to how ownership is stored — UPN,
  team, or a mapping table).
- Validate with **View as role** before publishing. RLS is enforced at the semantic
  model, so it protects every downstream report.

## 6. Recommended reports (governance-first)
1. **Findings dashboard** — count of open findings by `gtos_severity`, by
   `gtos_owner`, and by `gtos_retestresult`; highlight `gtos_accepted = false` +
   high severity.
2. **Audit trail** — chronological `gtos_audit` (actor / action / occurredOn /
   evidenceLink), filterable by governance record. This *is* the evidence bundle.
3. **State lifecycle** — distribution of `gtos_lifecyclestage` / `gtos_status`;
   entry/exit condition coverage.
4. **Transformation coverage** — input→output flow, evidence-requirements-met rate,
   status funnel.

## 7. Guardrails (must-follow)
- **Read-only layer.** Never let a report or dataflow write back to the operational
  GTOS tables. The Dataverse tables + the deterministic core remain the source of truth.
- **No secrets in PBIP/artifacts.** If you store Power BI project files (PBIP) in git,
  keep connection strings and any keys out of source control (same rule as `.env`).
- **Least-privilege sharing.** Share the workspace/app with the minimum audience; rely
  on RLS for row filtering, not on hiding pages.
- **Freshness ≠ authority.** OneLake mirror/shortcut is for analytics; a stale mirror
  must never be treated as the governing state.

## 8. Best-practice references to reuse (from awesome-copilot)
When building each layer, reuse these existing instruction sets rather than reinventing:
- `power-bi-data-modeling-best-practices` (star schema, relationships, DirectLake)
- `power-bi-security-rls-best-practices` (RLS + Fabric warehouse security)
- `power-bi-dax-best-practices` (measures, time intelligence)
- `power-bi-devops-alm-best-practices` (PBIP + deployment pipelines for CI/ALM)
- Skills: `powerbi-modeling`, `fabric-lakehouse`.

## 9. Verification checklist
- [ ] Six `gtos_*` tables appear in the Lakehouse / mirrored semantic model.
- [ ] The five relationships are present in the model (no manual keys added).
- [ ] `gtos_occurredon` recognized as a date; a Date dimension exists.
- [ ] At least one RLS role defined and validated with **View as role**.
- [ ] Findings, Audit, State, Transformation reports render with live data.
- [ ] No write-back path exists; workspace shared least-privilege.
