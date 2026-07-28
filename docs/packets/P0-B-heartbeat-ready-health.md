## Packet P0-B: heartbeat, readiness, health (OPERATIONAL-RUNTIME.md packet B)

**Agent:** platform-engineer  **Model:** sonnet — per a merged design, gate-covered.
Findings **M10-F40–F49**. Lane: `lane/p0-b`.

Implement design Part 5''s self-report half + Part 6''s endpoint split exactly: the
`runtime_heartbeat` table (observability package so D-038 holds; migration number
**0008 pre-allocated** — if a migration is genuinely needed, else in-schema per design),
heartbeat writes from the supervised parts (the design names which and how often),
`/api/ready` (readiness GATES — parts up, DB reachable, migrations current) split from
`/api/health` (explains — the parts_provider path from M9-10 extended per design), the
associated parameter-register rows WITH their Settings fields (legitimizing the ones P0-A
correctly deferred). NOT yours: the Temporal poller probe + the liveness VERDICT (P0-C).
$0; live read-only; scripted harness; no service starts. Gates exit 0; commit "P0-B: ";
never merge/push; no DECISIONS.md edits. Report 300/450.
**Escalate if** heartbeat writes need a scope the ledger/audit patterns don''t already
provide, or the ready/health split fights the M9-10 parts_provider shape.
