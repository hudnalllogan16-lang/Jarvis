## Packet M6-2b: implement D-023 dependency waves + wire the wake-cycle ceiling (M6-F23)

**Agent:** workflow-engineer   **Model:** opus — the dispatch loop in the Manager workflow
changes; determinism (D-004), bounded state (D-005), ceiling semantics (D-021/D-022), the
per-wave parallelism guard (M4-F1), and replay compatibility must hold at once.

**Part 1 — D-023 (quoted in full in docs/DECISIONS.md; its four numbered points are binding)**
The plan schema gains declared dependencies; the workflow dispatches in dependency waves;
dependent requests carry named prior results in their scoped context; a dependency on a
non-SUCCEEDED result means the dependent is not dispatched and synthesis sees why. Update the
planning prompt so the model knows it can (and when it should) declare dependencies — e.g. the
Affiliate flow: research → content(research) → compliance(content), then propose
`affiliate.publish_post` only from a compliance-reviewed draft. Cycles with no dependencies
must behave byte-for-byte as today (replay fixture stays valid, or re-capture per the M6-1b
rules — live spend for a re-capture capped ~$3).

Validation is platform-side (D-013): dependency references must name real invocations in the
same plan, no cycles in the graph, bounded depth (state the bound you choose and why in the
report — this is inside D-023's latitude). Malformed dependency declarations degrade like any
malformed proposal — recorded, skipped, never guessed at.

**Part 2 — M6-F23**
Give `BudgetSettings.default_wake_cycle_ceiling_usd` its reader: provisioning applies it when a
company is created without an explicit ceiling, and the create-company API accepts an explicit
one (operator language in any surfaced copy — §12.5 gate applies). The spec's Defaults in Force
require an explicit ceiling before any business launches: make the contract's ceiling
non-optional at provisioning time (default applied and recorded is fine; absent is not).

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; test count before → after
- [ ] Dependency-wave tests: waves execute in order; within-wave parallelism proven (M4-F1
      shape); non-SUCCEEDED dependency skips dependents with a recorded reason; cyclic/dangling
      declarations degrade safely
- [ ] Determinism + replay green (state which fixture: original or re-captured)
- [ ] A company created without a ceiling gets the configured default, recorded in its contract;
      one created with an explicit ceiling keeps it
- [ ] Report: live vs simulated, exactly

**Out of scope**
M6-3's tool execution. M6-F13/F17/F18 (resilience packet). Prompt tuning beyond dependency
awareness. `docs/DECISIONS.md` — Manager's memory; report findings, don't write them.

**Escalate instead of deciding if**
- Wave dispatch can't be expressed without nondeterminism in the workflow (D-004)
- Carrying prior results would exceed bounded workflow state (D-005) — the results belong in
  activity-fetched context, not workflow state; escalate if that shape doesn't hold
- The §2.2 scoped-request contract needs a new field the capability pool validates — name it,
  propose it, wait
