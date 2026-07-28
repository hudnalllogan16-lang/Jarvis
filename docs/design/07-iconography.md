# 07 — Iconography

## The position: Jarvis is nearly icon-free, and that is a decision

There are no icon fonts, no SVG sprite sheet, and no icon library in Jarvis. Three reasons, in
order of weight:

1. **Icons are ambiguous where Jarvis must be exact.** This is a surface where an operator
   authorises real money leaving a real account. A pencil, a gear, a lightning bolt — each is a
   guess the operator has to make. A word is not. `docs/PRODUCT.md` asks that "understanding
   should not require documentation"; icon literacy *is* documentation, just uncredited.
2. **An icon set is a dependency.** Dependency-light is a binding constraint of this phase
   (M8-PLAN Part 5). Icon libraries arrive as a font file, a sprite, or a build step, and all
   three are the thing this phase is not doing.
3. **Restraint is the identity.** The surface already reads as an instrument because of type and
   spacing. Icons on every button would make it read as a generic web app — the exact outcome
   D-028.4 exists to prevent.

## The exceptions, and why each earns its place

Three non-text marks exist. Each encodes something a word conveys worse, and each is drawn in
CSS — no asset, no request.

### The status dot (`.dot`, 6px circle)

Encodes liveness. Paired with the status word, always: the dot answers "is it live *right now*"
at a glance across a grid of cards, which reading three status labels does not. Its breathing
animation carries the same fact through time (`08-motion.md`).

### The meter segments (`.meter`, ten bars)

Encode a level. Ten discrete bars communicate "73 out of 100" pre-attentively; the number
alongside makes it exact. Neither alone is sufficient — the bar without the number is imprecise,
the number without the bar cannot be compared across three cards in one glance.

### Rules and left borders (hairlines, 1px and 3px)

Encode grouping and severity. A 3px left rule in `--status-risk` marks an approval card or a
failure banner as belonging to a class of thing. This is the cheapest possible "icon": it costs
one border property, works in both themes, and cannot be misread.

### Not an exception: typographic characters

`·` between two facts on a goal line, and `‹` before the company workspace's return link, are
**typography, not iconography**. The boundary is mechanical rather than aesthetic: a typographic
character comes from the font in the text run, inherits colour, size and weight from the words
beside it, needs no asset and no request, and cannot fail to load the way an icon can. None of
the three costs above applies to it.

One obligation comes with it. A directional character is punctuation to a reader and noise to a
screen reader, which announces `‹` by name — so it carries `aria-hidden="true"` and the words
beside it are the label. "‹ All companies" is announced as "All companies", link.

## If an icon is ever added

The bar is high, and these are the conditions — all of them, not any of them:

- The concept is **spatial or directional** (a trend arrow, a disclosure chevron, a close X),
  where the mark *is* the meaning rather than a picture standing for it.
- It is **inline SVG in the markup** — no icon font, no sprite request, no library.
- It carries `aria-hidden="true"` **and** an adjacent text label, or a real `aria-label` if it is
  genuinely the only content of a control.
- It is drawn at 16px or 20px on a 24px box, `stroke-width: 1.5`, `currentColor` — never a
  hard-coded hue, so it themes for free.
- It is **added to this document first**, with its meaning stated, before it appears in a
  component.

The three plausible near-term candidates, none yet justified: a disclosure chevron (native
`<details>` already provides one), a close X on the panel (the text button works and is
unambiguous), and a trend arrow (blocked on trend data existing at all).

## What is explicitly forbidden

- Icon-only controls. Every actionable element carries a word.
- Icons as decoration in empty states or headings.
- Emoji as iconography anywhere in the operator surface.
- A logo mark. The wordmark *is* the identity — set in the display face at 26px/800, and that is
  the whole of it.
