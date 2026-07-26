## Packet M7-5a: the REVISE round — the operator sees what kind of company it is, and what it measured

**Agent:** operator-surface-engineer   **Model:** sonnet — decided items, render-side,
gate-covered. Finding range: **M7-F61–F69**. Lane: `lane/m7-5a`.

**Items (from the M7-5 verdict and ranked opens, all recorded in DECISIONS.md)**
1. **Company identity survives creation.** The company payload (`/api/companies` and the
   detail route) carries the type's operator-facing display name and its descriptor sentence
   (for Finance: "It reads and reports only: it places no trades and moves no money") — from
   STORED type/template data, never model prose. The card shows the kind; Details shows the
   sentence. All three live companies must render distinguishably (verify live on :8110).
2. **Render `health_parts`.** `app.py:140` computes `{"Budget left", "Finishing its work",
   "Hitting its goals"}` and nothing consumes it. Render the three parts (card or Details —
   your layout call, stated in one line) in plain language. Where goals are measured, the
   drill-down should let the operator see what was measured against what (the API may need to
   ship the per-metric readings — stored values from `kpi_values`/targets, plain-language
   metric names via the type's display strings; if a metric has no display string, humanize
   the key).
3. **M7-F53 — wording agrees with the band.** Mature company, healthy band, partial
   attainment: the summary must not contradict the badge ("Healthy overall — goals need
   attention." or better §12.5 language). Young-company and stall wording unchanged. Both
   directions tested.
4. **M7-F50 render-side mitigation.** Add milestone codenames (word-boundary `M6`/`M7`/`M8`)
   and `KPI`/`KPIs` to the runtime guard vocabulary so feed prose echoing internal framing
   falls back neutrally. The rules text itself is owner-approved and appears only where
   approvals/compliance surfaces quote stored values — the guard applies to MODEL prose paths
   only; do not launder the owner's stored rules on surfaces that legitimately display them.
5. **M7-F60 display honesty (wording only).** "Finishing its work" is invocation-based; do
   not fake a better metric. If its label can be made honest cheaply ("Rounds completed"
   or similar D-007-consistent phrasing), do it; the metric semantics stay untouched.

**Scope**
`jarvis/api/app.py` (payload additions + the stale "Doing now" comment at ~:506, M7-F44),
`jarvis/api/render.py`, `jarvis/api/static/index.html` (card/details regions; NOT the
approval card), `jarvis/kpi/engine.py` (summary wording only), `jarvis/registry/` READ paths
only if needed to expose type display data, and tests. No manager/, no schema, no conftest.
$0 — no model calls; live DB read-mostly on :8110; never print `.env`.

**Lane workflow:** `D:\Projects\Jarvis-lanes\m7-5a` only; `uv sync --all-extras`; gates in
worktree; one commit on `lane/m7-5a` ("M7-5a: "); never merge/push. No DECISIONS.md edits.

**Acceptance criteria**
- [ ] Gates exit 0; tests before → after
- [ ] Live: three companies visually distinguishable by kind; Finance sentence in Details;
      the three health parts rendered; goals drill-down shows measured-vs-target in plain
      language; feed prose with "M7"/"KPIs" falls back neutrally
- [ ] Report (350/500): Changed / Decisions I did not make / Gates / Live verification /
      Findings M7-F61–F69 / Follow-ups

**Escalate instead of deciding if**
- Exposing type display data requires more than reading what the Registry already stores
- Per-metric readings can't be shipped without new queries that belong in the engine
