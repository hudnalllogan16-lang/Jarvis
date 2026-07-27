## Packet M8-8: the contract-refresh mechanism (framework packet C)

**Agent:** platform-engineer   **Model:** opus — Band B's write path touches stored
contracts, graduation state (A-003 reset), and D-029's authority line; a mistake rewrites
what an operator agreed to. Finding range: **M8-F100–F114**. Lane: `lane/m8-8`.

**Objective:** implement docs/design/PLUGIN-FRAMEWORK.md Part 4 exactly: `plan_refresh`
(diff model — per-company, per-band, human-readable field diffs from stored values) and
`apply_refresh` (Band B fields only, atomic per company, audited + Decision Log in operator
language, idempotent per D-024's key discipline). Include **M8-F8**: the A-003 major-version
graduation reset finally implemented (reset on major bump, audited, `plugin_major_version`
column gains its reader/writer; deferred-completion ledger row retired in DEPENDENCIES.md —
that file edit is authorized for the ledger row only). Retire `ManagerState.kpi_targets`
fallback (M8-F46) now that post-wake context carries targets. NO operator surface (packet
M8-9's); NO live-DB writes (M8-6 migrates live — your tests use throwaway DBs).

**Binding:** D-029/D-030/D-032 as recorded; Band C untouchable proven by test (Summit's
$2.00 ceiling shape as the guard case); consent is a required input to `apply_refresh`,
never implied. Gates exit 0; report 400/600; live DB read-only.

**Escalate if** Band B atomicity needs schema change, or the A-003 reset interacts with a
graduated action in any way the design didn't anticipate (none exist live — n=0).
