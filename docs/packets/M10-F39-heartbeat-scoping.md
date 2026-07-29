# Packet M10-F39 — health assessment must scope to the current runtime generation

Lane: `m10-f39` · Branch: `lane/m10-f39` · Owner: platform-engineer · Authority: this
packet + OPERATIONAL-RUNTIME.md Parts 3.3/3.5 + the soak evidence below.

## The defect, measured (soak checkpoint 1, 2026-07-29)

After 6h of soak, `/api/health` reports overall `ok:false` with `runtime: degraded`
("hasn't reported in recently") on every sample — while the live generation's four parts
beat perfectly. Cause, verified in `runtime_heartbeat`: rows from four SUPERSEDED
runtime generations (two ended by clean stop, marked with their `runtime`/`stopped`
row; two ended by taskkill, correctly unmarked) retain `state=running` part rows whose
beats are stale forever. The assessment reads all generations, so any restart leaves the
platform permanently self-reporting degraded. The write side is correct per D-060 (clean
stop vs disappearance ARE distinct recorded facts); the read side fails to scope.

## Mandate

1. The **current-health** verdict (the `runtime` component and whatever
   `assess`/pure-assessment function feeds it in `jarvis/observability/heartbeat.py`)
   scopes to the **newest generation** (latest `started_at`; tie-break `last_beat_at`).
   Superseded generations — any generation older than the newest, whether or not it
   bears a clean-stop marker — never degrade the current verdict.
2. History stays: older generations' rows are untouched (they are how past gaps render
   with a start and an end — design 3.5). No deletion, no migration.
3. A generation whose own `runtime` row says `stopped` is CLOSED — even if it is the
   newest (the window between a clean stop and the next start reads as "stopped
   cleanly," not "degraded").
4. Check the liveness verdict path (`jarvis/executive/liveness.py::assess_runtime_liveness`)
   for the same scoping question — during the soak it did NOT false-alarm, so it may
   already scope correctly; verify and add a regression test either way rather than
   assuming.
5. Tests: a restart sequence (old gen stale + new gen fresh) yields ok=true; a taskkilled
   predecessor doesn't degrade the successor; the CURRENT generation's genuinely stale
   part still degrades; a newest-generation clean stop reads stopped, not degraded.

## Boundaries

`jarvis/observability/heartbeat.py`, the health component wiring in `jarvis/api/app.py`
if needed, `jarvis/executive/liveness.py` only per item 4, tests. No schema changes, no
Supervisor/writer changes.

## Gates

`bash scripts/gates.sh` exit 0 in the worktree (NOTE: gates invoke pytest via
`python -m` — do not change that line; Smart App Control on this host blocks the shim,
see M10-F36). Commit on `lane/m10-f39` only; never merge/push. Report 120/200 words:
scoping rule implemented, liveness-path verdict (item 4 finding), gates + count.
