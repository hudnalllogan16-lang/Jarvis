## Packet M6-1: the Manager wakes and completes one cycle, live

**Agent:** workflow-engineer   **Model:** opus, effort high — no gate covers "does this replay
correctly against a real worker"; a mistake surfaces during recovery, not testing; and five
invariants must hold at once (D-004, D-005, D-006, §2.1 cost ceiling, wake-rate bound).

**Objective**
Against a live Temporal worker, a provisioned Affiliate company's Manager wakes on schedule,
runs one full cycle (plan → dispatch a capability → synthesize → write a Decision Log entry),
and suspends — and that cycle replays deterministically.

**Why this is first in the slice**
It is the oldest open row in the deferred-completion ledger and the least-tested link in the
whole transaction path. Everything downstream (approval, execution, audit) assumes the Manager
can actually run. Prove that before building on it. This packet was M6-2 in the prior roadmap;
under revision 4 it becomes the spine of the vertical slice.

**Context you need**
- D-004: workflow code is deterministic; all clock/id/IO lives in activities.
  `tests/test_manager_determinism.py` asserts this against the AST and must stay green.
- D-005: bounded state; `continue_as_new` after `CYCLES_BEFORE_CONTINUATION`; decision history
  in the Decision Log, not workflow state.
- D-006: an approval request *ends* the cycle; `approval.decided` on the bus starts a new one.
- The Affiliate type's wake schedule and its capabilities are already configured in
  `jarvis/businesses/affiliate.py`.

**Files in scope**
Read: `jarvis/manager/{workflow,activities,state}.py`, `jarvis/runtime/worker.py`,
`jarvis/scheduler/service.py`. Edit workflow/activities/worker/tests as needed; prefer adding a
replay test over restructuring the workflow.

**Acceptance criteria**
- [ ] A worker starts and registers `BusinessManagerWorkflow` against live Temporal
- [ ] A provisioned Affiliate company completes one cycle end to end; a Decision Log entry
      appears and is readable via the operator API
- [ ] A replay test using Temporal's replayer against captured history passes
- [ ] Parallel dispatch is observably parallel (regression guard on M4-F1)
- [ ] `bash scripts/gates.sh` passes; report its exit code honestly
- [ ] Report states exactly what ran against live Temporal vs what stayed simulated (and whether
      a real model key was used, or the capability was stubbed — either is fine, but say which)

**Out of scope**
The approval path (M6-2). Tool execution (M6-3). Finance (M7). Prompt tuning beyond what a cycle
needs to complete.

**Escalate instead of deciding if**
- Determinism can only be achieved by moving something across the workflow/activity boundary in
  a way that changes D-004
- A cycle cannot complete without changing the continuation model (D-006)
- Bounded state can't hold without dropping something the Manager needs
