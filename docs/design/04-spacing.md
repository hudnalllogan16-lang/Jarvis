# 04 — Spacing

## The 4px grid

Every margin, padding, gap and offset in Jarvis is a multiple of 4. Values that are not on the
grid are the reason interfaces look *almost* right — the eye reads inconsistent rhythm as
sloppiness long before it can name what is wrong.

| Token | px | Typical use |
|---|---|---|
| `--space-0` | 0 | reset |
| `--space-1` | 2 | hairline gaps — segments in a meter |
| `--space-2` | 4 | icon-to-label, tight inline pairs |
| `--space-3` | 6 | dot-to-label, chip padding (vertical) |
| `--space-4` | 8 | button groups, related inline controls |
| `--space-5` | 12 | grid gap between cards; card internal stack |
| `--space-6` | 14 | card internal stack (default), field spacing |
| `--space-7` | 16 | panel internal sections |
| `--space-8` | 20 | card padding, approval card padding |
| `--space-9` | 24 | page gutters (mobile) |
| `--space-10` | 28 | page top padding, panel padding |
| `--space-11` | 34 | section heading top margin |
| `--space-12` | 48 | major section separation |
| `--space-13` | 80 | page bottom padding |

`--space-1` (2px) is the one sub-4 value, and it exists for exactly one thing: the gaps between
meter segments, where 4px would make ten segments read as ten separate objects rather than one
divided bar.

## Density: dense, with air where it matters

Jarvis is an information-dense surface — an owner should see three companies, their health,
their spend and what they are doing without scrolling. Density is achieved by **tightening the
gaps between related things**, never by shrinking type or removing padding from containers.

The concrete expression of that:

- **Inside a card**: 20px padding, 14px between stacked blocks. Related lines within a block
  (label above value, value above unit) sit at 4–6px.
- **Between cards**: 12px. Cards are peers; a large gap makes them read as separate sections.
- **Between sections**: 34px above a section heading. This is the largest routine gap in the
  surface and it is what makes the page scannable — the eye finds section boundaries by rhythm.

The rule: **gap size encodes relatedness.** Two values 4px apart are one thing. Two values 34px
apart are different subjects. Any layout where an unrelated pair is closer than a related pair
is wrong regardless of how it looks.

## Vertical rhythm

Stacked blocks separate by `--space-6` (14px) by default. A block that introduces a new *kind*
of information separates with a hairline rule at `--border-subtle` plus 12px above and below —
the rule does the work that would otherwise need 28px of space, which is how the surface stays
dense without feeling crowded.

Rules are used sparingly: a card carries at most two. More than two and the card reads as a
table.

## Optical corrections

Two places where the grid is deliberately overridden, both documented so they are not "fixed"
later by someone tidying:

1. **The kind label under a company name** sits at `-7px` top margin. The display face's
   descender leaves visible space below the name; a grid-correct 0 margin reads as a gap. The
   negative value restores the *optical* baseline relationship.
2. **Uppercase eyebrow labels** carry ~1px more space below than above. Uppercase has no
   descenders, so its optical centre sits high; equal spacing reads as bottom-heavy.

Optical corrections are permitted. Arbitrary values are not. The difference is that an optical
correction has a stated reason, and this file is where the reason lives.

## What never gets a spacing value

Component internals do not invent spacing tokens. If a component needs a gap the scale does not
have, the answer is the nearest scale value — not a new token. The scale is deliberately fine
enough (2, 4, 6, 8, 12, 14, 16, 20…) that "the nearest value" is always within 2px of any
reasonable need.
