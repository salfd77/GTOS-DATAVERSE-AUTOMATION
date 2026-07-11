---
name: gtos-orchestration
version: 1.1.0
description: >
  Multi-task, multi-orchestrator, multi-agent operating model for GTOS work.
  Defines the roles (Planning Manager, Critics, Engineers, Execution Manager,
  Executive Manager), their handoffs, the approval gates, and how to fan work
  out across parallel tasks/agents and reconcile the results — so every GTOS
  deliverable passes plan → critique → execute → approve before it reaches the user.
triggers:
  - gtos orchestrate
  - gtos pipeline
  - multi agent gtos
  - multi task gtos
  - plan critics execute
  - run the pipeline
  - log chain of thoughts
---

# GTOS Multi-Agent Orchestration

## 1. When to use this
Use for any non-trivial GTOS deliverable (a skill, a schema change, a workflow, a
report design). It formalizes the role-based pipeline the project already uses:
**Planning Manager → Critics + Manager review → approve → Execution Manager →
Critics wake Engineers for fixes → Executive Manager approves → present to user.**
Skip it only for trivial, single-step edits.

## 2. Roles (the agents)
| Role | Mandate | Output |
|------|---------|--------|
| **Planning Manager** | Decompose the request into tasks, dependencies, acceptance criteria | `01_task_plan.md` |
| **Critics** (Architecture / Security / Quality) | Independently review plan & output; find gaps, risks, drift | `02_review_notes.md` |
| **Engineers** | Implement the tasks; apply fixes the critics raise | code / artifacts |
| **Execution Manager** | Sequence execution, track task state, drive fixes to done | `03_exec_log.md` |
| **Executive Manager** | Final gate; verify acceptance criteria met; sign off | sign-off in exec log |
| **Orchestrator** (you) | Route work between roles, enforce gates, keep artifacts in sync | the presented result |

## 3. The pipeline (single orchestrator)
```
User request
   │
   ▼
[Planning Manager] ─ decompose ─► 01_task_plan.md
   │
   ▼
[Critics + Manager] ─ review plan ─► 02_review_notes.md
   │        (gate 1: plan approved?)  ──no──► back to Planning
   ▼ yes
[Execution Manager] ─ assign ─► [Engineers] implement
   │                                   │
   │   ◄── Critics watch, raise fixes ─┘
   │        (gate 2: all fixes resolved?) ──no──► wake Engineers
   ▼ yes
[Executive Manager] ─ verify acceptance ─► sign-off (03_exec_log.md)
   │        (gate 3: signed off?) ──no──► back to Execution
   ▼ yes
Present to user
```

Three hard gates: **plan approved**, **fixes resolved**, **executive sign-off**.
Nothing reaches the user before gate 3.

