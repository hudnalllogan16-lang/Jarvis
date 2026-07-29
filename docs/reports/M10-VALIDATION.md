# M10 Production Runtime Validation — evidence record

Campaign per `docs/packets/P0-G-validation-soak.md`, executed by the Manager on the real
host (Windows 11 Pro, the development machine). Owner mandate: "Do not infer success.
Demonstrate it." Every claim below is a measurement with its instrument named. V1/V3 are
out of M10 scope by owner ruling 2026-07-28 (cold-boot recovery without user login is an
infrastructure decision — see DEPLOYMENT.md §M10-F11); everything else is measured here.

## Environment of record

- Host: Windows 11 Pro 10.0.26200; repo `D:\Projects\Jarvis` at Phase 0 complete (A–F),
  1441 tests, gates exit 0.
- Dependencies: docker compose services `postgres`, `redis`, `temporal`, `temporal-ui`,
  all recreated 2026-07-28 with `restart: unless-stopped` (M10-F14 closed on-host;
  postgres data volume `jarvis_jarvis-pg` verified named-volume before recreation).
- Service: `JarvisRun` under NSSM 2.24 (zip SHA-256 `727d1e42…aa6743`, binary
  `f689ee9a…06c97`, at `C:\Tools\nssm-2.24\win64\nssm.exe`), installed 2026-07-29 by
  `scripts/install-service.ps1` unmodified, values verified equal to design 6.1. Start
  type Automatic (Delayed). Logs: `logs\jarvis-run.log`, rotating.

## V0 (unscripted) — first headless life + overnight continuity

2026-07-28 17:29: `jarvis-run` started headless as a plain process — the platform's first
run with no desktop app and no console anywhere. `/api/ready` 200; `/api/health` all five
components ok, including Phase 0's `runtime` (heartbeat) and `workers` (poller probe).
It then served unattended overnight: at 2026-07-29 ~05:45, ~12.5 hours later, the same
process still answered 200 with all components ok. No restarts, no supervisor. Stopped
deliberately at 05:54 to hand the port to the service.

## V2 — kill recovery under NSSM: **PASS**

- 05:56:59 service first start: preflight ok on all components, ready 200.
- 05:58:27 `taskkill /F` (elevated, owner-approved) on runtime PID 6136.
- 05:58:33 kernel re-initialised on a fresh PID (service log timestamps): **6 seconds**
  kill-to-restart — AppRestartDelay 5000ms + spawn — far inside the 60s throttle window.
  Service `Running` throughout from the SCM's view; `/api/ready` 200 on the new process;
  new PID 844 confirmed listening.
- Criterion "console shows the gap as a duration": the 6s outage is *below* the 45s
  heartbeat staleness threshold, so no gap renders — recovery outran the instrument that
  would have displayed it. The gap-rendering path is exercised instead by the deliberate
  17:29→05:54/05:56 handover (previous runtime's final beats vs the service runtime's
  first), verified in the soak analysis.
- Tooling note (not a platform defect): PS 5.1 `Invoke-WebRequest` cached a dead
  keep-alive connection and mis-reported the recovery window; server-side logs are the
  evidence of record, and all further probing uses `curl.exe`.

## V4 — Temporal outage drill: pending (scripted background capture)

## V5 — wall-clock cron accuracy: pending (dedicated test company; parked companies untouched)

## V6 — late-wake honesty: pending (requires elevated service stop/start — evening window)

## V7 — console no-op over running service: pending

## Soak (~24h): pending — starts on service runtime, sampler via curl.exe
