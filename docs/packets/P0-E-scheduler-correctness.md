## Packet P0-E: scheduler correctness (OPERATIONAL-RUNTIME.md packet E)

**Agent:** platform-engineer  **Model:** sonnet — enumerated fixes per the design.
Findings **M10-F60–F69**. Lane: `lane/p0-e`.

Implement design packet E exactly: `run_scheduler`''s interval Settings-sourced (M9-F92 —
the config prose already names the gap; ANNOUNCING row per the register discipline);
per-step sweep containment (one failing sweep step — events, timers, reconcile,
managers_started — logs and continues, never kills the sweep; M6-F9 family); the
`managers_started` trigger in the sweep result (design recovery section); the `failing`
part state after 10 crashes (Supervisor semantics per design Part 2.3 — if this crosses
D-016/D-017 mechanism, ESCALATE); transition-deduped outage logging on scheduler DB/Temporal
connectivity (states not alerts). Sibling lane p0-c runs concurrently — it owns
executive/liveness + the probe; you own scheduler/ + supervisor state; the parameter
register is the known shared hotspot (append with a section comment, expect the queue to
compose). Scripted harness; $0; live read-only; report-don''t-kill. Gates exit 0; commit
"P0-E: "; never merge/push; no DECISIONS.md edits. Report 300/450.
