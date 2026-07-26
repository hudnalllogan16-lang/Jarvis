## Packet M6-4b: security denials must survive their own exception (M6-F38) + empty-payload refusal (M6-F37)

**Agent:** security-engineer   **Model:** opus — audit-trail integrity at the §10 boundary.

**Part 1 — M6-F38.** `BusinessRegistry._deny` records the `security.scope_violation` audit
entry and then raises inside `kernel.services()`, which rolls back on exception — probe showed
1 refusal, 0 persisted rows. Apply the own-transaction pattern (as in M6-4a's
`_assert_identity`): the denial record commits independently before the refusal propagates.
Sweep for the same shape anywhere else an audited refusal raises inside the session scope that
wrote it. Tests must use real commit semantics (the probe shape) — the existing bare-session
tests passed while the behaviour was broken; that class of test is the M5-F5 failure mode and
should be tightened where you touch it.

**Part 2 — M6-F37.** `WebhookPublishTool` publishes empty title/body rather than refusing,
contradicting the documented tool-boundary contract. Refuse at the tool boundary with an
audited, operator-readable failure (§12.5). The stale live approval `apr_1a161…` (payload
`{title}` only) stays unexecuted — it becomes the natural negative-control fixture shape.

**Acceptance:** gates exit 0; denial-persistence test with real commits + negative control;
empty-payload refusal test; report bounded (300/500), live vs simulated, findings continue
from M6-F38.

**Out of scope:** M6-5a surface items; DECISIONS.md.
**Escalate if:** the own-transaction pattern can't reach `_deny` without restructuring
`kernel.services()`, or any denial path can't be made persistent without changing D-001/D-002
semantics.
