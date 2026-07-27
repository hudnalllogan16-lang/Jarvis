## Packet M8-3: workflow hardening before the framework churns (Lane C, wave 0)

**Agent:** workflow-engineer   **Model:** opus — workflow-shape changes under two replay
fixtures, plus the versioning convention everything pre-production depends on. Finding
range: **M8-F40–F59**. Lane: `lane/m8-3`.

**Why first:** M8's framework work (Lane A) will change workflow-adjacent code; these two
disciplines must exist BEFORE that churn, not after.

**Part 1 — M7-F45, full scope (per audit F-B).** `load_cycle_context` runs before
`_await_wake`, so a woken cycle runs on a snapshot up to a wake-period old — carrying
`measures_kpis`, `day_ordinal` (drives D-021's daily allowance), and the wake-cycle ceiling.
Manager direction (recorded in DECISIONS): the cycle's context loads AFTER the wake — D-021
already defines the cycle as beginning when planning begins. Restructure accordingly;
observed live consequence to eliminate: a type upgrade taking a full extra wake to apply.
BOTH replay fixtures (affiliate 65-event, finance 156-event) must replay honestly — use the
recorded-result gating family of techniques (D-025/D-027 precedents); if no honest technique
exists, ESCALATE with options. Never weaken the determinism gate or a fixture.

**Part 2 — M6-F33: the workflow versioning convention.** M6-3 shipped by terminating and
restarting a Manager; that is recorded as unacceptable for production. Establish the
convention: `workflow.patched()` (or the temporalio-idiomatic equivalent you justify) as the
REQUIRED mechanism for any change to a live workflow path; a test that proves a patched
change replays old history AND executes the new path fresh; documentation as a proposed
D-entry (in your report — Manager writes it); retroactive statement of which M6/M7 changes
would have needed it. Keep it a convention + executable example + gate where checkable —
not speculative infrastructure.

**Out of scope:** M7-F17/M6-F17 cycle-id-on-retry (needs its own decision), resilience
ledger items (F13/F18/F42 — next wave under the 70% rule), anything in Lane A/B territory.
$0 — offline only; live DB read-only; both fixtures are your proof surface.

**Acceptance criteria**
- [ ] Gates exit 0; tests before → after; both fixtures replay; determinism gate green
- [ ] A type-version bump applies on the FIRST post-upgrade cycle (test proves it)
- [ ] Versioning convention: example + test + proposed D-entry in the report
- [ ] Report (400/600): Changed / Decisions I did not make / Gates / Replay honesty / Findings
      M8-F40–F59 / Follow-ups

**Escalate instead of deciding if** post-wake loading breaks D-006's continuation semantics,
the daily-allowance accounting can't survive the move, or versioning needs runtime
infrastructure beyond the SDK's mechanism.
