## Packet M9-1: Executive Layer design (M9 wave 0, Lane A)

**Agent:** platform-engineer  **Model:** opus — a new top-level component (spec §3/§3.1);
design-first per the M8-1 precedent. Findings **M9-F1–F19**. Lane: `lane/m9-1`.

**Objective:** `docs/design/EXECUTIVE-LAYER.md` + proposed D-entries (in report, not written):
how §3''s deterministic/judgment split is implemented — CFO budget rollups/cap tracking/
alerts and COO health aggregation as DETERMINISTIC scheduled code first (no model calls);
judgment cadences (weekly/monthly, §3 table) designed but explicitly deferred to a later
packet; interaction ONLY via the Standard Business Contract (§5) and Decision Log reads —
never business internals (§3). §3.1 strategic responsibilities (capital allocation, KPI
target setting) designed with their §8/§12.5 surfaces named (D-007 gives operator terms:
"Jarvis moved budget between companies, here''s why"). No standing loops (§3). State what M9
implements vs M10+ defers. Design only; throwaway probes fine; live DB read-only; $0.
Gates exit 0 (docs-only expected); commit "M9-1: "; never merge/push. Report 400/600.
**Escalate if** any §3 reading would change operator-visible behavior beyond D-007''s table
(owner-reserved) or requires a new layer not in §3.2.
