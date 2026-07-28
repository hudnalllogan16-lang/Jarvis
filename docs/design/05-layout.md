# 05 — Layout System

## The page frame

    ┌──────────────────────────────────────────────┐
    │  masthead      wordmark · stat tiles · acts  │
    ├──────────────────────────────────────────────┤
    │  system strip  health banners, flash, notes  │
    │  attention     approvals — loud, or one line │
    │  primary       "Your companies" — card grid  │
    └──────────────────────────────────────────────┘

Four regions, in a fixed order, and the order is the argument: **status of the platform, then
what needs you, then what you own.** An operator's eye travels top to bottom and answers
"is Jarvis working?", "does it need me?", "how are my companies?" in that sequence.

The attention region is the one that changes size dramatically. With pending approvals it is the
tallest thing on the page; with none it is a heading and one calm sentence. This movement is the
layout doing its job — see `01-principles.md` #2.

### Content width

`--layout-max: 1080px`, centred, with `--space-9`/`--space-5` gutters. 1080 is not arbitrary: it
fits exactly three 292px company cards plus two 12px gaps plus gutters, which is the density
target. Beyond ~1200px a centred text column reads as a narrow strip in a void; the Application
Shell (M8-4) introduces a sidebar which changes this calculation, and this token is where that
change lands.

## Grids

| Grid | Definition | Used by |
|---|---|---|
| Card grid | `repeat(auto-fill, minmax(292px, 1fr))`, gap 12px | company cards |
| Tile row | `repeat(auto-fit, minmax(180px, 1fr))`, gap 12px | stat tiles |
| Fact grid | `repeat(auto-fit, minmax(190px, 1fr))`, gap 14px 24px | approval card facts |
| Part row | flex, wrap, gap 20px | health parts |
| Workspace split | `minmax(0, 1fr) minmax(0, 320px)`, gap 24px | the company workspace (M9-2) |

The workspace split is the one grid in the system with an asymmetric, *fixed-ish* second track:
`--layout-side` is 320px because the side column carries the health meter, and a meter narrower
than about 300px puts its ten segments below the width at which a fill reads as a percentage
without counting them. It collapses at `--bp-md`, the same width the card grid goes two-up.

The last two gaps were 22px and 18px until M8-4 — neither on the 4px grid, and undocumented as
optical exceptions, so they were snapped to `--space-9` and `--space-8` in the same pass that
moved the ten inline styles onto the scale. `190px` became `--layout-fact-min`.

**`auto-fill` for cards, `auto-fit` for tiles** — and the difference matters. `auto-fill` keeps
empty column tracks, so one company card stays card-width instead of stretching across the
viewport (a single stretched card reads as a banner, not as one of a set). `auto-fit` collapses
empty tracks, so four stat tiles always divide the full width evenly. Getting these backwards is
the most common grid mistake in the system.

## Depth model

Four planes, and depth is carried by **surface value plus a hairline border** — not by shadow.

    sunken  ── wells, inset regions
    page    ── the base plane
    base    ── cards, tiles
    raised  ── panels, sheets, the modal

Shadow is reserved for exactly one thing: the modal sheet, which must read as detached from a
page that is still visible behind it. Everywhere else, shadow on a dark surface produces mud —
a dark shadow on a dark background is invisible, and the usual fix (a light shadow) reads as a
glow. The border-and-value model works identically in both themes, which is the deciding
argument.

Three stacking contexts since M8-4, and the order is an argument: `--z-topbar: 15` (the rail
scrim) < `--z-rail: 20` < `--z-panel: 30`. The modal must cover the rail, because a dialog opened
from the rail has to cover the thing that opened it. Toasts and popovers will need `--z-toast`/
`--z-popover` when they exist; they are not invented here.

## Responsive behaviour

Three breakpoints, chosen from content rather than from device classes:

| Token | Width | What changes |
|---|---|---|
| `--bp-sm` | 640px | tile row goes two-up; masthead actions wrap below the wordmark |
| `--bp-md` | 900px | card grid goes two-up; panel padding tightens |
| `--bp-lg` | 1080px | full three-up card grid — the design target |

Below `--bp-sm` everything is a single column, and the *order* above is what makes that
survivable: a phone-width Jarvis is still status → attention → companies, just stacked.

The card grid needs no media query — `auto-fill` with a 292px minimum handles every width on its
own. The breakpoints exist for the masthead and the panel, which have fixed structure.

## The slots the Application Shell fills — implemented at M8-4

Full specification: `12-application-shell.md`. The shapes reserved here were filled, with one
correction:

- **Sidebar** — `--layout-rail: 216px`. Layout is `grid-template-columns: var(--layout-rail) 1fr`
  and collapses to an overlay below **`--bp-shell` (1180px)**, not `--bp-lg`. The reservation
  above said `--bp-lg`, which was wrong by exactly the rail's own width: the docked rail needs
  216px *plus* the 1080px workspace measure, so docking at 1080 would have squeezed the card grid
  out of its three-up target on the very width the target was chosen for.
- **Top bar** — the masthead became the top bar; the stat tile row moved into the workspace body
  as a Command Center element, as reserved. `.top`, `.mark` and `.top__acts` were deleted rather
  than left as dead rules.
- **Workspace** — `.ws`, capped at `--layout-max`. `.wrap` is gone; `.shell__body` is its
  successor and owns the gutters.

`--layout-max` keeps its value and its argument: it is now the *workspace* measure rather than
the viewport measure, and the card arithmetic behind 1080 is unchanged.

## Layout rules

1. **No fixed heights on content containers.** Data arrives asynchronously and varies in length;
   a fixed height either clips it or leaves a hole.
2. **No layout shift when data arrives.** Regions that will be populated reserve their heading
   immediately and fill their body — this is why the approvals heading renders before its cards
   and why the flash region has `min-height`.
3. **Cards are peers of equal width, never of equal height.** Forcing equal height pads short
   cards with dead space; the grid handles ragged bottoms cleanly.
4. **The page never scrolls horizontally.** Anything that can overflow — payload text, audit
   JSON — scrolls inside its own container.
