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
| Fact grid | `repeat(auto-fit, minmax(190px, 1fr))`, gap 14px 22px | approval card facts |
| Part row | flex, wrap, gap 18px | health parts in Details |

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

`--z-panel: 10` is the only stacking context in the system today. Toasts and popovers will need
`--z-toast`/`--z-popover` when they exist; they are not invented here.

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

## The slots the Application Shell will fill

M8-4 introduces the command-center frame. This system reserves its shape now so that packet
extends rather than rewrites:

- **Sidebar** — a fixed-width primary nav rail (`--layout-rail`, currently unset). Layout becomes
  `grid-template-columns: var(--layout-rail) 1fr` at `--bp-lg` and collapses to an overlay below
  it.
- **Top bar** — the masthead becomes the shell's top bar; the stat tile row moves into the
  workspace body as a Command Center element rather than masthead chrome.
- **Workspace** — the region between rail and viewport edge; today's `.wrap` is its ancestor.

None of these are implemented. They are named so the tokens they will need have obvious homes.

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
