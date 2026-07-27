## Packet M8-2: the Design System — permanent artifact + foundation implementation (Lane B, wave 0)

**Agent:** experience-engineer   **Model:** opus — the foundation packet; every future UI
packet inherits its decisions. Finding range: **M8-F20–F39**. Lane: `lane/m8-2`.

**Objective (D-028.3/.4 — owner amendments, binding)**
The Design System exists as a permanent platform artifact in `docs/design/` AND is
implemented as the token/component foundation the Application Shell (M8-4) will build on —
with the current dashboard migrated onto the tokens without regression. This is where
Jarvis's product identity is established; the owner's Premium UI Concept is the north star
for craftsmanship (executive command center: calm dark surface, stat tiles, company cards
with trends, activity feed, approval cards, glanceable system health), NOT a pixel spec.

**Deliverables**
1. `docs/design/` documents, each real and specific to Jarvis (not boilerplate): Design
   Principles · Color System (fold in the existing health/risk semantics; light/dark
   posture decision stated) · Typography · Component Library (the set the shell needs:
   tiles, cards, feeds, badges, meters, persona chips) · Layout System · Spacing ·
   Iconography · Motion Guidelines · Accessibility Standards (contrast, focus,
   reduced-motion) · Interaction Patterns (incl. progressive disclosure card→details→history,
   and honest empty/null/error states).
2. Implementation: design tokens (CSS custom properties), the base component styles, and the
   `index.html` monolith decomposed into modules (markup/styles/behavior separated; the
   region-ownership era ends here). **Dependency-light: no build step, no framework** — that
   adoption decision belongs to the Phase-2 retrospective with evidence (M8-PLAN Part 5);
   modular vanilla (ES modules) is the floor.
3. Persona component SPEC (visual language for named managers per spec v1.5/D-028.1) —
   design only; persona *data* plumbing is a later packet. Placeholder copy flagged for
   operator-surface review.

**Hard constraints**
Every existing surface keeps working against real data (live-verify on :8110); the §12.5
static gate and all 734 tests stay green; escape-everything invariant holds in every new
module; no operator-copy changes beyond mechanical moves (flag anything that needs a surface
pass). Pre-report self-check (D-026 addendum): labels agree with content, scales explicit,
null states clean, everything escaped.

**Acceptance criteria**
- [ ] `docs/design/` complete; gates exit 0; tests ≥ 734 green; dashboard renders identically-
      or-better against the live DB (state what you verified in fetched-DOM terms)
- [ ] Report (450/600): Changed / Decisions I did not make / Gates / Live verification /
      Findings M8-F20–F39 / Follow-ups — plus one line naming the biggest design decision you
      made and why it fits Jarvis rather than a generic dashboard

**Escalate instead of deciding if** the decomposition can't preserve behavior without route/
API changes, or a design need collides with §12.5's forbidden vocabulary.
