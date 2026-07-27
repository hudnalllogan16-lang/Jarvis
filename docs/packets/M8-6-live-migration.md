## Packet M8-6: the live migration — three companies through the consented refresh

**Agent:** platform-engineer   **Model:** opus — first writes to the live evidence DB since
M7-3c, through the brand-new mechanism, with the operator consent path as the vehicle.
Finding range: **M8-F160–F169**. Lane: `lane/m8-6` (code diff expected small; the live proof
is the deliverable).

**Part 0 — F153 first:** `ContractRefreshService` derives `metrics_tracked`'s target via
`provisioned_kpi_targets`, same as provisioning — one derivation, not two. Test both paths
agree. Finance type is at 1.0.3 (capability-scoped reports mapping + derived target) — the
live registry adopts it at your worker startup via the version gate.

**Part 1 — migrate, in the design's order, via the REAL consent path** (the wired
`/api/companies/{id}/pending-update/apply` route — you are the operator's hands; the plan
each company shows must be quoted in your report before you apply it):
1. **Summit Trail Gear (negative control):** expect `pending_update: null` at 1.0.1→1.0.1…
   NOTE: affiliate is still 1.0.1 and its stored definition predates D-027 (M8-F3/M8-F60
   drift) — if the drift detector's audit and the plan disagree with "null", report exactly
   what renders; a drifted-same-version type is NOT refreshable by version bump and must not
   be silently "fixed" — that is the recorded design boundary.
2. **Portfolio Watch:** apply; verify attainment 45 → ~78 live (direction lands), the
   Decision Log narrates the update in operator language, Band C proven live (its ceiling
   and budget unchanged), graduation counters untouched (n=0 check before/after).
3. **Trailhead Gear Reviews:** apply; verify `capability.result_returned` leaves its stored
   wake conditions (the M6-F10 loop snapshot finally healed), everything Band C intact.

**Part 2 — evidence:** checksums on untouched scopes before/after; every apply audited +
Decision-Logged; `kpi_values`/health re-read after; one post-migration wake of Portfolio
Watch ONLY if needed to observe the corrected attainment (live spend cap $3; skip if health
recomputes without a cycle). M6/M7 historical rows untouched beyond these consented writes.

Constraints: $≤3; wake nothing but (optionally) Portfolio Watch; never print `.env`; gates
in worktree; commit only if code changed ("M8-6: "); no DECISIONS.md edits. Report 400/600:
Changed / Per-company migration narrative with quoted plans / Band-C live proof / Gates /
Findings M8-F160–F169 / Follow-ups.

**Escalate if** any plan proposes a change outside Band B, the affiliate drift case blocks
Summit's negative control in a way the design didn't anticipate, or an apply touches a
counter.
