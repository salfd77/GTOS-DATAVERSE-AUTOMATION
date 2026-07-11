---
name: gtos-dataverse-provisioning
description: >
  Operate and safely extend the GTOS Dataverse provisioning tool
  (provision_gtos_dataverse.py). Use when creating, updating, or auditing the
  GTOS data model (tables, columns, relationships) in a Microsoft Dataverse
  environment via the Dataverse Web API. Idempotent, --whatif-aware, least-privilege.
license: MIT
metadata:
  project: GTOS-DATAVERSE-AUTOMATION
  repo: https://github.com/salfd77/GTOS-DATAVERSE-AUTOMATION
  environment: org331e3f60.crm.dynamics.com
  publisher_prefix: gtos_
  language_code: 1033
trigger_phrases:
  - "provision gtos dataverse"
  - "add a gtos table / column / relationship"
  - "run provision_gtos_dataverse"
  - "gtos schema.json"
---

# GTOS Dataverse Provisioning Skill

## 1. When to use / when NOT to use
**Use this skill when** you need to:
- Add a new GTOS table, column, or relationship to the data model.
- Re-run provisioning safely (idempotent) or preview changes.
- Audit / troubleshoot the GTOS Dataverse environment.

**Do NOT use this skill for:**
- The Microsoft `PowerPlatform.Dataverse` **Python SDK (preview)** — GTOS uses the **raw
  Web API + `requests`**, a deliberately different approach. Do not swap SDKs.
- Any persona/roleplay behavior. Stay a precise engineering assistant.
- Blind re-provisioning: as of 2026-07-11 the full model (6 tables + 31 columns + 5
  relationships) **already exists**. A clean re-run must report `created: 0` everywhere.

## 2. Architecture & data model
Single source of truth is `schema.json`. The script `provision_gtos_dataverse.py`:
- Authenticates, then iterates `schema["tables"]` (creates table + its columns),
  **then** iterates `schema["relationships"]` (creates lookups) — in that order.
- Is **idempotent**: it checks existence before every create ("[skip] ... exists").
- Supports **`--whatif`** (dry run, writes nothing) and **`--interactive`** (device-code login).

### The 6 tables (prefix `gtos_`, primary `gtos_Name`)
| Table | Purpose | Key columns |
|-------|---------|-------------|
| `gtos_state` | State-graph nodes | LifecycleStage(choice), Status(choice), Entry/ExitConditions(memo), EvidenceBundle(memo) |
| `gtos_knowledge` | Fact/Assumption/Hypothesis/Decision/Lesson | KnowledgeType(choice), Statement(memo), Evidence(memo), Owner(string), Verified(bool) |
| `gtos_transformation` | Input→Transformation→Output | Goal(memo), Provider(string), Pre/PostConditions(memo), EvidenceRequirements(memo), Status(choice) |
| `gtos_governance` | Authority/Ownership/Approval | AuthorityScope(string), Ownership(string), ApprovalStatus(choice), ApprovedBy(string), Evidence(memo) |
| `gtos_audit` | Append-only audit trail | Actor(string), Action(memo), OccurredOn(datetime), EvidenceLink(string) |
| `gtos_finding` | Findings/Severity/Retest | Description(memo), Severity(choice), Owner(string), Fix(memo), RetestResult(choice), Accepted(bool) |

### The 5 relationships (One-to-Many lookups)
| Schema name | Parent (Referenced) → Child (Referencing) | Lookup |
|-------------|-------------------------------------------|--------|
| gtos_transformation_inputstate  | State → Transformation | gtos_InputState |
| gtos_transformation_outputstate | State → Transformation | gtos_OutputState |
| gtos_finding_transformation     | Transformation → Finding | gtos_Transformation |
| gtos_audit_governance           | Governance → Audit | gtos_Governance |
| gtos_knowledge_state            | State → Knowledge | gtos_RelatedState |

