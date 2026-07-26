## Packet M6-3: approved action executes, trail recorded

**Agent:** security-engineer   **Model:** opus, effort high — tool execution materialises
credentials and performs the real effect (§10, D-015); full review always.

**Objective**
The approved action runs through the tool boundary, the effect is performed idempotently with
credentials materialised only inside the tool call, and the complete trail — audit log entries
and a human-readable Decision Log narrative — is recorded and visible in the operator API.

**Why this is last in the slice**
It closes the loop: an approved decision becomes a real, recorded effect. With this green, the
entire path from "create company" to "audited completed action" is proven, and the platform —
not just its parts — is validated.

**Context you need**
- D-015: tools run only on the approved-action path; capabilities produce content, tools perform
  effects; the effect executes after the §8 gate, never from a model call directly.
- §10: credentials materialise inside the tool call and nowhere else — never in a prompt, log,
  or result. Verify this holds on the live path.
- §6 / A-001: effects are idempotent; a retried or replayed approved action replays its recorded
  result rather than performing twice.
- The executor is `jarvis/capabilities/tools.py`; the approved-action activity is in
  `jarvis/manager/activities.py` (`execute_approved_action`); it runs the operator's *decided*
  parameters (A-003 correction semantics), not the originally proposed ones.

**Files in scope**
Read: `jarvis/capabilities/tools.py`, `jarvis/manager/activities.py`,
`jarvis/observability/{audit,decision_log}.py`, `jarvis/api/app.py` (activity-feed / full-detail
routes). The Affiliate type's publish tool is `WebhookPublishTool`; a real webhook needs a URL +
credential handle, but the path can be proven against a mock endpoint — say which you used.

**Acceptance criteria**
- [ ] An approved Affiliate action executes through `ToolExecutor` on the live path
- [ ] The credential is present in the outgoing call and absent from the result, the logs, and
      any prompt (assert this — it is the §10 guarantee)
- [ ] Re-running the same approved action replays the recorded result; the effect happens once
- [ ] The audit log records the execution; the Decision Log carries a plain-language narrative
- [ ] Both are retrievable via the operator API (activity feed + full-details drill-down)
- [ ] `bash scripts/gates.sh` passes
- [ ] Report: mock vs real endpoint; what ran live vs simulated

**Out of scope**
Finance (M7). New tools. Retry-policy changes. Anything that widens a credential scope.

**Escalate instead of deciding if**
- Idempotency can't hold without a new persistent mechanism
- A credential must exist somewhere new to make execution work
- The decided-vs-proposed parameter distinction (A-003) needs to change
