## Packet M9-2a: the kpi-series read endpoint (rolling successor to M9-2)

**Agent:** platform-engineer  **Model:** sonnet — one read route, shape fully specified.
Findings **M9-F70–F74**. Lane: `lane/m9-2a`.

Implement `GET /api/companies/{business_id}/kpi-series?limit=30` EXACTLY as specified in
the M9-2 report (quoted in DECISIONS "M9-F20…F29" entry and reproduced in
docs/design/13-company-workspace.md if present): one entry per contract kpi_target —
operator_label never the key, unit, direction, target, oldest-first points, `points: []`
(never omitted) when unmeasured. Reuse `KpiEngine.series` — no new query, no engine change,
no client-side attainment. 404 unknown company. Tests incl. the empty-vs-zero distinction
and label-not-key assertion (§12.5). Live verify read-only on :8110 against Portfolio
Watch''s real series. $0. Gates exit 0; commit "M9-2a: "; never merge/push; no DECISIONS.md
edits. Report 250/400.
