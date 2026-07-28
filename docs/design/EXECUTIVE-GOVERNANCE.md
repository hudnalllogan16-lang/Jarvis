# Executive Governance

**Status:** design, owner-commissioned. Awaiting Manager review, then owner ratification for
the Part 8 amendments. No implementation. Packet M9-5, lane `lane/m9-5`.
**Scope:** the authority model that governs everything the platform does without asking —
its levels, its boundaries, the reasons those boundaries sit where they do, and the
mechanisms that keep them from moving by accident.

This document decides nothing that D-001…D-042 already decided. Where it would change a
MUST/MUST NOT, alter a D-entry's semantics, widen a security boundary, or add an
operator-visible concept beyond D-007's table, it stops and says so (Part 11).

Every claim about live behaviour below was read out of the live database **read-only on
2026-07-28**. Nothing was written. `.env` was never printed. Spend: $0.

The optimisation target, stated once and binding on every choice below: **predictable,
explainable, auditable behaviour — never maximum autonomy.** Where a design is safe and a
design is capable, this document picks safe and says what capability it cost.

---

## Part 0 — The owner's commission

Reproduced as delivered, because a governance document that paraphrases its own mandate has
already begun drifting from it.

> A formal authority model with explicit boundaries — levels, permitted actions, prohibited
> actions, escalation, audit, approvals — and **why each boundary exists**.
>
> The policy-execution principle evaluated, with proposed wording and placement.
>
> Budget-vs-reserve as **separate architectures**, with thresholds justified and the
> state-transitions-versus-alerts question decided.
>
> Operational Confidence approved or rejected, with a non-arbitrary design.
>
> The explainability structure established as a platform standard.
>
> The M10–M15 scaling review, with bottlenecks named.
>
> The safety review, hunting operator surprise, alert noise, boundary ambiguity, silent
> policy creep, plugin bypass, and accidental autonomy ratchets — **preventative
> architecture, not reactive fixes.**
>
> Deliverables: the specification, the authority matrix, the capital model, the
> budget/reserve architecture, the confidence proposal, the explainability standard, drafted
> constitutional and architecture amendments, drafted D-entries, and the deferred-M9
> implementation strategy.

### Deliverables index

| # | Deliverable | Where |
|---|---|---|
| 1 | The governance specification | this document entire |
| 2 | Authority matrix | Part 1.3 |
| 3 | Capital model | Part 3.1, Part 3.6 |
| 4 | Budget / reserve architecture | Part 3 |
| 5 | Operational Confidence proposal | Part 4 |
| 6 | Explainability standard | Part 5 |
| 7 | Scaling review M10–M15 | Part 6 |
| 8 | Safety review + preventative ratchets | Part 7 |
| 9 | Drafted constitutional + architecture amendments | Part 8 |
| 10 | Drafted D-entries (D-043…D-050) | Part 9 |
| 11 | Deferred-M9 implementation strategy | Part 10 |

---

## Part 0.1 — The live platform, read today

Three companies, all ACTIVE. Every figure below is a read, not a projection.

| Company | Type | Cap | Cycle ceiling | Settled spend | Cap used | Cycles | Runway | Health |
|---|---|---|---|---|---|---|---|---|
| Trailhead Gear Reviews | affiliate | $25.00 | $1.00 | $1.450000 | 5.80% | 1 | ≈16.2 cycles | 73 healthy |
| Summit Trail Gear | affiliate | $25.00 | $2.00 | $5.907450 | 23.63% | 8 | ≈25.9 cycles | 67 **watch** |
| Portfolio Watch | finance_tracking | $15.00 | $2.00 | $1.819100 | 12.13% | 3 | ≈21.7 cycles | 93 healthy |

Portfolio: **$65.00 committed capital**, **$9.176550 settled lifetime spend**, **$55.823450
headroom (85.88%)**, **$0 in the rolling 24h window** against a **$500/24h** platform ceiling
(0% utilised). Zero unresolved dead letters. Zero platform-scoped Decision Log rows. Four
notifications, all `needs_approval`, all dated 2026-07-26. **Zero `SPENDING` notices have ever
been written.** One autonomy counter row (Summit / `affiliate.publish_post`: 0 consecutive,
not graduated). Three `kpi_values` rows, all Portfolio Watch's.

The census, computed through the platform's own `compute_portfolio_health`:

```
healthy 2 · watch 1 · at risk 0 · never measured 0
Summit Trail Gear needs a look — it set goals and hasn't hit any of them yet.
```

### The event this whole document is built around

At **06:14:46–06:14:53 on 2026-07-28**, all three companies woke and all three cycles failed.

The ledger records it precisely: **nine reservations, three per company, every one RELEASED
and none SETTLED.** The three reservations belonging to one company share a single cycle key
(`cyc_…_2`, `cyc_…_3`) — D-034.2's deterministic derivation holding across activity retries,
now proven live for a third time. Each company wrote one `business.wake_cycle` Decision Log
entry: *"…couldn't finish this round of work and will try again…"* — M6-F9's containment
working exactly as designed. Total spend: **$0.00**.

Then consider what the platform said about it.

- **Zero notifications.** The operator's queue still holds the same four `needs_approval` rows
  from two days earlier.
- **Zero dead letters**, so `reliability` stayed 100 for all three companies.
- **Health bands unchanged**: 73 healthy, 67 watch, 93 healthy.
- **The census unchanged**: healthy 2, watch 1.
- **The rollup unchanged in the only place it looks**: rolling 24h spend $0, because nothing
  settled.

Ten minutes later, at 06:24:33 and 06:24:35, Trailhead Gear Reviews was paused and resumed by
an operator. Somebody noticed something. Nothing the platform surfaces would have told them.

**Every company on the platform failed simultaneously and every Executive surface reported
health.** That is not a defect in any of the four modules — each is correct on its own terms.
It is the shape of the gap this document exists to close, and it is why Part 4 approves
Operational Confidence rather than treating it as a nicety. **M9-F118.**

---

## Part 1 — The authority model

### 1.1 Four levels

Authority is a property of an **action type**, not of a component. A component may hold
several; an action type holds exactly one. That inversion is deliberate: components get
refactored, split, and renamed, and an authority model keyed to components silently
re-authorises whatever moves. An action type is the platform's existing unit of
authorisation — A-003 already makes it the key for graduation counters, §8's four facts, and
D-011's rendering — so keying authority to it adds no new vocabulary and inherits every
guard already built around the string.

---

**L0 — Deterministic computation.** Compute, report, notify. Nothing else.

*Exists today.* D-038's import-rule world: `jarvis/executive/` computes `PortfolioRollup` and
`PortfolioHealth` from stored values, writes notifications and platform Decision Log entries,
and imports `registry`, `budget`, `kpi`, `observability`, `notifications` and nothing else.

*Permitted:* reads across the frozen surface (EXECUTIVE-LAYER.md Part 1); writing
notifications, platform-scoped Decision Log entries, audit records.
*Prohibited:* any contract write; any model call; any uninjected clock; any read of business
internals.

*Why the boundary is here:* because it is checkable. `tests/test_executive_import_boundary.py`
turns "this component exercises no judgment" from a docstring promise into an AST assertion
with a proven negative control. An import of `jarvis.llm` **is** the violation event. A
boundary that can be crossed only by an edit a test refuses is worth more than a boundary
defended by review.

---

**L1 — Rule execution.** Automated actions whose entire behaviour is a comparison of stored
values against owner-set parameters. The breaker's halt narrative, spend alerts, policy-
parameterised pauses.

*Permitted:* firing, refusing, pausing, and announcing — automatically, without asking.
*Prohibited:* choosing its own parameters. **Code may not change a parameter's value; only
config can.** An L1 action is fully described by (rule, parameters) and the rule is frozen.
*Audit:* always. Every L1 firing writes an audit record and, where an operator is affected, a
Decision Log entry.

*Why the boundary is here:* an L1 action is safe precisely because a human can predict it
without reading code. That property survives only while the *numbers* are somewhere a human
can read and change. The moment a threshold lives in a module constant, the rule stops being
"the owner set 80%" and becomes "a developer chose 80% and nobody remembers", which is the
first step of silent policy creep (Part 7.4). This is where Position 1's "code cannot change a
parameter's value" earns its place, and Part 2.3 turns it into a test.

---

**L2 — Judgment proposal.** The Executive may PROPOSE. It may never enact.

Reallocation between companies, KPI target changes, retirement candidates, portfolio
rebalancing — all of §3.1's strategic responsibilities.

*Permitted:* producing a proposal, and only through Part 5's eight-field structure.
*Prohibited:* every effect. An L2 proposal reaches the world exclusively through an §8
approval answered by a human.
***L2 NEVER GRADUATES.*** §8's hard v1 constraint on capital actions, generalised: no L2
action type is graduation-eligible, ever, regardless of how many consecutive approvals it
accumulates. Part 6.1 makes this structural rather than configured.
*Audit:* the proposal is audited when made; the decision is audited when answered; both are
Decision-Logged.

*Why the boundary is here — and why "never graduates" rather than "graduates slowly":*
graduation is a **friction reduction justified by demonstrated repetition**. It is safe for
`affiliate.publish_post` because the fifth post is genuinely the same kind of act as the
first, and an operator who approved four has demonstrated a stable judgment about a stable
thing. An L2 action is not that. Each reallocation is a *different* judgment about a
*different* portfolio state; the previous four approvals are evidence about four situations
that no longer exist. Counting them is a category error, and D-030 already caught the same
error one layer over: refresh consent was deliberately kept out of §8's queue *because an
`action_type` would attach a graduation counter to configuration changes*. The reasoning that
protected configuration protects capital identically.

---

**L3 — Owner only.** Not a level the platform may reach at any autonomy setting.

Policy creation. Ceilings and windows. Autonomy grants. Spec changes. New integrations.
Credentials. Any change to the Authority Registry itself.

*Permitted to the platform:* nothing. The platform may *render* an L3 change for an owner to
make, and may *refuse* to operate without one.
*Prohibited:* proposal included. An L2 proposal is a request for a decision inside an
envelope; an L3 change moves the envelope, and the platform does not get to ask for that.

*Why the boundary is here:* see 1.4. This is the single most load-bearing line in the
document.

### 1.2 The never-autonomous list

Explicit, closed, and stated as a list because a rule expressed only as a principle gets
reasoned around one plausible case at a time.

The platform MUST NOT, at any autonomy level, in any milestone, without a human decision on
that specific act:

1. Raise, lower, or retarget any spending ceiling — per-invocation, per-cycle, per-company,
   or platform.
2. Create, edit, or delete an autonomy policy, or change any `graduation_threshold`,
   `graduation_eligible`, or authority level.
