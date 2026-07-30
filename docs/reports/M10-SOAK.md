# M10 Soak Test Results — 24 hours unattended

Window: 2026-07-29 15:16:45Z → 2026-07-30 15:15:33Z. Runtime: the `JarvisRun` NSSM
service (started 15:12:09Z by a scheduled task with nobody at the machine, and never
touched again). Instrument: a 5-minute sampler (`soak.csv`, 288 samples) + the
platform's own decision log, audit log, and notification feed. Owner mandate: "Do not
infer success. Demonstrate it."

## Headline: 288/288 samples nominal, one PID, zero silent failures

| Criterion (owner's list) | Result |
|---|---|
| Scheduler accuracy | **24/24 hourly fires; total lateness across the day: 0 seconds.** Dispatch latency 6–19s after each boundary, improving overnight. |
| Stability | One PID (46668) for the entire window; service `Running` in all 288 samples; zero part restarts; zero NSSM respawns. |
| Memory | Working set 62.3–150.5 MB, mean 103.9, final 73.7 — an OS-trimmed sawtooth with no growth trend. No leak. |
| Queue health / dispatch | `workers=ok` in 288/288 samples; `/api/ready` 200 in 288/288; every due wake served. |
| Heartbeat continuity | Live-generation beats fresh at every sample (evidenced via the workers verdict, parts states, and fire record; the `runtime` component read a cosmetic `degraded` all day — M10-F39, root-caused to superseded-generation scoping, fixed and merged mid-soak, verification at next restart). |
| Recovery | Exercised pre-soak the same day: V2 (6s kill-recovery), V4 (10-min dependency outage, honest degradation, unassisted reconnect), V6 (missed fire served once, 722s lateness recorded). Nothing during the soak required recovery — itself the desired result. |
| **No silent failures** | **The diff closes at zero.** Outcomes in window: 23 `budget_exhausted` + 1 `failed`. The failed cycle's operator notification was created the same second (20:00:08). The budget-exhausted rounds stand behind one unread `unfinished_round` notice per company — §12.5's deliberate dedup, with the count readable in the decision log. Every notification in the window (1 unfinished_round, 2 spending-ladder rungs) traces to its cause. |

## Anomalies

None. The only inline finding of the 24 hours was M10-F39 (found at checkpoint 1 by
the soak itself, fixed and merged within the hour, classification: implementation).
Checkpoint 2 and the final sweep recorded zero anomalies of any class.

## Notes for the record

- The probe company spent the day being *governed*: per-round ceiling stopped 23 rounds
  early, the spending ladder announced half → close in order, and the platform said so
  plainly each time. The soak therefore also demonstrates the budget machinery under
  continuous load.
- The `ok:false` cosmetic in every sample is fully explained, fixed in main, and
  becomes the first thing verified at the closeout restart.
- Environment note: Windows Smart App Control enforcement began mid-campaign
  (M10-F36); it did not affect the running service.
