## Packet M7-3: the first Finance company, provisioned and run live

**Agent:** workflow-engineer   **Model:** opus — first live no-approval cycle shape, a
composition-root edit, and live spend; replay implications must be reasoned about.
Finding range: **M7-F20–F29**. Lane: `lane/m7-3`.

**Part 0 — compliance text (owner-approved, verbatim; replaces the M7-1 draft)**
Update `jarvis/businesses/finance.py`'s `compliance_requirements` to exactly these seven
rules (type stays 1.0.0 — it has never been installed in the live registry):
1. "During M7, Finance operates in observation-only mode. It may collect data, calculate
   KPIs, evaluate portfolio health, and produce research reports."
2. "During M7, Finance must not place orders, modify orders, transfer funds, or perform any
   brokerage write operations."
3. "Finance may evolve in later milestones to generate trade recommendations, risk
   assessments, and eventually execute trades through approved brokerage integrations once
   the architecture explicitly enables those capabilities."
4. "Every reported figure must either cite its source, originate from an approved brokerage
   or market-data provider, or be clearly marked as estimated or unavailable."
5. "Finance may only access data that it is explicitly authorized to access by the
   architecture and business-isolation rules."
6. "Reports generated during M7 are informational only and do not constitute financial,
   investment, legal, or tax advice."
7. "The owner approves these compliance requirements for the M7 launch."
Do not add any permanent "never recommends trades" language anywhere — the owner explicitly
directed against it (DECISIONS.md "M7 owner decision"). D-014 gate stays green.

**Part 1 — M7-F1 fix (Manager-authorized composition-root edit)**
`jarvis/kernel/container.py` `ensure_builtin_types`: replace the hardcoded AFFILIATE handling
with a `BUILTIN_TYPES` tuple (AFFILIATE, FINANCE) iterated with the existing version-gate
logic, changing nothing else about install semantics (M6-F22/M7-F4: version-gated, not
idempotent-reinstall). This is the minimal demonstrated-need fix; the general installer
remains M8 design input — do not generalize further. Test: both builtins install on a fresh
DB; a version bump reinstalls; same-version is skipped.

**Part 2 — provision, live**
Through the real API against the default dev stack (Temporal `default`, Postgres `jarvis` —
the live M6 evidence DB; the Trailhead/Summit history is untouchable): create a Finance
company (pick a sensible operator-facing name), explicit ceiling (the $2.00 default is fine),
KPI targets via the existing contract mechanisms only — if no path exists to configure
per-instance tracked metrics, use the type's suggested targets and record it as the M7-F3
confirmation; do NOT invent a schema or API field (escalate if even the suggested-target path
is broken).

**Part 3 — the live cycle**
The company's Manager completes at least one full live cycle (wake via schedule or explicit
signal, as M6 did): research/finance capabilities dispatch and succeed, KPI rows recorded,
Decision Log narrates in operator language, health computes, the dashboard lists the new
company beside the two M6 companies. **Assert zero approvals were generated** (read-only
proven — `declared_action_types` is empty, so D-013 must degrade any proposed action to
no-action, recorded). If the no-approval cycle shape diverges from the committed replay
fixture's assumptions, capture a new fixture per the M6-1b rules rather than weakening the
replay test. Live spend cap **$5** total; if cycles fail repeatedly for one cause, STOP and
report.

**Out of scope**
Any generic change beyond Part 1's named edit (escalate). Trading/recommendation anything.
M8 installer generalization. `docs/DECISIONS.md`.

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-3`; `uv sync --all-extras`
first; gates in the worktree; commit on `lane/m7-3` ("M7-3: ..."); never merge or push.
Secret discipline: never print `.env` or any key.

**Acceptance criteria**
- [ ] Gates exit 0 in the worktree; count before → after
- [ ] Both builtin types install; Finance company exists via API; dashboard shows 3 companies
- [ ] ≥1 completed live cycle: capability successes, KPI rows, Decision Log entry, health
- [ ] Zero approvals generated, asserted from the DB, stated in the report
- [ ] M6 evidence trail untouched (verified read-only, stated)
- [ ] Report: live vs simulated, exact spend, findings M7-F20–F29

**Escalate instead of deciding if**
- Part 1 cannot stay minimal (install semantics would need to change)
- No existing mechanism sets any KPI target at creation (M7-F3 worst case)
- The no-approval cycle cannot complete without Manager workflow changes beyond capture/replay
