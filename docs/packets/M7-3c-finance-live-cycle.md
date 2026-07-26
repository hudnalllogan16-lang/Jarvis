## Packet M7-3c: the Finance live cycle — first KPI rows in the platform's history

**Agent:** workflow-engineer   **Model:** opus — live Temporal operation against the evidence
database with real spend. Finding range: **M7-F45–F54**. Lane: `lane/m7-3c` (for any fixes
live reality demands; expected diff: zero code).

**Objective**
Portfolio Watch completes ≥1 full live cycle on the current main (D-027 in): capabilities
dispatch and succeed with live model calls, `record_cycle_kpis` writes the first real
`kpi_values` rows per Finance's mappings, the Decision Log narrates, health/attainment
compute from measured values, the dashboard shows three companies — and still **zero
approvals**.

**Context**
- The credential in the main checkout's `.env` is NEW and validated (HTTP 200). Copy it into
  your lane (`Copy-Item D:\Projects\Jarvis\.env D:\Projects\Jarvis-lanes\m7-3c\.env` is
  already done by the Manager). Never print it.
- On worker startup, `ensure_builtin_types` must adopt `finance_tracking` 1.0.1 (mappings) via
  the version gate — verify the registry row before waking anything (M7-F36).
- Portfolio Watch (`biz_08122842…`) is `Running`, Manager parked on its 24h timer after the
  M7-F20 FAILED cycle. Wake it explicitly (signal, as M6/M7 did). **Wake ONLY Portfolio
  Watch.** Do not run the scheduler sweep and do not wake the affiliate companies — Trailhead
  carries the stale pre-M6-F10 wake-condition snapshot, and every affiliate wake is
  unbudgeted-for spend.
- Expected known skews you should observe and report, not chase: attainment direction
  (M7-F30) will depress the freshness component; `reports_delivered` double-count (M7-F33).
- Spend cap **$5**; repeated same-cause failures → STOP and report.

**Verification (all stated in the report with evidence)**
- `kpi_values` rows exist for Portfolio Watch, per-mapping, with plausible values; none for
  the affiliate companies.
- The planning prompt carried the seven compliance rules (assert from the recorded activity
  payload/audit, not by trusting the code).
- Approvals table still exactly 2 rows (both M6's). D-013 degradation path if the model
  proposes anything: recorded, no approval.
- Decision Log entry in operator language; health for Portfolio Watch computed with measured
  attainment; dashboard (API) lists 3 companies.
- M6+M7 evidence untouched beyond Portfolio Watch's own new rows: checksum the two affiliate
  companies' scoped rows before/after (the M7-3 technique).
- Replay: fetch the new live history and confirm it replays (the D-027 gate's first live
  test); if the committed fixture strategy needs a Finance-history fixture added, add it
  under the M6-1b rules — never replace the existing one silently.

**Out of scope**
Code changes unless live reality forces a fix (then: smallest change, report loudly).
M7-F30/F33 fixes (scheduled separately). Affiliate anything. `docs/DECISIONS.md`.

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-3c`; `uv sync --all-extras`
first; gates in the worktree (even for a zero-diff run — prove the tree you ran is green);
commit only if you changed files ("M7-3c: "); never merge or push.

**Acceptance criteria**
- [ ] ≥1 COMPLETED live cycle for Portfolio Watch; exact spend reported
- [ ] First `kpi_values` rows verified in the live DB, mapped correctly
- [ ] Zero new approvals; affiliate rows checksum-identical
- [ ] Gates exit 0; live history replays
- [ ] Report (450/600): Changed / Decisions I did not make / Gates / Live narrative with
      evidence / Findings M7-F45–F54 / Follow-ups
