# 13 — The Company Workspace

The pattern every per-company page inherits (M9-2, UI Phase 3). `12-application-shell.md`
built the frame and named four rail destinations; this document adds the first destination the
rail does **not** own — the page an operator reaches by drilling into one company.

    ┌────────────┬───────────────────────────────────────────────┐
    │  rail      │  top bar    Portfolio Watch · status · New co  │
    │  Companies ├───────────────────────────────────────────────┤
    │  ← lit     │  system strip                                 │
    │            ├───────────────────────────────────────────────┤
    │            │  ‹ All companies                              │
    │            │  Portfolio Watch          ● Running  [Pause]  │
    │            │  Finance tracker                              │
    │            │  ── tiles: health · goals · spent · your OK ── │
    │            │  ── approvals, scoped to this company ──────   │
    │            │  ┌── main ─────────────┐ ┌── side ──────────┐  │
    │            │  │ needs attention     │ │ health           │  │
    │            │  │ goals               │ │ money            │  │
    │            │  │ what it's doing     │ │ on its own       │  │
    │            │  │ full details        │ │                  │  │
    │            │  └─────────────────────┘ └──────────────────┘  │
    └────────────┴───────────────────────────────────────────────┘

---

## The decision this workspace rests on

> **The company page is level 2. It replaces the Details sheet; it is not added beside it.**

`10-interaction-patterns.md` opens with "exactly three levels — a fourth means the information
architecture is wrong." A company workspace that shipped *alongside* the Details sheet would be
that fourth level, and worse: two surfaces would answer the same question with the same fields,
diverging on the first change either one received.

So the sheet's whole contents move here — health parts, goals, activity, autonomy grants, stuck
work, the pending template update, and the "Full details" disclosure — and `openCo()` is deleted
rather than kept as a second door. The ladder is unchanged in shape:

| Level | Surface | Reached by |
|---|---|---|
| 1 | Company card | a glance at the Companies workspace |
| 2 | **Company workspace** (`#/companies/<id>`) | one click — a **link**, not a dialog |
| 3 | Full details | one more click, **and a fetch**, inside level 2 |

Three properties come free with the route that the sheet could never have: it survives a reload,
it can be linked and opened in a new tab, and Back returns the operator to where they came from.
A modal that carries a company's entire operational record was always a dialog impersonating a
page.

Because level 2 is now a route, the controls that reach it are `<a href>` and not buttons —
"Details" on the card, "more in Details" in a truncated update, and "Why?" on an approval all
navigate, so they are links (`12-application-shell.md`'s own argument for the rail, applied one
level down). They keep `.btn`/`.btn--link` styling; nothing about their appearance changes.

## Section order, and why it is that order

`05-layout.md` argues the page frame from the operator's eye: **status, then what needs you,
then what you own.** One company is the same question asked at smaller scale, so the order is:

1. **Return path** — `‹ All companies`. First in the DOM, so a keyboard operator's first Tab is
   the way out.
2. **Identity and state** — name, kind, what the kind promises, running/paused, and the one
   control that changes it.
3. **The summary band** — four tiles. This is a summary of the sections below it, which level 1
   is explicitly forbidden from being. The rule it does not break: level 1 must answer *"should
   I look closer?"* with one well-chosen fact, because a condensed everything is harder to read
   than one thing. The operator on this page has already decided to look closer; a band that
   orients them before they read is doing a different job.
4. **Approvals, scoped to this company** — the loud object, full width, above the split. It is
   the same `asks` region the Command Center and Approvals workspaces declare, so it inherits
   the mid-edit repaint suppression rather than reimplementing it.
5. **The split.** Main column: what is happening — stuck work, goals, the activity feed, full
   details. Side column: the standing numbers — health with its parts, money, autonomy grants.
   Things that *change* on the left, things that *are* on the right.

## What backs every element on this page

