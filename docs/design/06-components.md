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
`spending_paused`) and `/api/health`. A tile whose number has no endpoint does not ship —
the concept image's "milestone status" tile is exactly this case and was dropped, not faked.

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
    [Details] [Pause]

**States.** running (dot breathes) · paused (surface desaturates, text drops to secondary) ·
health band healthy / watch / at_risk (drives meter fill only) · truncated update (ellipsis
plus an explicit "more in Details" affordance — M7 product re-review F3).

**Rules.** **One meter and one sentence.** The three health parts belong to Details, not the
card; this was ratified at M7-5a and re-deciding it needs a reason. Colour means health and
nothing else, which is why `kind` is grey type rather than a badge. The card never shows a raw
identifier.

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

6px circle. `--running` takes `--status-healthy` and the `breathe` animation; paused is
`--text-muted` and static.

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

### Still SPEC ONLY

- **Persona chip** — see `11-persona-components.md`. **No rendering path until persona data
  exists.**
- **Trend indicator** — direction arrow plus delta, in `--font-data`. Requires a time series the
  API does not serve. Specified in `02-color.md`'s "not yet" section; not drawn here because its
  form depends on data shape that does not exist.
