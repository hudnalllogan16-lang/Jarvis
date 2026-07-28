## Packet M9-4: decline persistence (M8-F102 — M9 wave 0, Lane D)

**Agent:** data-engineer  **Model:** sonnet — one table/column + service check; migration
number **0007 pre-allocated**. Findings **M9-F50–F59**. Lane: `lane/m9-4`.

**Objective:** design 4.3''s rule becomes real: a declined refresh is re-offered only on the
next version change. Persist the decline (company id + declined source_digest + timestamp;
your schema call — smallest honest shape), `decline_refresh` writes it, `plan_refresh`
suppresses a plan whose band_b_digest matches a stored decline, a new version clears the
suppression naturally (digest differs). Migration 0007 upgrades/downgrades clean on scratch
Postgres THEN live (M6-1d discipline: scratch first, seeded, both directions). The inert
"Not now" control becomes real; audit Finding 3 closes. Update the pinned inert-behavior
test to assert the new truth. Live DB: migration only, after scratch proof. $0. Gates exit 0;
commit "M9-4: "; never merge/push. Report 350/500.
**Escalate if** suppression needs contract changes or the digest rule can''t distinguish
same-version drift (M8-F3''s class) from a new version.
