## Packet M9-5: the Executive Governance review (owner-commissioned)

**Agent:** platform-engineer  **Model:** opus — constitutional-grade design; Tier C; the
Manager reviews the document itself. Findings **M9-F115–F129**. Lane: `lane/m9-5`.

**Deliverable:** `docs/design/EXECUTIVE-GOVERNANCE.md` answering the owner''s seven parts and
ten deliverables (the full commission text is reproduced in Part 0 of your document from
this packet''s appendix below), plus drafted (never written) spec-amendment wording,
D-entries, and the deferred-M9 implementation strategy. Design only; probes fine; $0.

**Manager positions — BINDING (develop, evidence, and pressure-test them; where you would
overturn one, argue it explicitly as an alternative, never silently):**
1. **Four authority levels.** L0 deterministic computation (exists — D-038''s import-rule
   world; compute/report/notify only). L1 rule-executing actions (breaker, alerts, policy-
   parameterized pauses): automated, always audited, parameters owner-set, code cannot
   change a parameter''s value — only config can. L2 judgment proposals: the Executive may
   PROPOSE (reallocation, target changes, retirement candidates) exclusively through the
   Part-5 explainability structure; every proposal requires owner approval; L2 NEVER
   graduates (§8''s capital rule generalized). L3 owner-only: policy creation, ceilings/
   windows, autonomy grants, spec changes, new integrations. Explicit never-autonomous list.
2. **The principle stands:** "The Executive may execute policy. The Executive may not create
   policy." Belongs in BOTH the spec (proposed §15, owner-ratified) and the decision record;
   draft both wordings. Define "policy" precisely enough to test (a parameter, threshold,
   target, or rule whose change alters what the platform may do without new code review).
3. **Budget and reserve are different concepts — separate them.** Operational Budget =
   rolling windows (daily default; 50/80/halt bands — justify thresholds from operator
   reaction-time reasoning, not vibes; recovery = window rollover, automatic, stated).
   Capital Reserve = lifetime state machine (Normal → Low → Exhausted → Recovered), STATES
   not repeated alerts — this resolves M9-F81''s never-settling nag and the OPEN owner
   cap-window escalation; transitions audited + Decision-Logged once each. Map the existing
   `business_cap_usd`/platform breaker onto the two concepts; migration path for the three
   live contracts.
4. **Confidence: adopt as discrete STATE, not a score.** Current / Degraded / Blind, derived
   from enumerable boolean contributors (stale inputs beyond wake period, failed rollup
   reads, stuck-work count, aging unresolved approvals, unreachable services) — contributors
   LISTED to the operator, never weighted into an arbitrary number (D-039''s census
   philosophy applied to self-knowledge). Presentation drafted in D-007 language.
5. **The 8-field recommendation structure is the platform-wide standard** for any judgment
   output (Observation → Reasoning → Evidence → Confidence → Action → Expected outcome →
   Risk → Required approval); renders from stored values (D-011 extended); Manager-proposal
   unification scheduled for M10, not retrofitted now.
6. **Scaling (M10–M15):** address the platform-scoped approval need (the second OPEN owner
   escalation — draft the mechanism the owner would approve: platform-scope approvals with
   graduation structurally impossible); the Executive budget sub-ceiling (recorded);
   **plugin governance: every action type a plugin declares carries a declared authority
   level, validated at install; an undeclared level refuses install** (D-031/D-032
   extended); census at N companies.
7. **Safety: preventative ratchets.** An Authority Registry — every automated action type
   enumerated with its level, closed-surface like D-032, any level change requiring owner
   sign-off; parameters-live-in-config-with-provenance (the deterministic-becomes-policy
   guard); states-not-alerts as the noise defense; the "autonomy cannot increase
   accidentally" invariant made mechanically checkable (design the test).

Read first: docs/design/EXECUTIVE-LAYER.md; in docs/DECISIONS.md: D-003, D-007…D-013, D-029
…D-042 (held), the M9-F1…F114 record (esp. F81, the two OPEN owner escalations, F80);
spec §3/§3.1/§8/§12.5/§14 as quoted through the record. Cite live evidence where it exists.
Gates exit 0 (docs-only expected); commit "M9-5: "; never merge/push; no DECISIONS.md edits.
Report 450/650: positions developed vs challenged (explicitly) / the deliverables index /
proposed amendment + D-entry drafts (titles + one-line each; full text in the doc) /
deferred-M9 implementation strategy summary / Findings M9-F115–F129 / Follow-ups.
