## Packet M6-2: Business Manager's first live run

**Agent:** workflow-engineer   **Model:** opus — no gate covers "does this replay correctly
against a real worker", blast radius includes silent nondeterminism that surfaces only during
recovery, and five invariants must hold simultaneously (D-004 determinism, D-005 bounded
state, D-006 continuation, §2.1 cost ceiling, wake-rate bound).

**Objective**
Run `BusinessManagerWorkflow` against a live Temporal worker for the first time, prove one
complete wake cycle executes and replays deterministically, and fix what that reveals.

**Why this packet matters**
This is the oldest open row in the deferred-completion ledger. The workflow's determinism is
asserted only at source level — the AST gate proves the code contains no clock read, but
nothing has proven it actually replays. A replay divergence appears during recovery, which is
when it is least affordable, so this must be verified before more businesses depend on it.

**Context you need**
D-004: Temporal history is the replay substrate; all nondeterminism lives in activities.
`tests/test_manager_determinism.py` enforces this against the AST of
`jarvis/manager/workflow.py` and must keep passing.

D-005: workflow state is a bounded working set; `continue_as_new` after
`CYCLES_BEFORE_CONTINUATION`. Decision history lives in the Decision Log, not workflow state.

D-006: an approval request *ends* the cycle. The Manager does not park waiting for an answer;
the operator's decision arrives as an event that starts a new cycle. `approval.decided` is
published to the bus by `jarvis/approvals/service.py` — that loop was closed in M5 (finding
M5-F4) but has never been exercised live.

**Files in scope**
Read first:
- `jarvis/manager/workflow.py`, `jarvis/manager/activities.py`, `jarvis/manager/state.py`
- `jarvis/runtime/worker.py` — registration
- `jarvis/scheduler/service.py` — `dispatch_events` signals the Manager

You may edit workflow, activities, worker registration, and tests. Prefer adding a replay
test over changing workflow structure.

**Acceptance criteria**
- [ ] A Temporal worker starts and registers `BusinessManagerWorkflow` without error
- [ ] One wake cycle runs end to end for an Affiliate company: context loaded → plan →
      capability dispatch → synthesis → Decision Log entry written
- [ ] A replay test exists using Temporal's replayer against captured history, and passes
- [ ] Parallel dispatch is observably parallel, not sequential (regression on M4-F1)
- [ ] An approval-raising cycle ends as `AWAITING_APPROVAL` rather than blocking, and a
      subsequent `approval.decided` event starts a new cycle
- [ ] `bash scripts/gates.sh` passes, determinism gate included
- [ ] Report states plainly what ran against live Temporal versus what remains simulated

**Out of scope**
New capabilities. Changing the plan/synthesis prompts beyond what's needed to make a cycle
complete. The Finance type (packet M6-1). Executive Layer concerns.

**Escalate instead of deciding if**
- Determinism can only be achieved by moving something out of an activity into the workflow,
  or vice versa, in a way that changes D-004's boundary
- The continuation model needs to change for a cycle to complete
- Bounded state cannot be maintained without dropping something the Manager needs
- A real model call is required to prove the cycle, and no key is configured — report this
  rather than stubbing the model silently
