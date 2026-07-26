## Packet M6-2: approval generated, operator decides, cycle resumes

**Agent:** security-engineer   **Model:** opus, effort high — this is the human-authority
boundary (§8), full review always, and the continuation model (D-006) is subtle.

**Objective**
A Manager cycle proposes an action requiring approval; the approval appears in the operator
API and dashboard with §8's four facts rendered from stored values; the operator approves; and
`approval.decided` reaches the Manager and starts a new cycle that proceeds.

**Why this is second**
M6-1 proves a cycle runs. This proves the cycle can *pause for a human and resume* — the
mechanism that makes Jarvis safe rather than merely autonomous. It exercises D-006 end to end
for the first time, the loop that finding M5-F4 discovered was silently open and closed on paper.

**Context you need**
- §8: approval by default; the UI shows action, exact amount, triggering condition, downside.
- D-011: approval text renders from stored structured values, never model prose. Verify the
  amount the operator sees is the stored value, not regenerated text.
- D-006: the requesting cycle ends as `AWAITING_APPROVAL`; the operator's decision is published
  as `approval.decided`; the scheduler signals the Manager; a new cycle begins.
- The publish is in `jarvis/approvals/service.py`; the signal path is in
  `jarvis/scheduler/service.py` (`dispatch_events`).

**Files in scope**
Read: `jarvis/approvals/{service,models,rendering}.py`, `jarvis/manager/workflow.py`,
`jarvis/scheduler/service.py`, `jarvis/api/app.py` (approval routes). Edit as needed to make the
round trip work; add tests for the resume path.

**Acceptance criteria**
- [ ] A cycle that proposes an approval-required action ends `AWAITING_APPROVAL`, does not block
- [ ] The approval is listed by `/api/approvals` with all four §8 facts, in plain language
- [ ] Approving via the API publishes `approval.decided`; the scheduler signals the Manager
- [ ] The Manager starts a new cycle on that signal and proceeds past the approval
- [ ] A denied approval resets the graduation streak (D-010) and the cycle does not execute
- [ ] `bash scripts/gates.sh` passes, §12.5 gate included
- [ ] Report: what ran live vs simulated

**Out of scope**
Tool execution of the approved action (M6-3). Finance (M7). New autonomy policies.

**Escalate instead of deciding if**
- Resuming requires changing what ends a cycle (D-006)
- The approval can't render from stored values without model involvement (would violate D-011)
- Making the signal reliable needs a new persistent mechanism (that's a decision, not a fix)
