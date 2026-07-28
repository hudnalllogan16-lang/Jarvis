# 08 — Motion Guidelines

## The test every animation must pass

**What state change does this report?**

If the answer is "none — it looks nice", it does not ship. Jarvis is a surface an operator
watches while autonomous companies spend money; motion that means nothing trains the eye to
ignore motion that means something. That is a safety property, not an aesthetic preference.

## Tokens

| Token | Value | For |
|---|---|---|
| `--motion-instant` | `90ms` | state echo on a control the operator just touched |
| `--motion-quick` | `150ms` | hover, focus, colour and border transitions |
| `--motion-base` | `220ms` | something arriving or leaving |
| `--motion-slow` | `320ms` | a full region changing character (calm → urgent) |
| `--ease-standard` | `cubic-bezier(.2,0,0,1)` | anything entering or moving |
| `--ease-exit` | `cubic-bezier(.4,0,1,1)` | anything leaving |
| `--ease-breathe` | `ease-in-out` | the one looping animation |

Durations are short deliberately. Above ~320ms an interface feels like it is performing for the
operator rather than responding to them; below ~90ms the change is not perceived as motion at
all and may as well be instant.

**Asymmetric easing is the rule**: things enter decelerating (`--ease-standard`, fast start,
soft landing) and leave accelerating (`--ease-exit`). Entrances should feel arrived-at; exits
should get out of the way.

## The motion inventory

Everything that moves in Jarvis, and its justification. This list is exhaustive by design — a
new entry requires a new line here.

### 1. The breathing dot — `breathe`, 2.6s, infinite

    @keyframes breathe { 0%,100% { opacity: 1 } 50% { opacity: .28 } }

The only looping animation in the system. It marks a company as *currently running*, and it is
the one piece of state that a static mark genuinely cannot carry: "running" and "paused" both
look like a coloured dot in a screenshot. 2.6s is slow enough to read as breathing rather than
blinking — a 1s pulse reads as an alarm.

### 2. Hover and focus transitions — `--motion-quick`

Background, border and colour only. **Never transform.** A control that moves under the cursor
is a control that can be missed; on a surface with an Approve button that is unacceptable.

### 3. Attention-region change — `--motion-slow`

When the approvals region goes from calm to urgent, the heading's colour and its count pill
transition rather than snap. This is the page's centre of gravity moving, and the transition is
what makes an operator notice it happened rather than assume it was always that way.

### 4. Panel open — `--motion-base`, opacity plus 4px rise

The sheet fades in and rises 4px. Enough to read as arriving from in front of the page; not
enough to be a performance. The scrim fades with it.

### 5. Flash message — enters `--motion-base`, auto-dismisses after 6s

An action failed outside a dialog with its own error slot. It enters, it holds long enough to
read, it leaves.

## What does not move

- **No page-load animation.** No staggered card reveals, no fade-in-on-scroll. The data was
  fetched; showing it is not an event worth celebrating, and an operator reloading to check on a
  company should not wait for choreography.
- **No skeleton shimmer.** The 15-second repaint replaces content in place. A shimmer would
  animate every 15 seconds forever, which is precisely the "motion that means nothing" failure.
- **No number roll-ups.** A health score animating from 0 to 73 is a lie for 200ms. Values
  change in place; tabular figures (`03-typography.md`) make that legible without motion.
- **No parallax, no hover-tilt, no gradient drift.**
- **No theme-swap animation.** Switching Dark/Light/Match your device (Settings, M9-3) snaps
  instantly. It is the operator's own action, already reported by the control they just used —
  letting every element's own hover/colour transition fire on its own timing for the same repaint
  reads as a smear, not a change worth watching (M9-F25). `.theme-swap` (`base.css`) suppresses
  every transition for exactly that one repaint; see `app/theme.js`.

## Reduced motion

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .01ms !important;
        scroll-behavior: auto !important;
      }
    }

Honouring the preference is not optional, and the implementation must be *complete* — the
pre-M8 rule disabled `animation` but left `transition` running, which meant a user who asked for
reduced motion still got every hover and panel transition. Fixed here (finding M8-F22).

**The consequence must be designed, not accepted.** With motion off, the breathing dot stops —
so "running" would be carried by colour and by the status word alone. Both are present on every
card by rule (`02-color.md`, `07-iconography.md`), so no information is lost. Any future
animation must survive the same audit: **turn it off and check that nothing became unknowable.**
