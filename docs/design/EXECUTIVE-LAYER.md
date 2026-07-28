# The Executive Layer

**Status:** design, awaiting Manager review. No implementation. Packet M9-1, Lane A, wave 0.
**Scope:** how §3's deterministic/judgment split is implemented — the CFO's budget rollups,
cap tracking and alerts and the COO's health aggregation as deterministic scheduled code; the
judgment cadences designed and deferred; §3.1's strategic responsibilities designed with their
§8/§12.5 surfaces named; and the interaction boundary §3 and §5 draw around all of it.

This document decides nothing that D-001…D-037 already decided, and proposes nothing that
lacks a finding or a live reading behind it. Where a resolution would change a MUST/MUST NOT,
alter a D-entry's semantics, widen a security boundary, or change what an operator sees beyond
D-007's table, it stops and says so (Part 10).

Every claim about live behaviour below was read out of the live database read-only on
2026-07-27. Nothing was written.

---

## Part 0 — What the platform already contains of §3

The Executive Layer reads as unbuilt. It is not. **It is unassembled**: six of its parts exist
as platform primitives whose Executive-shaped caller was never written, and reading them
together is what this design starts from.

| §3 / §3.1 responsibility | Where it lives today | State |
|---|---|---|
| Health score, "a deterministic COO function" | `jarvis/kpi/engine.py`, D-009 | **Built, per company.** Nothing aggregates across companies. |
| Budget ceilings and pre-flight refusal | `jarvis/budget/ledger.py`, D-003/D-022 | **Built.** Enforcement only; no rollup, no forward-looking view. |
| Platform spending halt and its "why" (§9, §12.5) | `jarvis/budget/breaker.py` | `assert_closed` is wired at the pool boundary. **`trip()` has no caller in `jarvis/`.** |
| Executive/platform narrative (§11.5) | `DecisionLog.record_platform_decision`, `platform_feed` | Writer called only by `breaker.trip()`, which nothing calls. **Reader: none in `jarvis/`.** Live rows: **0**. |
| Spend alerting | `NotificationKind.SPENDING` | **Zero writers, zero readers.** A declared kind with no producer. |
| KPI targets "set by the Executive Layer (§3.1)" | `KpiTarget`, `contract.kpi_targets` | Built. Set by the **type's** defaults; M7-F24 confirmed no other source exists. |
| The §3.2 hierarchy seam | `ManagerState.supervisor = "executive"` | A string. **Nothing reads it**, deliberately (§14). |

Five of those seven rows are the shape `docs/DEPENDENCIES.md` has now recorded twice —
`KpiEngine.record` (M7-F21) and `AutonomyCounterRow.plugin_major_version` (M8-F8): a component
built ahead of its caller, never entered in the deferred-completion ledger, found by reading
rather than by failing. **M9-F1.** The ledger's own rule says the row is written when the
component is; the milestone that finally supplies the callers is the last honest moment to
write them, and this design's first obligation is therefore bookkeeping, not construction.

### What the live platform looks like today

Three companies, all ACTIVE, read 2026-07-27:

| Company | Type | Cap | Per-cycle ceiling | Lifetime spend | Cap used | Recorded cycles |
|---|---|---|---|---|---|---|
| Trailhead Gear Reviews | affiliate | $25.00 | $1.00 | $1.450000 | 5.80% | 0 |
| Summit Trail Gear | affiliate | $25.00 | $2.00 | $5.907450 | 23.63% | 7 |
| Portfolio Watch | finance_tracking | $15.00 | $2.00 | $1.819100 | 12.13% | 2 |

Computed through the platform's own `KpiEngine.health`, against those same rows:

| Company | Headroom | Reliability | Attainment | Score | Band | Summary |
|---|---|---|---|---|---|---|
| Trailhead Gear Reviews | 94 | 100 | 0 | **73** | healthy | "Just getting started — no goals hit yet." |
| Summit Trail Gear | 76 | 100 | 0 | **67** | **watch** | "Set goals but hasn't hit any of them yet." |
| Portfolio Watch | 87 | 100 | 91 | **93** | healthy | "Running normally." |

Portfolio totals: **$65.00 committed capital**, **$9.176550 lifetime spend**, **$55.82
headroom (85.9%)**, **$0** in the rolling 24h window, platform ceiling **$500/24h**. Zero
unresolved dead letters. Three `kpi_values` rows, all Portfolio Watch's. Four notifications,
all `needs_approval`. Zero platform-scoped Decision Log entries.

Two numbers in that table do the most work in this document, and both are Part 2's.

---

