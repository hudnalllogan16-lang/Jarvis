# 06 — Component Library

Every component the surface uses today, plus the ones the Application Shell (M8-4) needs.
Each entry gives **anatomy** (what it is made of), **states** (all of them, including the ugly
ones), and **rules** (what would be wrong).

Implementation: `jarvis/api/static/styles/components.css`. Markup is produced by the ES modules
in `jarvis/api/static/app/`.

Components marked **SPEC ONLY** have no rendering path yet, deliberately — the data behind them
does not exist. Shipping them would violate `01-principles.md` #3.

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
the reason something is wrong — e.g. spending paused) · null (value renders `—` **only** when
the platform genuinely has no value; a zero that means zero renders `0`).

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
why (`.entry__why`, secondary).

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
region collapses to a heading and "Nothing needs you right now.").

**Rules.** The payload is shown **open and in full**. An operator who approves a summary of the
words has not approved the words (§8). Every value on this card is escaped before it becomes
markup — this card is the system's highest-value injection target.

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

**Known gap (M8-F23):** focus is not yet trapped inside the open sheet, and focus does not
return to the invoking control on close. Recorded, not fixed here — it belongs with the shell's
focus management (M8-4). See `09-accessibility.md`.

### Disclosure — `<details>` / `.disclosure`

Native `<details>`/`<summary>`, styled to the eyebrow-label treatment.

**Rules.** Used for the third disclosure level only (`10-interaction-patterns.md`). Content
behind a disclosure is fetched on open, never eagerly — drill-down is opt-in per §12.5.
Exception: the approval payload's disclosure ships `open`, because it is not a drill-down; it is
the thing being authorised.

---

## Shell components — SPEC ONLY

Needed by M8-4, specified here so that packet extends rather than invents.

- **Nav rail** — vertical, fixed width, one item per workspace. Items are label-first; the
  active item is marked by an accent left rule plus `--text-primary`, never by colour alone.
- **Nav item badge** — a count pill reusing `.section-head__count`. Only ever shows a count that
  needs the operator (pending approvals); never a total.
- **Persona chip** — see `11-persona-components.md`. **No rendering path until persona data
  exists.**
- **Trend indicator** — direction arrow plus delta, in `--font-data`. Requires a time series the
  API does not serve. Specified in `02-color.md`'s "not yet" section; not drawn here because its
  form depends on data shape that does not exist.