3. Move capital between companies.
4. Create or retire a company.
5. Execute a trade, transfer funds, or move real capital by any path (§8, unchanged).
6. Grant, widen, or resolve a credential scope, tool scope, or memory scope.
7. Install, upgrade, enable, or disable a business type.
8. Change any compliance requirement.
9. Add, remove, or re-level an entry in the Authority Registry.
10. Change any parameter classed ENFORCING in the Parameter Register (Part 7.4).

Items 1, 2, 9 and 10 are the ones worth stating even though they sound obvious: they are the
*meta* prohibitions, and every one of the others can be reached by violating them. A platform
that may edit its own ceilings has every authority, one config write later.

### 1.3 The authority matrix

The deliverable. **L** = level; **G** = may ever graduate; **A** = audit obligation
(`aud` audit record, `dec` Decision Log entry, `ntf` operator notification when the condition
is operator-affecting).

| Action type | Where it lives today | L | G | A | Escalates to |
|---|---|---|---|---|---|
| `portfolio.compute_rollup` | `executive/rollup.py` | L0 | — | none (pure read) | — |
| `portfolio.compute_census` | `executive/health.py` | L0 | — | none (pure read) | — |
| `portfolio.compute_confidence` | *proposed, Part 4* | L0 | — | none | — |
| `platform.circuit_breaker` | `budget/breaker.py::trip` | L1 | no | aud + dec | L3 to change the ceiling |
| `spending.company_band_notice` | `executive/alerts.py` | L1 | no | aud + ntf | L3 to change the bands |
| `spending.platform_band_notice` | `executive/alerts.py` | L1 | no | aud + ntf | L3 to change the bands |
| `reserve.state_transition` | *proposed, Part 3.3* | L1 | no | aud + dec + ntf | L3 to change the reserve |
| `confidence.state_transition` | *proposed, Part 4* | L1 | no | aud + ntf | — |
| `platform.approval_expired` | `approvals/service.py` | L1 | no | aud + dec + ntf | — |
| `platform.lifecycle_transition` | `registry/registry.py` | L1 | no | aud + dec | — |
| `business.wake_cycle` | `manager/activities.py` | L1 | no | aud + dec | — |
| `affiliate.publish_post` | affiliate type | **L2-tactical** | **yes** | aud + dec + ntf | — |
| `platform.reallocate_capital` | *proposed, Part 6.1* | L2 | **never** | aud + dec + ntf | L3 to change committed capital |
| `platform.set_kpi_target` | *proposed, gated on M8-F6* | L2 | **never** | aud + dec + ntf | — |
| `platform.propose_retirement` | *proposed, deferred* | L2 | **never** | aud + dec + ntf | L3 to retire |
| ceiling / window changes | no path exists | **L3** | n/a | aud + dec | owner |
| autonomy grants and thresholds | contract, at creation | **L3** | n/a | aud + dec | owner |
| type install / upgrade / toggle | `businesses/provisioning.py` | **L3** | n/a | aud + dec | owner |
| credential and scope grants | contract, at creation | **L3** | n/a | aud | owner |

**The one row that needs its own paragraph.** `affiliate.publish_post` is marked **L2-tactical**
and it *does* graduate — which reads, at first glance, as the model contradicting itself one
row before it forbids exactly that.

It does not, and the distinction is the model's most important internal boundary. §2.1 splits
strategy from execution: a Business Manager exercises judgment *inside* a company, against a
contract the Executive and the owner set. `affiliate.publish_post` is judgment about **what to
do with the authority a company already has**. `platform.reallocate_capital` is judgment about
**how much authority a company should have**. The first is bounded by a contract; the second
edits one. Graduation is safe for the first because the bound does not move, and the operator
who graduated it can still see the bound. It is never safe for the second because graduating it
would mean the platform silently acquiring the ability to change its own bounds — the
autonomy ratchet, in its purest form.

So the matrix carries two L2 kinds and the difference is *whose envelope the judgment is
inside*:

> **L2-tactical:** judgment inside a company's own contract. Graduation-eligible, per §8's
> ladder, subject to every existing guard.
> **L2-strategic:** judgment about a company's contract, or about the portfolio. Never
> graduates. Never has a counter to graduate with (Part 6.1).

Every existing action type in the platform is L0, L1, or L2-tactical. **Every action type the
Executive Layer will ever propose is L2-strategic.** That is the sentence the Authority
Registry exists to keep true.

### 1.4 Escalation, and the envelope rule

An escalation path is what a level *does* when it meets something above it. Three rules, in
increasing order of importance:

**L0 → L1: never automatically.** A computation that discovers a threshold crossing does not
act on it; it returns the figure and an L1 rule compares it. The live code already obeys this,
and the reason is recorded in `alerts.py`: `record_platform_halt` asks
`CircuitBreaker.assert_closed` — the *enforcing* check — rather than comparing the rollup's
own arithmetic, because "an operator told that spending is paused when dispatch is in fact
still running has been told something false about the platform's safety". Keep it. Generalise
it: **the component that enforces a rule is the component that announces it.**

**L1 → L2: never.** An L1 rule that cannot fire does not escalate to judgment. It refuses, and
the refusal is the outcome. Halting is always available to L1; acting differently never is.

**L2 → L3: only as rendering, never as request.** And here is the rule the whole model turns
on:

> **The Executive may propose a move inside an owner-set envelope. It may never propose
> moving the envelope.**

An L2 proposal may reallocate $5,000 among companies whose committed capital totals $65,000.
It may not propose that committed capital become $70,000. It may propose retiring a company;
it may not propose raising the platform ceiling to make retirement unnecessary.

*Why this exists and why it is stated separately from "L3 is owner-only":* because "the owner
approves it" looks like sufficient protection and is not. A platform that may propose
envelope changes, and whose proposals are usually good, trains its owner to approve them. The
tenth approval is a reflex; the fiftieth is a rubber stamp. At that point the platform has
acquired the authority to set its own bounds, and every single step was human-approved.
**That is what silent policy creep actually looks like — not a bypass, but a well-behaved
proposal loop with a tired human at the end of it.** The only structural defence is that the
envelope-change proposal cannot be *generated*, so it never enters the queue and never
becomes routine. D-011's threat model is the same argument one layer down: it removed model
prose from between a decision and a human because the human's attention is the thing being
protected. This removes envelope proposals for the same reason.

**Consequence, accepted:** the platform can be stuck. If every company is out of reserve and
the envelope is fully allocated, the Executive can produce no useful proposal and must say so
in plain language — "every company is at its limit; only you can raise one" — and stop. That
is the correct behaviour and it is worth the cost.

### 1.5 What each level owes the audit

Not "everything is audited" — a uniform rule produces uniform noise and is why nobody reads
audit logs. Per level:

| Level | Audit record | Decision Log | Notification |
|---|---|---|---|
| L0 | no — a pure read that wrote nothing has nothing to record | no | no |
| L1 | **always**, at the firing | when an operator-visible state changed | on a state *transition* only |
| L2 | at proposal *and* at decision | both, linked by the approval id | on proposal |
| L3 | **always**, including the identity that made it | always | on change |

Two rules inside that table matter more than the table:

**L1 notifies on transitions, never on conditions.** Part 3.4 is the whole argument.

**L3 audit records the identity, and there is currently no way to.** Every L3 change today
arrives through config or a database write with no actor attached. `AuditLog.record` takes an
`actor` and the L3 paths that exist pass `"platform"` or `"operator"`. A governance model
whose highest level has the weakest attribution is inverted. Named, not solved: this needs an
operator-identity concept the platform does not have, which is beyond this packet
(Part 11.4).

### 1.6 Where today's platform lands

The honest audit, because a model that does not fit the running system is a wish.

| Mechanism | Level | Conforms? |
|---|---|---|
| `compute_portfolio_rollup` / `compute_portfolio_health` | L0 | **yes**, enforced by import test |
| `CircuitBreaker.assert_closed` (refusal) | L1 | **yes** — ceiling is config (`platform_rolling_24h_usd`) |
| `CircuitBreaker.trip` (narrative) | L1 | **yes** — once-per-halt derived from the log |
| `raise_spend_alerts` / `raise_platform_ceiling_alerts` | L1 | **partly** — bands are module constants, not config (**M9-F123**) |
| `BudgetLedger.reserve` refusal | L1 | **yes** — ceilings come from the contract |
| Approval expiry / auto-pause | L1 | **yes** — §9's timers |
| `_advance_counter` graduation | L2-tactical | **yes** on guards; **no** on provenance (**M9-F127**) |
| Executive tick interval | L1 parameter | **yes** — `ExecutiveSettings.tick_interval_seconds` |
| `max_cycles_per_day` = 48 | L1 parameter | **no** — code default (**M9-F117**) |
| `max_invocation_budget_usd` = $0.50 | L1 parameter | **no** — code default (**M9-F117**) |
| `business_cap_usd`, `wake_cycle_ceiling_usd` | L3 | **yes** — no default; must be explicit |
| `graduation_eligible` default | L3 parameter | **no** — defaults to `True` (**M9-F115**) |

Eleven of fifteen conform. The four that do not are all the same shape — **a value that
governs what the platform may do, living somewhere a human would have to read Python to
find** — which is precisely the hazard Position 1 named, present four times before anyone
built the thing it was written to guard.

---

## Part 2 — The policy-execution principle

### 2.1 The principle stands

> **The Executive may execute policy. The Executive may not create policy.**

Adopted as stated. Two refinements, argued rather than substituted.

**Refinement one — it needs a second sentence, because it names no creator.** As written the
principle is a prohibition with no corresponding grant, which leaves "who creates policy?"
to be answered by whoever needs an answer first. Proposed pairing:

> **Policy is created by the owner, recorded in configuration, and carries provenance. The
> platform executes policy and may propose changes within it; it may never change the bounds
> policy sets.**

**Refinement two — "the Executive" is too narrow.** The Business Manager is equally capable of
creating policy by accident: `KpiTarget`'s docstring already says "The Manager may not change
these — that is the strategy/execution split", which is this principle stated locally, four
milestones early, for one field. The principle should bind the platform, not one layer of it.
Proposed scope: *no automated component creates policy*, with the Executive named as the
instance that most needs saying.

*The alternative I considered and rejected:* keeping the principle Executive-scoped, on the
grounds that the Manager's constraint is already covered by §2.1's strategy/execution split.
Rejected because "already covered by an adjacent principle" is how two adjacent principles
drift apart; and because M10's Trading Analysis type will be the first Manager whose outputs
look like policy (a recommendation is a proposed target), so the wider scope earns its keep
in the very next milestone.

### 2.2 What "policy" means, precisely enough to test

> **A policy is a parameter, threshold, target, or rule whose change alters what the platform
> may do, without new code review.**

