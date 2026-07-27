## Packet M8-12: namespace hygiene (M8-F162 — urgent, blocks any worker start)

**Agent:** platform-engineer   **Model:** sonnet — surgical ops with an explicit protection
list + one test-routing change. Finding range: **M8-F170–F175**. Lane: `lane/m8-12`.

1. **Purge the orphans, surgically.** On Temporal `default` (localhost:7233): terminate every
   `BusinessManagerWorkflow` execution EXCEPT the three protected ids —
   `bm-biz_` prefixed ids belonging to Trailhead Gear Reviews, Summit Trail Gear
   (`biz_` per the live DB `business_instances` table — read them first and list all three in
   your report BEFORE terminating anything), and Portfolio Watch (`biz_08122842…`). Count
   before/after; the three survivors verified RUNNING/parked after. Script it
   idempotently (temporalio client, batch, reason string "M8-F162 orphan purge"); a dry-run
   listing first, then the terminate pass.
2. **Route tests off `default` permanently.** Any test or fixture that starts workflows
   against a live Temporal must target a lane namespace (`lane_env.py` exists) or an
   ephemeral/test env — never `default`. Find how the 442 got there (which tests/fixtures),
   fix the routing, and add a guard (test or conftest assertion) that fails any suite run
   pointing workflow-starting fixtures at `default`.

Constraints: the three live Managers are untouchable; live DB read-only; $0; never print
`.env`; gates in worktree; one commit ("M8-12: "); never merge/push; no DECISIONS.md edits.
Report 300/450: Protected ids (from DB) / counts before → after / routing root cause + fix +
guard / Gates / Findings M8-F170–F175.

**Escalate if** any non-BusinessManager workflow types exist on `default` (list, don't
touch), or a protected id is ambiguous.
