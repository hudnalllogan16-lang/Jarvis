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

**M8-F23 — closed at M8-4.** The modal sheet contains Tab while it is open and returns focus to
the invoking control on close; the overlay nav rail does the same through the same module
(`app/focus.js`). Verified live with real key presses: five Tab presses inside an open Details
sheet stayed inside it, and Escape both closed the sheet and restored focus to the exact button
that opened it.

Two failure modes were found *by that verification* and would not have been found by reading:

- Focus restored to an invoker the 15-second repaint had already replaced silently dropped the
  operator on `<body>`. Fallback is now the workspace (**M8-F79**).
- `document.activeElement` is `<body>` when nothing holds focus, and `body.focus()` is a no-op —
  a restore that looks correct in source and does nothing in a browser.

**Still not trapped:** the background is not `inert`. A screen reader's virtual cursor can still
browse the page behind an open sheet even though Tab cannot reach it. `inert` is the correct fix
and is a follow-up, not a silent omission.

### Navigation

The rail is `<a href>` elements — they navigate, so they are links — with `aria-current="page"`
on the active one. The closed overlay rail is `visibility: hidden`, which is what removes it
from the tab order; a transformed-off-screen element is still focusable, and leaving it that way
would make a keyboard operator traverse four invisible links to reach the control that reveals
them (**M8-F80**). A skip link precedes the rail so the workspace is one Tab away.

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

## Target sizes and input — M8-F27, resolved at M8-4

Default buttons are ≥32px. `.btn--small`, used on cards and in sheets, is **26px painted and
44px as a target**.

The distinction is the whole resolution. WCAG 2.5.5 measures the region that *accepts the
pointer*, not the region that is inked. `.btn--small::after` is an absolutely-positioned 44px-tall
box centred on the button and extended horizontally by 4px each side — half the 8px row gap — so
two adjacent card buttons meet exactly and never overlap. Verified live with
`document.elementFromPoint` at ±21px above and below the button's centre: both hit the button.

This satisfies the 44px AAA advisory **without** the density cost that motivated deferring it:
raising the painted height to 44px would add ~36px to every company card and break the three-up
grid that `--layout-max` exists to produce.

For reference on the thresholds actually binding here: this system targets WCAG 2.1 AA, where
target size is not a criterion at all; 2.5.8 (Target Size (Minimum), 24px) arrives in WCAG 2.2
and the painted 26px already cleared it. So the pseudo-element buys the AAA advisory rather than
fixing a conformance failure — recorded plainly rather than claimed as a fix for a violation
that was not one.

## What is not yet verified

Stated plainly, per this project's verified-vs-written discipline:

- Contrast: **computed** from token values (arithmetic, reproducible). Not recomputed for the
  shell's own surfaces at M8-4 — the rail uses `--surface-sunken` with `--text-secondary` and
  `--text-primary`, both already in the measured table above, so no new pairing was introduced.
- Structure, roles, focus rules, live regions: **source-verified and rendered-DOM-verified**.
- Focus containment and restore: **verified live**, with real key presses for the sheet and
  programmatically for the rail (the browser pane stopped accepting synthetic input mid-session;
  stated rather than glossed).
- Tab order: **verified live** against the rendered DOM — skip link → rail → top bar →
  workspace, matching reading order, with the closed overlay rail absent from the sequence.
- Screen-reader behaviour with an actual screen reader: **not tested**.
- `inert` on the background behind an open sheet: **not implemented**.

A full assistive-technology audit is now the right next step: the shell has landed, so the
surface it would audit is the one that will exist.
