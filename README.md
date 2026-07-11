# GTOS Dataverse Automation

Automatically provisions the six GTOS tables (their columns **and** their
relationships) into a Microsoft Dataverse environment from a single
`schema.json`, via the Dataverse Web API.

Tables created (prefix `gtos_` by default):

| Table | Purpose | Source physics file |
|-------|---------|---------------------|
| `gtos_state` | State Graph nodes | 04_STATE_PHYSICS |
| `gtos_knowledge` | Fact/Assumption/Hypothesis/Decision/Lesson | 02_KNOWLEDGE_PHYSICS |
| `gtos_transformation` | Input→Transformation→Output | 03_TRANSFORMATION_PHYSICS |
| `gtos_governance` | Authority/Ownership/Evidence/Approval | 06_GOVERNANCE_PHYSICS |
| `gtos_audit` | Append-only audit trail | 06_GOVERNANCE_PHYSICS |
| `gtos_finding` | Findings/Severity/Owner/Retest/Acceptance | 07_VERIFICATION_MESH |

Relationships created (One-to-Many lookups, from the `relationships` block in `schema.json`):

| Relationship (SchemaName) | Child (referencing) → Parent (referenced) | Lookup column |
|---------------------------|--------------------------------------------|---------------|
| `gtos_transformation_inputstate` | Transformation → State | Input State |
| `gtos_transformation_outputstate` | Transformation → State | Output State |
| `gtos_finding_transformation` | Finding → Transformation | Transformation |
| `gtos_audit_governance` | Audit → Governance | Governance |
| `gtos_knowledge_state` | Knowledge → State | Related State |

## Files

```text
GTOS-DATAVERSE-AUTOMATION/
├── schema.json                    ← single source of truth (edit tables/columns/relationships here)
├── provision_gtos_dataverse.py    ← the automation (Web API, idempotent, dry-run)
├── provision_with_pac.ps1         ← optional pac-CLI wrapper (Windows/WSL2)
├── requirements.txt               ← pip deps (requests, msal)
├── .env.example                   ← copy to .env and fill credentials
└── README.md                      ← this file
```

## Two ways to authenticate

### A) Interactive — sign in as yourself (EASIEST, no app registration)
Best when you do not have rights to create an app registration (e.g. a managed
university/organization tenant). You only need the environment URL.

```powershell
# 1. install deps
python -m pip install -r requirements.txt
# 2. set only the URL in .env  (DATAVERSE_URL=https://YOUR_ORG.crm.dynamics.com)
# 3. preview, then run interactively:
python provision_gtos_dataverse.py --whatif
python provision_gtos_dataverse.py --interactive
```
It prints a code and a link (microsoft.com/devicelogin). Open it in a browser,
sign in with your work/school account, and the script uses *your* Dataverse
permissions (you must be able to customize the environment — Maker / System
Customizer). No secret is stored anywhere.

### B) App-only — client credentials (for automation/CI)
Uses a dedicated app registration + secret. See prerequisites below.

## Prerequisites (one-time) — for app-only (B) only

1. **App registration (Entra ID)** — create an app registration; add a client secret.
2. **Give it Dataverse access (least privilege):**
   - In Power Platform admin center → your environment → **Settings → Users + permissions → Application users → New app user**.
   - Add the app registration as an **Application user**.
   - Assign a security role that allows **customizing entities/metadata** but nothing more than needed (e.g. **System Customizer**). Avoid System Administrator if you can.
3. **Python 3.9+** on Windows or WSL2.

## Setup

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2. configure credentials
cp .env.example .env
#   then edit .env:
#   DATAVERSE_URL=https://org331e3f60.crm.dynamics.com   (your env URL from the browser)
#   TENANT_ID / CLIENT_ID / CLIENT_SECRET
```

## Run

```bash
# preview everything first — NO changes are written:
python provision_gtos_dataverse.py --whatif

# apply for real:
python provision_gtos_dataverse.py
```

The script is **idempotent**: re-running it skips tables/columns/relationships
that already exist, so it is safe to run again after editing `schema.json`.

## What the script does (evidence trail)

For each table it prints one of `[create]` / `[skip]` per table and per column,
then per relationship, then a summary
(`Tables created: N, columns created: M, relationships created: R`). This is your
evidence bundle for the provisioning transformation (see GTOS governance).

Relationships are created **after** all tables and columns exist, so both the
referenced and referencing tables are guaranteed to be present.

## Customizing

- **Change the prefix**: edit `publisherPrefix` in `schema.json` (default `gtos`).
  The prefix must match a publisher in your solution if you use `SOLUTION_NAME`.
- **Add a column**: add an object under a table's `columns` with a `type` of
  `string`, `memo`, `choice`, `boolean`, or `datetime`.
- **Add a table**: copy an existing table block in `schema.json`.
- **Add a relationship**: add an object under the top-level `relationships` array
  with `schemaName`, `referenced`, `referencing`, `lookupSchemaName`,
  `lookupDisplayName`, and (optional) `lookupDescription`. A One-to-Many lookup
  is created on the referencing (child) table pointing at the referenced (parent).

## Security notes (GTOS-aligned)

- **Least privilege**: the app user should have only the roles it needs.
- **No secrets in source control**: `.env` holds the secret; never commit it.
- **Dry run first**: always run `--whatif` before a live run.
- **Not the core**: these tables are a durable *adapter* for GTOS state and
  governance — the deterministic core must not depend solely on Dataverse.
