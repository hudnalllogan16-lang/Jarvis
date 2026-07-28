## Packet P0-A: one part table, the headless platform (OPERATIONAL-RUNTIME.md packet A)

**Agent:** platform-engineer  **Model:** opus — a new composition root + topology surgery.
Findings **M10-F20–F29**. Lane: `lane/p0-a`.

Implement design Parts 2–4 exactly: `jarvis/shell/service.py` (the ONE part table +
`bootstrap(posture)` + `build_supervisor`), `jarvis-run` headless entrypoint (signals, exit
codes, WAIT posture), the desktop launcher reduced to bootstrap+window (REFUSE posture),
**delete `worker.py::main`**, api-only untouched as console, `test_one_part_table`
(AST: Supervisor.add from exactly one module) + the posture tests. Registry/parameter rows
per the design''s governance section (two L1 actions, seven parameters — the two honest
PLATFORM_DEFAULTs stay flagged). $0; live DB/Temporal read-only; no worker/service starts
(scripted harness); report port conflicts, never kill unowned. Gates exit 0; commit
"P0-A: "; never merge/push; no DECISIONS.md edits. Report 350/500.
**Escalate if** the one-table rule can''t hold without touching D-016/D-017 semantics.
