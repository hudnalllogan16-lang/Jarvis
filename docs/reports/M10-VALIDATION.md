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

## V4 — Temporal outage drill: **PASS on resilience and alerting; one log-discipline finding**

2026-07-29 06:10:11 `docker stop jarvis-temporal-1`; restarted 06:20:13 (10m02s outage).
Scripted 30s sampling throughout (`v4-capture.log`, 20 outage + 9 recovery samples).

Measured, against the design's criteria:
- **`workers` read `unknown`, never zero**, all 20 outage samples, with the honest operator
  copy ("Jarvis can't tell whether anything is picking up work right now"). Overall health
  `ok:false` while `can_serve:true` — the surface told the truth and kept serving.
- **No crash loop, process never exited:** all four parts `running`, restarts 0, runtime
  PID 844 identical before/during/after.
- **Recovery:** SDK pollers reconnected unassisted; health fully `ok` within ~2 minutes of
  the container returning; `workers` back to ok.
- **CORRECTED (2026-07-29, second pass):** the notification pair first attributed to this
  drill actually timestamps to the previous evening's boot — a misreading of an API view
  that omitted timestamps. During V4's Temporal-only outage **no liveness notification
  fired, and that is the designed behavior**: heartbeats stayed fresh (the runtime was
  up), pollers read *unknown*, and the verdict refuses to call "blind" an outage
  (unknown-never-zero, D-046). The operator's surfaces during a pure dependency outage
  are the console (`workers=unknown` with honest copy — verified in all 20 samples) and,
  post-M10-F34, the scheduler's WARNING transition line. Whether a *sustained* unknown
  should eventually escalate to a notification is recorded as a post-M10 operator-surface
  question, not a defect. The verdict's outage/recovery pair was instead demonstrated
  live twice during V6's stop windows (14:26Z, 15:12Z — both announced on the first
  executive pass after restart, per design 9.1's "past outage reliably").
- `/api/ready` stayed 200 throughout: by design — ready gates what a restart would fix
  (migrations/config/DB); a dependency outage is the WAIT posture, and restarting the
  runtime would not help. The truth lived in `/api/health`, where it belongs.
- **M10-F34 (implementation defect, fix dispatched):** the criterion's "exactly one
  WARNING transition line" from the scheduler never appeared — zero structured log lines
  during the window. Cause: the sweep's Temporal client calls retry `Unavailable` inside
  the SDK with unbounded patience, so a 10-minute outage never surfaces to the sweep as a
  failure and P0-E's transition-dedup logging cannot fire for this failure mode. The
  alerting layer above it worked; the log layer beneath needs a bounded RPC deadline.
- **M10-F35 (minor, operational):** temporalio's Rust core writes raw ANSI-colored ERROR
  lines into the otherwise-JSON service log during outages (poller retries). Cosmetic,
  real: log consumers must tolerate mixed formats until routed.

## V5 — wall-clock cron accuracy: **PASS at 0-second deviation** (criterion: ±30s)

Dedicated probe company "V5 Wall-Clock Probe" (`biz_660bdcdd…`, finance-tracking, $5
budget / $0.50 per round); schedule set to `*/5 * * * *` UTC by owner-approved contract
write (provenance recorded: `approved_config`, `owner-chat-approval-2026-07-29`); stale
pre-change execution terminated with recorded reason; sweep reconcile re-dispatched a
fresh execution unassisted in under 4 minutes.

Workflow history (Temporal event log, the platform's own record):
`TimerFired` at 13:35:00, 13:40:00, 13:45:00, 13:50:00, 13:55:00Z — **five consecutive
fires, each at the exact second of its 5-minute boundary**. Cycle work dispatched 9–12s
after each fire. **The anchor never moved:** cycles completed at +21s/+22s/+21s/+26s
offsets, and every next fire computed back to the absolute boundary — D-059's
next-fire-as-absolute-instant behavior, the property M10-F4 found missing, now measured
present. Probe throttled to `0 * * * *` (hourly, owner-approved) for the soak.

## V6 — late-wake honesty: **PASS (served-late branch)**

Service stopped 14:27:28Z (owner-approved elevation), held across the probe's 15:00:00Z
fire, auto-restarted 15:12:09Z by an owner-approved one-shot SYSTEM task — the restart
itself ran with nobody at the machine. (An earlier 14:14–14:26Z stop/start was a
sequencing error by the Manager — clock misread — recorded as an unplanned but clean
operator stop/start drill; NSSM honored operator-stop-stays-stopped in both windows.)

Measured:
- **The missed fire was served once, 722 seconds late** — `wake_lateness_seconds=722`
  in the cycle's decision record, matching the outage duration to the second; every
  on-time cycle records an explicit `0` (the trendable-every-round promise, kept).
- **Zero replayed cycles**; next park computed back to the absolute boundary (16:00Z).
- **The outage rendered afterwards with a duration**: the recovery notification's body
  carries it, and the audit transition rows hold start and end.
- **No late-wake notice — correct**: the notice is the *skip* branch's (design 4.4: a
  wake still unserved when its **next** fire passes). A 45-minute stop against an hourly
  period exercises the *served-late* branch. The skip branch remains demonstrated by
  P0-D's replay fixtures only; a live skip drill would need a stop longer than one full
  period and is recorded as optional residual, not a gap in behavior.

## V7 — console no-op over running service: **PASS** (the headline)

2026-07-29 06:08–06:09. Baseline: all components ok, service runtime PID 844 holding
port 8000. Desktop console opened (PID 7580), alive 20s over the service — service PID
unchanged, all components ok, port never contested (attach, not compete — design 6.3).
Console closed; service unchanged. Repeated (PID 42220): identical. After both rounds all
four companies read exactly as before. Closing the desktop application does nothing to
the platform — the criterion M10 exists to meet, measured.

## Soak (~24h): pending — starts on service runtime, sampler via curl.exe
