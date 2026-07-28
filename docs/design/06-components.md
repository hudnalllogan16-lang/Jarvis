# 06 — Component Library

Every component the surface uses today, plus the ones the Application Shell (M8-4) needs.
Each entry gives **anatomy** (what it is made of), **states** (all of them, including the ugly
ones), and **rules** (what would be wrong).

Implementation: `jarvis/api/static/styles/components.css`. Markup is produced by the ES modules
in `jarvis/api/static/app/`.

Components marked **SPEC ONLY** have no rendering path yet, deliberately — the data behind them
does not exist. Shipping them would violate `01-principles.md` #3.

## The naming convention

One convention, stated, and migrated completely at M8-4:

    .block            a thing            .co-card   .entry   .ask   .meter
    .block__element   part of that thing .co-card__name   .entry__why
    .block--modifier  a variant of it    .btn--small      .banner--down

A block name may be hyphenated (`.co-card`, `.section-head`, `.health-parts`). A class that is
only meaningful inside another block **carries that block's prefix** — this is the rule that was
half-applied before M8-4, when BEM elements (`.co-card__name`) sat beside flat legacy classes
doing element work (`.facts`, `.fld`, `.why`, `.seg`, `.part`). Bare element selectors scoped to
a block (`.empty p`, `.health-parts__item b`) are permitted for text-level children that have no
variants; introducing a variant is the signal to give it a class.

The migration closed at M8-4: `.facts`→`.ask__facts`, `.fact`→`.ask__fact`,
`.waited`→`.ask__waited`, `.fld`→`.outgoing__field`, `.seg`→`.meter__seg`,
`.part`/`.parts`→`.health-parts__item`/`.health-parts`, and `.why`→`.entry__why` /
`.outgoing__why` — one flat class had been doing two blocks' work, which is why the doc-vs-code
mismatch below could exist at all.

---

## Foundations

### Button — `.btn`

**Anatomy.** Label only. No icons (see `07-iconography.md`).

**Variants.** `.btn` default (bordered, transparent) · `.btn--primary` (filled accent, for the
one affirmative action in a context) · `.btn--small` (12px, for card and inline actions) ·
`.btn--link` (underlined text, for in-prose affordances like "more in Details").

**States.** rest · hover (surface lifts to `--surface-hover`; primary shifts hue) · focus-visible
(2px `--accent` ring, 2px offset — never `outline: none`) · active · disabled (60% opacity,
`cursor: not-allowed`) · busy (label swaps to a present-participle sentence, control disabled;
this is how "Install starter template" behaves).

**Rules.** One primary per context. Destructive actions are *not* red — "Say no" on an approval
is a legitimate, safe answer, and colouring it as danger tells the operator the wrong thing about
their own choice. Never a bare icon button.

### Field — `.field`

**Anatomy.** Uppercase eyebrow `<label>` → control → optional `.field__hint`.

**States.** rest · focus (2px `--accent` ring inset) · error (border `--status-risk`, message in
`.formErr` **above** the action buttons, never trailing after them — M7 product re-review F4).

