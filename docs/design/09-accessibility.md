# 09 — Accessibility Standards

**Target: WCAG 2.1 AA**, with the contrast figures below *measured* rather than asserted.

## Contrast — measured

Every ratio in this section was computed from the shipped token values with the WCAG 2.1
relative-luminance formula. Thresholds: **4.5:1** normal text · **3:1** large text (≥18.66px
bold / ≥24px) and non-text/graphical objects.

### Dark theme (the default)

Foreground against each surface plane. Surfaces: page `#0B0E14`, sunken `#10141C`, base
`#151A24`, raised `#1B2130`, hover `#232A3A`.

| Foreground | page | sunken | base | raised | hover | Min |
|---|---|---|---|---|---|---|
| `--text-primary` `#E4EAF4` | 15.98 | 15.26 | 14.42 | 13.30 | 11.87 | **11.87** AAA |
| `--text-secondary` `#A7B2C6` | 9.04 | 8.63 | 8.15 | 7.52 | 6.71 | **6.71** AA |
| `--text-muted` `#8B97AD` | 6.56 | 6.26 | 5.91 | 5.45 | 4.87 | **4.87** AA |
| `--status-healthy` `#3FBF8F` | 8.33 | 7.96 | 7.52 | 6.93 | 6.19 | **6.19** AA |
| `--status-watch` `#E0A93C` | 9.12 | 8.70 | 8.22 | 7.58 | 6.77 | **6.77** AA |
| `--status-risk` `#F2617A` | 6.22 | 5.94 | 5.61 | 5.18 | 4.62 | **4.62** AA |
| `--accent` `#7C9BFF` | 7.35 | 7.02 | 6.63 | 6.11 | 5.46 | **5.46** AA |

### Light theme

Surfaces: page `#EEF1F6`, sunken `#E4E8F0`, base/raised `#FFFFFF`.

| Foreground | page | sunken | base | Min |
|---|---|---|---|---|
| `--text-primary` `#12151D` | 16.12 | 14.86 | 18.25 | **14.86** AAA |
| `--text-secondary` `#4A5468` | 6.72 | 6.20 | 7.61 | **6.20** AA |
| `--text-muted` `#5D6779` | 5.04 | 4.64 | 5.70 | **4.64** AA |
| `--status-healthy` `#1A6B4F` | 5.69 | 5.25 | 6.44 | **5.25** AA |
| `--status-watch` `#8A5D0B` | 5.08 | 4.68 | 5.75 | **4.68** AA |
| `--status-risk` `#A11D42` | 6.70 | 6.17 | 7.58 | **6.17** AA |
| `--accent` `#33415C` | 9.04 | 8.34 | 10.24 | **8.34** AAA |

**Two colours were changed by measurement, not by eye.** Light `healthy` moved
`#1F7A5A → #1A6B4F` (4.29:1 on sunken — a failure) and light `watch` moved `#9A6B10 → #8A5D0B`.
Both had shipped since M5. Recorded as finding **M8-F20**.

### Non-text contrast

Meter fills against their own track — the case that matters, since the meter is read as a
graphic:

| | healthy | watch | at risk |
|---|---|---|---|
| dark, vs track `#2E3648` | 5.21 | 5.70 | **3.89** |
| light, vs track `#CBD2DE` | 4.24 | 3.78 | 4.99 |

Minimum 3.78 (light watch) against a 3:1 requirement. The focus ring meets ≥5.46:1 (dark) and
≥8.34:1 (light) against every surface it can land on.

## Colour is never the only channel

A hard rule, not a guideline. Every status in Jarvis is carried by **colour + word**:

| State | Colour | The word that carries it |
|---|---|---|
| health band | meter fill hue | the health reason sentence, and the numeric score |
| running / paused | dot hue + motion | the status label beside the dot |
| approval urgency | left rule + heading | "Needs your OK" and the count |
| degraded dependency | banner rule | the summary sentence and its remedy |

An operator with any colour-vision deficiency, or reading a greyscale screenshot, loses nothing.
This is why compliance-check chips are specified to carry the word "passed" and not just a
green fill (`06-components.md`).

## Focus

- **Every** interactive element has a visible focus state. `outline: none` without a replacement
  is forbidden; the shipped rule is a 2px `--accent` ring at 2px offset (inset for form
  controls, where an outset ring would collide with a neighbour).
- `:focus-visible` is used rather than `:focus`, so pointer users are not shown rings — but the
  fallback for browsers lacking it must never be "no ring".
- Focus order follows DOM order, which follows reading order. Nothing in the surface uses a
  positive `tabindex`.
- The focus ring must clear its surroundings at every plane; measured above.

**Known gap, recorded as M8-F23:** the modal sheet does not trap focus, and focus is not
restored to the invoking control on close. Tab from inside the open panel reaches the page
behind it. The panel is otherwise correct (`role="dialog"`, `aria-modal`, `aria-labelledby`,
Escape and scrim dismissal). This is a real AA failure under 2.4.3 and it belongs with the
shell's focus management in M8-4 rather than being half-fixed here.

## Semantics

- One `<h1>`-equivalent per view; headings descend without skipping.
- Live regions: the health banner and flash region carry `aria-live="polite"` so a failure
  announces itself without stealing focus. `assertive` is not used — nothing in this surface is
  urgent enough to interrupt a screen-reader user mid-sentence.
- The relative timestamps in the feed are wrapped in `<time datetime="…">`, so the machine-
  readable absolute value is present even though the visible text is "3h ago".
- Dynamic content is rendered into containers that exist in the initial markup, so a screen
  reader's virtual buffer has a stable shape.
- Buttons are `<button>`. Links are `<a>`. A `<div>` with a click handler does not exist in this
  surface, and the event-delegation layer does not make one possible: it dispatches on
  `[data-act]`, which is only ever placed on real controls.

## Motion and preference

`prefers-reduced-motion: reduce` disables **both** animation and transition (see `08-motion.md`;
the pre-M8 rule covered only animation — finding M8-F22). No information is lost when motion is
off, by the rule above.

`prefers-color-scheme` selects the theme, and an explicit `[data-theme]` overrides it in both
directions.

## Target sizes and input

Interactive controls are at least 32px in their smaller dimension for default buttons. The
`.btn--small` variant used on cards is 26px tall — **below** the 44px WCAG 2.5.5 (AAA) advisory
and below the 24px AA minimum only in the sense that it clears it narrowly. Recorded as a
follow-up for the shell pass rather than changed here, because raising it changes card density
and that is M8-4's decision to make with the whole layout in view.

## What is not yet verified

Stated plainly, per this project's verified-vs-written discipline:

- Contrast: **computed** from token values (arithmetic, reproducible).
- Structure, roles, focus rules, live regions: **source-verified and rendered-DOM-verified**.
- Screen-reader behaviour with an actual screen reader: **not tested**.
- Keyboard-only traversal of every path: **partially exercised**; the focus-trap gap above was
  found by inspection, not by a full traversal audit.

A full assistive-technology audit is a follow-up, and it should happen after the Application
Shell lands rather than before — auditing a surface that is about to gain a nav rail and a
theme switch would be auditing the wrong thing.
