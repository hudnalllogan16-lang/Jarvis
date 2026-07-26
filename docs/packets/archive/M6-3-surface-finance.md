## Packet M6-3: surface Finance in the Shell

**Agent:** operator-surface-engineer   **Model:** sonnet — §12.5 compliance is fully
gate-covered, and the blast radius is presentation only.

**Objective**
Make a Finance company creatable and legible in the running application, beside Affiliate,
with no infrastructure vocabulary anywhere an owner can read.

**Context you need**
The template picker already reads installed types from `/api/company-templates`, so if M6-1
installed the type correctly this may need little or no code. **Find out before writing
anything** — if it already works, the correct output is a report saying so plus any test that
locks the behaviour in. Do not manufacture work.

§12.5 is binding and gate-enforced. A Finance company's activity feed, health reason, and any
new copy must read as plain language to a non-technical owner.

Finance Tracking is read-only: it reports, it does not act. If the card or detail view implies
it can spend or transact, that is a correctness defect, not a wording preference.

**Files in scope**
- `jarvis/api/static/index.html` — dashboard
- `jarvis/api/app.py` — only if a payload genuinely lacks a field the UI needs
- `tests/test_operator_language.py` — extend if you add copy

**Acceptance criteria**
- [ ] Finance appears in the New-company flow with a description an owner understands
- [ ] A created Finance company renders a card: health, spend against budget, what it's doing
- [ ] Its detail view shows its activity feed and KPI attainment
- [ ] Nothing in the UI implies it can move money
- [ ] §12.5 gate passes on all new copy
- [ ] `bash scripts/gates.sh` passes

**Out of scope**
Redesigning the dashboard. Charts or visualisations beyond the existing health meter.
Changing the Affiliate presentation.

**Escalate instead of deciding if**
- Presenting Finance well requires a concept not already in the operator vocabulary
- The API genuinely lacks data the card needs (that's a platform-engineer packet)
- Read-only versus acting companies need a visible distinction — that's an operator-model
  decision, not a styling one
