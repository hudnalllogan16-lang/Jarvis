## Packet M6-4: vertical-slice audit and merge verdict

**Agent:** architecture-auditor   **Model:** opus — the judgement no gate makes; its verdict is
what the Manager merges on.

**Objective**
Audit the complete Affiliate vertical slice (M6-0 through M6-3) for architectural compliance and
return a merge verdict, with special attention to the seams between the parts, because that is
where this project's real defects have consistently lived.

**The central question**
Did proving the path require any change that a business type or a business's Manager should not
have caused? A slice that only works because the *generic* machinery grew a business-specific
special case is a slice that disproved D-014 while appearing to succeed. Say so plainly if it
happened.

**Audit specifically**
- The full path runs: create → wake → execute → propose → approve → execute effect → audit. Is
  every link real, or is one still simulated in a way the reports understate?
- D-004/005/006: did making the Manager run live weaken determinism, bounded state, or the
  continuation model? Check for a clock read or id-mint that crept into workflow code.
- D-011: is the approved amount the operator saw the stored value, or regenerated text?
- D-015 / §10: on the live execution path, does the credential appear anywhere it must not?
- §6 / A-001: is the effect genuinely idempotent, or does a replay perform twice?
- §12.5: any raw diagnostic or infrastructure vocabulary now reaching the operator?
- Ledger: is the "Manager never run live" row retired, and honestly?
- Verified vs written: does any report claim live verification that was actually simulated?
  Overclaiming is a finding (M5-F5 is the standing example).

**Deliverable**
One verdict — MERGE / MERGE WITH FOLLOW-UPS / REVISE / ESCALATE — findings in priority order,
each with file, the decision it conflicts with, and the specific change needed. Run
`bash scripts/gates.sh` yourself; do not trust a report's claim that it passed.