## Part 1 — The split, and what makes it enforceable

§3 divides the Executive Layer into functions that are deterministic and functions that
exercise judgment. M9 builds the first half and designs the second. The division is only worth
anything if "deterministic" is a checkable property rather than a label, so it is defined here
by its inputs:

> **A deterministic Executive function is a pure function of stored values** — ledger rows,
> stored contracts, `kpi_values`, Decision Log entries — **whose output is reproducible from
> those values alone.** No model call. No wall clock except an injected one. No dependence on
> the order it happened to read things in.

### The rule that keeps the halves apart

> **A deterministic Executive function computes and reports. It never writes to a contract.**

Every strategic responsibility §3.1 names — capital allocation, KPI target setting, portfolio
balancing — is a *contract write*. Freezing the deterministic half to reads therefore puts the
whole judgment surface on one side of one boundary, and makes "the deterministic half calls no
model" enforceable as a property of a package rather than a promise in a docstring.

### The frozen surface, enumerated

**The Executive Layer MAY read:**

| Source | Through |
|---|---|
| Which companies exist, and their state | `BusinessRegistry.list_instances`, `get_state` |
| Any company's Standard Business Contract (§5) | `BusinessRegistry.get_contract` |
| Spend, per business / per cycle / platform 24h | `BudgetLedger.business_spend`, `cycle_spend`, `platform_spend_24h` |
| Health and attainment, per company | `KpiEngine.health`, `attainment`, `latest`, `series` |
| The operator-facing narrative | `DecisionLog.activity_feed`, `platform_feed` |
| Raw detail, drill-down only (§11) | `AuditLog` |

**The Executive Layer MUST NOT read** — every one of these is a business internal, and §3 says
the Executive interacts with a business only through the §5 contract:

- `ManagerState` or any Temporal workflow state. D-005 already made the Decision Log the
  history of record; reading workflow state would give the Executive a second, divergent one.
- Prompt templates, capability results, tool payloads, invocation parameters.
- `capability_permissions[].credential_refs`, or anything reachable from them (§10).
- Business-local memory (§7). There is no cross-business read to reach it with, by
  construction, and this design adds none.

**The Executive Layer MAY write:** platform-scoped Decision Log entries
(`record_platform_decision`), operator notifications, and audit records. Nothing else, in the
deterministic half.