Load-bearing clauses:

- **"alters what the platform may do"** — not what it *says*, not what it *computes*. A
  threshold that changes when an operator is told something is not policy; a threshold that
  changes whether a dispatch is refused is.
- **"without new code review"** — a value in config, a contract field, or a database row.
  Something in code is not policy, it is *implementation*, and changing it is a code review.
  Which is exactly why a policy value living in code is dangerous: it is policy by effect and
  implementation by location, so it changes under review rules nobody thinks apply to policy.

The test, stated so a reader can apply it in one pass:

> **Could changing this value cause the platform to permit something it previously refused,
> or refuse something it previously permitted?** If yes, it is policy. If it only changes what
> the operator reads, it is not.

### 2.3 The consequence: two classes of parameter

Applying that test to the running platform splits L1's parameters in two, and the split is
worth naming because collapsing it is how this principle would get either ignored or absurd.

| Class | Test result | Examples | Change rule |
|---|---|---|---|
| **ENFORCING** | a refusal depends on it | `platform_rolling_24h_usd`, `business_cap_usd`, `wake_cycle_ceiling_usd`, `max_invocation_budget_usd`, `max_cycles_per_day`, `graduation_threshold`, `graduation_eligible` | **is policy.** L3. Config only, with provenance. No code default. |
| **ANNOUNCING** | only a notice depends on it | `SPEND_BANDS`, `PLATFORM_BANDS`, `STALLED_CYCLE_THRESHOLD`, `tick_interval_seconds` | **not policy.** Owner-settable, registered, provenanced — but changing one is a code review, not a spec question. |

This is a refinement of Position 1, not a departure from it: Position 1 said code cannot
change a parameter's value, only config can. That remains true for both classes. What the
split adds is *which changes are governance events and which are engineering*, so the
governance process is not spent on notification thresholds and is definitely spent on
ceilings.

**The rule that keeps the split honest, and it is mechanically checkable:**

> **No ENFORCING parameter may have a default.** A ceiling nobody chose is a ceiling nobody
> owns.

Applied to the live platform this fails twice — `max_cycles_per_day = 48` and
`max_invocation_budget_usd = $0.50` (**M9-F117**) — and passes exactly where the spec insisted
it should: `business_cap_usd` and `wake_cycle_ceiling_usd` carry no defaults, with
`wake_cycle_ceiling_usd`'s docstring saying so in words ("MUST be explicit before a business
launches — there is no platform default"). The spec got this right for the two ceilings it
thought about; the rule generalises it to the two it did not.

### 2.4 Placement: both, and they say different things

Position 2 says the principle belongs in the spec *and* the decision record. Agreed, and the
reason is that they carry different obligations: the spec's version binds the architecture and
can only be changed by the owner; the record's version binds implementation and carries the
test in 2.2 so a worker can apply it. Full wordings are drafted in Part 8.1 (spec §15.2) and
Part 9.2 (D-044).

---

## Part 3 — Budget and Reserve are different architectures

### 3.1 The capital model

The platform today has one word — "budget" — doing four jobs at four scales, and D-003's
hierarchy relates them by *containment* while saying nothing about their *kind*. That is the
root of M9-F1, of the owner's open cap-window escalation, and of M9-F81's never-settling nag.

Two kinds, and every ceiling in the platform is one or the other:

> **An Operational Budget is a flow.** It is denominated per window, it refills when the
> window rolls, and exhausting one costs *time*. Recovery is automatic and requires no human.
>
> **A Capital Reserve is a stock.** It is denominated per lifetime, it only depletes, and
> exhausting one costs *the company*. Recovery requires a human decision and nothing else can
> produce it.

Everything else follows from that one distinction, including the thresholds and including the
alerts-versus-states question.

The capital model, complete:

| Scope | Kind | Today | Recovery |
|---|---|---|---|
| Per invocation (`max_invocation_budget_usd`) | Operational Budget (window = one invocation) | exists | automatic, next invocation |
| Per wake cycle (`wake_cycle_ceiling_usd`) | Operational Budget (window = one cycle) | exists | automatic, next cycle |
| Per company per day | **Operational Budget (window = 24h)** | **does not exist** (**M9-F129**) | automatic, next day |
| Per company lifetime (`business_cap_usd`) | **Capital Reserve** | exists, mislabelled as a budget | **owner only** |
| Platform per 24h (`platform_rolling_24h_usd`) | Operational Budget (window = 24h) | exists | automatic, next window |
| Executive reasoning sub-ceiling | Operational Budget (window = per evaluation) | Manager-decided, unbuilt | automatic |

The missing row is the finding. A company has a per-invocation flow control, a per-cycle flow
control, and a lifetime stock — **and nothing in between.** Which means the only thing standing
between a company and its entire reserve is how many cycles it is allowed to run in a day.

### 3.2 What the live numbers do to that

Mean cost per recorded cycle, from today's read: Trailhead $1.4500, Summit $0.73843, Portfolio
Watch $0.60637; platform-wide $9.176550 / 12 cycles = **$0.7647**.

Against `max_cycles_per_day = 48`:

| Company | Reserve | Cycles of reserve | **Days of permitted work** |
|---|---|---|---|
| Trailhead Gear Reviews | $25.00 | 17.2 | **0.36** |
| Portfolio Watch | $15.00 | 24.7 | **0.51** |
| Summit Trail Gear | $25.00 | 33.9 | **0.71** |

**Every live company's entire lifetime reserve is less than one day of the work the platform
already permits it to do.** M9-F1 found this for Summit on 2026-07-27; on today's data all
three are under the line and Trailhead is at a third of a day. **M9-F119.**

Nothing has actually burned that way, because nothing has run at anything like 48 cycles/day.
That is the point: the platform's *permission* and the platform's *observed behaviour* differ
by two orders of magnitude, and the only reason no company has vanished is that none has been
busy. Safety by idleness is not safety.

And the platform ceiling: the busiest day ever observed is 2026-07-26 at **$9.18 settled
across three companies — 1.8% of the $500/24h ceiling.** The breaker sits at 54× the largest
day the platform has ever had. At $0.7647/cycle and 48 cycles/day, one company's maximum
permitted daily burn is $36.71, so the platform ceiling first becomes the *binding* constraint
at **≈13.6 companies**. Below that, D-003 rule 3's ordering — per-business caps first,
platform breaker as backstop — holds by dimensioning rather than by design. **M9-F120**, and
Part 6.4 carries it into the scaling review.

### 3.3 The two architectures

**Operational Budget — rolling windows, percentage bands, automatic recovery.**

