## Packet M7-3d: attainment learns direction (M7-F30)

**Agent:** platform-engineer   **Model:** sonnet — additive field + one comparison, fully
gate-covered (a characterization test is waiting to flip). Finding range: **M7-F55–F59**.
Lane: `lane/m7-3d`.

**Objective**
Lower-is-better metrics score correctly: `KpiTarget` gains a `direction` field
(`"above"` default | `"below"`), `KpiEngine.attainment` respects it, Finance declares
`data_freshness_hours` as `below`, and the M7-F30 characterization test is rewritten to
assert the *correct* behaviour (1h against a 24h `below` target ≈ full attainment).

**Scope**
- `jarvis/domain/` (KpiTarget) — additive with a default, so the three live companies' stored
  contract JSON deserializes unchanged; PROVE that with a test against a contract snapshot
  lacking the field. If additive-with-default cannot hold (migration or stored-contract break),
  ESCALATE — do not migrate.
- `jarvis/kpi/engine.py` — direction-aware ratio (for `below`: target/actual capped at 1,
  guarding zero-actual; state your zero handling in the report).
- `jarvis/businesses/finance.py` — freshness target direction + version 1.0.1 → 1.0.2.
- Tests: flip the characterization test per its own docstring; both-direction coverage;
  negative control (an `above` metric unaffected).

**Out of scope**
M7-F33 (reports_delivered semantics — a metric-meaning judgement, not this packet).
M7-F31 wording. Anything in `jarvis/manager/`. `docs/DECISIONS.md`. $0 — no model calls.

**Parallel-lane note:** lane/m7-3c is live-running Portfolio Watch from its own worktree
concurrently — you share no files with it (it has a zero-code diff by design). Never touch
the live DB; your tests are SQLite/throwaway only.

**Lane workflow:** `D:\Projects\Jarvis-lanes\m7-3d` only; `uv sync --all-extras`; gates in
worktree; one commit on `lane/m7-3d` ("M7-3d: "); never merge/push. Never print `.env`.

**Acceptance criteria**
- [ ] Gates exit 0; tests before → after
- [ ] Stored-contract compatibility proven by test
- [ ] Characterization test now asserts correctness and passes; both directions covered
- [ ] Report (300/450): Changed / Decisions I did not make / Gates / Verified vs written /
      Findings M7-F55–F59 / Follow-ups
