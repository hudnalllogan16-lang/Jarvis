## Packet M9-2: business workspaces (UI Phase 3 foundation — M9 wave 0, Lane B)

**Agent:** experience-engineer  **Model:** opus — the workspace pattern every company page
inherits. Findings **M9-F20–F39**. Lane: `lane/m9-2`.

**Objective:** each company becomes an operational workspace (design north star + owner
Phase-3 list): status, KPIs measured-vs-target, health with parts, ongoing work, approvals
scoped to the company, execution history, recent activity, trends where real series exist
(kpi_values is real now — render it honestly; no fake trendlines). Route: extend the shell''s
Companies workspace into per-company pages (drill from card). Use EXISTING endpoints
(company_detail, approvals, the goals data); if a read is genuinely missing, design the
surface, stub nothing, and report the exact endpoint shape needed (platform packet follows
same wave under rolling dispatch — do not add API routes yourself). Design-system
extend-first rule; §12.5 gate; escaping total; pre-report self-check; product-reviewer gates
this phase after merge. Live verify on :8110 read-mostly; $0. Gates exit 0; commit "M9-2: ";
never merge/push. Report 450/600.