**The Executive Layer MUST NOT vary or contain:** business-specific logic of any kind (§5,
stated in `jarvis/domain/contract.py`'s own module docstring); the Health Score formula
(D-009 — a portfolio-level formula would reintroduce, one layer up, exactly the
incomparability D-009 exists to prevent); the approval gate and its rendering (D-011, D-013,
D-024); the budget hierarchy (D-003); the lifecycle machine (D-008).

### Making the boundary a test rather than a convention

The mechanically checkable form, in the spirit of `tests/test_manager_determinism.py`:

> **The deterministic Executive package imports `registry`, `budget`, `kpi`, `observability`
> and `notifications`, and nothing else.** In particular it does not import `jarvis.llm`,
> `jarvis.manager`, or `jarvis.capabilities`.

An import of `jarvis.llm` from that package is precisely the event "someone crossed the
deterministic/judgment line", and it is the cheapest possible detector for it. `jarvis.manager`
and `jarvis.capabilities` are the two packages through which business internals are reachable,
so excluding them enforces §3's interaction boundary structurally rather than by review.

### Layering, and one real consequence

A new `jarvis/executive/` package is **milestone 9**: it reads `registry`/`observability` (M1),
`budget` (M2), `kpi`/`notifications` (M3), and must be imported by nothing earlier. It needs a
row in `tests/test_layering.py`'s `MILESTONE` map and in `docs/DEPENDENCIES.md`'s table, or
`test_every_package_has_a_milestone` fails — which is the invariant working.

The consequence that is not bookkeeping: **`Scheduler` is milestone 4 and cannot call into
milestone 9.** The deterministic Executive functions therefore cannot ride `Scheduler.sweep`,
which was the obvious home for them. Part 7 resolves it, and the resolution turns out to be
better than the thing the invariant forbade.

---

## Part 2 — The CFO's deterministic functions

### 2.1 — The finding that shapes everything: the business cap has no window

`BudgetLedger._business_spend` sums the ledger for a business **with no time bound**.
`_platform_spend_24h` bounds its aggregate to a rolling 24 hours. So the two ceilings D-003
relates are measured in different units:

- **`business_cap_usd` is a lifetime budget.** It depletes and never refills.
- **The platform ceiling is a daily flow.** It refills every 24 hours.

Three consequences, all live rather than theoretical.

**A rollup that adds the caps and compares them to the platform ceiling is meaningless.**
$65.00 committed against $500/24h compares a stock to a flow. Anything the CFO reports must
name its window in the same breath as its number, or it will be read as the comparison it
cannot be.

**A company's budget headroom can only ever fall.** Headroom is 30% of D-009's Health Score.
Summit Trail Gear is at 23.63% of its cap after two days; its headroom component has gone from
100 to 76 and has no path back. As headroom → 0 its score converges on
`reliability × 0.45 + attainment × 0.25` — for Summit today, with attainment 0, a floor of
**45**, five points above the `at_risk` threshold of 40. A company reaches that by nothing
worse than continuing to work.

**The runway is short and countable.** Summit's seven recorded cycles cost $5.907450, or
$0.8439 per cycle. Its remaining $19.09 is **≈22 more cycles**. Set that against
`max_cycles_per_day` = 48 and the comparison is stark: **Summit's entire lifetime cap is ≈30
cycles — smaller than a single day's permitted allowance.** A day of work at the rate the
platform permits would cost $40.51 against a $25.00 lifetime cap. The company halts
permanently, and nothing but a person raising the cap restarts it.

That last sentence is the strongest argument in this document for why §3.1's capital allocation
is not decoration. Today the only mechanisms that can return headroom to a company are an
operator editing the cap — and no such surface exists (M7-F24's neighbour) — or an Executive
reallocation, which does not exist either.

**Whether `business_cap_usd` is a lifetime budget or a windowed one is a D-003 semantics
question and this packet does not answer it (Part 10.1, ESCALATION).** What the CFO design can
do inside its mandate is refuse to hide it, which is what 2.2 does.

### 2.2 — The rollup

`PortfolioRollup` — a frozen value, produced by a pure function over stored values, where
**every field names its own window**:

| Field | Window | Live value |
|---|---|---|
| `committed_capital_usd` | lifetime, sum of caps over non-RETIRED companies | $65.00 |
| `lifetime_spend_usd` | lifetime | $9.176550 |
| `lifetime_headroom_usd` / `_pct` | lifetime | $55.823450 / 85.9% |
| `rolling_24h_spend_usd` | 24h | $0 |
| `platform_ceiling_usd` / `rolling_24h_utilisation_pct` | 24h | $500.00 / 0% |
| `per_company[]`: cap, lifetime spend, headroom, utilisation | lifetime | see Part 0 |
| `per_company[].runway_cycles` | per cycle | Summit ≈22 |

`runway_cycles` is deliberately expressed in **cycles, not days**: a cap is consumed per cycle,
`max_cycles_per_day` bounds only the ceiling of the rate, and reporting "1.9 days" would state
a precision the platform does not have. It is computed as remaining headroom divided by
observed mean cost per recorded cycle, and it is **undefined, not zero, when a company has no
recorded cycles** — which is Trailhead's live state and is why the field must carry an absent
case rather than a default (a default of 0 would render as "no runway" for a company that has
simply never been measured; a default of infinity would render as "fine" for the same reason,
and both are the M7-F21 failure with a different number).

Nothing here is new arithmetic. Every input is a value the platform already stores.

### 2.3 — Cap tracking and alerts

Deterministic, scheduled, and the first writer for a notification kind that has had none since
M3.

**Bands: 50%, 80%, and breach**, of `business_cap_usd`. Chosen against the live data rather
than by convention: the largest live utilisation is Summit's 23.63%, so 50% is a threshold
nothing has yet crossed — the right property for a first alert, which should fire while there
is still something an operator can do. At Summit's observed rate 50% leaves ≈15 cycles and 80%
leaves ≈6, so the two bands are "there is time to decide" and "decide now" rather than two
arbitrary percentages. Breach is already surfaced at the point of refusal (2.4).

2.1's arithmetic is also the honest caveat on the whole band scheme: a company whose entire cap
is smaller than one day's permitted cycles can cross 50% and 80% inside a single working
session. Percentage bands are the right alert for the cap as *specified*; whether they are a
useful alert for the cap as *currently measured* depends on the escalation in Part 10.1.

**Kind: `NotificationKind.SPENDING`.** No new kind, no new vocabulary.

**Deduplication needs no new state.** `NotificationService.has_unread(business_id, kind=…)` is
per company and per kind, and its recorded posture is exactly right here: an operator who
dismissed the notice has said they know, and a condition still true at the next check is worth
saying again. One further rule the alert itself must carry: **the band is the state**, so
crossing 50% announces once and crossing 80% announces again — re-announcing the same band on
every sweep is the ninety-six-notices-a-day failure `has_unread`'s docstring already names.
Because the notification row records which band was announced, this needs no table.

**The sentences are D-007's, moved earlier.** D-007 already gives "[Company] hit its spending
limit" for a reached cap; the alert says the same thing before it happens. That matters for
this packet's escalation trigger: the CFO's alerting introduces **no operator-visible behaviour
beyond D-007's table** — it changes *when* an existing sentence arrives, not what an operator
is told exists.

### 2.4 — The narrative that is never written

`CircuitBreaker.trip()` writes §12.5's promised "Jarvis paused spending across all companies"
into the platform Decision Log. **Nothing in `jarvis/` calls it.** `CapabilityPool` calls
`assert_closed`, which raises `CircuitBreakerOpenError` and returns a refusal; the explanation
is never recorded. The live database corroborates it exactly: **zero rows** in `decision_log`
with `business_id IS NULL`.

So the platform's one existing Executive-shaped narrative — the single most likely prompt for
"why did everything stop?", by the breaker module's own docstring — has a writer, a Decision
Log, an operator feed, and no path between them. It is §3's CFO row (budget alerts) and it is
a one-caller fix. **M9-F2.**

The fix belongs beside `assert_closed`'s caller, not inside `assert_closed`: a check that
writes is no longer a check, and the pool boundary is invoked per dispatch, so recording there
would write one entry per refused invocation instead of one per halt. The honest shape is a
transition — the halt is recorded when the breaker *becomes* open, which is a state change the
CFO's scheduled pass can observe deterministically from spend and ceiling alone.

---

## Part 3 — The COO's health aggregation

D-009 put the Health Score in the platform "because a score must be comparable across
businesses to be aggregatable at all". Aggregation is the half that was never built. The
question no §5 or §3 sentence answers is what a *portfolio's* health is, and the live data
answers it better than an argument would.

Three candidate aggregates, computed from the same three live scores:

| Candidate | Value | Band it would read as |
|---|---|---|
| Unweighted mean | 77.67 | healthy |
| Capital-weighted mean | 75.31 | healthy |
| Worst company | 67 | watch |

**All three means say "healthy" while a third of the portfolio sits on `watch` with zero goal
attainment after seven cycles.** That is not a tuning problem; it is what a mean does.

### The design: a portfolio has a census, not a score

`PortfolioHealth` carries **counts per band, the worst company named, and the distinct reasons
present** — and no single number:

```
healthy 2 · watch 1 · at risk 0
Summit Trail Gear needs a look — it set goals and hasn't hit any of them yet.
```

Three arguments, in order of weight:

1. **A mean of comparable scores is not comparable to anything.** D-009 made per-company scores
   mean the same thing so they could be set beside each other. Averaging them produces a
   number with no referent — there is no threshold at which a portfolio mean of 75 means
   something an operator can act on — and its only reliable effect is the one the table above
   demonstrates: making a portfolio containing a failing company look fine.
2. **It keeps D-009's frozen surface frozen.** Part 1 forbids a type declaring a health
   formula. A portfolio score would be a *second* formula, invented one layer up, with no
   §5 field behind it and no finding requiring it.
3. **It needs no new operator vocabulary.** The operator already reads bands per company
   (M8's tile row). A census is those same words counted, which is why this satisfies §12.5
   without touching D-007's table.

`PortfolioHealth` is a pure function over exactly the reads D-009 already makes — no new
arithmetic, no new persistence, and it is falsifiable in the way Part 5 of the plugin design
called for: on a portfolio where every company is healthy it must produce a census with a zero
`watch` count and **name nobody**, and today it must name Summit.

### One honest limitation, stated rather than smoothed

Two of three live companies score 0 attainment because they have never written a `kpi_value` —
Trailhead has no recorded cycles at all, and its "Just getting started" summary is D-027.4's
grace period doing its job. A census that counted Trailhead as evidence about the portfolio's
goal attainment would be counting an absence as a reading, which is M7-F21's failure in
aggregate form. **The census reports never-measured companies as their own count**, not folded
into `healthy`. Coordinating the resulting wording with the M9-3 backlog item
("healthy-labelled companies whose sentences say nothing was achieved") is a rendering
question, and it belongs to the operator-surface lane, not here.

---

## Part 4 — The interaction boundary, and why it is drawn at reads

§3 says the Executive interacts with businesses only through the §5 contract. §5's own module
docstring says the same from the other side. Part 1 enumerated the surface; this part records
the two places where the boundary is easy to cross by accident, both of which the deterministic
design avoids by construction.

**Cycle-level detail is not a contract field.** `BudgetLedger.cycle_spend` is reachable and
tempting — a CFO wanting cost-per-cycle can get it — but a cycle is a Manager's internal unit
(§2.1, D-021), and reporting on it is reporting on business internals. The rollup uses cycle
cost only as the denominator of `runway_cycles`, which is a statement about *the company's
budget*, not about how it spends a cycle. The line: the Executive may divide a company's own
spend by its own recorded cycle count; it may not enumerate, inspect, or explain cycles.

**The Decision Log is read as a feed, never as a fact source.** `activity_feed` returns the
operator's narrative. The Executive reads it for the same reason an operator does, and never
parses it: D-005 makes the log the durable record of decisions and §11.5 makes it prose, and a
platform function that extracted structure from prose would be building a second, unstated
schema on top of sentences written for a person. Where the Executive needs a number it reads
the number's own store — the ledger, `kpi_values`, the contract.

---

## Part 5 — §3.1's strategic responsibilities: designed, not built

Two of §3.1's responsibilities are within reach of two live business types and are designed
here so the deterministic half is built with the right seams. Neither is implemented in M9.

### 5.1 — Capital allocation, and the collision worth naming precisely

D-007 gives the operator terms: the Executive Layer is invisible except as **"Jarvis moved
budget between companies, here's why"**, and capital reallocation surfaces as **"Budget
moved"**. So an operator-visible budget move is inside D-007's table, not beyond it.

But `budget` is **Band C** under D-029: `BusinessRegistry.refresh_contract` re-reads the stored
contract, compares every Band C field, and refuses the entire write if any moved — with the
recorded argument that a spending limit is *the operator's money* and Summit's $2.00 per-cycle
ceiling is an explicit operator choice against its template's $1.00 suggestion.

These do not conflict, and the distinction is this design's most load-bearing sentence:

> **D-029 Band C freezes budget against a *type upgrade* — a change nobody decided, arriving
> as a side effect of a developer's version bump. It says nothing about an Executive
> reallocation, which is a decision, with a rationale, and — per §8 — an approval.**

The evidence that this is the intended reading rather than a convenient one is that the spec
anticipates it from two directions at once: D-007 pre-writes the operator's sentence for budget
moving between companies, and §8's hard constraint pre-writes the rule that capital actions
never graduate. A mechanism the specification gives an operator sentence *and* a permanent
approval gate is not a mechanism it forbids.

**The design consequence: capital allocation needs its own write path, and the Band C guard
must not be widened to accommodate it.** Widening `refresh_contract` — a flag, a bypass, a
"trusted caller" argument — would open the same hole to the type-upgrade path the guard exists
to close, and the guard's value is that it holds for every future caller including ones that do
not exist yet. A second, narrower writer is strictly safer than a wider one.

The shape, specified and not built:

- `plan_allocation(...) -> AllocationProposal` — pure, no writes, over stored values: which
  company, from where, how much, and the rationale composed from the numbers themselves
  (headroom, utilisation, runway, attainment). Both sides stored, so the rendered proposal is
  D-011-shaped by construction — no model sits between the change and the human.
- `apply_allocation(...)` — refuses unless an approved §8 approval exists for it; writes both
  contracts; audits; writes the platform Decision Log entry that D-007's sentence renders from.
- Graduation is structurally impossible for it, and pleasingly so: `_advance_counter` reads
  `contract.autonomy_for(action_type)` and returns early when there is no policy, and
  independently computes `capital_action = row.amount_usd is not None`. A reallocation has an
  amount and no per-business policy, so **both** of §8's guards refuse it without anyone adding
  a third.

**And there it stops, on an escalation.** `ApprovalRequest.business_id` is required, every
`action_type` in the system is namespaced to a business *type* (A-003), and
`declared_action_types`' own docstring states the rule that makes a platform-scoped approval
impossible today: *"a string outside this set names no action … an operator approving it would
authorise nothing."* A reallocation belongs to two companies and to neither. Creating a
platform-scoped approval is a D-013 and §8 change and a security-boundary question — Part 10.2.

### 5.2 — KPI target setting, and the decision it is already bound to

`KpiTarget`'s docstring says "A KPI target set by the Executive Layer (spec §3.1)". No
Executive exists to set one. Today the type's `default_kpi_targets` are the only source
(M7-F24), and D-029 Band B refreshes them *from the type* with operator consent. The platform
therefore implements "the type sets targets", not §3.1's "the Executive sets targets".
**M9-F3.**

The design contribution here is not a mechanism but a dated consequence, and it should be
recorded before either half is built:

> **M8-F6 and Executive target-setting are the same event, arriving from opposite directions.**

M8-F6 records that Band B's `target_value` rule is "lossless by construction" *only* while the
type default is the sole source, and that the argument expires the day a per-instance target
edit surface lands. An Executive that sets targets **is** that surface. If Executive
target-setting ships before refresh gains per-field provenance, the next type upgrade will
present an operator with a consent screen that silently proposes reverting the Executive's
targets to the type's defaults — and the operator, correctly told that accepting an update is
routine, will accept it.

So: **whoever builds §3.1 target-setting inherits M8-F6 and the two land together.** That is a
sequencing constraint, not a mechanism, and recording it is cheaper than rediscovering it.

---

## Part 6 — The judgment cadences (§3's weekly/monthly table)

Designed here, deferred deliberately, and the reason for the deferral is a finding rather than
capacity.

**A cadence is a scheduled evaluation, not a standing loop.** §3 forbids standing reasoning
loops and D-012 already established the platform's answer to that shape: the Manager wakes,
reasons, ends. An Executive cadence takes the same form — a timer fires, one bounded evaluation
runs, proposals are written, nothing waits. Weekly and monthly are *timers*, not processes.

**A cadence produces proposals, never effects.** Everything in Part 5 is gated on an approval;
a cadence that could act would be §8 with the human removed.

**And here is why it cannot be built yet: the Executive has no budget scope.** D-003's hierarchy
is `invocation → wake cycle → business → platform`. An Executive reasoning call belongs to no
business, so it debits **none of the first three** and reaches the platform 24h ceiling
directly. That inverts D-003 rule 3, which puts per-business caps as the first line and the
platform breaker as the backstop precisely so that one runaway reasoner cannot halt every
healthy company. An unbounded reasoning caller sitting directly under the $500 breaker is the
one place in the platform where §9 would be the *first* line — the arrangement D-003 rule 3
exists to reject. **M9-F4**, and Part 10.3 escalates it.

That is the deferral's real justification. The judgment half is not deferred because there was
no time; it is deferred because **the first model call it makes would spend money against a
ceiling nobody chose for it.**

---

## Part 7 — Where the deterministic half runs

`jarvis/scheduler/service.py`'s own docstring supplies the argument, already made once for the
§9 timers and once for D-034.3's reservation sweep:

> deterministic bookkeeping over rows, has no reasoning in it, and running it as a workflow
> would put a scheduled loop in the workflow layer for no benefit — §2.1 and §3 reserve that
> layer for things that reason.

Every word applies. The CFO rollup and the COO census are a plain async service on a timer:
not a workflow (nothing to replay, D-004), not a Manager activity (it belongs to no business),
not a standing loop (it computes and returns).

**It runs as its own timer, not inside `Scheduler.sweep`.** Two reasons, and the second is the
better one:

1. **The invariant forbids the alternative.** `scheduler` is milestone 4 and `executive` is
   milestone 9 (Part 1); `Scheduler.sweep` calling into it is a forward import outside a
   composition root.
2. **The cadences are genuinely different.** The sweep's rhythm is tuned to §9's approval
   timers (24h re-notify, 7d expire) and D-034.3's one-hour orphan bound. Spend moves at a
   different rate and its alert thresholds are percentages of a cap, not ages. Bolting a
   financial cadence onto a timer chosen for approvals would make one number govern two
   unrelated things — and the first person who tuned either would silently retune the other.

Composed at `jarvis/runtime/worker.py`, which is already a registered composition root and
already the entrypoint that registers the scheduler beside the workflow. No new root, no new
exemption.

---

## Part 8 — The operator surface (D-007, §12.5)

**D-007's rows this touches, all of them already written:**

| Technical term | Operator-facing term |
|---|---|
| Executive Layer | invisible — "Jarvis moved budget between companies, here's why" |
| Capital reallocation | "Budget moved" |
| Business budget cap reached | "[Company] hit its spending limit" |
| Wake-cycle budget exhausted | "[Company] stopped early to stay in budget" |

**Half of that table is already implemented, at the point of refusal.** The last two sentences
exist verbatim as `operator_message` on `BudgetExceededError` in `jarvis/budget/ledger.py`. So
the operator today learns about a limit **only by hitting it**. The CFO's whole visible
contribution is that same sentence, earlier — which is why this design's operator surface stays
inside D-007's table and does not trip the packet's escalation trigger.

**Where it renders: `DecisionLog.platform_feed` gets its first reader.** It has none in
`jarvis/` today and zero rows live. Every Executive narrative — a spending halt, a future
budget move — is a platform-scoped Decision Log entry, and D-007's "here's why" is that entry's
`rationale`. Nothing new needs to be invented to carry it; something needs to read it.

**Vocabulary hazards, named because the gate is real.** `tests/surface_sources.FORBIDDEN` bans
seventeen terms, and **"business" is one of them** (D-007's own Business → Company term). So:
"company" and "companies", never "business"; never "the Executive Layer" — D-007 makes it
invisible and the actor is always **Jarvis**; never "wake cycle" or "woken", which rules out
narrating `runway_cycles` to an operator in its own units. "Budget", "spending", "limit" and
"goals" are all clear, and all already in shipped copy.

**One thing this design deliberately refuses to surface: a portfolio score.** Part 3's argument
is the reason, and it is worth restating as a surface rule — a single number covering three
companies is the one addition here that *would* go beyond D-007's table, because it would give
the operator a new thing to believe.

**Rendering is not this packet's territory.** The surface is named here and designed by
`operator-surface-engineer`, product-reviewer gated, per the M8 precedent. It coordinates with
the M9-3 backlog round, which is already touching health wording.

---

## Part 9 — What M9 implements, and what M10+ defers

| | M9 | Later |
|---|---|---|
| CFO budget rollup, windows named (2.2) | **Yes** | |
| Cap tracking + `SPENDING` alerts at 50/80/breach (2.3) | **Yes** | |
| Circuit-breaker halt narrative gets its caller (2.4, M9-F2) | **Yes** | |
| COO portfolio census (Part 3) | **Yes** | |
| `platform_feed`'s first reader (Part 8) | **Yes**, surface lane | |
| Deferred-completion ledger rows for Part 0's five (M9-F1) | **Yes**, bookkeeping | |
| Judgment cadences, weekly/monthly (Part 6) | Designed only | Gated on an Executive budget scope (M9-F4) |
| Capital allocation (5.1) | Designed only | Gated on a platform-scoped approval (Part 10.2) |
| KPI target setting (5.2) | Designed only | Lands with M8-F6, never before |
| Per-model cost tracking (10.4) | **No** | Named, with its reason |
| District Managers (§3.2) | **No** | §14 — no demonstrated need |
| Business creation / retirement decisions (§3.1) | **No** | §14 — nothing requires them yet |

---

## Part 10 — What this design does not do

Escalations and deliberate non-decisions. Each is a decision the Manager or the owner makes,
not this packet.

1. **The window semantics of `business_cap_usd` (ESCALATION).** 2.1 established from live data
   that a business cap is a lifetime budget that only depletes, while the platform ceiling is a
   daily flow; that budget headroom is therefore a monotonically falling 30% of every Health
   Score; and that Summit Trail Gear has ≈22 cycles of runway against a 48-cycle daily
   allowance. Whether that is D-003's intent, or an unstated assumption that has now been
   proven live, is a D-003 semantics decision. It changes what a ceiling *means*, so it is not
   a design packet's to make. The CFO rollup is built to report the situation honestly either
   way.
2. **A platform-scoped approval `action_type` (ESCALATION).** Capital allocation is designed
   (5.1) and cannot be built: `ApprovalRequest.business_id` is required, A-003 namespaces every
   action type to a business type, and `declared_action_types` states that a string outside a
   company's set authorises nothing. Creating an approval that belongs to the platform rather
   than to a company is a D-013 and §8 change and a security-boundary question — security-
   engineer review with an owner-visible argument, not a framework packet.
3. **An Executive budget scope for judgment calls (ESCALATION).** Part 6's M9-F4: an Executive
   reasoning call debits no scope but the platform breaker, inverting D-003 rule 3. Fixing it
   means either a fifth scope in D-003's hierarchy or an explicit decision that Executive
   reasoning is platform spend with its own sub-ceiling. Either is a D-003 amendment.
4. **Per-model cost tracking.** Three separate docstrings — `budget/ledger.py`,
   `capabilities/pool.py`, `kernel/config.py` — say per-model pricing "does not exist until the
   Executive Layer's cost tracking lands", which names this milestone. **It does not land
   here**, and the reason is that the absence is currently *safe*: D-022 derives a reservation
   from a call's token ceiling at a configured upper-bound price ($50/M today), so every
   reservation over-states cost and settles back to reported tokens. Replacing a conservative
   bound with real rates can only ever let *more* spend pass a ceiling check, so it is a change
   that needs its own evidence, not a rider on a rollup. **M9-F5**, recorded so the three
   docstrings' promise is answered rather than left dangling.
5. **Portfolio balancing and cross-business optimisation (§3.1).** Named by the M6,M7 → M9 edge
   in `docs/DEPENDENCIES.md`. Both are capital allocation with a policy on top, and both are
   downstream of 10.2. Nothing is invented for them here.
6. **District Managers (§3.2).** `ManagerState.supervisor` stays an unread string. Stated
   explicitly because the temptation runs the other way: M9 is the first milestone with an
   "executive" that could plausibly read it, and **a reader would fix the hierarchy the field
   exists to keep open.** §4.1 requires districts be insertable without a Manager redesign; the
   field earns that by being written and never read.
7. **Memory promotion across companies** (D-007's "Lesson shared with your other companies").
   §7 makes memory business-local and `CapabilityPermission` has no field to grant another
   company's memory "by construction". Cross-business memory is a §7 and §10 change with no
   finding behind it. §14.
8. **Any change to D-009's formula, banding, or weights.** The census aggregates the scores the
   platform already computes; it does not recompute them.

---

## Part 11 — Proposed decisions

Drafted for the Manager to write into `docs/DECISIONS.md` after review. **Not written here.**

- **D-038 — the Executive Layer's deterministic half computes and reports; it never writes to a
  contract.** Deterministic is defined by inputs (pure function of stored values, no model call,
  no uninjected clock) and enforced by an import rule: the executive package imports `registry`,
  `budget`, `kpi`, `observability`, `notifications` and nothing else — in particular not
  `jarvis.llm`, `jarvis.manager`, or `jarvis.capabilities` (Part 1). Reversal cost: low — it
  records the split §3 already draws, and makes it a test.
- **D-039 — a portfolio has a census, not a score.** The COO aggregate reports counts per band,
  the worst company named, and never-measured companies counted separately; it never produces a
  single portfolio number. Averaging comparable scores yields a number comparable to nothing,
  and the live portfolio is the proof: every mean reads healthy while a third of it is on watch
  (Part 3). Reversal cost: low.
- **D-040 — every Executive financial figure names its window.** A business cap is a lifetime
  budget; the platform ceiling is a rolling 24h flow; the two are incommensurable and the
  rollup states which is which per field (Part 2.1–2.2). Runway is reported in cycles and is
  absent, not zero, for a company with no recorded cycles. Reversal cost: low — it constrains
  presentation, not arithmetic.
- **D-041 — the Executive Layer's deterministic cadence is its own timer, composed at
  `runtime/worker.py`, never a workflow and never `Scheduler.sweep`.** D-012's argument, plus
  the layering invariant, plus the fact that approval timers and spend thresholds are unrelated
  rhythms (Part 7). Reversal cost: low.
- **D-042 — capital allocation gets its own contract writer; D-029's Band C guard is never
  widened.** Band C freezes budget against a type upgrade, which nobody decided; an Executive
  reallocation is a decision with a rationale and an §8 approval. A second narrow writer is
  safer than a widened guard, which would reopen the guarded hole to the type-upgrade path
  (Part 5.1). Reversal cost: medium — it fixes the shape of a write path before the write path
  exists, and it is gated on the Part 10.2 escalation regardless.

---

## Part 12 — Implementation packets this document cuts into

Proposed, in merge order. Sizing is the Manager's.

| Packet | Content | Owner |
|---|---|---|
| A | `jarvis/executive/` package + layering rows + `PortfolioRollup` and its pure computation (2.2) + the import-boundary test (Part 1) + the five deferred-completion ledger rows (M9-F1) | platform-engineer |
| B | `PortfolioHealth` census (Part 3) | platform-engineer |
| C | Cap tracking + `SPENDING` alerts with band-crossing semantics (2.3), and the circuit-breaker halt narrative's missing caller (2.4, M9-F2) | platform-engineer |
| D | The scheduled runner + composition at `runtime/worker.py` (Part 7) | platform-engineer |
| E | The operator surface: `platform_feed`'s first reader, spend-alert copy, census rendering (Part 8) | operator-surface-engineer, product-reviewer gated |

**Cross-lane dependency:** packet E's census wording overlaps the M9-3 surface backlog item on
healthy-labelled companies that have achieved nothing. If M9-3 has merged first, E extends its
wording; if not, the two must agree on how a never-measured company reads before either ships,
or the operator will meet two different sentences for one condition.

**Sequencing note:** A before C. The alert thresholds are percentages of the rollup's own
fields, and computing them twice in two places is how two numbers that must agree stop
agreeing.
