## Packet M9-1d: executive packet E — the portfolio surface + marker wiring

**Agent:** operator-surface-engineer  **Model:** sonnet — decided surfaces; explicit app.py
naming per D-037. Findings **M9-F105–F114**. Lane: `lane/m9-1d`.

1. **The census on the Command Center** (design packet E, docs/design/EXECUTIVE-LAYER.md):
   the health tile grows into the census (counts per band, worst company NAMED as a link to
   its workspace, never a portfolio score — D-039); `platform_feed` gets its reader ("Jarvis
   paused spending — here''s why" reaches the operator; M9-F76: link_ref NOT linkified);
   spend alerts'' notification copy verified in place (they render via existing kinds).
   Retire the platform_feed-reader ledger row.
2. **Light the grid marker**: add `"pending_update": bool` presence-only to
   `_company_payload` via a CHEAP existence check — a helper that compares installed
   version/digest + declined_version WITHOUT building ContractRefreshPlan (the shape m9-2c''s
   report requested; if the cheap check can''t be honest about Band-B-emptiness without the
   full plan, say so and gate the marker on the workspace fetch instead — never N×
   plan_refresh on the roster read).
3. Windows labeled (D-040) everywhere a figure lands; §12.5 + escaping + both themes +
   self-check; design-system extend-first for the census tile.

Live verify :8110 read-only (the census against the real roster: healthy 1 / watch 1 /
never-measured 1, Summit named); $0. Gates exit 0; commit "M9-1d: "; never merge/push; no
DECISIONS.md edits. Report 350/500.
**Escalate if** the census can''t render from rollup/health public surfaces, or the cheap
existence check needs registry internals.
