## Packet M9-G1a: the platform-wide Action Registry + inheritance + namespace (G1 core)

**Agent:** security-engineer  **Model:** opus — the governance enforcement itself.
Findings **M9-F160–F174**. Lane: `lane/m9-g1a`.

Implement EXECUTIVE-GOVERNANCE.md (revision 2) G1a''/G1-registry/G1-namespace exactly:
the Action Registry as the platform-wide enumeration (Action → Level → Approval Rule →
Audit Record, closed sets, the cross-constraints as schema — L2-strategic admits only
OWNER_APPROVAL, L3 only OWNER_ONLY); every currently-executable action enumerated (~25 per
the design — completeness proven by the design''s coverage test: an executable action absent
from the registry fails the build); A-003 namespace enforcement (a business type may not
declare platform.*; M9-F116 closes); the downward-inheritance sweep (layers 1–2 per the
design; layer 3 recorded blocked per M9-F134); the ratchet test (an authority-level increase
anywhere fails unless an owner-sign-off marker accompanies it — design the marker
honestly). Where the registry must classify an existing ambiguous action, classify
conservatively (higher approval) and flag. M9-F115 (`graduation_eligible` default True)
belongs to you: flip the default to False — eligibility becomes opt-in per action
declaration (the ratchet-safe default); the two live companies'' existing declarations are
data (Band C protects them; note the owner question stays open on publish_post itself).
Live DB read-only; $0. Gates exit 0; commit "M9-G1a: "; never merge/push; no DECISIONS.md
edits. Report 400/600.
**Escalate if** enumeration finds an action that fits no level without a semantics change,
or the registry needs schema (data-engineer''s migration lane).
