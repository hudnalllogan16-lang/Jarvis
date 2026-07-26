## Packet M7-R1: reserve surface fixes (M6-5 re-review F3 + F4)

**Agent:** operator-surface-engineer   **Model:** sonnet — two decided cosmetic items,
gate-covered. Finding range: **M7-F40–F44**. Lane: `lane/m7-r1`.

**Items (from the M6-5 re-review, recorded in DECISIONS.md "M6 closure")**
1. **F3 — "Doing now" answers the wrong question.** The company card renders past-tense
   post-mortems under a present-tense label, truncated mid-word with no affordance. Fix at
   the render boundary (`jarvis/api/render.py` + the card region of
   `jarvis/api/static/index.html`): cap at a word boundary with an ellipsis, add a "more in
   Details" affordance, and rename the field label to something the content can honestly
   satisfy (e.g. "Latest update") — or render present activity if the data supports it.
   State which you chose and why in one line.
2. **F4 — the create-dialog error is styled as a timestamp.** "Give it a name first."
   renders in `.waited` (11px grey mono after the buttons); the stylesheet already carries an
   unused `.formErr` in the risk colour. Use it, positioned where an error belongs.

**Scope discipline (parallel-lane safety):** you may touch ONLY `jarvis/api/render.py`,
`jarvis/api/static/index.html` (card + create-dialog regions; NOT the approval card, NOT the
notification strip), and tests. Do NOT touch `jarvis/kpi/` (another lane owns health wording
right now), `jarvis/manager/`, `jarvis/api/app.py` route logic, or `tests/conftest.py`.
Escalate rather than cross those lines.

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-r1`; `uv sync --all-extras`
first; gates in the worktree; commit on `lane/m7-r1` ("M7-R1: "); never merge or push. $0 —
no model calls; never print `.env`. Live API on `JARVIS_API_PORT=8110` if you verify against
the real DB (read-mostly, no raw writes).

**Acceptance criteria**
- [ ] Gates exit 0 in the worktree; count before → after
- [ ] No mid-word truncation; label and content agree; error is visibly an error
- [ ] Report (300/450 cap): Changed / Decisions I did not make / Gates / Live verification /
      Findings (M7-F40–F44) / Follow-ups