## 3. Safe operating procedure
1. **Sync the code + schema first.** Never trust a stale local copy (see §7). Pull latest
   `provision_gtos_dataverse.py` **and** `schema.json` from `main`.
2. **Set `DATAVERSE_URL`** in `.env` → `https://org331e3f60.crm.dynamics.com`.
3. **Preview:** `python provision_gtos_dataverse.py --whatif`  (writes nothing).
4. **Apply:** `python provision_gtos_dataverse.py --interactive`  (device-code sign-in), or
   app-only via `TENANT_ID` / `CLIENT_ID` / `CLIENT_SECRET`.
5. **Verify:** a second run must print `Tables created: 0, columns created: 0, relationships created: 0`.

## 4. How to extend the model
Edit `schema.json` only — never hand-create metadata out-of-band.

### Add a column
Append to the table's `columns` array: `{ "name": "gtos_myfield", "type": "memo|string|choice|boolean|datetime" }`.

### Add a table
Append to `schema["tables"]` with `name`, `primary` (`gtos_Name`), and `columns`.

### Add a relationship (created AFTER tables/columns; retry-on-lock)
Append to `schema["relationships"]`. In `schema.json` you only declare the intent
(referenced/referencing entities + lookup); the script **auto-builds** the payload below —
including the `gtos_`-prefixed logical/schema names — from those fields plus the configured
`publisherPrefix`. The `gtos_parent` / `gtos_child` / `gtos_ParentLookup` values shown here are
**illustrative outputs, not literals to hand-type**. The Web API payload is an
`Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata` POSTed to `/RelationshipDefinitions`:
```jsonc
{
  "@odata.type": "Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata",
  "SchemaName": "gtos_child_parent",
  "ReferencedEntity": "gtos_parent",     // lowercase logical name (the "one" side)
  "ReferencingEntity": "gtos_child",     // lowercase logical name (the "many" side)
  "Lookup": {
    "@odata.type": "Microsoft.Dynamics.CRM.LookupAttributeMetadata",
    "SchemaName": "gtos_ParentLookup"
  }
}
```
> Relationships MUST be created only after BOTH entities exist; the platform may return a
> metadata lock — the script already retries with backoff. Do not remove that logic.

## 5. Guardrails (non-negotiable)
- **Secrets hygiene:** NEVER commit `.env`, client secrets, or tokens. Keep `.env` in `.gitignore`.
- **Least privilege:** prefer app-only with **System Customizer** over System Administrator when
  the tenant allows it; scope the app registration to only what provisioning needs.
- **Shared machines:** avoid `--interactive` device-code auth on shared/unattended hosts.
- **Idempotency is sacred:** every create path must be preceded by an existence check. Never
  introduce a blind create.
- **Service-protection limits:** Dataverse throttles bulk metadata ops (HTTP 429 + `Retry-After`).
  Respect backoff; do not hammer the API.
- **--whatif before every apply.** No exceptions on a live environment.

## 6. Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| `DATAVERSE_URL is not set` | missing/blank `.env` | create `.env` with the org URL |
| `relationships created: 0` but you expected 5 | **stale local `schema.json`** (no `relationships` block) | re-download `schema.json` from `main` |
| Relationships missing though tables exist | running an **old script** that ignored `schema["relationships"]` | re-download `provision_gtos_dataverse.py` from `main` (fix merged in PR #1, commit 50341ed) |
| Relationship create fails intermittently | metadata lock right after table creation | expected; the retry-on-lock loop handles it |
| Everything says `[skip]` | model already provisioned | that is success, not an error |

## 7. Verification checklist
- [ ] Latest `provision_gtos_dataverse.py` AND `schema.json` pulled from `main`.
- [ ] `.env` has `DATAVERSE_URL`; secrets are NOT committed.
- [ ] `--whatif` run reviewed and matches intent.
- [ ] Apply run completed; auth succeeded.
- [ ] Re-run reports `created: 0` across tables/columns/relationships (idempotency proven).
- [ ] Any new table/column/relationship exists in the Dataverse maker portal.
