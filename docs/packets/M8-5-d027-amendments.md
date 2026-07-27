## Packet M8-5: the D-027 amendment pass — metric semantics (wave 3 Lane B)

**Agent:** platform-engineer   **Model:** sonnet — Manager rulings below are binding; gates
+ existing KPI tests cover. Finding range: **M8-F150–F159**. Lane: `lane/m8-5`.

**Rulings (record-backed, implement exactly):**
1. **M7-F33:** `KpiMapping` gains an optional capability filter (pure data, D-014-safe);
   Finance's `reports_delivered` counts finance-capability successes only. Type version
   bumps (minor). A cycle running research+finance scores 1 report for 1 report.
2. **M7-F49:** `metrics_tracked`'s TARGET derives from the type's own configured target
   count at provisioning (3 targets → target 3, reads 3/3) — the structural 60% cap dies.
   Provisioning-time derivation, not a live formula; existing companies get it via a Band B
   refresh (M8-6 will carry it live).
3. **M7-F32:** `record_cycle_kpis` also runs on NOTHING_TO_DO outcomes; each `KpiSource`
   declares (platform-owned property) whether it is cycle-result-scoped (records only with
   results: reports) or observation-scoped (records on any completed wake: metrics_tracked,
   freshness — freshness reads the latest audit fact, which exists independent of this
   cycle's results). Workflow change if any → D-033 discipline.
4. **M7-F60 (declared out of scope):** result-usefulness vs invocation-success needs
   capability-result semantics that M10's trading analysis will actually shape — deferred to
   M9/M10, recorded. Do not touch reliability semantics.

Constraints: both replay fixtures; determinism gate; D-014 gate (filter is data); $0; live
DB read-only; gates in worktree; one commit ("M8-5: "); never merge/push; no DECISIONS.md
edits. Report 350/500. **Escalate if** ruling 3 can't ride recorded-result gating honestly,
or ruling 2's derivation fights explicit operator-set targets (precedence: explicit wins).
