# M10 Closeout Report — Operational Readiness

**STATUS: DRAFT — soak in progress; sections marked ⏳ complete after soak analysis
(~2026-07-30 15:20Z). Nothing in this document is asserted until the draft marker is
removed.**

## Executive Summary ⏳
(Written last, from evidence only.)

## Objectives Completed

Phase 0, complete: one supervised runtime with one part table (P0-A, D-054/D-055);
`jarvis-run` headless entrypoint; runtime heartbeats + `/api/ready` vs `/api/health`
separation (P0-B, D-057/D-058/D-060); two-signal liveness verdict with
transition-deduped operator notices (P0-C); wall-clock cron with skip-not-replay and
per-cycle lateness (P0-D, D-059); scheduler correctness — per-step containment,
transition-deduped connectivity, Settings-sourced interval (P0-E, closes M9-F92);
deployment artifacts — NSSM service scripts, compose restart policy, DEPLOYMENT.md as
one topology authority (P0-F, closes M10-F3/F14); the M9-owed surface pass (P0-H);
preflight/health unification (DEBT-1, closes M8-F44/M9-F155). Windows service
installed and validated on the host of record (NSSM 2.24, hashes pinned).

## Architecture Changes

D-054…D-060 (recorded in DECISIONS.md; drafted in OPERATIONAL-RUNTIME.md Part 10).
Net: the desktop application became a console; the platform became a service. No
governance-model changes; two L1 actions added (liveness verdict, late-wake notice);
AUTONOMY_PIN moved exactly two rows.

## Runtime & Operational Improvements

Two-tier restart proven live (V2: 6s kill-to-recovery). Honest degradation proven live
(V4: unknown-never-zero through a real 10-minute dependency outage; process never
exited). Wall-clock scheduling proven live (V5: five fires at 0s deviation; V6: missed
fire served once, 722s lateness recorded, zero replays). Console-independence proven
live (V7: zero effect from console open/close — the owner's headline criterion).

## Validation Results

docs/reports/M10-VALIDATION.md is the evidence record: V0/V2/V4/V5/V6/V7 measured;
V1/V3 out of M10 scope by owner ruling 2026-07-29 (cold-boot recovery without user
login is an infrastructure decision for the next-phase deployment evaluation, not an
engineering deficiency); late-wake SKIP branch fixture-covered, live drill optional.

## Soak Test Results ⏳
(24h record: docs/reports/M10-SOAK.md — written from soak.csv + audit/notification
diff after completion. Checkpoint 1 at 6h: single PID, flat memory, six fires at 0s
lateness, spending notices correct; M10-F39 found and fixed same-day.)

## Defects Found by Validation (all same-day root-caused)

| Finding | Class | Status |
|---|---|---|
| M10-F34 sweep blind to outages (SDK unbounded retry) | implementation | fixed, merged 1451 |
| M10-F35 SDK ANSI noise in JSON log | operational | recorded, deferred to log-routing pass |
| M10-F36 host App Control blocks unsigned shims | environmental | gates moved to signed interpreter; DEPLOYMENT.md §1a fallback |
| M10-F39 health reads superseded heartbeat generations | implementation | fixed, merged 1457 |
| Manager clock misread (premature V6 restart) | operational (process) | recorded; cost 2 elevations; teardown-after-green restored |

## Performance Observations ⏳
(Memory slope, fire dispatch latencies, recovery timings — from soak.csv.)

## Remaining Risks ⏳
(Drafted after soak; known now: in-band alerting cannot report its own host's death
(design 9.1 — external notifier is M11 scope); single-runtime assumption (9.3); V1/V3
unmeasured pending infrastructure decision; sustained-unknown escalation question.)

## Deferred Work & Technical Debt Update

Out of M10 by owner ruling: deployment-architecture evaluation (Windows native
services / WSL2 / dedicated server / NAS / cloud VM), V1/V3, M10-F33 (no Dockerfile —
container mode parseable, not buildable). Deferred with records: M10-F35 log routing;
sustained-unknown escalation (surface question); late-wake skip-branch live drill;
M9-F160/F134 + M10-F32 ratchet residue sweep (next governance pass); container seam
consolidation (M9-F111); reliability-blind-to-FAILED (M7-F60, metric pass); JS
runner/build tooling retrospective; L3 actor attribution (owner-acknowledged).
Closed this milestone from the register: M8-F44/M9-F155 (DEBT-1), M9-F92, M10-F2/F3/
F4/F5/F7/F14, consent labels + copy minors (P0-H).

## Lessons Learned ⏳
(Includes: the soak found what no test found; validation instruments need the same
rigor as code (Invoke-WebRequest, clock misread); environmental drift (App Control)
is a real mid-campaign actor.)

## Readiness Assessment vs the Owner's Six Criteria ⏳

## Trading / Modules Gate Recommendation ⏳

## Ratification Recommendation ⏳
