# Incident Report — M9-F118: the silent triple failure (2026-07-28 06:14 UTC)

**What happened.** All three companies'' Managers failed their cycles within 7 seconds, each
with `ProviderError: anthropic returned HTTP 404` from `plan_cycle` on final retry — same
worker (PID 36092), same cause ×3. Nine budget reservations reserved and released correctly
(D-034.2 held); $0 spent; zero operator-visible signal.

**Root cause.** Two stacked causes. (1) *The trigger:* a transient API-side 404 on
/v1/messages for the configured model — the Manager''s post-incident probe confirms
`claude-sonnet-5` is currently listed and routes (a probe returns 400-validation, not 404),
so the model id is valid and no config change is warranted. (2) *The amplifier:* the
"simultaneous wake" was a worker-outage artifact — the three wakes had fired independently
7.5–20 hours earlier (WFT_TIMEDOUT, no worker polling) and were drained in one burst when a
short-lived worker started at 06:14. Not synchronized scheduling; a recovery burst.

**The silence chain (every component individually correct).** Retries: exhausted as
designed. M6-F9 containment: caught, logged, parked — as designed. Notifications:
`record_cycle_decision` has NO notification call on FAILED (the park path does; the FAILED
path never did) — structurally silent, not a failed notification. Dead letters: correctly
empty (planning failed before any dispatch). Reliability: counts dead letters only —
mechanically blind to FAILED cycles; read 100 throughout.

**Governance validation.** The incident is the governance model''s motivating exhibit:
Operational Confidence would have read BLIND (no worker polling → the Executive cannot see)
then DEGRADED (cycles failing); Decision Lineage would have exposed the failed plan nodes;
the two-ladder split names what "reliability 100" hid. The governance review''s account was
accurate except the "simultaneous wake" framing — corrected here, because it changes the
fix from scheduling to supervision.

**Fixes.** M9-7 (dispatched): FAILED-cycle notification (the structural silence), startup
model validation fail-loud against the live model list. Recorded, deferred with owners:
worker-supervision posture (the launcher IS the supervised topology; ad-hoc lane workers are
dev artifacts — posture note in the M9 report); reliability''s blindness to FAILED cycles
(joins the M10 metric-semantics pass with M7-F60); Confidence states (G2, governance-gated).
**Recurrence:** with a working worker and the API healthy, tomorrow''s 06:14 wakes should
succeed; if the API blips again, M9-7 makes it loud instead of silent.
