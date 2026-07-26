## Packet M7-3b: implement D-027 — the cycle measures KPIs

**Agent:** workflow-engineer   **Model:** opus — a new cycle activity touches D-004/D-005/
replay simultaneously; the mapping boundary (facts only, never model prose) is a correctness
judgement no gate fully covers. Finding range: **M7-F30–F39**. Lane: `lane/m7-3b`.

**Objective**
D-027's five numbered points (quoted in full in docs/DECISIONS.md — binding) are implemented:
every completed cycle writes KPI observations for types that declare mappings, Finance
declares them, attainment becomes meaningful, young-company health wording agrees with the
band, and the planning prompt carries the stored compliance_requirements verbatim.

**Scope**
- `jarvis/manager/` — `record_cycle_kpis` activity (after synthesis, before the decision
  record), workflow wiring, timeout-bounded like every activity; determinism gate stays green.
- `jarvis/businesses/finance.py` — KPI mappings as pure data (D-014 gate stays green); bump
  version 1.0.0 → 1.0.1 so the live registry adopts it (M6-F22/M7-F4: version-gated).
- `jarvis/kpi/engine.py` — young-company summary wording (D-027.4): below the stall
  threshold, "Just getting started — no goals hit yet." replaces "Behind on its goals.";
  wording and band must agree in both directions (tests).
- Prompt assembly in `jarvis/manager/activities.py` — include the type's stored
  compliance_requirements verbatim in the planning prompt (D-027.5).
- Tests throughout; the committed replay fixture: adding an activity to the cycle path may
  break replay of the captured history — handle per the M6-1b rules. With no valid model
  credential available (M7-F20), a live re-capture is IMPOSSIBLE right now: if the fixture
  cannot survive, gate the new activity behind the same shape M6-F9 used (or capture-compat
  technique of your choice) and if nothing honest works, ESCALATE with the options — do not
  weaken or delete the replay test, and do not fabricate a fixture.

**Mappings for Finance (D-027.2 — facts only, all derivable offline):**
`reports_delivered` ← count of SUCCEEDED capability results in the cycle whose request was
dispatched by this business; `data_freshness_hours` ← hours since the newest SUCCEEDED
result's recorded completion (in-activity clock read); `metrics_tracked` ← count of KPI
targets configured on the contract. If a mapping you believe correct cannot be derived from
platform facts, leave it unmapped and report it — never let the model author a number.

**Out of scope**
Affiliate mappings (recorded follow-up). Live model calls ($0 — the credential is dead;
everything here is provable offline). The live cycle re-run (M7-3c, blocked on the owner).
Schema changes (`kpi_values` exists). `docs/DECISIONS.md`.

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-3b`; `uv sync --all-extras`
first; gates in the worktree; commit on `lane/m7-3b` ("M7-3b: "); never merge or push.
Never print `.env`.

**Acceptance criteria**
- [ ] Gates exit 0 in the worktree; count before → after
- [ ] A simulated completed cycle writes kpi_values rows for Finance per the mappings; a
      type without mappings writes none (negative control)
- [ ] Attainment computes non-zero when observations meet targets (test both directions)
- [ ] Young-company wording agrees with band; stall wording unchanged past threshold
- [ ] Planning prompt contains the seven stored rules verbatim (test asserts from the
      contract, not from a copy)
- [ ] Replay test green with an honest technique, or an ESCALATION

**Escalate instead of deciding if**
- The activity cannot be added without breaking replay and no honest compatibility technique
  exists offline
- A mapping requires data the platform does not record (that is M8 evidence, not a hack)
- Prompt inclusion would exceed bounded-state or budget assumptions (D-005, D-021)
