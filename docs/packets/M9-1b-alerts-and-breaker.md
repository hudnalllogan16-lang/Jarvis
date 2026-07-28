## Packet M9-1b: executive packet C — cap alerts + the breaker''s missing caller

**Agent:** security-engineer  **Model:** opus — budget enforcement territory (the breaker
has had zero callers since M2; §3 CRO: rule-based circuit breakers, real-time, hard stop).
Findings **M9-F75–F84**. Lane: `lane/m9-1b`.

Implement docs/design/EXECUTIVE-LAYER.md packet C exactly: SPENDING alerts at 50/80/breach
of the business cap (the notification kind with zero writers since M3 — read thresholds off
PortfolioRollup''s fields, never recompute — Part 12 sequencing note); the platform
breaker''s caller wired so a breach actually trips and the §12.5 sentence ("Jarvis paused
spending — here''s why") is finally WRITTEN to the platform Decision Log with stored-value
rendering (D-011). Respect the OPEN owner escalation on cap-window semantics: alert on the
recorded lifetime figures with windows labeled (D-040) — do not resolve the window question.
Executive import rule binds (executive imports budget''s PUBLIC api; trip via its existing
public surface; if trip''s call site can''t live outside jarvis/budget cleanly, put the
caller in budget with executive supplying the rollup numbers — your territory, your call,
state it). No timer yet (packet D). Retire the two matching ledger rows. Live DB read-only;
$0. Gates exit 0; commit "M9-1b: "; never merge/push; no DECISIONS.md edits. Report 350/500.
**Escalate if** alert thresholds need contract fields that don''t exist, or trip semantics
would kill in-flight work (D-003 rule 4 forbids).
