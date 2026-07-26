## Packet M6-1b: enforce the wake-cycle ceiling (D-021) and make cycle failure a survivable outcome

**Agent:** workflow-engineer   **Model:** opus — Manager workflow/activity boundary; five
invariants at once (D-003, D-004, D-005, §2.1 ceiling, §9 failure surfacing); replay
compatibility with captured history must be reasoned about, not assumed.

**Part 1 — implement D-021 (fixes M6-F8)**
D-021 (quoted): "a cycle begins when planning begins. `plan_cycle` (an activity — D-004 keeps
minting out of the workflow) mints the `cycle_id` and it threads through dispatch, synthesis,
and the decision record." Today every `ScopedRequest.cycle_id` is NULL, so the budget ledger's
per-cycle check (`if cycle_id is not None`) never fires — D-003 tier 2 is dead and
`BUDGET_EXHAUSTED` unreachable. Thread the id through the three payloads M6-1's report
identified. Add a test proving a cycle that exhausts its ceiling ends in `BUDGET_EXHAUSTED`
with a Decision Log entry explaining it (D-003 rule 5), and a test that ledger rows now carry
the cycle id.

**Part 2 — fix M6-F9**
An activity failure currently fails the entire Manager workflow (`WORKFLOW_EXECUTION_FAILED`,
observed live) — the business is left Manager-less and `CycleOutcome.FAILED` is unreachable.
§9: "Business Manager wake cycles MUST be independently subject to the same retry/timeout
discipline as any other workflow — a stuck Manager MUST NOT be able to hold a business in an
indefinite pending state without surfacing." Make a failed cycle a *recorded outcome* — the
cycle ends `FAILED`, a Decision Log entry says so in operator language, the workflow survives
to its next wake. Respect existing retry policies on activities; this is about what happens
when retries are exhausted. Add tests, including the negative control (a healthy cycle still
ends `COMPLETED`).

**Replay compatibility**
`tests/fixtures/manager_cycle_history.json` is a captured live history and
`tests/test_manager_replay.py` replays it. If your payload changes break replay of that
fixture, that is expected and acceptable **only if** you re-capture an equivalent history from
a live run (services are up; .env is configured — same secret discipline as M6-1: never print
the key) or justify precisely why the old fixture must be superseded. Never delete the replay
test; never weaken determinism (`tests/test_manager_determinism.py` stays green).

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; report test count before → after
- [ ] Ledger rows from a cycle carry its `cycle_id`; ceiling breach → `BUDGET_EXHAUSTED` + log entry
- [ ] Activity failure past retries → `CycleOutcome.FAILED`, workflow alive, Decision Log entry
- [ ] Replay test green (original fixture or a justified re-capture)
- [ ] Report: live vs simulated, exactly

**Out of scope**
Approval path (M6-2), M6-F7/F10/F11, prompt changes.

**Escalate instead of deciding if**
- Threading `cycle_id` requires changing the event bus contract or a table schema beyond adding
  use of the existing nullable column
- Surviving failure requires changing the continuation model (D-006)
- Any live re-capture would exceed ~$2 model spend
