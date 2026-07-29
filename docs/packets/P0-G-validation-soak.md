# Packet P0-G — Production runtime validation + soak (Manager campaign)

Executed by the Manager on the real host — not a lane. It needs the canonical repo, the
live stack, elevation for service install, and it produces evidence artifacts, not code.
Any code defect it finds is classified (implementation / architecture / governance /
operational) and bounced to a lane. Design authority: OPERATIONAL-RUNTIME.md Part 8.
Owner mandate: "Do not infer success. Demonstrate it."

## Preconditions

P0-F merged. Service installed on this host via `scripts/install-service.ps1` (announced
in-session; elevation expected). NSSM SHA-256 recorded into DEPLOYMENT.md at install.

## Stage 1 — Validation matrix (evidence per row, artifacts into docs/reports/M10-VALIDATION.md)

| # | Test | Status under M10-F11 DEFER |
|---|---|---|
| V1 | Logged-out autonomy, 10 min | **OUT OF M10 SCOPE** — infrastructure decision (owner ruling 2026-07-28); measured when the production environment is chosen next phase |
| V2 | `taskkill /F` the runtime; pollers return in throttle window; gap shown as duration | RUN |
| V3 | Reboot recovery | **OUT OF M10 SCOPE** — same ruling as V1 |
| V4 | Stop Temporal 10 min: one WARNING transition + heartbeats, `workers` unknown-never-zero, one recovery line, no crash loop, process never exits | RUN — recorded as measured under current topology |
| V5 | `*/5 * * * *` on one company, three consecutive fires within ±30s, anchor immobile | RUN |
| V6 | Park a Manager, stop runtime past its fire, restart: one late-wake notice, zero replays, lateness recorded | RUN |
| V7 | **Headline.** Open/close the desktop console twice over the running service: zero effect on pollers, heartbeats, companies | RUN |

## Stage 2 — Soak (~24h unattended where practical)

Service left running; checkpoints via scheduled session wakeups (~every 2–4h) sampling:
scheduler accuracy (V5 cadence continuing), heartbeat continuity (no unexplained gaps),
process stability + working-set trend (leak check), queue health (poller counts, backlog),
dispatch reliability (every due wake served or skipped-with-notice, never silently lost),
recovery events (count + cause), and the silent-failure cross-check (every FAILED anywhere
has a matching notification; audit log vs notifications diff). Every anomaly recorded in
docs/reports/M10-SOAK.md with its classification — an anomaly is data, not embarrassment.

## Stage 3 — Closeout inputs

The nine owner deliverables (ops readiness report, implementation summary, architecture
delta, validation results, soak results, remaining risks, debt update, readiness assessment
vs the six criteria, Trading recommendation) and the formal M10 Closeout Report. Readiness
is asserted only where measured; V1/V3 deferral is stated in the assessment, not footnoted.
Trading gate: recommend open only if the evidence supports it.
