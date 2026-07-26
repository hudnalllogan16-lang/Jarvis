## Packet M6-1d: implement D-022 — reservations committed before spend, serialized per scope

**Agent:** security-engineer   **Model:** opus — budget enforcement is a security boundary
(D-003, spec §9/§10); a plausible mistake lets concurrent spend blow through ceilings (observed
live in M6-F12) or deadlocks dispatch; concurrency correctness has no full gate coverage.

**Objective**
The M6-F12 race is closed and the M6-F14 gap is metered: no combination of concurrent
reservations can commit spend past any D-003 ceiling, the Manager's own reasoning calls debit
the cycle ceiling, and parallel dispatch remains observably parallel.

**Context you need**
Read `docs/DECISIONS.md`: D-003, D-021, D-022 (the mechanism you are implementing — its three
numbered points are binding), and the M6-F12/M6-F14 entries. The live race evidence: two
concurrent reservations of one cycle each read 0.00 prior spend, both passed, committed 1.40
against a 1.00 ceiling. Root cause: each dispatch activity holds its own session committing at
activity end, so pre-flight sums cannot see sibling in-flight spend.

**Files in scope**
Read: `jarvis/budget/` (ledger), `jarvis/manager/activities.py` (`plan_cycle`,
`synthesize_results`, `_ask_model`, dispatch path), `jarvis/capabilities/` (invocation
terminal-result path), `migrations/versions/` (chain tip is 0005).
Edit: ledger + a new migration (0006) + the spend-path call sites + tests. Migration must
upgrade cleanly on the live schema (Postgres is running with real M6-1 data — verify against a
scratch database first, then the real one).

**Requirements**
- D-022 point 1: reservation in its own short transaction; per-scope serialization via advisory
  xact lock or `FOR UPDATE` scope row; check counts committed spend + live reservations; the
  serialized section never spans the actual work.
- D-022 point 2: dispatch reservations = the §2.2 allocation; reasoning-call reservations = the
  call's bounded worst-case cost derived from its token ceiling. If a reasoning call has no
  token ceiling today, that is a finding — bound it, don't invent a number silently (state what
  bound you chose and why in the report).
- D-022 point 3: terminality finalizes/releases, riding D-001. A refused reservation follows
  D-003's refusal semantics (rule 5 for the cycle ceiling: `BUDGET_EXHAUSTED` + Decision Log).
- Concurrency proof: a test that runs genuinely concurrent reservations against one scope
  (the M6-F12 shape) and asserts the ceiling holds. SQLite may serialize where Postgres
  doesn't — if the race is only provable against real Postgres, write the test to use the live
  instance the way M6-1b's probe did (own schema, cleaned up, no business data touched) and
  mark it appropriately; a test that passes vacuously on SQLite is the M5-F5 failure mode.
- Determinism: nothing here enters workflow code; all ledger work stays in activities (D-004).
  `tests/test_manager_determinism.py` stays green.

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; test count before → after
- [ ] Concurrency test proves the M6-F12 shape is refused (and states where it runs)
- [ ] Reasoning calls debit the cycle ceiling (M6-F14 closed) — test proves a cycle's plan call
      alone can exhaust a tiny ceiling into `BUDGET_EXHAUSTED`
- [ ] Migration 0006 applied to the live database after scratch verification; outcome reported
- [ ] Parallel-dispatch regression guard still green
- [ ] Report: live vs simulated, exactly; no secrets printed

**Out of scope**
M6-F13 (load_cycle_context policy — separate). The approval path. Any spend-policy change
(ceiling values, D-003 ordering). `docs/DECISIONS.md` — the Manager maintains it; report
findings, don't write them there.

**Escalate instead of deciding if**
- D-022's short-transaction reservation cannot coexist with the existing session-per-activity
  pattern without restructuring `kernel.services()`
- Terminality-based release would require changing the D-001 result contract
- The migration cannot be made safe against the live data
