# 02 — Color System

## The posture decision: dark-first, light fully supported

**Decision: Jarvis ships dark by default. Light is a complete, first-class alternate theme, not
a degraded fallback.**

Authority: M8-PLAN Part 5 names "dark-first" as the Phase-1 token deliverable, and the owner's
Premium UI Concept — adopted as the craftsmanship bar by D-028.4 — is a calm dark executive
surface. The pre-M8 dashboard was light (`--paper:#E9ECF2`); that was a prototype default, not a
product decision, and `docs/PRODUCT.md` says so explicitly.

Why light survives rather than being dropped:

- The health/risk semantics have to hold in both. A colour system that only works on one
  background is a colour system that has not been tested.
- Owners read financial surfaces in daylight. Forcing dark is a preference imposed as a default.
- Keeping both honest is cheap *if* the token layer is built for it from the start, and
  expensive to retrofit later. This is that start.

The theme resolves in this order: `[data-theme="light"|"dark"]` on `<html>` (explicit choice)
overrides `prefers-color-scheme` (system preference) overrides dark (the shipped default). The
toggle shipped at M9-3, in Settings (the Application Shell workspace that owns operator-facing
chrome, per the plan above) — "Match your device" / "Dark" / "Light", persisted in a plain
cookie the surface reads before its own first paint (`index.html`'s bootstrap script,
`app/theme.js`) rather than in `localStorage`/`sessionStorage`. "Match your device" is the
default and is not a fourth token state: it is simply the explicit `[data-theme]` staying unset,
which is what already fell through to `prefers-color-scheme` above.

---

## Three tiers, and the rule that makes them worth having

    tier 1  primitives   raw ramp values          --n-850, --green-400
    tier 2  semantic     what the value means     --surface-base, --status-healthy
    tier 3  component    only where a component needs its own knob

**Components reference tier 2 only.** A component that reaches for `--n-850` has hard-coded a
theme, because the *whole* theme swap happens at tier 2. This is the single rule that makes the
light/dark posture above cost nothing to maintain, and the one most likely to be broken by a
future packet in a hurry.

Primitives are declared once and never redeclared per theme. Semantic tokens are declared twice
— once per theme — and that is the entire theme definition.

---

## Tier 1 — primitives

### Neutral ramp

The spine of the system. Cool-shifted (a trace of blue) rather than pure grey: a neutral dark
surface reads as dead, and a warm one reads as a document. Jarvis is an instrument.

| Token | Value | |
|---|---|---|
| `--n-950` | `#0B0E14` | deepest — page behind everything |
| `--n-900` | `#10141C` | sunken wells, inset areas |
| `--n-850` | `#151A24` | the default card surface in dark |
| `--n-800` | `#1B2130` | raised — panels above cards |
| `--n-750` | `#232A3A` | hover / pressed on dark |
| `--n-700` | `#2E3648` | strong border, meter track on dark |
| `--n-600` | `#3D4759` | default border on dark |
| `--n-500` | `#5A6478` | subtle border on dark |
| `--n-400` | `#8B97AD` | muted text on dark |
| `--n-300` | `#A7B2C6` | secondary text on dark |
| `--n-200` | `#C2CBDC` | — |
| `--n-100` | `#E4EAF4` | primary text on dark |
| `--n-050` | `#F4F7FB` | — |
| `--n-000` | `#FFFFFF` | card surface in light |

Light-theme neutrals reuse the same ramp inverted, plus two dedicated page values
(`--n-l-page:#EEF1F6`, `--n-l-sunken:#E4E8F0`) because a straight inversion of `--n-950` is
pure white and loses the card/page distinction the layout depends on.

### Status hues

