## Packet M8-9: the pending-update surface + the owed copy pass (framework packet D)

**Agent:** operator-surface-engineer   **Model:** sonnet — decided semantics, gate-covered,
product-gated. Finding range: **M8-F115–F129**. Lane: `lane/m8-9`.

**Objective:** (1) the pending-update surface per design Part 6: a company with a pending
Band-B refresh shows it ("An update is available for how this company works"), the
field-to-sentence table renders the diff in plain language from stored values, consent =
an explicit operator action wired to `apply_refresh` (D-030: NOT an approval-queue item —
no graduation semantics, distinct visual treatment); `not_ready_count` wired (M8-F61).
(2) The owed copy pass: shell placeholder copy (top-bar status words, notification-center
and parts-of-app empty states, "Updates" label), the park copy (M8-7's STUCK notification +
Decision Log park entry wording), and the D-035 "answered while paused" notification copy.
All §12.5-gated; escaping total; pre-report self-check.

Interface contract: build against M8-8's `plan_refresh` output shape — coordinate by reading
its merged code (it merges before you; if your lane opens first, read its packet's Part 4
reference and stub only in tests). Gates exit 0; live-verify on :8110 read-mostly; $0.
Report 400/600.

**Escalate if** the diff can't render from stored values without model prose (D-011), or
consent UX can't stay visually distinct from approvals without new components (extend the
design system first per its own rule).