- Window: **24h rolling**, default, matching the platform ceiling's existing window and
  `PLATFORM_SPEND_WINDOW` — one window constant, not two (M9-F79's discipline).
- Bands: **50% and 80%, then halt at 100%.** Kept as shipped.
- Halt: refuse new dispatch for that scope. In-flight work is never killed (D-003 rule 4).
- **Recovery: window rollover. Automatic. Stated in the notice itself.** The operator is told
  "new work starts again tomorrow" — because it does, and because a limit that heals itself is
  a fundamentally different thing to be told about than one that does not.
- Announcement: a notification per band crossing, deduplicated by band (today's mechanism,
  unchanged).

**Capital Reserve — lifetime stock, a state machine, no automatic recovery.**

```
NORMAL ──> LOW ──> EXHAUSTED
   ^                   │
   └─── RECOVERED <────┘
         (owner raises the reserve)
```

- **NORMAL:** headroom remains and runway exceeds one day of permitted work.
- **LOW:** `runway_cycles < max_cycles_per_day`. The company is, by the platform's own
  configuration, less than one day of permitted work from stopping.
- **EXHAUSTED:** headroom is zero. Dispatch is refused. Only a human restarts it.
- **RECOVERED:** an owner raised the reserve. Transitional, resolving to NORMAL or LOW on the
  next evaluation, and it exists as a distinct state solely so the operator gets one entry
  saying the thing they did worked.

### 3.4 Thresholds justified, and the states-versus-alerts decision

Position 3 asked for thresholds justified from operator reaction-time reasoning rather than
vibes. Following that instruction produces a conclusion sharper than a number, and it decides
the alerts question on the way.

**What the platform already assumes about human latency.** §9 sets 24h re-notification and
7-day auto-pause on an unanswered approval. Those are the only recorded assertions the
architecture makes about how fast a human responds, and what they assert is: *24 hours may
elapse before an operator has acted, and that is normal, not an incident.*

**Apply that to a 24h Operational Budget.** For a percentage band to give an operator time to
act, it must leave at least one reaction interval of headroom. On a 24h window, no percentage
can: 50% of a 24h window is at most 12 hours, and the window itself is 24. **No band on a
daily budget is a reaction-time mechanism.** It cannot be, arithmetically.

That is not a reason to remove the bands. It is a reason to be honest about what they are for:

> **Operational Budget bands exist to explain, not to protect.** Protection comes from the
> window rolling over. The worst case is losing part of a day, automatically recovered, and
> the bands are how an operator learns *why* today was quiet.

**Now apply the same test to the Capital Reserve.** There is no rollover. The worst case is a
company that never runs again until a human intervenes — and the human may be asleep, or on
holiday, or reading a notification queue that has said the same thing eleven times. Here
reaction time is the *entire* problem, and a percentage is the wrong unit for it: 80% of a cap
means nothing about how long you have. **Cycles are the unit in which time-to-stop is actually
denominated**, `runway_cycles` is already a `PortfolioRollup` field, and `max_cycles_per_day`
is already the contract's own statement of how fast a company may consume them.

So: **LOW fires when remaining runway is less than one day of permitted work.** Not a chosen
percentage — a comparison of two numbers the contract already contains. On the live portfolio
that threshold is 48 cycles and all three companies' *entire reserves* are below it, which is
the alarm firing correctly on its first evaluation rather than a threshold tuned until it
stayed quiet.

**And therefore, the decision: STATES, not repeated alerts.**

> **Operational Budget → alerts.** Repetition is acceptable because the condition genuinely
> recurs and genuinely resolves. Yesterday's 80% notice and today's 80% notice describe two
> different days.
>
> **Capital Reserve → states.** A reserve condition does not recur; it *persists*. Announcing
> a persisting condition repeatedly is not information, it is nagging, and the operator learns
> to dismiss the category.

M9-F81 is the live proof and it is exactly this failure: a lifetime breach never settles, so
the deduplication that works correctly for a windowed condition produces a notice that can
never stop being true. The current implementation is not wrong — `has_unread` is doing what
its docstring says, and `alerts.py` says in its own module comment that the copy will be wrong
if the escalation rules the cap is windowed. It is the *concept* that is wrong: a stock was
given a flow's announcement mechanism.

Under the state machine, M9-F81 dissolves. **Each transition announces exactly once**, into
the audit log and the Decision Log, and the *state* is what the operator's surface renders —
so a company sitting in EXHAUSTED for three weeks shows EXHAUSTED for three weeks and
generates one entry, not twenty-one.

**Alert noise, quantified as a design rule:** the number of notifications a persisting
condition may generate is **one**. Not one per sweep, not one per day — one per transition
into the state. If the condition changes, that is a new transition and a new notice. This is
the noise defence Position 7 asks for and it is a consequence of the state machine rather
than a rule bolted beside it.

### 3.5 Mapping the existing mechanisms

| Today | Becomes | What changes |
|---|---|---|
| `business_cap_usd` | **Capital Reserve** | the field is renamed in concept, not in schema; alerts become states |
| 50/80/100 bands on `business_cap_usd` | **Reserve states** NORMAL / LOW / EXHAUSTED | percentage bands → runway-in-cycles; announce once per transition |
| `platform_rolling_24h_usd` + breaker | **platform Operational Budget** | unchanged; already a flow with automatic recovery |
| 50/80 bands on the platform ceiling | **stay as alerts** | unchanged — correct as built, for the reasons in 3.4 |
| `wake_cycle_ceiling_usd` | per-cycle Operational Budget | unchanged |
| `max_invocation_budget_usd` | per-invocation Operational Budget | unchanged, except it acquires a Parameter Register row and loses its default |
| *nothing* | **per-company daily Operational Budget** | new, and the one genuinely new mechanism here |

The new row is the only addition, and §14 requires a demonstrated need rather than a plausible
one. The demonstration is 3.2: every live company's entire reserve is under one day of
permitted work, so the *only* control preventing a company from consuming its whole reserve in
an afternoon is a cycle count, and a cycle count is not a spending control — it bounds
frequency, not cost. A company whose cycles got 3× more expensive would burn 3× faster with
every ceiling still nominally satisfied. That is the need, it is measured rather than
imagined, and Part 10 schedules it.

### 3.6 Migration for the three live contracts

Non-negotiable constraint: **Band C is never widened** (D-042, D-029). `business_cap_usd` is a
Band C field, frozen against type upgrades because it is the operator's money, and Summit's
$2.00 per-cycle ceiling is a live example of an explicit operator choice a refresh must never
touch. Nothing here changes that; the migration is additive and every existing byte stays put.

1. **`business_cap_usd` is not renamed and not migrated.** It *is* the Capital Reserve. The
   concept changes; the column, the value, and the Band C freeze do not. Three live contracts
   stay byte-identical, which is the same property M8-6 proved for the refresh migration.
2. **The Reserve state is computed, never stored.** Derived per evaluation from
   `lifetime_headroom_usd`, `runway_cycles`, and `max_cycles_per_day` — all existing fields.
   No migration, and it inherits M8-F109's already-ratified posture that pending state is
   computed rather than stored.
3. **The transition is what persists**, as a Decision Log entry with a structured
   `action_type` (`reserve.state_transition`). The current state is re-derived on read; the
   *history* comes from the log, which is what D-005 makes the log for. `_halt_already_
   explained` already demonstrates the pattern — read the log for a structured action_type,
   never parse its prose.
4. **The per-company daily Operational Budget is additive with an explicit default of
   "unset".** Unset means "bounded only by the reserve and the cycle count", i.e. exactly
   today's behaviour, so no live contract changes meaning on the day the field lands. It is
   set per company at creation, by the owner, deliberately with **no platform default** (2.3's
   rule: it is ENFORCING).
5. **Ordering, from M8-6's proven sequence:** Summit → Portfolio Watch → Trailhead, one at a
   time, with a negative control first. Summit is the right first subject for the same reason
   it was in M8-6: it has the most history and the operator-chosen ceiling that must not move.

**What migration does *not* do:** it does not answer whether `business_cap_usd` *should* be a
lifetime stock. That is the owner's open escalation and it stays open (Part 11.1). What this
design does is make the two possible answers cost differently: if the cap stays a lifetime
stock, the Reserve state machine is its correct mechanism and this design is complete. If the
owner rules it should be windowed, then `business_cap_usd` becomes a per-company Operational
Budget, the new daily-budget row in 3.5 collapses into it, and the Reserve concept survives
with no field behind it until capital allocation lands. **Either ruling leaves this
architecture standing**, which is the property a design blocked on an open escalation has to
have.

---

## Part 4 — Operational Confidence

### 4.1 Approved, as a state

Position 4 proposes Operational Confidence as a discrete state — Current / Degraded / Blind —
derived from enumerable boolean contributors, listed to the operator, never weighted into a
number. **Approved**, and the live record makes the case better than the argument does.

At 06:14 today the platform failed every company simultaneously and every surface it has
reported health (Part 0.1). Trace *why*, mechanism by mechanism, because the answer is that
nothing was broken:

- `reliability` counts unresolved dead letters. There were none — the cycles failed at
  planning, before dispatch. Reliability 100 is **correct**.
- `budget_headroom` reads settled spend. Nothing settled; all nine reservations released.
  Headroom unchanged is **correct**.
- `attainment` reads `kpi_values`. A failed cycle records none, so attainment is unchanged.
  **Correct.**
- The census aggregates those bands. healthy 2 / watch 1 is **correct**.
- The rollup reports $0 rolling 24h spend. **Correct** — $0 was spent.

Five components, five correct answers, and an operator who would have been told nothing. The
gap is not in any component's arithmetic. It is that **the platform has no representation of
its own operational state at all** — only of its companies' business state. Health answers
"is this company doing well?". Nothing answers "is Jarvis working right now?".

Rejecting Confidence would leave that question unanswerable, and the failure mode is the worst
kind: the platform is confidently wrong, in the operator's favour, in exactly the moment they
need to intervene.

### 4.2 The non-arbitrary design

The design constraint that makes this safe rather than another number to distrust:
**contributors are booleans, enumerated in code, listed to the operator, and never weighted.**
This is D-039's census philosophy turned on the platform itself — the same argument that
refused a portfolio score refuses a confidence score, for the same reason: a weighted number
over incommensurable facts is comparable to nothing, and its only reliable effect is to make a
bad situation average out.

**The contributors.** Closed set, each a boolean over stored values, each independently
falsifiable, each naming the finding or spec clause it exists for:

| # | Contributor | True when | Reads | Live now |
|---|---|---|---|---|
| C1 | `recent_cycle_failed` | any ACTIVE company's most recent recorded cycle did not complete successfully | Decision Log | **true** (all three) |
| C2 | `inputs_stale` | an ACTIVE company's last recorded cycle is older than twice its wake period | Decision Log + contract | false |
| C3 | `rollup_unreadable` | the last tick could not compute the rollup or census | tick outcome | false |
| C4 | `stuck_work_present` | unresolved dead letters > 0 (§9) | dead letters | false |
| C5 | `approvals_aging` | a pending approval is older than §9's 24h re-notification | approvals | **true** (4 rows, 2 days old) |
| C6 | `runway_unknown` | a company has a reserve and no recorded cycles | rollup (`runway_cycles is None`) | false |
| C7 | `executive_tick_stale` | no successful tick within N tick intervals | tick outcome | **true** (never ticked live) |

**The states.**

- **CURRENT** — every contributor false. The platform is reading everything it needs and
  everything it read looks normal.
- **DEGRADED** — one or more contributors true, and the Executive can still read what it
  needs. *"I can see the platform and something is wrong."*
- **BLIND** — C3 or C7 true. *"I cannot see the platform."*

BLIND is not "worse DEGRADED"; it is a different claim, and collapsing them is the mistake
this design most needs to avoid. DEGRADED is a statement about the platform. BLIND is a
statement about the statement — and an operator who is told "degraded" when the truth is
"unknown" has been given a fact where they should have been given a gap.

**Three rules that make it non-arbitrary, in order of importance:**

1. **BLIND is the startup state.** Not CURRENT. A confidence state that begins at CURRENT
   before its first successful tick is asserting knowledge it does not have — the M7-F21
   failure applied to self-knowledge, where an absence of readings became a reading. C7 makes
   this fall out for free: at startup no tick has succeeded, so C7 is true, so the state is
   BLIND until the first tick proves otherwise.
2. **Contributors are listed, never counted.** The operator reads which contributors are true,
   in D-007 language. "Three contributors" is a score with extra steps.
3. **Confidence is reported beside the census, never folded into it.** Folding a confidence
   signal into a health band would make the band mean two things — and D-039's whole argument
   is that a band means one comparable thing.

**Presentation, drafted in D-007's language** (rendering is the operator-surface lane's, per
the M8 precedent; this is the vocabulary constraint, not the design):

| State | Operator sentence |
|---|---|
| CURRENT | "Everything's running." |
| DEGRADED | "Something needs a look." + the true contributors, one line each |
| BLIND | "Jarvis can't check on your companies right now." |

Contributor lines, same register — "Every company's last round of work didn't finish";
"Nothing has been checked for a while"; "Something is waiting for your OK"; "One company got
stuck". Never "wake cycle", never "business", never "the Executive Layer" — D-007 makes the
actor Jarvis, and `tests/surface_sources.FORBIDDEN` will enforce it.

**Note the interlock with §12.5's completeness gate.** Confidence introduces an operator-
visible concept that is **not** in D-007's table, which by this packet's own rule is an
escalation trigger. It is raised as one (Part 11.2), with the argument that the concept is not
new *behaviour* — the platform already degrades and already goes blind, and does it silently.

### 4.3 What Confidence must never become

Stated because the drift is predictable:

- **Never a number.** The moment it is 0–100 it is a health score for the platform, and D-039's
  argument applies unchanged.
- **Never a gate.** Confidence describes; it does not refuse. A DEGRADED platform still runs.
  Making it a gate would create an automated pause with no owner-set parameter behind it —
  an L1 action failing L1's own rule.
- **Never inferred from model output.** Every contributor is a query over stored values. There
  is no path by which one could be otherwise: D-038's import rule keeps `jarvis.llm` out of the
  package that computes it.
- **Never silently extended.** The contributor set is closed, like D-032's type-parameter
  surface. Adding one changes what "CURRENT" means, so it is a decision, not a patch.

---

## Part 5 — The explainability standard

### 5.1 The eight fields, adopted platform-wide

Every judgment output the platform produces — an Executive proposal, a Manager recommendation,
any future advisory from Trading Analysis — renders through one structure:

