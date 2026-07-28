## Packet P0-D: wall-clock cron (OPERATIONAL-RUNTIME.md packet D — merges ALONE)

**Agent:** workflow-engineer  **Model:** opus — workflow-shape change under D-033 with
three live executions parked on the old path. Findings **M10-F30–F39**. Lane: `lane/p0-d`.

Implement design Part 7 exactly: `next_fire_at` absolute UTC computed in an activity (real
five-field cron semantics — ''0 9 * * *'' fires at 09:00, ''0 9,16 * * *'' twice daily),
the workflow parks to it behind **PATCH_WALL_CLOCK_SCHEDULE**; one cycle per schedule
period; a missed wake SKIPS with the late-wake notice (the new registered L1 action), never
replays; both fixtures replay unedited with the patch honest per D-033 (neither holds the
new path — scripted boundary pair per precedent); the M10-F13 drift shape becomes a test
(anchor 22:40, next fire 09:00, not 22:40+24h). Design''s dependency note binds: no new
dependency without flagging (croniter vs hand-rolled — justify in one line). $0; live
read-only; no worker starts. Gates exit 0; commit "P0-D: "; never merge/push; no
DECISIONS.md edits. Report 350/500.
**Escalate if** one-cycle-per-period conflicts with any D-021 accounting, or the patch
cannot keep the parked live executions replayable.