Nothing here is drawn from a value Jarvis does not serve (`01-principles.md` #3).

| Section | Fields | Endpoint |
|---|---|---|
| Header | `name`, `kind`, `kind_description`, `status`, `running` | `/api/companies/{id}` |
| Tile — health | `health`, `health_band` | `/api/companies/{id}` |
| Tile — goals measured | how many of `goals[]` have a `measured` | `/api/companies/{id}` |
| Tile — spent | `spent`, `budget` | `/api/companies/{id}` |
| Tile — needs your OK | the queue filtered on `company_id` | `/api/approvals` |
| Pending update | `pending_update` | `/api/companies/{id}` |
| Approvals | full card, filtered on `company_id` | `/api/approvals` |
| Needs attention | `stuck[]` | `/api/companies/{id}` |
| Goals | `goals[]` — `label`, `measured`, `target`, `unit`, `direction` | `/api/companies/{id}` |
| Activity | `activity[]` — `when`, `what`, `why` | `/api/companies/{id}` |
| Health | `health`, `health_band`, `health_reason`, `health_parts` | `/api/companies/{id}` |
| Money | `spent`, `budget`, `per_round_limit` | `/api/companies/{id}` |
| On its own | `can_do_alone[]` | `/api/companies/{id}` |
| Full details | the raw audit record | `/api/companies/{id}/full-details` |

### The arithmetic rule

> **The surface never recomputes a number the platform already computes.**

Goal attainment is direction-aware — a lower-is-better metric at 0.5 against a 24-hour target is
excellent, not a 98% miss (`KpiEngine.attainment`, M7-F30). Deriving a per-goal percentage in
JavaScript would put a second implementation of that rule in a second language, and the two would
disagree the first time either changed. So the page renders `measured` against `target` in the
metric's own unit and takes the aggregate from `health_parts` — server-computed, one source.

Counting is not computing: "2 of 3 measured" counts array members and states no judgement about
whether either number is good.

## The reservation, and what happened to it

`12-application-shell.md` reserves *destinations*; this document reserved an *element* — the
trend — for the same reason and at the same cost to the operator, none:

> **Trend indicator / sparkline.** `kpi_values` is a real append-only series since D-027 and
> `KpiEngine.series()` already reads it — but no route serves it. The page has `measured` (the
> latest reading) and nothing before it. A line drawn through one point is not a trend, and a
> trend drawn from anything else is invented. **Unblocked by:** a per-company KPI series read.

**Released at M9-2b.** `GET /api/companies/{id}/kpi-series` shipped at M9-2a and the component
is `.trend` in `06-components.md`. Two things are worth keeping from how it went:

- The reservation named its unblocking condition, and the endpoint that arrived satisfied it —
  so the surface consumed a real read on the first attempt instead of negotiating a shape.
- **The reservation's own worry turned out to be the live case.** Every real series on the
  platform today holds exactly one reading (M9-F72). The temptation the reservation existed to
  resist — "a target, a current reading and a direction is *almost* enough to draw an arrow" —
  is still the whole of the data. The component answers it by rendering one point as one point:
  a dot against the target line, and the sentence "one reading so far — a trend needs a second".

Nothing else on this page is reserved.

## Fetching the series without paying for it every cycle

The workspace repaints every 15 seconds and `/api/companies/{id}` is already the most expensive
read on the surface (M9-F26). Adding a second per-company fetch to that cycle unconditionally
would have doubled exactly the wrong thing.

**The series is refetched only when a new reading could exist.** KPI observations are written by
the wake cycle, and D-021 makes every completed cycle write exactly one Decision Log entry — so
`activity[0].when`, which this page already holds from the detail payload it just fetched, is a
sound freshness key at zero extra cost. The cached series is reused until that timestamp moves.

    fetch the series when   the route's company changed
                     or     nothing is cached for it
                     or     the newest activity timestamp differs from the cached one
                            AND document.visibilityState === 'visible'

The visibility condition guards the third case only. A hidden tab has nobody reading it and its
series can wait for the repaint after it comes back; but a page painting for the first time must
show real data whether or not the browser calls the tab foreground, and a cache miss has nothing
to fall back on — so the first two conditions are unconditional.

The cache holds **one** company, not a map. An operator moving back and forth between two
companies refetches a read they are actively looking at, which is the case a cache is not for,
and a map would keep a company's readings alive long after the operator left it.

**The coupling to accept, stated rather than buried:** a reading recorded without any Decision
Log entry would go unseen until the next cycle that writes one. D-021 makes that impossible
today, and the staleness would be bounded by one cycle rather than unbounded — but the freshness
key is tied to D-021, not to `kpi_values` itself, so a future change to cycle recording should
know it has a reader here.

## Repaint rules

The surface repaints every 15 seconds (`10-interaction-patterns.md`). This page adds one case to
the two rules already there:

> **Reading in depth is work too.** While the "Full details" disclosure is open, the main column
> is not repainted. A repaint would replace the `<details>` element, snapping it shut and
> discarding the audit record the operator asked for and waited on — the same defect class as
> deleting half-typed text in an approval, arrived at from the other direction.

The header, the summary band and the approvals region keep updating; only the column holding the
open disclosure is held. The audit record behind it is append-only history, so holding it costs
the operator nothing they would have wanted.

The top bar's title is the company's name, which is data and arrives with the fetch. The shell
sets the parent workspace's label on navigation and the workspace's own module replaces it —
so the title is never blank, and never a raw identifier while it loads.

## Empty, null and error states

| State | Treatment |
|---|---|
| No approvals for this company | `.calm` — "Nothing from *[name]* needs you right now." Scoped, so it cannot be confused with an empty platform-wide queue. |
| No stuck work | The section does not render. There is no container waiting to be filled — the health reason already carries "Nothing stuck". |
| No autonomy grants | One sentence naming what would appear here and how it gets there. This is a teaching empty state: grants are earned, and an operator who has never seen one does not know that. |
| Every goal unmeasured | One sentence for the whole section (M7-5b item 3), unchanged from the sheet and still pinned by test. The goals tile agrees with it — its context line reads "nothing measured yet", not "against its own targets", because `0 of 1` beside the latter invites the reading that the company *missed* one. |
| No goals at all | The tile value is `—` with "no goals set yet" beside it. A tile shows `—` only when the platform genuinely has no value; `0 of 0` would be a zero that means nothing. |
| No activity | "Nothing has happened yet." |
| The id in the URL matches no company | An `.empty` state naming the situation and offering the way back. A hand-edited hash is not an exception the surface may fail silently on. |

## Responsive

The split is `minmax(0, 1fr)` main / `minmax(0, var(--layout-side))` side, and collapses to one
column at `--bp-md` (900px) — the same breakpoint at which the card grid goes two-up. Below it
the order is main-then-side, which keeps "what is happening" above "what the numbers are" on a
narrow screen, exactly as the four-region page frame keeps attention above inventory.

`minmax(0, …)` on both tracks rather than a bare `1fr`: a grid item's default `min-width: auto`
is its content, so one long unbroken string in the activity feed would push the column wider than
its track and scroll the page sideways — which `05-layout.md` rule 4 forbids.
