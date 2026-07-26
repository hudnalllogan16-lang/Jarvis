## Packet M6-5a: the M6-5 REVISE round — make the dashboard truthful and alive

**Agent:** operator-surface-engineer   **Model:** sonnet — every item has a named surface and
a smallest-change; §12.5 static gate + new tests cover the risky parts.

The product review (verdict REVISE, findings in `docs/DECISIONS.md` "M6-4 / M6-5 verdicts")
found the dashboard renders blank and, once visible, would mislead. Items, in order:

1. **Un-blank the dashboard.** `index.html:245` binds `$('newBtn')` — no such id (button is
   `newco`); the TypeError halts `paintAll()` and the refresh timer. Fix the binding.
2. **One create flow.** Keep the better one (single dialog), one label: "Spending limit" —
   not "Monthly budget". Expose `per_round_limit_usd` in the create dialog (plain language,
   e.g. "Most it can spend per work session") and in company detail views.
3. **Escape everything.** M6-4a added `esc()` and used it on the approval card; apply it to
   every interpolation of stored/model-derived text (`${c.doing}`, `${e.what}`, `${e.why}`,
   `${s.what}`, `${n.title}`, `${n.body}`, can_do_alone, `${t.name}`). This closes M6-F35's
   residue — it becomes exploitable the moment item 1 ships. Add a test if the harness allows
   markup assertions (test_operator_language.py shows the pattern for static scans).
4. **Decision-log rendering boundary.** Live "why"/"what" prose leaks approval ids, wake
   vocabulary, and raw lifecycle states. At the API/render boundary (not in stored data):
   strip/replace raw ids (`apr_…`, `biz_…`, `cyc_…`), translate lifecycle states per D-007,
   and cap "Doing now" to one sentence (~140 chars, ellipsis) with full text in the drill-down
   panel. Wire `contains_technical_language` as a runtime guard on operator-bound summaries:
   flagged text falls back to a neutral stored-value rendering ("Working — details inside"),
   never to the raw prose. Follow `approvals/rendering.py`'s stored-values pattern where the
   data exists.
5. **Notifications resolve.** A notification tied to an approval clears when that approval is
   decided; add a dismiss control for the rest. No permanent accumulation.
6. **Health honesty (D-020 amendment, quoted in DECISIONS.md).** KPI targets configured +
   attainment 0 + ≥5 completed cycles since activation → band caps at `watch`. Implement in
   `jarvis/kpi/engine.py` alongside the stuck-work cap; tests both directions (a shipping
   company stays healthy).
7. **No silent failures.** `decide()`/`toggle()` surface non-2xx responses in plain language
   (the 409 already says "You've already answered this one" — show it).
8. **Small fixes:** approval card h2/fact duplication (`app.py:285-286`); can_do_alone
   humanizes the action id (strip type prefix, underscores → spaces); mojibake in the live
   feed (`checkâ€"so` — find the encoding fault at its source: likely a UTF-8/cp1252 mismatch
   on a write path or a missing `<meta charset>` — fix the cause, and repair the affected
   stored rows only if the cause is in the write path, via a recorded correction);
   `/api/health` exists under `jarvis.api.server` topology too (M6-5's false-red).

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; test count before → after
- [ ] Dashboard paints the two live companies with real data (verify against the running API —
      state what you loaded and saw)
- [ ] Every REVISE item above addressed or explicitly reported blocked with reason
- [ ] §12.5 static gate green; runtime guard proven by test (technical prose in, neutral out)
- [ ] Report: live vs simulated

**Out of scope**
Approval-card region beyond item 8's duplication fix (M6-4a owns it — rebase on its current
state, don't rework it). Prompt changes (M6-F34 packet). DECISIONS.md.

**Escalate instead of deciding if**
- The decision-log boundary can't distinguish stored-value-backed entries from free prose
  without a schema change
- Repairing mojibake rows would require editing audit history (append a correction instead —
  if even that feels wrong, stop and report)
- The runtime §12.5 guard would need to run on model output *before* storage (that's a
  different architecture — flag, don't build)
