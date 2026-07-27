## Packet M8-11: refresh wiring, font hookup, installer guards (wave 3 Lane A)

**Agent:** platform-engineer   **Model:** sonnet — decided integrations, gate-covered.
Finding range: **M8-F140–F149**. Lane: `lane/m8-11`.

1. **Wire the refresh seam (M8-F115, the M6-F20 pattern):** `kernel.build_refresh` feeds
   `create_app` the way approvals do; `_pending_update` returns real `plan_refresh` output
   rendered through `jarvis/api/pending_update.py`; the apply/dismiss routes call
   `apply_refresh`/`decline_refresh` with explicit consent semantics (D-030). The 409 seam
   dies; layering gate stays green (api never imports businesses — the kernel hands it a
   built service).
2. **Font hookup:** link `fonts.css` (vendored, committed) into the page ahead of tokens;
   verify the three families actually serve and render (fetched bytes + computed font-family);
   M8-F21 closes.
3. **Installer guards:** M8-F111 (install refuses an upgrade whose Band B projection is
   invalid — reuse `plan_refresh`'s own validation, don't duplicate); M8-F110 (consolidate
   the three `plugin_metadata["definition"]` readers onto one accessor).

Constraints: no schema (decline persistence M8-F102 stays deferred — a decline still
re-offers; honest, recorded); live DB read-mostly (:8110 verify); $0; gates in worktree; one
commit ("M8-11: "); never merge/push; no DECISIONS.md edits. Report 350/500.
**Escalate if** consent wiring can't avoid the approval queue visually/semantically (D-030)
or the kernel builder needs manager-layer imports.