These are **not** decorative. They are the platform's health banding
(`healthy` / `watch` / `at_risk`, from `jarvis`'s health engine) and they arrive on the surface
as data, not as styling choices. Each hue is defined per theme because a green that reads
"healthy" on `#151A24` is not the green that reads "healthy" on `#FFFFFF`.

| Meaning | Dark | Light | Comes from |
|---|---|---|---|
| healthy | `#3FBF8F` | `#1A6B4F` | `health_band == "healthy"` |
| watch | `#E0A93C` | `#8A5D0B` | `health_band == "watch"` |
| at risk | `#F2617A` | `#A11D42` | `health_band == "at_risk"` |
| accent / interactive | `#7C9BFF` | `#33415C` | not data — affordance only |

The light values are the pre-M8 ones with two corrections found by measurement, not by eye:
`healthy` moved `#1F7A5A → #1A6B4F` (it failed AA on the sunken surface at 4.29:1) and `watch`
moved `#9A6B10 → #8A5D0B` for the same reason. See `09-accessibility.md` for every measured
ratio.

---

## Tier 2 — semantic tokens

### Surfaces

| Token | Means |
|---|---|
| `--surface-page` | the page behind everything |
| `--surface-sunken` | wells and inset regions — *below* the page plane |
| `--surface-base` | the default card / tile surface |
| `--surface-raised` | panels and sheets that sit above cards |
| `--surface-overlay` | the modal scrim |
| `--surface-hover` | hover and pressed states on any surface |

Four planes, and no more. Depth in this system is carried by **surface value and a hairline
border**, not by shadow — see `05-layout.md`. A fifth plane would make the stack unreadable.

### Text

| Token | Means | Typical use |
|---|---|---|
| `--text-primary` | the thing you are reading | company names, values, body |
| `--text-secondary` | supporting prose | health reasons, activity `why` lines |
| `--text-muted` | labels and metadata | eyebrow labels, timestamps, units |
| `--text-inverse` | text on a filled accent | primary button label |

### Borders

`--border-subtle` (internal rules and dividers) · `--border-default` (component outlines) ·
`--border-strong` (emphasis, masthead rule).

### Status, applied

Each status hue is exposed three ways, because a status shows up as a mark, a fill and a region:

    --status-healthy          the hue itself — meter fills, dots, text
    --status-healthy-bg       a low-alpha wash for banner backgrounds
    --status-healthy-border   the hue at region-edge weight

The `-bg` values are **alpha composites of the hue over the current surface**, not separate
opaque colours. That is what lets one banner style work on `--surface-page` and
`--surface-raised` without a second definition, and it is why they are declared with
`color-mix()` rather than hand-picked hex.

---

## Rules for using colour

1. **Colour never carries meaning alone.** Every status is accompanied by a word — the health
   reason sentence, the state label, the banner text. An operator with a colour-vision
   deficiency loses nothing. This is a hard rule, not a preference; see `09-accessibility.md`.
2. **One meaning per surface.** On a company card, colour means health. The kind label is
   therefore grey type, not a badge (this was decided at M7-5a and is worth re-deciding never).
3. **The accent is an affordance, not a status.** `--accent` marks what you can act on. It
   never encodes how something is doing.
4. **No gradients as surfaces.** A gradient is permitted only where it encodes a scale (a meter
   or a trend), never as card decoration.
5. **Never introduce a hue outside this file.** A new hue means a new meaning, and a new meaning
   needs a decision, not a hex value in a component.

## What this system does not have yet, deliberately

- **A data-visualisation categorical palette.** Phase 3 arrived and this is *still* not needed,
  which is the useful half of the answer. The trend component (`06-components.md`, M9-2b) draws
  one series per chart against one target, so there is nothing to tell apart by hue. It is drawn
  in **ink, not in colour** — `--text-secondary` for the readings, `--text-primary` for the
  latest one, `--border-strong` dashed for the target.

  That is a decision, not an omission. Rule 2 above says one meaning per surface, and on a
  company page colour already means health; a series coloured by attainment would be a second
  meaning competing with the meter beside it, and it would restate as a hue what the health
  parts already give as a number. A categorical ramp becomes due when one chart has to carry
  two series at once — and it extends this file when it does.

  The three tokens are contrast-measured as *text* already; used as **graphics** they are a new
  usage class, so they are measured again in `09-accessibility.md`, "Non-text contrast".
  Minimum 3.25:1 (dark `--border-strong` on `--surface-page`) against a 3:1 requirement.
- **A brand colour distinct from the accent.** Jarvis's identity is currently carried by
  typography and restraint. If a brand hue is introduced it is an owner decision, not a
  design-system one.
