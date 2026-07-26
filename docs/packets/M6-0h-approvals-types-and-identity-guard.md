## Packet M6-0h: approvals typing errors + the workflow-less-activity identity guard

**Agent:** security-engineer   **Model:** opus — approval persistence (D-011/D-013) and the
D-002 identity boundary; a plausible mistake corrupts stored approval parameters or widens
identity derivation; type errors here may be real defects.

**Part 1 — `jarvis/approvals/service.py:195`, the last 3 pyright errors in the tree**
```
195:34 error: No overloads for "__init__" match the provided arguments (reportCallIssue)
195:34 error: Cannot assign to attribute "decided_parameters" (reportAttributeAccessIssue)
195:39 error: Argument of type "dict[str, object] | None" ... (reportArgumentType)
```
Investigate whether this is annotation noise or a genuine mismatch between what the service
stores and what `ApprovalRow.decided_parameters` is declared to hold. D-011 is the governing
decision: approval text renders from **stored values**, never model prose — so what gets stored
here is load-bearing for the operator approval surface. If the minimal type-correct change would
alter what is persisted, STOP and escalate with the exact before/after. If it is a real defect
(e.g. `None` can reach a non-nullable column, or the wrong shape is stored), fix it and add a
regression test whose docstring names the finding.

**Part 2 — `jarvis/kernel/runtime.py`: implement the documented rejection (Manager decision,
binding — this resolves M6-0g's escalation)**
`from_activity` reads `activity.info().workflow_id`, which temporalio types `str | None` (None
when an activity was not started by a workflow). Today a None would raise a bare `TypeError`
inside `from_workflow_id`'s regex; the docstring promises `ScopeViolationError`. Decision: add
the guard — a workflow-less activity has no derivable business identity and MUST be rejected
with `ScopeViolationError` (D-002: identity derives from the workflow id; no workflow, no
identity, fail closed). Remove the `# pyright: ignore[reportArgumentType]` M6-0g placed there.
Add a regression test (docstring: finding M6-F4) proving None → `ScopeViolationError`, plus the
negative control (a well-formed workflow id still resolves).

**Acceptance criteria**
- [ ] `uv run pyright jarvis` → 0 errors, no new ignores
- [ ] `uv run pytest -q` → all pass (395 + your new tests); nothing weakened
- [ ] `bash scripts/gates.sh` → exit code quoted; 0 expected — the first fully green run in
      this project's history. If anything else fails, report verbatim, do not chase it.

**Out of scope**
Anything beyond these two files and their tests. Provider code. API surface.

**Escalate instead of deciding if**
- Part 1's fix would change what is persisted or displayed for approvals
- Part 2's guard breaks any existing caller that legitimately runs activities outside workflows
  (if one exists, that is an architectural surprise — stop and report it)
