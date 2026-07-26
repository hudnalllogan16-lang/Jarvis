## Packet M7-2: carried surface follow-ups (M6 product re-review F1/F2/F6 + runtime terms)

**Agent:** operator-surface-engineer   **Model:** sonnet — decided items, gate-covered.
Finding range: **M7-F10–F19**. Lane: `lane/m7-2`.

**Objective**
The four data-correctness items from the M6 product re-review (recorded in DECISIONS.md
"M6 closure") are fixed; the notification strip can no longer contradict the approval queue.

**Items**
1. **F1 — notifications reconcile against reality on read.** `/api/notifications` does not
   return an approval-linked notification whose approval is no longer pending — regardless of
   how it got answered (decided, withdrawn, expired). The decide-path `resolve_for` stays as
   the eager path; the read-path filter is the guarantee no future event-coverage gap can
   break. Include the 24h-reminder case.
2. **F2 — id stripping drops the parenthetical.** "a pending approval (something)" → "a
   pending approval". Fix in `jarvis/api/render.py`; regression test with the live-observed
   shapes.
3. **F6 — notification bodies go through the render boundary.** Stored `title`/`body` are
   laundered like cards and the feed (id-strip, term-guard, length behaviour consistent).
4. **Runtime §12.5 term coverage.** The runtime guard's list misses morphology: "woken"
   (vs "wake cycle") and "business" (vs "company") passed live. Extend
   `contains_technical_language`/the guard's vocabulary to cover word-boundary and
   morphological variants of the D-007 forbidden set; negative controls prove the detector
   detects without false-positives on legitimate words ("busy", "awoken" in… no — keep it
   honest: test the actual boundary cases you choose).

**Scope**
`jarvis/api/render.py`, notification read routes in `jarvis/api/app.py`,
`jarvis/notifications/`, the notification strip region of `jarvis/api/static/index.html`,
and tests. Do NOT touch: the approval-card region (M6-4a's), `jarvis/kpi/`, `jarvis/manager/`,
`tests/conftest.py`. No migrations.

**Verification against real data:** the default dev DB holds the live M6 notifications
(4, several stale — the F1 specimens). You may run the API from your worktree with
`JARVIS_API_PORT=8100` against it to verify the read-path filter renders truthfully; treat
the DB as read-mostly (a dismiss/resolve through real mechanisms is fine; no raw UPDATEs).
`.env` holds real secrets — never print it; no model calls ($0).

**Lane workflow:** work only in `D:\Projects\Jarvis-lanes\m7-2`; `uv sync --all-extras` first;
gates in the worktree; commit on `lane/m7-2` ("M7-2: ..."); never merge or push.

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0 in the worktree; count before → after
- [ ] Stale live notifications no longer render as needing the operator (state what the strip
      shows before/after against the real DB)
- [ ] "(something)" gone; term-guard morphology proven both directions
- [ ] Report: verified vs written; findings in M7-F10–F19
