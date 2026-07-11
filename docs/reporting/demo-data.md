# Demo data seeder

`seed_gtos_demo.py` (repo root) fills the six GTOS tables with one coherent
**charter-verification** scenario so the dashboards in this folder render on real
data instead of empty tables.

## What it creates (11 records)
| Table | Records |
|-------|---------|
| State | `S1 - Draft Charter` (Superseded), `S2 - Verified Charter` (Active) |
| Knowledge | `K1 - Scope assumption`, `K2 - Verification lesson` (each -> a State) |
| Governance | `G1 - Charter Authority` (Approved) |
| Transformation | `T1 - Draft to Verified Charter` (Verified; Input=S1, Output=S2) |
| Audit | `A1 - Charter submitted`, `A2 - Charter approved` (-> G1) |
| Finding | `F1` Blocker/Pass/Accepted, `F2` Major/Pass/Accepted, `F3` Minor/Pending (all -> T1) |

Findings carry `gtos_detectedon` dates spread over the last week so the
time-intelligence measures and the findings-over-time visual have something to plot.

## Run it
```bash
# 1) preview (no writes)
python seed_gtos_demo.py --interactive --whatif

# 2) create the demo records (stamp yourself as owner so RLS demos work)
python seed_gtos_demo.py --interactive --owner you@yourtenant.com

# 3) undo everything it created
python seed_gtos_demo.py --interactive --purge
```

## Properties
- **Idempotent** — records are matched by primary name; re-running skips existing ones.
- **Reversible** — `--purge` deletes exactly these records (children first).
- **Safe** — `--whatif` writes nothing; choice values are read from `schema.json`;
  lookups are bound via each relationship's queried `ReferencingEntityNavigationPropertyName`.
- **Prerequisite** — the model (incl. `gtos_detectedon` on Finding) must be provisioned first.

> This is demonstration data. Purge it before using the environment for anything real.
