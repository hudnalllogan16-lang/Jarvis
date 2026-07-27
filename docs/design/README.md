# The Jarvis Design System

This directory is a **permanent platform artifact** (D-028.3). It carries the same weight as
`docs/DEPENDENCIES.md` or `docs/DECISIONS.md`: future UI work *extends* this system, it does not
reinvent it. If a packet needs a pattern the system lacks, the pattern is added here first —
documented, with its rationale — and only then used in code.

It is the counterpart to `docs/PRODUCT.md`. PRODUCT.md says what operating Jarvis should *feel*
like; this says what that feeling is *made of*.

## Reading order

| # | Document | Answers |
|---|---|---|
| 01 | [Design Principles](01-principles.md) | Why the surface looks the way it does |
| 02 | [Color System](02-color.md) | Tokens, the health/risk semantics, light/dark posture |
| 03 | [Typography](03-typography.md) | Three families, one scale, and which is for what |
| 04 | [Spacing](04-spacing.md) | The 4px grid and the density argument |
| 05 | [Layout System](05-layout.md) | Page frame, grids, breakpoints, the shell's slots |
| 06 | [Component Library](06-components.md) | Every component, its anatomy and its states |
| 07 | [Iconography](07-iconography.md) | Why Jarvis is nearly icon-free, and the exceptions |
| 08 | [Motion Guidelines](08-motion.md) | Motion communicates state change; it never decorates |
| 09 | [Accessibility Standards](09-accessibility.md) | Contrast (measured), focus, reduced motion |
| 10 | [Interaction Patterns](10-interaction-patterns.md) | Progressive disclosure, empty/null/error states |
| 11 | [Persona Components](11-persona-components.md) | Manager personas (spec v1.5 / D-028.1) — spec only |

## Where the system lives in code

    jarvis/api/static/
      index.html            markup shell only — no inline <style>, no inline <script>
      styles/tokens.css     tier 1 primitives + tier 2 semantic tokens, both themes
      styles/base.css       reset, document defaults, typography application
      styles/components.css every component in 06-components.md
      app/*.js              ES modules — behaviour only, no styling decisions

**Dependency-light is a constraint, not an accident** (M8-PLAN Part 5): no build step, no
framework, no package manager in the browser path. Modular vanilla ES modules are the floor.
Adopting a build system is a tooling decision the owner hears about first, and the Phase-2
retrospective decides it with evidence.

## The three rules that bind every future UI packet

1. **Components reference semantic tokens only.** Never a raw hex, never a primitive
   (`--n-800`), never a magic pixel value outside the spacing scale. A component that needs a
   colour the semantic layer lacks means the semantic layer is incomplete — extend it.
2. **Nothing decorative that lies.** Every number, meter, trend and tile on a surface must be
   backed by data Jarvis actually serves. A placeholder that looks like real data is a defect,
   not a mock.
3. **Escape everything.** Every value interpolated into markup passes through `esc()` from
   `app/format.js`. Company names, activity prose and approval payloads are model-authored or
   read off the open internet; an approval card that can be made to run script is a card that
   can press its own Approve button.

## The boundary this system does not cross

The design system owns the **container**: structure, hierarchy, colour, rhythm, motion, states.
It does not own the **words**. Operator copy, D-007 translation, rendering boundaries and §12.5
implementation belong to `operator-surface-engineer`. Where these documents show copy, it is
illustrative — the placeholder-quality text is flagged for a surface pass, never ratified here.

The §12.5 forbidden-vocabulary gate binds this system like everything else. If a design wants to
show something §12.5 forbids, **the design is wrong, not the rule.**
