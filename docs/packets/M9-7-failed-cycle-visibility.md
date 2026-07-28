## Packet M9-7: the FAILED cycle becomes loud (incident M9-F118 fixes)

**Agent:** workflow-engineer  **Model:** opus — workflow-path change under D-033.
Findings **M9-F150–F159**. Lane: `lane/m9-7`.

Per docs/reports/INCIDENT-M9-F118.md: (1) a FAILED/BUDGET_EXHAUSTED cycle notifies —
`record_cycle_decision` gains the notification the park path already has (operator language,
deduped per company per condition like the park''s, STUCK-family kind or justify a better
one); workflow-path change ships behind a PATCH_* id with per-fixture proof (neither fixture
holds a FAILED cycle — verify, use the scripted-boundary precedent). (2) Startup model
validation: the kernel/worker startup validates `settings.llm.model` against the provider''s
live model list, failing LOUD (supervisor-visible, operator-sentence per §12.5) instead of
deferring to the first plan_cycle; offline/unreachable list = a warning not a refusal (the
API being down must not stop the platform that could still serve read surfaces — state the
posture). (3) The reliability-blind-to-FAILED note goes in code comment + report only
(metric change is the M10 pass — do NOT touch the formula). Live DB read-only; $0 (the
validation test mocks the transport). Gates exit 0; commit "M9-7: "; never merge/push; no
DECISIONS.md edits. Report 300/450.
