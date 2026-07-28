## Packet M9-G1b: the parameter register + provenance head (G1 support)

**Agent:** platform-engineer  **Model:** sonnet — registration + tests per a merged design.
Findings **M9-F175–F184**. Lane: `lane/m9-g1b`.

Implement EXECUTIVE-GOVERNANCE.md G1-parameters + the provenance HEAD (static half per
M9-F139): every governing parameter registered (name, class per the design''s taxonomy,
origin, current source — code default vs approved config), with the design''s two rules
enforced by test: no ENFORCING parameter may have a code default (M9-F117''s two violations
fix or get owner-flagged), and a parameter absent from the register that gates behavior
fails the build. M9-F130 remediation schedule: the three illegitimate constraints + the
persisted 48 default enumerated in a REMEDIATION table (for the owner''s retroactive
blessing at ratification — implement nothing, change no live contract). Provenance head:
the Origin/Modified-By/Approved-By fields'' storage shape on the artifacts that already
exist (types, policies-as-config, targets), additive, no migration if achievable inside
existing JSON metadata (else escalate to data-engineer). Live DB read-only; $0. Gates exit
0; commit "M9-G1b: "; never merge/push; no DECISIONS.md edits. Report 350/500.