**Rules.** Every control has a real `<label for>`. Hints explain consequences ("It stops on its
own at this limit"), never restate the label. Errors say what to do, not what failed.

### Section heading — `.section-head`

Uppercase `--font-data` eyebrow at `--size-xs`, `--track-wide`, `--text-muted`, with an optional
`.section-head__count` pill and an optional trailing action pushed right by `margin-left: auto`.

`.section-head--urgent` recolours to `--status-risk` and fills the count pill. This is the
mechanism by which the approvals region becomes loud.

---

## Data display

### Stat tile — `.tile`

**Anatomy.** eyebrow label → value (`--font-data`, tabular) → optional context line.

    ┌─────────────────────┐
    │ COMPANIES RUNNING   │  ← --size-2xs, muted, tracked
    │ 3 of 3              │  ← --size-3xl data, primary
    │ all running         │  ← --size-base, secondary
    └─────────────────────┘

**States.** normal · `--attention` (value takes `--status-risk`, used when the tile's number is
the reason something is wrong — e.g. spending paused, or at least one company is `at_risk`) ·
`--watch` (value takes `--status-watch`; the "Needs a look" tile when every company pulling the
count down is at `watch` and none is `at_risk` — M9-3: a tile colour may never claim a severity
worse than the companies actually driving it, the same rule the company card already keeps
between its `watch` and `at_risk` bands) · null (value renders `—` **only** when the platform
genuinely has no value; a zero that means zero renders `0`).

**Rules.** Every tile maps to a served field. The four shipped tiles are backed by
`/api/summary` (`companies`, `running`, `waiting_on_you`, `spent_today`, `spend_limit`,
`spending_paused`, `spending_paused_reason`, `census`) and `/api/health`. A tile whose number
has no endpoint does not ship — the concept image's "milestone status" tile is exactly this
case and was dropped, not faked.

**The census tile (M9-1d, design EXECUTIVE-LAYER.md Part 3/8, D-039).** "Needs a look" no
longer counts `health_band !== 'healthy'` client-side — `never_measured` cannot be told apart
from `healthy` on the card alone (D-027.4's grace period bands a young, unmeasured company
`healthy`, correctly, for that company), so the count comes from `/api/summary`'s `census`
object (`healthy`, `watch`, `at_risk`, `never_measured`, `worst_company`), a direct read of
`PortfolioHealth`. The context line states counts per band, `never_measured` on its own, and
names the worst company as a link into its own workspace — the same `#/companies/<id>` route
the card's own "Details" link opens, styled `.btn--link` like any other in-prose affordance
(the company card's own "more in Details"). **Never a portfolio score.** Averaging comparable
per-company scores produces a number comparable to nothing (design Part 3) — this tile has no
value that is not one of the four counts above or a company's own name.

The context line is where scale lives. A tile reading `$1.82` with no context is a number
without a denominator; `of $500.00 today` makes it a measurement.

### Company card — `.co-card`

The most important object in the product.

**Anatomy** (fixed order):

    name (display)                    state dot + status
    kind (quiet grey data label)
    ── HEALTH ────────────── 73
    ▮▮▮▮▮▮▮▯▯▯                        the meter
    "Just getting started — no goals hit yet."
    spent $1.45 of $25.00
    ── LATEST UPDATE ─────────────────
    "We couldn't verify how many posts…"  [more in Details]
    ▏ UPDATE AVAILABLE                the pending-update marker, when there is one
    [Details] [Pause]

**States.** running (dot breathes) · paused (surface desaturates, text drops to secondary) ·
health band healthy / watch / at_risk (drives meter fill only) · truncated update (ellipsis
plus an explicit "more in Details" affordance — M7 product re-review F3) · **update available**
(below).

**Rules.** **One meter and one sentence.** The three health parts belong to Details, not the
card; this was ratified at M7-5a and re-deciding it needs a reason. Colour means health and
nothing else, which is why `kind` is grey type rather than a badge. The card never shows a raw
identifier.

#### Pending-update marker — `.co-card__update`

Added at M9-2c by Phase-3 gate ruling (M9-F27). Before it, the only way to discover that a
company's template had an update waiting was to open every company one at a time — a search no
operator should have to run across their own roster.

**Anatomy.** One line, `--font-data`, uppercase, behind a 2px `--accent` left rule: the
`.pending-update` card's own signature from the company workspace, shrunk to a single line so the
operator meets the same mark at both levels.

**Rules.**

- **A marker, not a control.** The Details link directly beneath it is the way in; a second link
  to the same destination would spend the card's one destination affordance twice.
- **`--accent`, never a status hue.** This is the exception the card's colour rule already has:
  `02-color.md` rule 3 makes the accent an *affordance*, not a status, which is why `.btn--link`
  is already accent-coloured here. A pending update is not a health problem and must never be
  able to look like one — it carries no amount and can never graduate (D-030).
- **Never inferred.** It renders from a served field or not at all. Deriving it across the roster
  from the surface would cost one `/api/companies/{id}` fetch per company — the exact price
  `12-application-shell.md` refused a cross-company Goals workspace for.

**Lit at M9-1d.** `/api/companies` now carries a presence-only `pending_update` boolean on every
card, from a cheap existence check (`PlatformKernel.has_pending_update`) that compares the
installed type's Band B digest against the stored contract's and the operator's own decline
record — never the full `ContractRefreshPlan` the company's own Details page still builds for
the drill-down, and never one `/api/companies/{id}` fetch per company across the roster. A
company the check cannot answer honestly (its type is no longer installed, or the refreshed
contract would be invalid) reads `false`, the same silence Details already keeps for its own
uncertain case — a marker that might be wrong is worse than one that says nothing.

### Meter — `.meter`

Ten segments, 2px apart, filled left to right. **Not a progress bar** — a progress bar implies a
task moving toward completion; health is a level that moves in both directions. The segmented
form reads as a gauge.

**Anatomy.** `.meter__row` (uppercase label, value right-aligned) above `.meter` (ten `.seg`,
`.seg--on` filled with the band's status colour).

**States.** by band (healthy / watch / at_risk) · empty (all segments track-coloured) · unknown
(track only, with the value rendered as a sentence beside it, never as `0`).

**Rules.** Segment count is fixed at 10 so the fill is readable as a percentage without a legend.
The numeric value is *always* shown next to it — the meter is the glance, the number is the fact.
Fill colour meets 3:1 against its own track in both themes (`09-accessibility.md`).

### Status dot — `.dot`

6px circle. Running takes `--status-healthy` and the `breathe` animation; paused is
`--text-muted` and static.

The running state has two selectors and one rule: `.co-card--running .dot` (inherited from the
card's own modifier) and the standalone `.dot--running`, for a dot outside a card — the company
workspace header being the first. One declaration, two entry points; defining the animation twice
is how two dots start breathing at different rates.

**Rules.** Always paired with a text status label. Never the sole carrier of a state.

### Badge / chip — `.chip`

Small pill: `--font-data`, `--size-sm`, uppercase off, `--surface-hover` fill,
`--border-subtle`.

**Variants.** `.chip--pass` / `.chip--fail` / `.chip--pending` for compliance-check chips on
approval cards — **SPEC ONLY**, awaiting the compliance-result field on the approval payload.
When it lands, a passing check is a chip with the healthy hue *and the word "passed"*.

**Rules.** Chips carry facts, not categories. A chip that says what kind of thing something is
duplicates a label and spends colour for nothing.

### Activity feed entry — `.entry`

**Anatomy.** hairline rule → `<time>` (relative, `--font-data`, muted) → what (body) →
why (`.entry__why`, secondary). An entry carrying a trailing control uses `.entry__row`
(flex, baseline) with `.entry__act` pushed right.

`.entry__why` was documented here from M8-2 while the code shipped a bare `.why` — the
doc-vs-code mismatch the UI Phase-1 gate recorded, in a system whose first rule is "extend,
don't reinvent". Resolved at M8-4 **in the code's direction of travel but at the doc's name**:
`.why` was also in use inside `.outgoing`, so the flat class was serving two blocks and neither
could own it.

**States.** normal · stuck (`.stuck` — left rule in `--status-risk`, washed background) ·
empty ("Nothing has happened yet.").

**Rules.** Relative time ("3h ago") in the feed; absolute time belongs in the audit drill-down.
Newest first. The `why` line is never omitted — an event without a reason is a log line, and
`docs/PRODUCT.md` asks the interface to explain itself.

### Goal line — `.entry` (goals variant)

Renders measured-vs-target in the metric's own unit, with direction-aware phrasing: `at most`
for `direction == "below"`, `at least` for `above`. A lower-is-better metric is not "behind" for
being small.

**States.** measured · unmeasured (one sentence) · **all unmeasured** (the whole section
collapses to a single sentence rather than a list of per-target stutters — M7-5b item 3, pinned
by test).

### Trend — `.trend`

Shipped at M9-2b, once `/api/companies/{id}/kpi-series` made a history readable. It was
**SPEC ONLY** from M8-2 to M9-2 because the data was unreachable, not because the form was
undecided — the reservation is what kept a plausible line off the page for three milestones.

**Anatomy.** A small inline `<svg>` above one line of `--font-data` prose, inside the goal
`.entry` it belongs to, so a metric and its history are never separated.

    ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈   ← the target, dashed, --border-strong
    ╲    ╱╲               ← the readings, --text-secondary
     ╲__╱  ●              ← the latest, --text-primary, filled
    5 readings · up from 2 metrics

**States — and the number of points decides which, never a preference.**

| Points | Renders |
|---|---|
| 0 | nothing at all. The goals section's own unmeasured sentence already says it, and an empty chart frame is a container promising a value it does not have. |
| 1 | the target line and **one dot**, no line, placed a *fixed* distance above / on / below the target — plus "on target · one reading so far — a trend needs a second." |
| 2+ | the target line, the reading line scaled to its own domain, the latest dot, and "ahead of target · *n* readings, up from / down from / unchanged". |

Every note leads with the **relation** — where the newest reading stands against its target — and
follows with the **movement**. A metric with no target has no relation to state and shows the
movement alone.

**Rules.**

1. **A line is never drawn through one point.** This is the whole reason the component was
   reserved rather than approximated, and it is the state most of the live data is in today
   (M9-F72): every real series on the platform holds exactly one reading. A two-point line
   invented from one reading and its target would be `01-principles.md` #3's defect with a chart
   drawn around it.
2. **The y domain includes the target.** Scaling to the readings alone is the truncated-axis
   lie: it turns noise into a swing, and it hides the only comparison a page about goals is
   for. Including the target answers "is this heading toward the line or away from it" — and it
   costs a metric sitting far from its target a flat-looking series, honestly flat, because it
   is.
3. **The chart never encodes a magnitude it cannot scale.** One reading has no domain: it and
   its target are the only two numbers, so they would always land on opposite edges of the box
   and a one-unit shortfall would draw identically to a thousand-unit one. The eye reads that
   distance as magnitude; it is not magnitude, it is an artifact of having two numbers. So a
   lone reading sits a **fixed** distance from its target line — relation stated, magnitude
   withheld, exact figures in the sentence directly above. This is the same instinct as rule 1
   one level down: do not draw what the data cannot support, even when the pixels are willing.
   *Above* and *below* are in value space, not in "good" space — a lower-is-better metric puts a
   good reading below the line, and which way is good is what the goal sentence says.
4. **It spends no colour.** The line is `--text-secondary` ink, the latest reading
   `--text-primary`, the target `--border-strong` dashed — three tokens the system already has,
   none of them a status hue. Colouring the line by attainment would put a second meaning on
   colour inside a page whose meter already means health (`01-principles.md` #2), and it would
   restate as a hue a judgement the health parts already give as a number.
5. **The prose line is the accessible equivalent, not a caption.** The `<svg>` is
   `aria-hidden="true"`, so everything the drawing says has to be sayable there — legible in
   greyscale and out loud. Same division of labour as the meter: the chart is the glance, the
   words are the fact.
6. **The relation is stated in words, because geometry cannot carry it.** Added at M9-2c by
   Phase-3 gate ruling (M9-F100). The chart alone drew Data freshness (0.0005 against a 24-hour
   ceiling — excellent) and Reports delivered (3 against a goal of 4 — short) as the *identical*
   mark: a dot below a line. It had to. The y axis is **value** space, and value space does not
   know which way is good — `direction: "below"` means lower is better (M7-F30), so "below the
   line" is a triumph for one metric and a shortfall for the next. Only words can say which, and
   because the `<svg>` is `aria-hidden` they were also the only channel a screen reader had. The
   relation compares the **newest** reading with the target, direction-aware, and is stated
   exactly once — the movement half never re-judges it.
7. **No draw-on animation** (`08-motion.md`). A line that animates into place performs; the data
   did not arrive gradually.
8. **Geometry is computed into SVG attributes, never into `style=`** — which the surface forbids
   outright, and which is the shape a CSS-drawn sparkline would have been forced into. The
   constraint chose the technique here, not taste.

**Not iconography.** `07-iconography.md` governs marks that stand for a concept. This is a
*data* mark, the same family as `.meter`: it renders values, it is inline markup with no asset
and no request, and it disappears when the values do.

---

## Attention

### Approval card — `.ask`

The loud object. Left rule in `--status-risk`, `--surface-base`, 20px padding.

**Anatomy.**

    "Trailhead Gear Reviews wants to publish today's post."   ← display, 19px
    ── facts grid ──────────────────────────────────
    WHAT HAPPENS   HOW MUCH   WHY NOW   WHAT COULD GO WRONG
    ── what will go out (open) ─────────────────────
    [full payload, every field, never trimmed]
    ── [Approve] [Say no] [Why?]        waiting 3h ago

**States.** editable payload (inputs, plus the sentence that says correcting it means Jarvis
keeps asking — D-010) · read-only payload (`<pre>`, "This is exactly what gets sent.") ·
mid-edit (the 15-second repaint is suppressed so typing is never destroyed) · empty queue (the
region collapses to a heading and "Nothing needs you right now." — on the Approvals workspace,
where this region is the whole page rather than a line above the company grid, the sentence
continues into what will appear here and why, so the good emptiness still teaches — M9-3).

**Rules.** The payload is shown **open and in full**. An operator who approves a summary of the
words has not approved the words (§8). Every value on this card is escaped before it becomes
markup — this card is the system's highest-value injection target.

### Pending update — `.pending-update`

A company whose installed template changed since it was created (design
`PLUGIN-FRAMEWORK.md` Part 4/6, D-030). Lives on the company's own Details
sheet, never in the approvals queue — it never carries an amount and can
never graduate, so it must not read as an `.ask`.

**Anatomy.**

    "Trailhead Gear Reviews — an update is ready for this company."   ← headline, display
    "The Affiliate publisher setup has changed since this company was created."  ← intro
    • It will stop starting a new round of work when its own work comes back.
    [Review and apply] [Not now]

**States.** present (rendered only when at least one changed field has an approved sentence
— design Part 6: an unrenderable field is an unrefreshable one) · absent (nothing renders;
this is also today's status quo, so absent is always a safe default).

**Rules.** Left rule is `--accent`, never `--status-risk` — this is the platform proposing a
change, not a company asking for money or authorization (contrast `.ask`). Every sentence in
the changed-fields list comes from the platform-owned field-to-sentence table, filled from
stored values — never a raw field name, a version string, or model prose (D-011). "Review and
apply" is `.btn--primary`, matching "one primary action per context" — the context is what
distinguishes it from an approval's own primary button, not the button's own colour.

### Banner — `.banner`

One-line status region with a 3px left rule.

**Variants.** `.banner--watch` (degraded dependency) · `.banner--down` (failure, also used by
the transient action-failure flash) · `.banner--note` (a notification, with a dismiss control
and a relative timestamp pushed right).

**Rules.** Banners state a consequence and, where one exists, a remedy. They are never used for
success — a successful action shows its result, not a congratulation.

### Empty state — `.empty`

Dashed border, centred, generous padding.

**Anatomy.** headline (display) → one sentence explaining what will appear here and how to begin
→ the primary action.

**Rules.** Never "No data". The empty state is a teaching surface — it names the thing that will
appear, says what it will do, and offers the first step. This is `docs/PRODUCT.md`'s
"empty states should teach" made structural.

---

## Containers

### Panel / sheet — `.panel` / `.sheet`

Modal overlay: `--surface-overlay` scrim, `--surface-raised` sheet, max 640px, the system's only
shadow.

**Behaviour.** `role="dialog"`, `aria-modal="true"`, labelled by its own title. Closes on
Escape, on scrim click, and on its Close button. Scrolls internally.

**States.** closed · open · loading a lazy section (audit detail is fetched only when its
`<details>` is opened).

**Focus (M8-F23, closed at M8-4).** Focus enters the sheet on open, Tab is contained while it is
open, and focus returns to the invoking control on close — or to the workspace when the repaint
has since replaced that control. Shared with the overlay rail via `app/focus.js`; see
`12-application-shell.md`.

### Disclosure — `<details>` / `.disclosure`

Native `<details>`/`<summary>`, styled to the eyebrow-label treatment.

**Rules.** Used for the third disclosure level only (`10-interaction-patterns.md`). Content
behind a disclosure is fetched on open, never eagerly — drill-down is opt-in per §12.5.
Exception: the approval payload's disclosure ships `open`, because it is not a drill-down; it is
the thing being authorised.

---

## Shell components — shipped at M8-4

Full specification: `12-application-shell.md`.

### Nav item — `.nav-item`

**Anatomy.** Label only, no icon (`07-iconography.md`). Optional `.nav-item__count`.

**States.** rest (`--text-secondary`) · hover (surface lifts) · active `.nav-item--on` (accent
left rule **plus** `--text-primary` **plus** `aria-current="page"` — three channels, never
colour alone) · focus-visible (the system ring).

**Rules.** The transparent left border is present at rest, so becoming active moves no text. An
item exists only if its workspace exists — see `12-application-shell.md`, "a nav item is a
promise that a destination exists".

### Nav item badge — `.nav-item__count`

Only ever a count that **needs the operator** (pending approvals); never a total. Zero removes
the badge rather than rendering `0`.

### Top bar — `.topbar`

**Anatomy.** Menu control (overlay widths only) → workspace title (`<h1>`, display face) →
status word → notification control → New company.

**Rules.** The status word is always present and always paired with the banner beneath it; the
word carries the state and the colour only emphasises it.

### Notification center — `.note-center`

A disclosure in the frame, not a workspace. The count on its control is always visible, so the
existence of an update is never hidden — only the reading of it is deferred to one click. Empty
state is `.calm`: no notifications is a good emptiness.

---

## Workspace components — shipped at M9-2

Full specification: `13-company-workspace.md`.

### Return link — `.ws-back`

**Anatomy.** A single `<a href>` to the parent workspace, prefixed by a `‹` and reading
"All companies" — the destination, never "Back". "Back" describes the operator's history; the
label should describe where they will land, because a route can be arrived at from anywhere
(a link, a reload, a bookmark) and only one of those has a "back".

**Rules.** First element in the pane, so it is the first Tab stop. Muted at rest, primary text on
hover; it is a way out, not an invitation. It never replaces the browser's own Back — it is a
second, visible path to the same place.

### Company page header — `.co-head`

**Anatomy.** Two groups on one row, wrapping at narrow widths.

    Portfolio Watch                        ● Running   [Pause]
    Finance tracker
    Tracks the financial metrics you configure…

Left: name (`--font-display`, `--size-4xl`), `.kind`, `.kind-desc`. Right: `.dot` +
status word, then the one lifecycle control.

**States.** running · paused (`.co-head--paused` desaturates the name to secondary, matching
`.co-card--paused`, so a paused company looks the same at both levels).

**Rules.** The header carries identity and the *one* action that changes it. Every other number
belongs to a tile or a section below — a header that grows a fourth fact has become a dashboard
and stopped being a title.

The name is a `<p>`, **not a heading**. On this route the top bar's `<h1>` already *is* the
company's name, and a second heading one level down makes a screen reader announce it twice; the
page's heading outline is then one `h1` and one `h2` per section, with no duplicate and no skip.
Same shape as `.co-card__name`, which is a `<div>` for the same reason.

### Workspace split — `.co-layout`

Two columns: `minmax(0, 1fr)` main and `minmax(0, var(--layout-side))` side, `--space-9` gap,
collapsing to one column at `--bp-md`.

**Rules.** Things that change go left, things that are go right. Both tracks are `minmax(0, …)`,
never a bare `1fr`: a grid item's default `min-width` is its content, and one long unbroken
string in the activity feed would widen its track and scroll the page sideways.

### Still SPEC ONLY

- **Persona chip** — see `11-persona-components.md`. **No rendering path until persona data
  exists.**
**Trend indicator — released.** It sat here from M8-2 to M9-2 for want of a route, and shipped
at M9-2b as **`.trend`** (above) once `/api/companies/{id}/kpi-series` existed. The delta it
was specified as — "direction arrow plus delta" — did not survive the real data: with one
reading per series there is no delta to state, so the component's one-point state says so in
words instead of pointing an arrow at nothing. The reservation worked exactly as intended; what
it protected was three milestones of not drawing that arrow anyway.
