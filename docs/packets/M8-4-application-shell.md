## Packet M8-4: the Application Shell (UI Phase 2)

**Agent:** experience-engineer   **Model:** opus — no gate covers premium; the shell is the
permanent frame every later phase inherits. Finding range: **M8-F70–F84**. Lane: `lane/m8-4`.

**Objective**
The permanent application frame per the north-star concept and the design system: sidebar
navigation (Command Center · Companies · Approvals · Goals & KPIs · Activity · Audit ·
Settings — a Managers section only if persona DATA exists to render honestly; it does not
yet, so reserve the slot, ship nothing decorative), top bar (status, time range if real,
New company), the Command Center as the composed home (stat row, companies, activity feed,
approvals, system health strip), notification center, responsive behavior. Every surface
renders REAL served data — the design system's principle 3 (drop, don't fake) binds.

**Phase-gate debts, all owed here:** the ten inline-style sites move to the sheet on-scale;
`06-components.md`'s `.entry__why` doc-vs-code mismatch fixed (pick doc or code, align both);
the naming migration completed (one convention, stated); self-hosted fonts (M8-F21); modal
focus trap + restore (M8-F23, WCAG 2.4.3); ≥44px touch targets or documented exception
(M8-F27).

**Constraints:** extend the design system — a needed-but-missing pattern goes into
docs/design/ first, then use; §12.5 static gate + surface-sources guard green; escaping
invariant total; operator copy placeholder-quality is acceptable ONLY where new (flag every
instance for the operator-surface pass — D-028 split); dependency-light stays (no build
step). All 773 tests green; live-verify on :8110 in fetched-DOM terms; pre-report product
self-check. $0.

**Acceptance:** gates exit 0; tests before → after; the shell composes the existing
Command-Center content without information loss (everything reachable before is reachable
after, stated); keyboard walk of the primary flows (nav → card → details → close) verified.
Report 450/600.

**Escalate if** the shell needs API additions beyond read-shaping, or any nav concept lacks
real data and the design wants it anyway.
