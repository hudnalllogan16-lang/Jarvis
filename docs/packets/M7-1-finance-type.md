## Packet M7-1: the Finance Tracking type — pure data, or a D-014 escalation

**Agent:** business-type-author   **Model:** sonnet — one invariant (data-only), fully
gate-covered, reversible. Finding range: **M7-F1–F9**. Lane: `lane/m7-1`.

**Objective**
`jarvis/businesses/finance.py` defines the Finance Tracking Business as pure data (D-014),
installable via `ensure_builtin_types`, passing the same data-only AST gate as Affiliate —
**or** an ESCALATION naming exactly what generic machinery a second type turns out to need.
Both outcomes succeed; guessing does not. This packet is the real test of D-014, and its
constraint — you may not touch generic machinery — is the entire point.

**Owner-approved scope (quoted from the accepted M7 plan):** Finance Tracking reads
"operator-configured metrics and public data via the Research capability only — it does not
read other businesses' ledgers or memory." Read-only per spec §13 Step 3: no execution
capability. Trading/brokerage arrive later as separate types (M10/M12), not here.

**The type, as data**
- Identity/version (start 1.0.0), operator-facing template copy (§12.5 language).
- Wake conditions: **schedule-based only.** Nothing is approvable, so no `approval.decided`
  trigger (D-006 still holds platform-wide; this type simply never raises one).
- Capability permissions: `research` and `finance`, with memory/tool/credential scopes limited
  per §2.2 — no tool scopes that perform effects.
- `declared_action_types`: **empty** — read-only means nothing proposable, nothing approvable,
  nothing executable (M6-2's D-013 validation then guarantees any model-proposed action
  degrades to no-action, recorded).
- KPI schema + suggested targets (e.g. metrics-tracked, data-freshness, configured-metric
  values); suggested wake-cycle ceiling (provisioning precedence per M6-2b: explicit →
  configured default → type suggestion).
- Domain prompt/template configuration for plan/synthesize in the finance-tracking domain,
  teaching the model its job is observation and reporting, never action.
- `compliance_requirements` **draft** — reproduce it verbatim in your report: the owner must
  sign it off before any Finance company launches (spec Defaults in Force). Do not launch
  anything.

**Tests** (yours to add): extend the D-014 data-only gate to the finance module exactly as
`tests/test_affiliate_type.py` shapes it (zero functions, zero classes); installation/version
registration test.

**Hard constraints**
Only `jarvis/businesses/finance.py` (or a sibling data module) and its tests. Any need to edit
anything else — contract, provisioning, capabilities, prompts machinery — is an ESCALATION
with the exact missing piece named. No migrations (a data-only type needing schema is itself a
D-014 finding). No company creation, no live runs (M7-3's job).

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-1`; `uv sync --all-extras` first;
gates in the worktree; commit on `lane/m7-1` ("M7-1: ..."); never merge or push.

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0 in the worktree; count before → after
- [ ] Finance passes the D-014 data-only gate; installs by version-gated registration
- [ ] compliance_requirements draft reproduced in the report for owner sign-off
- [ ] Report: verified vs written; findings in M7-F1–F9
