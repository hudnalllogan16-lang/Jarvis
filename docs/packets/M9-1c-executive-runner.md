## Packet M9-1c: executive packet D — the runner (D-041)

**Agent:** platform-engineer  **Model:** sonnet — wiring per a merged design; gate-covered.
Findings **M9-F90–F99**. Lane: `lane/m9-1c`.

Implement docs/design/EXECUTIVE-LAYER.md packet D exactly: the Executive''s own asyncio
timer at `runtime/worker.py` (D-041 — never a workflow, never Scheduler.sweep; composition
root may import executive), interval from Settings (design names it; default per design),
each tick: rollup → census → raise_spend_alerts → record_platform_halt, all reads/writes
through the existing public surfaces. Resolve M9-F78/F79: ONE Settings value feeds rollup
ceiling AND breaker (source exactly as container.py does); the 24h window constant
single-sourced (budget''s PLATFORM_SPEND_WINDOW). M9-F83: add the 50/80 warning bands for
the PLATFORM ceiling in the same alert pass (same fixed-copy table pattern — §12.5 language,
windows labeled). Retire the M9-F84 ledger row + the alerts row. Tick failure: contained,
logged, next tick unaffected (M6-F9 family); no tick overlap. Tests incl. a scripted
two-tick run proving once-per-halt and band-dedupe survive ticks. Live DB read-only in
tests; $0; NO live worker start needed (scripted harness like M8-7''s). Gates exit 0;
commit "M9-1c: "; never merge/push; no DECISIONS.md edits. Report 300/450.
**Escalate if** the timer can''t live in worker.py without supervisor changes (D-016/17) or
tick semantics need a new persistence mechanism.