| # | Field | Answers | Source |
|---|---|---|---|
| 1 | **Observation** | what was seen | stored values, named with their windows (D-040) |
| 2 | **Reasoning** | which rule connected observation to action | a **rule identifier**, not prose — see 5.2 |
| 3 | **Evidence** | on what basis | `(source, value, window)` triples, each traceable to a store |
| 4 | **Confidence** | how sure, and about what | Part 4's state + the true contributors |
| 5 | **Action** | what is proposed | a declared `action_type` + stored parameters |
| 6 | **Expected outcome** | what should change if it works | a named stored metric and its projected value |
| 7 | **Risk** | what could go wrong | the stored downside (§8's fourth fact) |
| 8 | **Required approval** | who must say yes | authority level → approval path |

Fields 5, 7 and 8 already exist in the approvals schema (`action_type`, `downside`,
`parameters`, plus the approval row itself); field 1 is most of `triggering_condition`. So the
eight-field structure is **§8's four required facts plus four**, not a parallel scheme — which
is why unification is coherent and why Position 5's deferral of it to M10 is right rather than
merely convenient.

### 5.2 The field that would have broken it, and the fix

**Reasoning cannot be prose.** If a model authors field 2, D-011's threat model is reopened at
full strength: capabilities read untrusted external content, and attacker-influenced text
would sit between a portfolio state and a human authorising money. An eight-field structure
whose second field is free text is a beautifully organised D-011 violation.

The resolution, and it is what makes this a standard rather than a template:

> **Reasoning renders from a stored rule identifier plus the stored values that rule
> consumed.** The platform holds a closed set of rule identifiers, each with a fixed sentence
> template. The rule that fired is stored; the sentence is assembled deterministically.

The platform already does exactly this and has live proof it works: `BAND_COPY` in
`alerts.py` is a `dict[int, _BandCopy]` of fixed sentences selected by which band was crossed,
with a docstring recording *why* it is data beside the band — so a test can walk every sentence
the module can ever emit, including bands nothing has crossed. `DROPPED_WAKE_COPY` established
the same discipline for D-035. Field 2 is that pattern applied to judgment instead of to
thresholds.

**Evidence has the same hazard and the same fix.** Field 3 is a list of triples, never a
paragraph. Each triple names a store the Executive is permitted to read (Part 1's frozen
surface), the value read, and its window. This makes evidence *checkable*: a reviewer can
re-run the read. Prose evidence cannot be re-run, which is what makes it not evidence.

### 5.3 What the standard makes testable

Three assertions, in the shape the suite already uses:

1. **Every rendered field is reachable from stored columns.** An AST/structural check that the
   renderer's inputs are all stored values — extending `test_operator_render.py`'s existing
   render-boundary discipline.
2. **The rule-identifier set is closed and its sentences are enumerable.** Walk every template,
   assert each is reachable from a rule id and each rule id has a template — the bidirectional
   form `test_design_system.py` uses for rail↔pane and `test_workflow_versioning.py` uses for
   the activity inventory.
3. **Every sentence passes §12.5.** `tests/surface_sources.py` is already the single source for
   the forbidden term list (M8-F115's consolidation); the templates join its inputs.

### 5.4 Scope, and the deliberate non-retrofit

**In scope now:** every judgment output the Executive Layer will ever produce. The structure is
specified before the first proposal exists, which is the only moment it can be free.

**Not retrofitted:** the Manager's existing proposal path. Position 5 schedules unification for
M10 and that is right — M10's Trading Analysis is the first type whose output is *inherently* a
recommendation, so the unification will have a real second instance to generalise from rather
than one instance and an assumption. M8-1's Part 0 recorded what happens when you generalise
from one instance: you get a framework shaped like that instance.

**One thing the standard must not become:** a required shape for *operator notifications*. A
notification is one sentence with a consequence. Eight fields in a notification is the thing
§12.5 exists to prevent. The standard governs judgment outputs the operator *decides on*, not
things they are *told*.

---

## Part 6 — Scaling review: M10 → M15

Four bottlenecks, each named with the milestone that hits it and the mechanism that gives way.

### 6.1 Platform-scoped approvals — the mechanism to draft (blocks M9's capital allocation, and M10)

This is the second open owner escalation. EXECUTIVE-LAYER.md 5.1 established that capital
allocation is designed and cannot be built: `ApprovalRequest.business_id` is required, A-003
namespaces every action type to a business *type*, and `declared_action_types`' docstring
states that a string outside a company's set authorises nothing. A reallocation belongs to two
companies and to neither.

**The mechanism the owner would approve, drafted:**

1. **A closed platform action-type registry**, in platform code, not in any type definition:
   `platform.reallocate_capital`, `platform.set_kpi_target`, `platform.propose_retirement`.
   Frozen and enumerated, the way `PLATFORM_HALT_ACTION_TYPE` already is.
2. **A platform approval is a distinct row shape with `business_id` NULL** — the same NULL the
   Decision Log already uses to mean platform-scoped, and the same NULL
   `raise_platform_ceiling_alerts` already passes to `notify` for a platform-wide notice. No new
   concept of scope is invented; the existing one is reused.
3. **It shares the rendering path and the operator queue.** D-011 unchanged: text renders from
   stored values. §8's four facts unchanged. The operator's experience of approving a
   reallocation is the experience of approving anything.
4. **Graduation is impossible because there is nowhere to count.** This is the design's key
   move, and it is stronger than the three guards that would otherwise apply:

   > **Platform approvals have no counter table.** `AutonomyCounterRow` is keyed
   > `(business_instance_id, action_type)`. A platform approval has no business instance, so
   > there is no row to advance, no row to set `graduated = True` on, and no schema in which
   > one could exist.

   The three incidental guards still hold and are worth recording as defence in depth:
   `_advance_counter` returns early when `contract.autonomy_for(action_type)` is None (there is
   no contract at all); `capital_action = row.amount_usd is not None` refuses a reallocation,
   which always carries an amount; and the platform registry declares
   `graduation_eligible = False` with no field by which a type could set it True. **Four
   independent reasons, one of which is the absence of the mechanism itself.** "Structurally
   impossible" means the code that would have to exist does not, and that is the standard
   Position 6 set.

5. **The security boundary that must be reviewed, and is not this packet's to widen:** a
   platform approval is an authorisation with no derived identity behind it. D-002 makes
   identity derive from the Temporal workflow id, and a platform action has no workflow.
   Escalated (Part 11.3) rather than resolved.

**Bottleneck named:** without this, §3.1's capital allocation, portfolio balancing, and
cross-business optimisation are all unbuildable — three of the Executive Layer's five stated
responsibilities. It is the single largest blocker in the roadmap after M9.

### 6.2 The Executive budget sub-ceiling scales with N, and its current form does not (M10)

Manager-decided in the M9-1 round: an explicit sub-ceiling within D-003's platform scope, set
at Executive-enablement time, not a fifth scope. Correct, and it has a scaling problem that
should be fixed before it ships rather than after.

An Executive judgment cadence reads every company. Its cost is **O(N)**. A sub-ceiling
expressed as dollars-per-day is therefore an N-dependent constant, and the failure mode is the
worst kind: at N=3 it is generous, at N=30 the weekly cadence silently stops finishing, and
nothing says so.

**The fix, and it costs nothing to adopt now:** express the sub-ceiling **per evaluation**, and
make the number of evaluations per period its own ENFORCING parameter. Two numbers a human can
reason about independently — "each strategic review may cost this much" and "there may be this
many" — where one number conflates them and hides N inside itself.

### 6.3 Plugin governance: a declared authority level, or no install (M10, and it is due before M10)

Position 6: every action type a plugin declares carries a declared authority level, validated
at install; an undeclared level refuses install. **Adopted**, with the implementation shape and
two additions the live code makes necessary.

**Shape.** `AutonomyPolicy` gains `authority_level: AuthorityLevel` with **no default.** The
absence of a default is the entire mechanism — a default is precisely how "undeclared" becomes
"L2-tactical by accident", and the platform already has a live instance of that failure mode:
`graduation_eligible: bool = True` (**M9-F115**, Part 7.5).

**Validation at install**, joining the five checks `ProvisioningService.install` already
performs — a list that has grown by demonstrated need each time (M6-F10's wake loop, M7-F35's
self-measurement, M8-F111's unrefreshable upgrade), which is exactly the precedent for adding
a sixth:

1. Every declared `action_type` carries an `authority_level`. Undeclared → `ConfigurationError`,
   refuse the install.
2. `authority_level` is L2-tactical or lower. **A type may not declare an L2-strategic or L3
   action type at all** — those are platform-owned, and a type declaring one is asking to
   create policy (Part 2).
3. `authority_level == L2-tactical` requires `graduation_eligible` to be explicitly set. Not
   defaulted, not inferred.
4. **Namespace enforcement — new, and the bypass it closes is live.** A-003 says an action type
   is namespaced to the business *type*. **Nothing enforces it.** `AutonomyPolicy.action_type`'s
   pattern is `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`, so a business type today may legally
   declare `platform.reallocate_capital` or `platform.circuit_breaker`, and both would validate,
   install, and enter `declared_action_types`. **M9-F116.** The fix is one comparison at install:
   the prefix must equal the type's own name, and `platform.` is reserved.

   Contained today — `platform_feed()` filters on `business_id IS NULL` so a company's rows
   cannot masquerade as platform ones, and no platform approval path exists to confuse. But
   6.1 builds exactly that path, and building it against an unreserved namespace is how a
   plugin acquires a platform authority. **Reserve the namespace before the path exists**,
   which is this document's whole posture in one item.

**Bottleneck named:** M10's Trading Analysis is the first type whose action types are genuinely
judgment-shaped. If levels are not declared before it lands, M10 ships a type whose actions
have no recorded authority and the registry backfills them by inference — which is the
autonomy ratchet arriving through the front door.

### 6.4 The census, the tick, and the queue at N companies (M11, M13–M15)

**The tick is O(N) round trips at a fixed interval.** `compute_portfolio_rollup` performs three
reads per company (contract, spend, cycle count) plus one platform read;
`compute_portfolio_health` performs three more (contract, spend, health) plus a cycle count.
At N=3 that is roughly 21 round trips per 60-second tick — invisible. At N=100 it is ~700, and
`ExecutiveSettings.tick_interval_seconds` is still 60.

The failure mode is what makes this worth naming: the runner has no-overlap protection
(M9-1c), so a tick that outruns its interval does not pile up — **it is skipped, silently.**
The Executive would simply run less often, with no signal.

Except that Part 4 supplies the signal for free: **C7 `executive_tick_stale`** is true exactly
when ticks stop landing, so the platform goes DEGRADED and says so. That interlock is worth
stating explicitly because it is the reason to build Confidence *before* N grows, not after.

**The census names one company.** `worst_company` is a single display name. At N=3 that is the
census's best feature. At N=100, "Summit Trail Gear needs a look" out of a hundred is a score
in disguise — one number's worth of information wearing a name. **M9-F122.** Past roughly N=10
the census needs a severity distribution (counts per band, already present, plus the worst *k*
by band) rather than a single name. D-039 is not threatened by this: the rule is "no single
portfolio number", and a distribution is the opposite of one.

**The notification queue is O(N) for platform-wide conditions.** `has_unread` deduplicates per
`(business_id, kind, link_ref)`, so a condition true of every company produces N notices. At
N=100 a single platform event fills the operator's queue. The rule, and the live code already
follows it: **a platform-wide condition produces one platform-scoped notice**
(`business_id=None`), never N company-scoped ones. `raise_platform_ceiling_alerts` is the
worked example. Make it the rule before a second platform-wide condition is written.

**Milestone map:**

| Milestone | What it adds | What gives way first |
|---|---|---|
| M10 Trading Analysis | judgment-shaped action types | authority-level declaration (6.3); the sub-ceiling's N-dependence (6.2) |
| M11 Additional types | N grows past ~10 | the census's single name (6.4); notification fan-out |
| M12 Live Trading | §8's hardest constraint becomes load-bearing | the Authority Registry must already be enforcing, not documenting (Part 7.2) |
| M13–M15 | N grows past ~14 | the platform ceiling becomes the *first* binding constraint (**M9-F120**), inverting D-003 rule 3's intent |

That last row is the one nobody would predict from reading the code. D-003 rule 3 puts
per-business caps first and the platform breaker as a backstop, deliberately, so one runaway
company cannot halt healthy ones. Today that ordering is guaranteed by the ceiling being 20×
any single company's entire reserve. At ~14 companies operating at their permitted rate the
guarantee evaporates and the backstop becomes the front line — the precise arrangement D-003
rule 3 exists to reject. **It is a dimensioning property masquerading as a design property**,
and it will fail quietly, as one company's refusal spreading to all of them.

---

## Part 7 — Safety review: preventative architecture

Six hazards, each with the mechanism that prevents it rather than the fix that would follow it.

### 7.1 Operator surprise

**The hazard.** The operator's model of what the platform is doing diverges from what it is
doing, and they discover the divergence from the consequence.

**Live instance.** 06:14 today (Part 0.1). Every company failed; every surface said healthy;
the operator paused and resumed a company ten minutes later with nothing to go on.

**Preventative mechanisms:**
- **Operational Confidence** (Part 4) — the platform reports its own state, and BLIND is the
  startup default so it never claims knowledge it lacks.
- **Reserve states** (Part 3.3) — a company one day from stopping says so, in the unit that
  makes "one day" meaningful, before it stops.
- **The envelope rule** (Part 1.4) — the platform can never surprise an operator by having
  acquired authority, because acquiring authority is not something it can propose.
- **Confidence beside the census, never inside it** — one signal, one meaning.

### 7.2 Boundary ambiguity — the Authority Registry

**The hazard.** An action type's authority is decided implicitly, by which code path happens to
reach it, and two readers disagree about what the platform may do.

**Preventative mechanism.** A single frozen registry, closed-surface like D-032's
type-parameter list:

```
AUTHORITY_REGISTRY: Mapping[str, AuthorityEntry]
    action_type -> (level, graduation_eligible, audit_obligations, escalates_to)
```

Its guards, all in the shape the suite already proves:

1. **Bidirectional completeness.** Every action type the platform can emit appears in the
   registry, and every registry entry names an action type that exists. The exact pattern
   `test_workflow_versioning.py` uses for its frozen inventory of the nine schedulable
   activities, and `test_design_system.py` uses for rail↔pane.
2. **No entry above L2-tactical is graduation-eligible.** A structural assertion, not a
   convention.
3. **The registry is pinned by digest**, and the pin is what makes "any level change requires
   owner sign-off" mechanical. Changing a level fails the test; the failure message names the
   sign-off requirement and the D-entry; updating the pin is a visible, reviewable, single-line
   diff that cannot be mistaken for anything else.
4. **A negative control**, per M8-F120's discipline: a gate that has never failed is
   indistinguishable from a gate that cannot fail. The suite asserts a synthetic level
   downgrade is caught — `test_executive_import_boundary.py` already demonstrates the pattern
   in both directions, including proof the detector is not trigger-happy.

**Why a registry rather than a field on each policy.** A field is per-instance, so N contracts
carry N answers and drift is invisible until two disagree. A registry is one answer, in one
place, that a human can read end to end in a minute — and reading it end to end is the actual
governance act.

### 7.3 Alert noise

**The hazard.** The operator learns to dismiss a category of notice, and the one that mattered
is dismissed with the rest.

**Live instance.** M9-F81: a lifetime breach never settles, so its notice can never stop being
true, and `has_unread`'s correct posture re-raises it after every dismissal — indefinitely.

**Preventative mechanism.** Part 3.4's decision, expressed as an invariant:

> **A persisting condition produces exactly one notification: the one announcing the
> transition into it. A recurring condition may notify per occurrence.**

Testable directly: given a condition held true across K evaluations, assert exactly one
notification for a state and at most one per window for a band. The scripted multi-tick proof
`test_executive_runner.py` already performs for band dedup and once-per-halt is the same shape,
extended to states.

### 7.4 Silent policy creep — the Parameter Register

**The hazard.** A number that governs what the platform may do drifts from owner-set to
developer-chosen, one reasonable edit at a time, and nobody can say who chose it or why.

**Live instances, four of them, before the Executive's judgment half exists at all:**
`max_cycles_per_day = 48`, `max_invocation_budget_usd = $0.50` (**M9-F117**),
`graduation_eligible = True` (**M9-F115**), and the alert bands as module constants
(**M9-F123**).

**Preventative mechanism.** A Parameter Register — one table, maintained beside the Authority
Registry, one row per parameter:

| Column | Why it is there |
|---|---|
| name | identity |
| class | ENFORCING or ANNOUNCING (Part 2.3) — decides whether changing it is governance or engineering |
| location | the config path or contract field it is read from |
| default | must be **empty** for ENFORCING |
| authority to change | L3 for ENFORCING; owner-settable for ANNOUNCING |
| provenance | the D-entry, finding, or spec clause that set it — this is the column that stops "nobody remembers why 48" |

**The guard test, and it is the one that would have caught all four:**

> **No ENFORCING parameter is a literal in `jarvis/`.** Every ENFORCING parameter is reachable
> from `Settings` or from a contract field with no default.

An AST sweep over the register's ENFORCING rows, asserting each resolves to a settings path or
a defaultless contract field. It fails today, twice, which is the right way for a new guard to
arrive: with a list of the debt it found.

### 7.5 Accidental autonomy ratchets

**The hazard.** Autonomy increases without anyone deciding it should. The subtle version is not
a bypass — it is a default, an inference, or a refactor.

**Live instance, and it is a default.** `AutonomyPolicy.graduation_eligible: bool = True`. A
type author who omits the field gets a graduation-eligible action. §8 says approval by default
with no exception at launch; this field defaults the other way. Two of the three live contracts
carry `graduation_eligible: true` with `graduation_threshold: 5`, and Summit's counter row is
live at 0 consecutive approvals — the ratchet is armed, correctly at zero, and enabled by a
default nobody chose. **M9-F115.** The fix is one character of intent: no default, so a type
must say.

**The invariant, made mechanically checkable — the deliverable Position 7 asks for:**

> **Autonomy cannot increase accidentally: every increase is a diff a human approved.**

Four assertions, and the fourth is the ratchet proper:

1. **One writer.** An AST sweep asserts `AutonomyCounterRow.graduated = True` is assigned in
   exactly one place, and that place is `ApprovalService._advance_counter`. The pattern is
   M1-R2's — the structural test forbidding a bare `raise ScopeViolationError` outside
   `_deny` — applied to a privilege grant instead of a refusal. (**M9-F127**: the two guards
   in `_advance_counter` are correct and nothing asserts they are the only path.)
2. **Both guards present.** In that one function, the assignment is dominated by both
   `policy.graduation_eligible` and `row.amount_usd is None`. AST-level, in the shape
   `test_manager_determinism.py` already asserts every `execute_activity` carries a timeout.
3. **No L2-strategic or L3 entry is graduation-eligible**, from the Authority Registry (7.2).
4. **The pinned autonomy inventory.** A frozen snapshot of every
   `(action_type → level, graduation_eligible, graduation_threshold)` across the built-in
   catalog and the platform registry. The test compares live definitions to the pin and fails
   on **any** difference — including a safe one.

   Failing in both directions is deliberate and is the design decision inside this test. A
   ratchet guard that only fires on dangerous changes lets the pin rot on safe ones, and a
   rotted pin catches nothing. **The asymmetry belongs in the message, not the trigger:** a
   change that lowers required authority, enables graduation, or lowers a threshold reports
   *"this increases autonomy — owner sign-off required (§15, D-043)"*; a change in the safe
   direction reports *"update the pin"*. Every change is deliberate; only one kind is
   escalated.

### 7.6 Plugin bypass

**The hazard.** A business type acquires an authority the platform never granted it, by
declaring data the platform trusts.

**Live instance.** A-003's namespace rule is unenforced: a type may declare `platform.*` action
types today and they validate and install (**M9-F116**, Part 6.3).

**Preventative mechanisms**, in order of strength:
- **Namespace enforcement at install** — the prefix must equal the type's own name;
  `platform.` is reserved. One comparison, refuses at install rather than at first approval.
- **Declared authority level with no default** — an undeclared level refuses install (6.3).
- **A type may not declare an L2-strategic or L3 action type at all** — a type declaring one is
  asking to create policy, which Part 2 forbids categorically.
- **The Authority Registry is platform-owned** — a type declares *what it wants*; the registry
  says *what that means*. D-014's rule, applied to authority: this is the same mechanism that
  has now survived three business types, and PLUGIN-FRAMEWORK Part 1 already states the
  general form.
- **The existing four-layer Band C guard is untouched.** `autonomy_policies` and `graduation`
  are Band C, so a type upgrade cannot alter an existing company's autonomy at all. That guard
  is real (M8-4's audit verdict: "four-layered and real") and nothing here widens it — Part 3.6
  keeps additivity precisely so it need not be.

---

## Part 8 — Drafted amendments

**Drafted, never written.** The spec is owner-held and this document does not edit it. Each
draft below is proposed wording with its classification, so the owner can ratify, revise, or
refuse a specific sentence rather than a concept.

### 8.1 New §15 — The Authority Model *(constitutional; owner ratification required)*

> **§15.1 Authority levels.** Every automated action the platform can take belongs to exactly
> one authority level, determined by its action type.
>
> **L0 — Deterministic computation.** Computes and reports over stored values. MUST NOT write
> to a Standard Business Contract, call a model, or read business internals.
>
> **L1 — Rule execution.** Executes a frozen rule against owner-set parameters. MUST be
> audited on every firing. Code MUST NOT determine a parameter's value; configuration MUST.
>
> **L2 — Judgment proposal.** MAY propose; MUST NOT enact. Every L2 output reaches effect only
> through §8 approval. **L2-strategic actions — those that would change a company's contract or
> the portfolio's allocation — MUST NOT be eligible for autonomy graduation under any
> configuration.**
>
> **L3 — Owner only.** Policy creation, ceilings and windows, autonomy grants, authority-level
> changes, specification changes, and new integrations. The platform MUST NOT take an L3 action
> and MUST NOT propose one.
>
> **§15.2 The policy-execution principle.** The Executive Layer MAY execute policy. The
> Executive Layer MUST NOT create policy. Policy is created by the owner, recorded in
> configuration, and carries provenance. A policy is a parameter, threshold, target, or rule
> whose change alters what the platform may do without new code review.
>
> **§15.3 The envelope rule.** An L2 proposal MAY propose an allocation within an owner-set
> envelope. It MUST NOT propose a change to the envelope itself.
>
> **§15.4 The Authority Registry.** Every action type the platform may take MUST appear in a
> platform-owned registry recording its authority level, graduation eligibility, and audit
> obligations. A business type MUST NOT declare an action type at L2-strategic or L3. An action
> type declared without an authority level MUST refuse installation. A change to a registered
> authority level requires owner authorisation.
>
> **§15.5 The never-autonomous list.** [Part 1.2's ten items, enumerated.]

*Classification: constitutional.* Adds a section; contradicts no existing MUST. §15.1's L2
clause generalises §8's existing hard constraint on capital actions rather than replacing it.

### 8.2 Amendment to §3.1 *(constitutional)*

> Add: The Executive Layer's strategic responsibilities are exercised as proposals under §15.2
> and §15.3. The Executive Layer MUST NOT enact a capital allocation, KPI target change, or
> retirement without approval under §8, and these actions MUST NOT graduate.

*Why:* §3.1 today names responsibilities without naming their authority, so the authority is
inferred from whichever mechanism gets built first.

### 8.3 Amendment to §8 *(constitutional; security boundary — security-engineer review)*

> Add: An approval MAY be platform-scoped, belonging to the platform rather than to a single
> business. A platform-scoped approval carries no graduation counter and MUST NOT graduate
> under any configuration. Its action type MUST come from the platform's own registry and MUST
> NOT be declarable by a business type.

*Why:* the second open owner escalation (Part 6.1). *Not this packet's to make* — it widens the
approval path's identity model (Part 11.3).

### 8.4 Amendment to §5 *(architecture)*

> Add to the Standard Business Contract: an **Operational Budget** (a spending ceiling per
> rolling window, recovering automatically on rollover) distinct from the **Capital Reserve**
> (a lifetime allocation recovering only by owner decision). Each autonomy policy MUST declare
> an authority level. Neither ceiling MAY carry a platform default.

*Why:* Part 3. Additive; no live contract changes meaning (Part 3.6).

### 8.5 Amendment to §12.5 *(architecture; operator-visible)*

> Add: The operator MUST be able to determine whether the platform is currently able to observe
> its companies. This is presented as a state — working, needs a look, or cannot check — never
> as a score, and its contributing reasons are listed rather than summarised.

*Why:* Part 4, and §12.5's own completeness gate: the platform can already be blind and says
nothing. Adds an operator-visible concept beyond D-007's table → **escalation** (Part 11.2).

### 8.6 D-007 table additions *(wording; reversal cost none)*

| Technical term | Operator-facing term |
|---|---|
| Operational Confidence | "Everything's running" / "Something needs a look" / "Jarvis can't check on your companies right now" |
| Capital Reserve state | "Running normally" / "Nearly out of budget" / "Out of budget — only you can add more" |
| Operational Budget band | "[Company] has used half today's budget" / "…is close to today's budget" |
| Authority level | (invisible — "what Jarvis can do on its own", already D-007's autonomy row) |

---

## Part 9 — Drafted D-entries

Drafted for the Manager to write into `docs/DECISIONS.md` after review. **Not written here.**
D-042 is held pending owner escalation 2, so these begin at D-043.

- **D-043 — authority is a property of an action type, and every action type is registered.**
  Four levels (L0 deterministic / L1 rule execution / L2 judgment proposal / L3 owner-only),
  with L2 split into tactical (inside a company's contract — graduates under §8) and strategic
  (about a company's contract or the portfolio — never graduates, has no counter). Enumerated
  in a platform-owned Authority Registry, closed-surface like D-032, pinned by digest, with a
  bidirectional completeness test and a negative control. Keyed to action types rather than
  components because components get refactored and A-003 already makes the action type the unit
  of authorisation. *Reversal cost: medium — it is bookkeeping over existing behaviour, but
  every future action type is written against it.*

- **D-044 — the Executive may execute policy; it may not create policy; and it may not propose
  moving the envelope.** Policy = a parameter, threshold, target, or rule whose change alters
  what the platform may do without new code review. Binds every automated component, not only
  the Executive (`KpiTarget`'s "the Manager may not change these" is the same rule stated
  locally four milestones early). The envelope rule is the operative half: an approval loop the
  platform can initiate is an autonomy ratchet with a human in it, and the defence is that the
  proposal cannot be generated. *Reversal cost: low to record, high to reverse once §3.1's
  responsibilities are built against it.*

- **D-045 — an Operational Budget and a Capital Reserve are different architectures.** A budget
  is a flow: windowed, automatically recovering, announced with percentage bands, and a breach
  costs time. A reserve is a stock: lifetime, recovering only by owner decision, represented as
  a state machine (NORMAL → LOW → EXHAUSTED → RECOVERED), and a breach costs the company. LOW
  fires when `runway_cycles < max_cycles_per_day` — a comparison of two existing contract-
  derived numbers, not a chosen percentage. `business_cap_usd` is a Reserve; the platform
  ceiling is a Budget; a per-company daily Budget is the one new mechanism, justified by
  M9-F119 (every live company's whole reserve is under one day of permitted work). *Reversal
  cost: medium — additive, no migration, and it survives either ruling on the open cap-window
  escalation.*

- **D-046 — a persisting condition is a state, announced once; a recurring condition is an
  alert.** Resolves M9-F81: a lifetime breach never settles, so `has_unread`'s correct posture
  re-raises it forever. State transitions write one audit record and one Decision Log entry
  each; the current state is re-derived on read, never stored (M8-F109's ratified posture).
  *Reversal cost: low.*

- **D-047 — Operational Confidence is a state with listed contributors, never a score.**
  CURRENT / DEGRADED / BLIND over seven enumerated boolean contributors, listed to the operator,
  never weighted. BLIND is the startup state, because a confidence that begins CURRENT asserts
  knowledge it does not have (M7-F21's failure applied to self-knowledge). Reported beside the
  census, never folded into it. Never a gate. The 06:14 event of 2026-07-28 is the argument:
  every company failed and five correct components reported health. *Reversal cost: low.*

- **D-048 — every automated parameter is registered, classed, and provenanced.** ENFORCING (a
  refusal depends on it) versus ANNOUNCING (only a notice depends on it). **No ENFORCING
  parameter has a default**, enforced by an AST sweep asserting each resolves to a `Settings`
  path or a defaultless contract field. Fails today on `max_cycles_per_day` and
  `max_invocation_budget_usd` (M9-F117), and passes exactly where the spec insisted —
  `business_cap_usd`, `wake_cycle_ceiling_usd`. *Reversal cost: low; it constrains where values
  live, not what they are.*

- **D-049 — a platform-scoped approval has no counter, and therefore cannot graduate.**
  `business_id` NULL (the same NULL the Decision Log and platform notifications already use),
  action type from a closed platform registry no business type may declare, sharing D-011's
  rendering and the operator queue. Graduation is impossible because `AutonomyCounterRow` is
  keyed `(business_instance_id, action_type)` and there is no business instance — the mechanism
  that would have to exist does not. Three further guards hold as defence in depth.
  **Gated on owner escalation 2 and security-engineer review of the identity question.**
  *Reversal cost: high — it is a security boundary.*

- **D-050 — a business type declares an authority level for every action type, or the install
  refuses.** No default (a default is how "undeclared" becomes "L2 by accident" — see M9-F115,
  where `graduation_eligible` defaults True today). A type may not declare an L2-strategic or L3
  action type at all. **A-003's namespace rule becomes enforced**: the prefix must equal the
  type's own name and `platform.` is reserved (M9-F116 — unenforced today, contained today,
  and a live bypass the moment D-049's path exists). Joins the five checks
  `ProvisioningService.install` already performs. *Reversal cost: low-medium — one field, one
  validation, one namespace comparison.*

---

## Part 10 — The deferred-M9 implementation strategy

M9 deferred four things, each on a stated gate: the judgment cadences (M9-F4, an Executive
budget scope), capital allocation (owner escalation 2), KPI target setting (lands with M8-F6),
and per-model cost tracking (M9-F5). This document adds work of its own. The strategy is the
order, and the ordering principle is stated first because it is the whole argument:

> **Every governance mechanism ships before the capability it governs.** A registry written
> after the actions it registers is an inventory; written before, it is a gate. This is the
> only sequencing rule that distinguishes preventative architecture from documentation.

**Wave G1 — governance skeleton. No new capability. Ships against today's platform.**

| Packet | Content | Why first |
|---|---|---|
| G1a | Authority Registry + its four guards (7.2); every existing action type enumerated at its current level | it is a pure statement of what is already true, so it can be verified against a running system rather than a plan |
| G1b | Parameter Register + the no-default-for-ENFORCING sweep (7.4); close M9-F117 | it arrives with the debt it found, which is how a guard should arrive |
| G1c | The autonomy ratchet test, all four assertions (7.5); close M9-F115 and M9-F127 | `graduation_eligible = True` is armed and live on two of three companies today |
| G1d | Namespace enforcement at install; reserve `platform.` (6.3, M9-F116) | must precede D-049's path, not follow it |

G1 changes no behaviour except refusing four things it currently permits. It is the cheapest
wave in the plan and the one that must not be resequenced behind anything.

**Wave G2 — self-knowledge. Ships the answer to 06:14.**

| Packet | Content |
|---|---|
| G2a | Operational Confidence: contributors, states, tick integration (Part 4) |
| G2b | Reserve state machine replacing the cap's percentage bands (3.3–3.5); closes M9-F81 |
| G2c | The operator surface for both — operator-surface-engineer, product-reviewer gated, coordinating with packet E's census tile |

G2b's ordering note, inherited from EXECUTIVE-LAYER Part 12: the states are derived from the
rollup's own fields, so rollup before states, and the arithmetic is never computed twice.

**Wave G3 — the standard, before the first judgment output exists.**

| Packet | Content |
|---|---|
| G3a | The eight-field structure: rule-identifier vocabulary, evidence triples, the three tests (5.3) |
| G3b | `AutonomyPolicy.authority_level`, install validation, catalog backfill (6.3, D-050) |

**Wave G4 — gated, in dependency order, each on a stated gate:**

| Deferred item | Gate | Unblocks |
|---|---|---|
| Platform-scoped approvals (D-049) | **owner escalation 2** + security-engineer on identity (11.3) | capital allocation, portfolio balancing, cross-business optimisation |
| Capital allocation (EXECUTIVE-LAYER 5.1) | the above | §3.1 |
| Executive budget sub-ceiling, **per evaluation** (6.2) | Manager-decided; needs an owner-visible surface | the judgment cadences |
| Judgment cadences (M9-F4) | the sub-ceiling | weekly/monthly strategic review |
| KPI target setting | **M8-F6** — lands with per-field refresh provenance, never before | §3.1 target setting |
| Per-company daily Operational Budget (3.5) | none — additive, defaults to today's behaviour | the missing flow control |
| Per-model cost tracking (M9-F5) | its own evidence; deliberately not a rider | accurate reserve arithmetic |

**The two dependencies worth stating separately**, because forgetting either is expensive:

1. **The cap-window escalation (11.1) does not block any of this.** Part 3.6 was designed so
   both rulings leave the architecture standing. Do not wait on it.
2. **M8-F6 and Executive target-setting are one event arriving from two directions**, recorded
   in EXECUTIVE-LAYER 5.2. If target-setting ships first, the next type upgrade offers the
   operator a routine-looking consent screen that silently reverts the Executive's targets. The
   sequencing constraint is the whole finding; it is not a preference.

**Sizing, packet count, and lane assignment are the Manager's.** The dependency edges above are
this document's contribution; G1 is four small packets that could run as one lane, G2 needs a
surface lane, and G4 is gated rather than scheduled.

---

## Part 11 — What this document does not decide

Escalations and deliberate non-decisions. Each belongs to the Manager or the owner.

1. **The window semantics of `business_cap_usd` (OWNER ESCALATION, open since M9-1,
   re-surfaced per D-037).** Part 3 gives the concept — a lifetime stock is a Reserve, a
   windowed flow is a Budget — and Part 3.6 makes both rulings survivable. It does **not** rule
   which one a spending limit ought to be, because that changes what a limit *means to the
   operator*, which is user-facing and the owner's. New evidence for the ruling: all three live
   companies now hold under one day of permitted work in reserve (**M9-F119**), and M9-F81's
   never-settling alert is a direct symptom of the ambiguity.

2. **Operational Confidence is a new operator-visible concept (ESCALATION).** §12.5's
   completeness gate and D-007's table are the constraint; this document drafts wording
   (8.5, 8.6) and does not add a row. The argument for approving it: the concept is not new
   *behaviour* — the platform already degrades and already goes blind, silently, as 06:14
   demonstrated. The argument against: it is one more thing an operator must learn. The owner's
   call.

3. **Platform-scoped approvals widen the identity model (ESCALATION, security).** D-002 derives
   identity from the Temporal workflow id; a platform action has no workflow. D-049's mechanism
   is drafted and its graduation-impossibility is structural, but *who authorised this, derived
   how* is unanswered. Security-engineer review with an owner-visible argument, not a framework
   packet.

4. **L3 actions have no actor identity to audit (ESCALATION).** Part 1.5: the highest authority
   level has the weakest attribution, because every L3 path today passes `"platform"` or
   `"operator"` as its actor. Fixing it needs an operator-identity concept the platform does not
   have. Named because a governance model that cannot say *who* is a governance model with one
   layer missing.

5. **Whether `affiliate.publish_post` should remain graduation-eligible.** It is L2-tactical and
   graduates by design (Part 1.3), the live policy sets a threshold of 5, and the counter sits
   at 0. This document explains why that is *coherent*; it does not rule whether it is *desired*
   for this specific action. An owner question, surfaced rather than assumed.

6. **Any change to D-009's formula, D-039's census rule, or D-011's rendering.** Confidence sits
   beside health and never inside it; the eight-field structure extends D-011's stored-values
   principle and never relaxes it.

7. **The severity distribution that replaces `worst_company` past N≈10** (M9-F122). Named as a
   bottleneck with its threshold; the replacement is a product decision for the milestone that
   reaches it, and inventing it now would be §14 speculation.

8. **Per-model cost tracking (M9-F5, unchanged).** Still homed here, still deferred, still for
   the reason M9 gave: replacing a conservative bound with real rates can only let *more* spend
   pass a ceiling check. Part 3's arithmetic depends on cost-per-cycle figures that are
   over-stated by construction, which is the safe direction and is stated rather than smoothed.

---

## Part 12 — Findings

| # | Finding |
|---|---|
| **M9-F115** | `AutonomyPolicy.graduation_eligible` defaults to `True`. §8 requires approval by default with no exception at launch; this field defaults the other way, so a type author who omits it gets a graduation-eligible action. Live on two of three companies (threshold 5, counter at 0). The accidental-autonomy ratchet, armed by a default. |
| **M9-F116** | A-003's namespace rule is unenforced. `AutonomyPolicy.action_type`'s pattern admits any `x.y`, so a business type may legally declare `platform.reallocate_capital` or `platform.circuit_breaker`. `platform.` is a de-facto reserved namespace (three live uses) with no reservation. Contained today; a live bypass the moment platform-scoped approvals exist. |
| **M9-F117** | Two ENFORCING budget parameters carry code defaults — `max_cycles_per_day = 48` and `max_invocation_budget_usd = $0.50`, the latter being D-003's innermost debit scope — while the two the spec insisted be explicit (`business_cap_usd`, `wake_cycle_ceiling_usd`) correctly carry none. Policy by effect, implementation by location. |
| **M9-F118** | **2026-07-28 06:14:46–06:14:53: all three companies woke and all three cycles failed.** Nine reservations opened and released, $0 settled, one Decision Log entry each. Zero notifications, zero dead letters, reliability 100 for all three, health bands unchanged, census unchanged at healthy 2 / watch 1. Five components each correct; the operator told nothing. The platform has no representation of its own operational state. |
| **M9-F119** | Every live company's entire Capital Reserve is under one day of permitted work: Trailhead 0.36 days (17.2 cycles), Portfolio Watch 0.51 (24.7), Summit 0.71 (33.9), at the observed platform mean of $0.7647/cycle against `max_cycles_per_day = 48`. M9-F1 on fresh data, with all three now under the line. |
| **M9-F120** | The $500/24h platform ceiling is 54× the busiest day the platform has ever had ($9.18 settled, 2026-07-26 — 1.8% utilisation) and first becomes the binding constraint at ≈13.6 companies. D-003 rule 3's ordering — per-business caps first, breaker as backstop — currently holds by dimensioning, not by design, and inverts quietly at scale. |
| **M9-F121** | The Executive tick is O(N) database round trips at a fixed 60s interval (≈21 at N=3; ≈700 at N=100). The runner's no-overlap protection means the failure mode is silently skipped ticks. Confidence contributor C7 is the interlock that makes it visible — an argument for building Confidence before N grows, not after. |
| **M9-F122** | `PortfolioHealth.worst_company` names exactly one company. Correct at N=3, a single number wearing a name at N=100. Past roughly N=10 the census needs a severity distribution — which does not threaten D-039, since a distribution is the opposite of a single score. |
| **M9-F123** | `SPEND_BANDS` and `PLATFORM_BANDS` are module constants, not config. ANNOUNCING under Part 2.3's test, so not policy — but the first live instance of the deterministic-becomes-policy hazard Position 1 named, and Parameter Register rows regardless. |
| **M9-F124** | `decision_log` still holds **zero** platform-scoped rows. `record_platform_halt` has been merged since M9-1b and has never fired live (correctly — the ceiling is at 0%). `platform_feed`'s reader remains the last Open deferred-completion row. The halt narrative is written, wired, and unproven against live data. |
| **M9-F125** | No notification kind represents operational health. `SPENDING` has never been written live (zero rows). Confidence needs either a new kind or a non-notification surface — a D-007/§12.5 question, escalated (11.2), not decided here. |
| **M9-F126** | The Reserve's LOW state is uncomputable for a company with no recorded cycles: `runway_cycles` is `None` by design (M7-F21's lesson — absent is not zero). The absent case is an Operational Confidence contributor (C6 `runway_unknown`), not a Reserve state. The two mechanisms interlock rather than one papering over the other. |
| **M9-F127** | `_advance_counter`'s two guards (`graduation_eligible` and `amount_usd is None`) are correct, and **nothing asserts they are the only path to `graduated = True`.** The privilege grant has no structural guard, where the refusal path has had one since M1-R2. |
| **M9-F128** | The census reports never-measured companies separately but counts a company whose *last cycle failed* as healthy. Never-measured and recently-failed are different absences; only one is reported. Live at 06:14 today, in triplicate. |
| **M9-F129** | No per-company windowed spending control exists at all. `max_invocation_budget_usd` is per invocation, `wake_cycle_ceiling_usd` is per cycle, `business_cap_usd` is lifetime — nothing bounds a company's spend per day. The only thing between a company and its whole reserve is a cycle count, which bounds frequency rather than cost. |

---

## Part 13 — Verified versus written

Per the project's standing discipline (M5-F5), stated explicitly.

**Verified by execution, read-only, 2026-07-28:** every figure in Part 0.1 and Part 3.2. The
rollup and census were produced by running the platform's own
`compute_portfolio_rollup` and `compute_portfolio_health` against the live database; the health
scores by `KpiEngine.health`; everything else by direct SQL. The 06:14 event is reconstructed
from `budget_ledger` and `decision_log` rows, not inferred. Nothing was written. $0 spent.

**Read but not executed:** all source-level claims about `alerts.py`, `runner.py`, `rollup.py`,
`health.py`, `contract.py`, `provisioning.py`, `breaker.py`, `approvals/service.py` and the
executive import-boundary test — read directly, cited by mechanism, not run beyond the
read-only calls above.

**Written, not verified:** every mechanism this document proposes. No test in Part 7 exists;
no registry in Part 7.2 exists; the Reserve state machine, Operational Confidence, the
eight-field renderer, the authority-level field and the namespace check are all design. The
findings are verified; the remedies are drafted.

**Not determinable from the database:** *why* the three cycles failed at 06:14. The evidence
establishes that each company's `plan_cycle` was attempted three times, every reservation was
released, nothing settled, and each cycle ended in M6-F9's containment path. The cause —
provider, credential, or configuration — is not in any table this document read, and is not
claimed.
