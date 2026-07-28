## Packet M9-1a: Executive packets A+B — portfolio rollup, census, ledger rows

**Agent:** platform-engineer  **Model:** sonnet — implementing a merged opus design
(docs/design/EXECUTIVE-LAYER.md Parts 1-3, 5-6 are authoritative); gate-covered incl. the
new import rule. Findings **M9-F60–F69**. Lane: `lane/m9-1a`.

Implement design packets A and B exactly: the `jarvis/executive/` package (milestone 9 in
the layering table + DEPENDENCIES), `PortfolioRollup` with every field naming its window
(D-040), the health census (D-039 — counts per band, worst company named, NO single score),
the deferred-completion ledger rows Part 0 demands, and the import-rule test (D-038:
executive imports registry/budget/kpi/observability/notifications ONLY; the test proves the
detector detects). Deterministic only — no model calls, no contract writes, no timer yet
(packet D), no alerts yet (packet C). Respect the two OPEN owner escalations: the rollup
reports the cap figures AS RECORDED with their windows labeled (D-040 makes the ambiguity
visible instead of resolving it). Live DB read-only; $0. Gates exit 0; commit "M9-1a: ";
never merge/push; no DECISIONS.md edits. Report 350/500.
**Escalate if** the census needs data the contract does not expose (§3''s only-via-contract
rule) or a ledger row cannot be written without a schema change.