## 4. Multi-task fan-out
When the request splits into independent tasks (e.g. "build workflow" + "build report
skill" + "build orchestration skill"):
1. Planning Manager lists tasks with an explicit **dependency graph** and marks which
   are parallel-safe (no shared files, no ordering constraint).
2. Execution Manager runs parallel-safe tasks concurrently (batch the tool calls),
   serializes only where a dependency exists.
3. Each task carries its own acceptance criteria; a task is "done" only when its
   criteria pass and critics have no open items on it.
4. Reconcile: before the executive gate, check cross-task consistency (naming,
   shared conventions, no conflicting edits to the same artifact).

## 5. Multi-orchestrator (scaling out)
For large efforts, run more than one orchestrator, each owning a **bounded context**
(e.g. one owns "provisioning/CI", another owns "reporting layer"):
- Each orchestrator runs its own full pipeline (§3) inside its context.
- A **lead orchestrator** owns the shared contract between contexts (schema names,
  prefixes, security model) and resolves cross-context conflicts.
- Handoff between orchestrators is a written artifact (plan + acceptance + sign-off),
  never an implicit assumption.
- Keep contexts loosely coupled: shared truth lives in `schema.json` / memory, not in
  one orchestrator's head.

## 6. Multi-agent handoff contract
Every handoff between roles/agents must carry:
- **Goal + acceptance criteria** (what "done" means).
- **Inputs / ground truth** (schema, env `org331e3f60`, prefix `gtos_`, existing tables).
- **Constraints** (least privilege, dry-run first, no secrets in source, read-only
  reporting layer).
- **Open questions** (explicitly listed, never silently assumed).
A handoff without acceptance criteria is rejected by the receiving role.

## 7. Artifacts (evidence trail — GTOS-aligned)
Persist these per deliverable (mirrors `gtos_audit` discipline):
- `01_task_plan.md` — Planning Manager output.
- `02_review_notes.md` — Critics + manager review.
- `03_exec_log.md` — execution log + executive sign-off.
These are the deliverable's evidence bundle; keep them with the work.

## 8. Guardrails
- **No gate-skipping.** Even under time pressure, the three gates hold.
- **Critics are independent.** A critic never approves work they implemented.
- **Ground truth over memory.** Always re-read `schema.json` / project memory before
  planning; do not act on stale assumptions.
- **Least privilege end-to-end.** Same security posture as the rest of GTOS.
- **Present only after sign-off.** The user sees the result *and* the evidence trail.

## 9. Verification checklist
- [ ] `01_task_plan.md` exists with tasks + dependency graph + acceptance criteria.
- [ ] `02_review_notes.md` records critic findings and their resolution.
- [ ] Parallel-safe tasks were actually fanned out; dependencies serialized.
- [ ] Cross-task/cross-context consistency reconciled.
- [ ] `03_exec_log.md` carries the executive sign-off.
- [ ] Only signed-off work was presented to the user.

## 10. Chain-of-Thought logging (transparency + governed evidence)
When this pipeline runs as a **Copilot Studio agent**, make the orchestrator's
intermediate reasoning visible and auditable using the PowerCAT Copilot Studio Kit
**"Log Chain of Thoughts"** component.

### 10.1 What the component does
It is a topic with one required string input `CoT` that emits the reasoning back to
the conversation as an italicized message:
```
Activity:  _Thinking: {Topic.CoT}_
```
So after every tool, topic, or step, the agent narrates *why* it did it. This is the
conversational equivalent of the `03_exec_log.md` evidence trail — but live.

### 10.2 Install (one-time, in Copilot Studio)
1. Import the managed solution `CopilotStudioKit_LogCoT_Component` (publisher PowerCAT,
   prefix `cat`) into the environment, **or** add it from Agent Library → Component
   collection → *Log Chain of Thoughts* → **Import**.
2. Add this instruction to the agent:
   > "After every tool, topic, or step you take (except when you are already calling
   > /Log Chain of Thoughts or other debug/logging topics), log your intermediate
   > reasoning by calling /Log Chain of Thoughts."

### 10.3 GTOS wiring — gate it, don't leak it
CoT is powerful but must respect the same guardrails:
- **Governance/PII:** never emit secrets, tokens, or raw personal data in `CoT`.
  Log the *decision and rationale*, not credentials or full record payloads.
- **Gate visibility by audience:** enable CoT for builders/critics; for end users,
  keep it on only when transparency is explicitly wanted (it is verbose).
- **Map CoT to the gates (§3):** at gate 1/2/3 the CoT message should state which
  gate was evaluated and its outcome (e.g. `_Thinking: gate 2 — 0 open critic items,
  proceeding to executive review_`). This makes gate decisions self-documenting.

### 10.4 Persist CoT as GTOS audit evidence (optional)
To turn transient CoT into durable evidence aligned with `gtos_audit`, after a
significant step also write an audit row:
- `gtos_name` — short step label (e.g. "Gate 2 passed: relationships verified").
- `gtos_actor` — the agent/orchestrator identity (UPN).
- `gtos_action` — the CoT rationale (trimmed, no secrets).
- `gtos_occurredon` — timestamp.
- `gtos_evidencelink` — link to the plan/PR/exec-log artifact.
- Bind `gtos_audit_governance` to the governing `gtos_governance` record.

This makes the reasoning queryable in the reporting layer (the Audit trail page in
`docs/reporting/`), so "why did the agent do X?" is answerable months later.

### 10.5 Verification checklist (CoT)
- [ ] Component imported; agent instruction added.
- [ ] CoT messages appear per step and name the gate at each gate.
- [ ] No secrets/PII ever appear in a CoT message.
- [ ] (If persisted) audit rows created for significant steps and visible in the
      Audit trail report.
