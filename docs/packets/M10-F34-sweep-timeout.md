# Packet M10-F34 — bounded RPC deadline on scheduler sweep Temporal calls

Lane: `m10-f34` · Branch: `lane/m10-f34` · Owner: platform-engineer · Authority:
OPERATIONAL-RUNTIME.md Parts 4.6/5.2, DECISIONS.md M10-F34 record, and the V4 evidence in
docs/reports/M10-VALIDATION.md.

## The defect, measured

During a real 10m02s Temporal outage (V4 drill, 2026-07-29), the scheduler emitted zero
log lines: its Temporal client calls sit inside the SDK's own retry of `Unavailable`
with no deadline, so the sweep never observed a failure and P0-E's transition-deduped
connectivity logging (built for exactly this) could not fire. The Executive's
`runtime.liveness_verdict` notified correctly above it; the scheduler's own log
discipline — one WARNING on transition to unreachable, one recovery line — is the gap.

## Mandate

1. Bound every Temporal client call made by the scheduler sweep with a deadline sourced
   from Settings: `SchedulerSettings.sweep_rpc_timeout_seconds`, default 30. Prefer the
   client/SDK's own per-call RPC timeout mechanism over ad-hoc `asyncio.wait_for` if the
   SDK exposes one; either way the deadline must actually fire during an outage.
2. A deadline expiry is a connectivity failure: it feeds the EXISTING transition-dedup
   path (P0-E) so the WARNING fires once on transition, the periodic still-unreachable
   heartbeat and single recovery line behave as already built. No new logging vocabulary.
3. Parameter register row for the new setting (ANNOUNCING / APPROVED_CONFIG), mirroring
   `settings.scheduler.sweep_interval_seconds`. No new actions.
4. Tests: a client fake that hangs past the deadline → step contained, WARNING transition
   logged once across consecutive failing sweeps, recovery logged once when the fake
   heals; deadline value flows from Settings.

## Boundaries

Scheduler/sweep scope only (`jarvis/scheduler/`, Settings, register, tests). Do not touch
executive liveness, heartbeat, workflow code, or worker wiring. Do not weaken D-046
quiet-when-normal: a healthy sweep still logs nothing.

## Gates

`bash scripts/gates.sh` exit 0 in the worktree. Commit on `lane/m10-f34` only; never
merge/push. Report 120/200 words: mechanism chosen (SDK timeout vs wrapper, and why),
gate result + count.
