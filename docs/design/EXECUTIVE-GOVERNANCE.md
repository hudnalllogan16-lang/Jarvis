# Executive Governance

**Status:** design, **revision 2** — incorporating the owner's review of revision 1 (four
ratification conditions, six refinements). Parts 10 and 11 are the ratification package: they
return to the owner for final approval. No implementation. Packets M9-5 and M9-5b,
lanes `lane/m9-5`, `lane/m9-5b`.

**Scope, widened by the owner's first condition.** Revision 1 governed the Executive Layer.
Revision 2 governs **every executable action the platform can take** — Executive, Manager,
plugin, workflow, integration, and every business type not yet written. The owner's standard
for this document is that after it, *governance is never invented again*: a new capability
registers under the existing model or it does not ship.

This document decides nothing that D-001…D-042 already decided. Where it would change a
MUST/MUST NOT, alter a D-entry's semantics, widen a security boundary, or add an
operator-visible concept beyond D-007's table, it stops and says so (Part 13). Where an owner
direction meets an existing invariant, the tension is **flagged, never silently resolved**
(Part 13.9).

Every claim about live behaviour below was read out of the live database **read-only on
2026-07-28**. Nothing was written. `.env` was never printed. Spend: $0.

The optimisation target, binding on every choice below: **predictable, explainable, auditable
behaviour — never maximum autonomy.**

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
| 2 | Authority matrix → **the platform-wide Action Registry** | Part 1.4 |
| 3 | Capital model | Part 5.1, Part 5.7 |
| 4 | Budget / reserve architecture → **two health ladders** | Part 5 |
| 5 | Operational Confidence proposal (**four states**) | Part 6 |
| 6 | Explainability standard (**nine fields**) | Part 7 |
| 7 | Scaling review M10–M15 | Part 8 |
| 8 | Safety review + preventative ratchets | Part 9 |
| 9 | Drafted constitutional + architecture amendments | Part 10 |
| 10 | Drafted D-entries (D-043…D-052) | Part 11 |
| 11 | Deferred-M9 implementation strategy | Part 12 |
| 12 | **Provenance** — the shape, designed once | Part 3 |
| 13 | **Decision Lineage** — the proof tree | Part 4 |

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
It is the shape of the gap this document exists to close, and it is why Part 6 approves
Operational Confidence rather than treating it as a nicety. **M9-F118.**

---

## Part 0.2 — The owner's review of revision 1

Recorded verbatim-in-intent from `docs/DECISIONS.md`, "Owner review of the Governance
specification". Verdict: excellent across all areas. Ten directions, before ratification.

**The four conditions — structural:**

1. **Authority becomes platform-wide.** A property of *every* executable action, expressed as
   **Action → Authority Level → Approval Rule → Audit Record**, inherited by plugins,
   workflows, managers, trading modules, and integrations. "You never need to invent
   governance again."
2. **Policy formally defined**, verbatim:
   > *"A durable owner-authorized constraint that determines what actions are permitted,
   > required, or prohibited. Policies may only originate from: Owner, Approved
   > specifications, Approved configuration. No model output shall become policy without
   > explicit owner authorization."*

   — and **testable, not aspirational**.
3. **Decision Lineage as a first-class concept.** Every recommendation reconstructable as a
   proof tree: **Observation → Inference → Policy → Authority → Recommendation → Execution.**
4. **The constitutional invariant:** *"Authority is inherited downward and never upward."*
   Higher may perform lower's actions, never the reverse; escalation only through explicit
   approval. Mechanically checkable.

**The six refinements:**

5. **Operational health separated from financial health.** Healthy → Warning → Limited →
   Halted, versus Healthy → Low → Critical → Exhausted. *"Slow down"* versus *"you literally
   cannot continue."*
6. **Confidence gains a fourth state:** Current / Limited / Degraded / Blind.
7. **AUTHORITY becomes the explainability structure's fifth field** — *"why is Jarvis allowed
   to recommend this?"* — nine fields total.
8. **Plugin governance strengthened:** *"Plugins may request authority. Plugins never possess
   authority. Authority is granted by installation."*
9. **Provenance extends beyond parameters to everything** — goals, policies, budgets,
   thresholds, trading rules, risk limits: **Origin → Modified By → Approved By → Executed
   By.**
10. **L4 and L5 reserved.** *"Constitutions age better with room to evolve."*

Where a direction met an existing invariant, the meeting is recorded in Part 13.9 rather than
absorbed. There are seven such meetings and two of them are load-bearing.

---

## Part 1 — The platform-wide authority model

### 1.1 The levels

Authority is a property of an **action**, not of a component. A component may hold several; an
action holds exactly one. That inversion is deliberate: components get refactored, split, and
renamed, and an authority model keyed to components silently re-authorises whatever moves. An
action type is the platform's existing unit of authorisation — A-003 already makes it the key
for graduation counters, §8's four facts, and D-011's rendering — so keying authority to it
adds no new vocabulary and inherits every guard already built around the string.

**Revision 2's widening.** In revision 1 the model covered the Executive Layer. Under the
owner's first condition it covers **every executable action in the platform**: the Manager's
cycle decisions, the registry's lifecycle transitions, the approval subsystem's expiries, the
budget ledger's refusals, every tool a business type executes, every integration the platform
will ever acquire. The levels did not change. What changed is that there is now no action
outside them.

---

**L0 — Deterministic computation.** Compute, report, notify. Nothing else.

*Permitted:* reads across a declared surface; writing notifications, Decision Log entries,
audit records.
*Prohibited:* any contract write; any model call; any uninjected clock; any external effect.

*Why the boundary is here:* because it is checkable. `tests/test_executive_import_boundary.py`
turns "this component exercises no judgment" from a docstring promise into an AST assertion
with a proven negative control. An import of `jarvis.llm` **is** the violation event. A
boundary that can be crossed only by an edit a test refuses is worth more than a boundary
defended by review.

---

**L1 — Rule execution.** Automated actions whose entire behaviour is a comparison of stored
values against owner-set parameters. The breaker's halt, spend alerts, budget refusals,
approval expiry, lifecycle transitions, policy-parameterised pauses.

*Permitted:* firing, refusing, pausing, and announcing — automatically, without asking.
*Prohibited:* choosing its own parameters. **Code may not determine a parameter's value; only
policy can.** An L1 action is fully described by (rule, parameters) and the rule is frozen.
*Audit:* always.

*Why the boundary is here:* an L1 action is safe precisely because a human can predict it
without reading code. That property survives only while the *numbers* are somewhere a human
can read and change. The moment a threshold lives in a module constant, the rule stops being
"the owner set 80%" and becomes "a developer chose 80% and nobody remembers", which is the
first step of silent policy creep (Part 9.4). Part 2 makes this the owner's own origin clause
rather than a stylistic preference.

---

**L2 — Judgment proposal.** May PROPOSE. May never enact.

Split, because the platform already ships both kinds and a single L2 would contradict a live
configuration:

> **L2-tactical:** judgment *inside* a company's own contract — what to do with authority the
> company already has. `affiliate.publish_post` is the live instance. Graduation-eligible under
> §8's ladder, subject to every existing guard.
>
> **L2-strategic:** judgment *about* a company's contract, or about the portfolio —
> reallocation, target changes, retirement candidates. **Never graduates. Has no counter to
> graduate with** (Part 8.1).

*Why the split, and why strategic never graduates:* graduation is a **friction reduction
justified by demonstrated repetition**. It is safe for `affiliate.publish_post` because the
fifth post is genuinely the same kind of act as the first, against a bound that has not moved,
and an operator who approved four has demonstrated a stable judgment about a stable thing. An
L2-strategic action is not that. Each reallocation is a *different* judgment about a
*different* portfolio state; the previous four approvals are evidence about four situations
that no longer exist. Counting them is a category error, and D-030 already caught the same
error one layer over: refresh consent was deliberately kept out of §8's queue *because an
`action_type` would attach a graduation counter to configuration changes*. The reasoning that
protected configuration protects capital identically.

---

**L3 — Owner only.** Not a level the platform may reach at any autonomy setting.

Policy creation. Ceilings and windows. Autonomy grants. Authority-level changes. Spec changes.
New integrations. Credentials.

*Permitted to the platform:* nothing. The platform may *render* an L3 change for an owner to
make, and may *refuse* to operate without one.
*Prohibited:* proposal included. See the envelope rule, 1.6.

---

**L4 and L5 — reserved.** No action is registered at either, and a test asserts it
(Part 9.2, guard 5). This is the M8-4 discipline applied to a constitution: *"a nav item is a
promise that a destination exists"*, enforced by a bidirectional test. A reserved level that
something quietly starts using is worse than no reserved level at all.

Candidate semantics, recorded as candidates and **not assigned**:

| Level | Candidate meaning | Milestone that would need it |
|---|---|---|
| L4 | **Delegated human authority** — an operator who is not the owner; §3.2's District Managers; role-scoped humans | §3.2, or the first multi-operator deployment |
| L5 | **Multi-party or institutional authority** — an action requiring more than one human, or a counterparty | M12 live trading, or a regulated deployment |

Both candidates are *capability* tiers, deliberately. Part 13.9's tension T5 records why a
*constraint* tier — a rule binding even the owner — is the wrong shape for this ladder, and
where such rules belong instead.

### 1.2 The four-tuple

The owner's first condition names the shape. It is the whole registry schema, and every field
is drawn from a **closed set**, which is what makes "you never need to invent governance
again" true rather than hopeful: a new capability does not design a governance story, it picks
four values, and the cross-constraints refuse an incoherent pick.

> **Action → Authority Level → Approval Rule → Audit Record**

**Action.** An `action_type` string, A-003's dotted identifier, namespaced to its owning type
or to `platform` (Part 8.3's reservation).

**Authority Level.** L0 · L1 · L2-tactical · L2-strategic · L3. (L4, L5 reserved.)

**Approval Rule.** Closed set of four:

| Rule | Meaning |
|---|---|
| `NONE` | executes automatically; no human in the path |
| `GRADUATED` | approval by default, may reduce to none via §8's ladder after a clean streak |
| `OWNER_APPROVAL` | a human must answer a specific §8 approval before any effect; never reduces |
| `OWNER_ONLY` | not requestable by the platform at all; only an owner performs it |

**Audit Record.** Closed set of five obligations, any combination:
`AUDIT` · `DECISION_LOG` · `NOTIFY_ON_TRANSITION` · `NOTIFY_ON_PROPOSAL` · `ACTOR_IDENTITY`.

**The cross-constraints — this is the part that is testable.** Level determines which approval
rules are admissible, and every registry entry is checked against this table:

| Level | Admissible Approval Rules | Minimum Audit Record |
|---|---|---|
| L0 | `NONE` | — (a pure read that wrote nothing has nothing to record) |
| L1 | `NONE` | `AUDIT`; `DECISION_LOG` when operator-visible state changed; `NOTIFY_ON_TRANSITION` only |
| L2-tactical | `GRADUATED`, `OWNER_APPROVAL` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_PROPOSAL` |
| L2-strategic | `OWNER_APPROVAL` **only** | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_PROPOSAL` |
| L3 | `OWNER_ONLY` | `AUDIT` + `DECISION_LOG` + `ACTOR_IDENTITY` |

Two rows carry the model's hardest guarantees. **L2-strategic admits exactly one approval
rule**, so "never graduates" is a schema property rather than a configuration choice. **L3
admits only `OWNER_ONLY`**, so there is no combination of registry values that lets the
platform request an L3 action.

### 1.3 The never-autonomous list

Explicit, closed, and stated as a list because a rule expressed only as a principle gets
reasoned around one plausible case at a time.

The platform MUST NOT, at any authority level, in any milestone, without a human decision on
that specific act:

1. Raise, lower, or retarget any spending ceiling — per-invocation, per-cycle, per-company,
   per-day, or platform.
2. Create, edit, or delete an autonomy policy, or change any `graduation_threshold`,
   `graduation_eligible`, or authority level.
3. Move capital between companies.
4. Create or retire a company.
5. Execute a trade, transfer funds, or move real capital by any path (§8, unchanged).
6. Grant, widen, or resolve a credential scope, tool scope, or memory scope.
7. Install, upgrade, enable, or disable a business type.
8. Change any compliance requirement.
9. Add, remove, or re-level an entry in the Action Registry.
10. Change any value whose Provenance Origin is `OWNER`, `SPECIFICATION`, or `APPROVED_CONFIG`
    (Part 3) — which is, under the owner's definition, every policy.

Items 1, 2, 9 and 10 are the *meta* prohibitions, and every one of the others can be reached by
violating them. A platform that may edit its own ceilings has every authority, one config
write later.

### 1.4 The Action Registry — the platform-wide matrix

Deliverable 2. **Revision 1's authority matrix covered eleven Executive-adjacent actions.
Revision 2 covers the platform.**

**Platform actions — L0**

| Action | Component | Approval Rule | Audit Record |
|---|---|---|---|
| `portfolio.compute_rollup` | `executive/rollup.py` | `NONE` | — |
| `portfolio.compute_census` | `executive/health.py` | `NONE` | — |
| `portfolio.compute_confidence` | *proposed, Part 6* | `NONE` | — |
| `kpi.compute_health` | `kpi/engine.py` | `NONE` | — |
| `budget.read_aggregates` | `budget/ledger.py` (reads) | `NONE` | — |

**Platform actions — L1**

| Action | Component | Approval Rule | Audit Record |
|---|---|---|---|
| `platform.circuit_breaker` | `budget/breaker.py::trip` | `NONE` | `AUDIT` + `DECISION_LOG` |
| `budget.refuse_reservation` | `budget/ledger.py::reserve` | `NONE` | `AUDIT` |
| `spending.company_band_notice` | `executive/alerts.py` | `NONE` | `AUDIT` + `NOTIFY_ON_TRANSITION` |
| `spending.platform_band_notice` | `executive/alerts.py` | `NONE` | `AUDIT` + `NOTIFY_ON_TRANSITION` |
| `reserve.state_transition` | *proposed, Part 5.4* | `NONE` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_TRANSITION` |
| `operational.state_transition` | *proposed, Part 5.3* | `NONE` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_TRANSITION` |
| `confidence.state_transition` | *proposed, Part 6* | `NONE` | `AUDIT` + `NOTIFY_ON_TRANSITION` |
| `platform.approval_expired` | `approvals/service.py` | `NONE` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_TRANSITION` |
| `platform.lifecycle_transition` | `registry/registry.py` | `NONE` | `AUDIT` + `DECISION_LOG` |
| `business.wake_cycle` | `manager/activities.py` | `NONE` | `AUDIT` + `DECISION_LOG` |
| `business.park_degraded` | `manager/`, D-034.1 | `NONE` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_TRANSITION` |
| `business.dropped_wake_notice` | D-035 | `NONE` | `AUDIT` + `NOTIFY_ON_TRANSITION` |
| `capability.dispatch` | `capabilities/pool.py` | `NONE` | `AUDIT` |
| `capability.deny` | `registry/registry.py::_deny` | `NONE` | `AUDIT` |
| `reservation.reconcile` | `scheduler/`, D-034.3 | `NONE` | `AUDIT` |
| `autonomy.reset` | `approvals/service.py` | `NONE` | `AUDIT` |

**Business-type actions — L2-tactical.** Declared by a type as a *request*; **granted** at
install (Part 8.3).

| Action | Type | Approval Rule | Audit Record |
|---|---|---|---|
| `affiliate.publish_post` | affiliate | `GRADUATED` (threshold 5, live) | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_PROPOSAL` |
| *(finance_tracking declares none — read-only by owner decision, M7)* | | | |
| `trading.recommend_*` | M10, unwritten | `OWNER_APPROVAL` (Part 8.4) | full |
| `trading.execute_*` | M12, unwritten | `OWNER_APPROVAL`, never `GRADUATED` (§8 hard constraint) | full |

**Platform actions — L2-strategic.** All proposed; none exist.

| Action | Approval Rule | Audit Record |
|---|---|---|
| `platform.reallocate_capital` | `OWNER_APPROVAL` | `AUDIT` + `DECISION_LOG` + `NOTIFY_ON_PROPOSAL` |
| `platform.set_kpi_target` | `OWNER_APPROVAL` | same |
| `platform.propose_retirement` | `OWNER_APPROVAL` | same |

**Owner actions — L3**

| Action | Where | Approval Rule | Audit Record |
|---|---|---|---|
| ceiling / window change | config; no path exists | `OWNER_ONLY` | `AUDIT` + `DECISION_LOG` + `ACTOR_IDENTITY` |
| autonomy grant / threshold change | contract, at creation | `OWNER_ONLY` | same |
| authority-level change | Action Registry | `OWNER_ONLY` | same |
| type install / upgrade / toggle | `businesses/provisioning.py` | `OWNER_ONLY` | same |
| credential and scope grant | contract, at creation | `OWNER_ONLY` | same |
| compliance-requirement change | type definition, owner-signed | `OWNER_ONLY` | same |

**L4, L5 — reserved. No entries. Asserted empty by test.**

**What the widening exposed.** Enumerating the *whole* platform rather than the Executive's
neighbourhood produced three observations revision 1 could not have made. Sixteen L1 actions
exist against five L0 and one live L2 — the platform is overwhelmingly a rule-executing system,
which is the right shape and worth knowing. Eight of those sixteen write a notification or a
Decision Log entry, so eight are operator-visible, and only three of the eight will be
deduplicated by a state once Part 5 lands. And `ACTOR_IDENTITY` is required by six L3 rows and
**satisfiable by none** — see 1.7.

### 1.5 The downward-inheritance invariant

The owner's fourth condition, adopted as constitutional text (Part 10.1, §15.6):

> **Authority is inherited downward and never upward.** A holder of a higher authority level
> may perform the actions of every lower level. A holder of a lower level may never perform
> the actions of a higher one. Escalation occurs only through explicit approval.

**What it means in practice.** An execution context — a component, a workflow, an activity —
carries a level. It may emit any action registered at or below that level. The Executive
computes L0 rollups and fires L1 alerts because it is L2-capable; the budget ledger refuses at
L1 and may not propose; nothing below L3 may touch a ceiling.

**Why it is worth stating as a constitutional invariant rather than leaving it implicit:**
because the natural failure is not a component reaching *up* — that is obvious and would be
caught in review. It is a component being promoted *sideways*: a module that gains one L2
responsibility and thereby carries L2 authority into every L1 path it already had. The
invariant makes the promotion the reviewable event.

**The mechanical check, designed.** Three layers, cheapest first:

1. **Static — declared emitter, unique emit site.** Every registry entry names the module
   permitted to emit that action. A test asserts (a) each action's emit site is unique — the
   M1-R2 pattern, which already forbids a bare `raise ScopeViolationError` outside `_deny` —
   and (b) the emitting module's declared level is ≥ the action's level. A whole-registry
   sweep; no call-graph analysis needed.
2. **Static — no forward emission.** An AST sweep asserting no module declared at level N
   references an action registered above N. Same machinery as
   `test_executive_import_boundary.py`, which already walks per file and proves its own
   detector both fires and does not over-fire.
3. **Runtime — the context assertion.** Where an action executes, the platform asserts
   `context_level >= action_level` and, on failure, **refuses and audits** through the D-025
   independent-commit path — never narrows, never silently corrects. This is D-002's posture
   applied to authority instead of to identity.

Layer 3 cannot be built yet: **the platform has no execution-context authority level to compare
against** (**M9-F134**). Layers 1 and 2 are buildable today and catch the failure at the only
moment it is cheap — before the code runs. The runtime layer is scheduled with the Action
Registry's first consumer, and the gap is stated rather than assumed away.

**The invariant's honest limit, and it matters.** Inheritance governs what a component **may**
do. It does not govern what a component **can** do. `jarvis/executive/` is L2-capable under this
model, and D-038's import rule still forbids it `jarvis.llm` — because *may* and *can* are
different constraints and both are load-bearing. A reader who concludes "the Executive is L2,
therefore it may call a model" has read the invariant correctly and the architecture wrongly.
The consequence is real and is recorded as **M9-F132**: L2-strategic proposal *generation*, when
the judgment half lands, cannot live in `jarvis/executive/`. It needs a sibling package with
its own boundary, and naming that now is what prevents D-038 being widened later to accommodate
it.

### 1.6 Escalation, and the envelope rule

**L0 → L1: never automatically.** A computation that discovers a threshold crossing does not
act on it; it returns the figure and an L1 rule compares it. The live code already obeys this,
and the reason is recorded in `alerts.py`: `record_platform_halt` asks
`CircuitBreaker.assert_closed` — the *enforcing* check — rather than comparing the rollup's own
arithmetic, because "an operator told that spending is paused when dispatch is in fact still
running has been told something false about the platform's safety". Generalise it: **the
component that enforces a rule is the component that announces it.**

**L1 → L2: never.** An L1 rule that cannot fire does not escalate to judgment. It refuses, and
the refusal is the outcome. Halting is always available to L1; acting differently never is.

**L2 → L3: only as rendering, never as request.** And here is the rule the whole model turns
on:

> **The Executive may propose a move inside an owner-set envelope. It may never propose moving
> the envelope.**

An L2 proposal may reallocate $5,000 among companies whose committed capital totals $65,000.
It may not propose that committed capital become $70,000. It may propose retiring a company;
it may not propose raising the platform ceiling to make retirement unnecessary.

*Why this is stated separately from "L3 is owner-only":* because "the owner approves it" looks
like sufficient protection and is not. A platform that may propose envelope changes, and whose
proposals are usually good, trains its owner to approve them. The tenth approval is a reflex;
the fiftieth is a rubber stamp. At that point the platform has acquired the authority to set
its own bounds, and every single step was human-approved. **That is what silent policy creep
actually looks like — not a bypass, but a well-behaved proposal loop with a tired human at the
end of it.** The only structural defence is that the envelope-change proposal cannot be
*generated*, so it never enters the queue and never becomes routine. D-011's threat model is
the same argument one layer down: it removed model prose from between a decision and a human
because the human's attention is the thing being protected.

**Consequence, accepted:** the platform can be stuck. If every company is out of reserve and
the envelope is fully allocated, the Executive can produce no useful proposal and must say so
in plain language — "every company is at its limit; only you can raise one" — and stop. That
is the correct behaviour and it is worth the cost.

### 1.7 What each level owes the audit

Not "everything is audited" — a uniform rule produces uniform noise and is why nobody reads
audit logs. The obligations are the four-tuple's fourth field (1.2); this records why each is
where it is.

**L1 notifies on transitions, never on conditions.** Part 5.5 is the whole argument.

**L3 requires `ACTOR_IDENTITY` and nothing can supply it.** Every L3 path today passes
`"platform"` or `"operator"` as its actor. A governance model whose highest level has the
weakest attribution is inverted, and under revision 2 it is worse than under revision 1: the
platform-wide registry has **six** L3 rows, all requiring an identity the platform cannot
produce. Named, not solved: this needs an operator-identity concept the platform does not have
(Part 13.4). It is the single largest structural gap this document leaves open, and Part 3's
Provenance shape is designed so the field exists and is honestly empty rather than absent.

### 1.8 Where today's platform lands

The honest audit, because a model that does not fit the running system is a wish.

| Mechanism | Level | Conforms? |
|---|---|---|
| `compute_portfolio_rollup` / `compute_portfolio_health` | L0 | **yes**, enforced by import test |
| `KpiEngine.health` | L0 | **yes** |
| `CircuitBreaker.assert_closed` (refusal) | L1 | **yes** — ceiling is config (`platform_rolling_24h_usd`) |
| `CircuitBreaker.trip` (narrative) | L1 | **yes** — once-per-halt derived from the log |
| `BudgetLedger.reserve` refusal | L1 | **yes** — ceilings come from the contract |
| `raise_spend_alerts` / `raise_platform_ceiling_alerts` | L1 | **partly** — bands are module constants (**M9-F123**) |
| Approval expiry / auto-pause | L1 | **yes** — §9's timers |
| Lifecycle transitions | L1 | **yes** — D-008's matrix, all 25 pairs tested |
| `_deny` refusals | L1 | **yes** — audited, structurally enforced (M1-R2) |
| D-034.1 park, D-035 dropped-wake notice | L1 | **yes** |
| `_advance_counter` graduation | L2-tactical | **yes** on guards; **no** on provenance (**M9-F127**) |
| Executive tick interval | L1 parameter | **yes** — `ExecutiveSettings.tick_interval_seconds` |
| `max_cycles_per_day` = 48 | L1 parameter | **no** — code default (**M9-F117** → **M9-F130**) |
| `max_invocation_budget_usd` = $0.50 | L1 parameter | **no** — code default (**M9-F117** → **M9-F130**) |
| `business_cap_usd`, `wake_cycle_ceiling_usd` | L3 | **yes** — no default; must be explicit |
| `graduation_eligible` default `True` | L3 parameter | **no** — defaults to permission (**M9-F115** → **M9-F130**) |
| Every L3 path's actor | L3 | **no** — no identity exists (1.7) |

Fourteen of eighteen conform. The four that do not are all the same shape — **a value that
governs what the platform may do, chosen somewhere a human would have to read Python to
find** — plus the attribution gap. Under revision 1 those were hygiene findings. Under the
owner's policy definition they are **rule violations**, which is Part 2's most consequential
consequence.

---

## Part 2 — Policy

### 2.1 The owner's definition, adopted verbatim

> **A policy is a durable owner-authorized constraint that determines what actions are
> permitted, required, or prohibited. Policies may only originate from: Owner, Approved
> specifications, Approved configuration. No model output shall become policy without explicit
> owner authorization.**

This goes into §15.2 unchanged (Part 10.1). It is stronger than revision 1's definition, and
in a specific way worth naming: revision 1 defined policy by its **effect** ("a value whose
change alters what the platform may do"); the owner defines it by its **nature and its
origin**. Effect is a good discriminator and a poor rule — it tells you what to look at and
nothing about what is allowed. Origin is a rule, and a rule is what a test can hold.

**The two definitions compose rather than compete**, and the composition is the design:

| Question | Answered by | Used for |
|---|---|---|
| *Is this thing a policy?* | the **effect test** — could changing this value cause the platform to permit something it previously refused, or refuse something it previously permitted? | classification: what must be registered |
| *May this thing be a policy?* | the owner's **origin clause** — Origin ∈ {Owner, Approved specification, Approved configuration} | admission: whether a registered policy is legitimate |

Revision 1's ENFORCING/ANNOUNCING split survives as the classification step: an ENFORCING value
is a policy and inherits the origin clause; an ANNOUNCING value is not policy and is governed
as engineering. What changes is the consequence of failing. Under revision 1, a ceiling with a
code default was untidy. Under the owner's definition its Origin is `PLATFORM_DEFAULT`, which
is not one of the three permitted origins, so **it is not a legitimate policy** — and the
platform is currently enforcing it. **M9-F130.**

### 2.2 The principle, and its two refinements

> **The Executive may execute policy. The Executive may not create policy.**

Adopted. Both revision-1 refinements are retained and both are now supported by the owner's own
text.

**It needs a second sentence, because it names no creator.** The owner's definition supplies
it: policy originates from Owner, approved specification, or approved configuration. The
prohibition and the grant now sit in one paragraph.

**"The Executive" is too narrow.** The Business Manager can create policy by accident:
`KpiTarget`'s docstring already says "The Manager may not change these — that is the
strategy/execution split", which is this principle stated locally, four milestones early, for
one field. Under the owner's first condition — authority is platform-wide — the principle must
be platform-wide too, or the two conditions disagree. §15.2 is therefore written to bind every
automated component, with the Executive named as the instance that most needs saying.

### 2.3 Testable, not aspirational — the tests, designed

The owner's condition is that the definition be testable. Four tests, one per clause, each in a
shape the suite already runs.

**Test 1 — "durable": a policy survives a restart.**
Every registered policy resolves to a stored location: a `Settings` path, a contract field, or
a database row. A policy held only in memory is not durable and is not policy.
*Mechanism:* the Policy Register (Part 3.3) names each policy's location; the test resolves
every location and fails on any that is a module-level literal.
*Fails today:* twice — `max_cycles_per_day`, `max_invocation_budget_usd`.

**Test 2 — the origin clause: every policy has a permitted Origin.**
`Origin ∈ {OWNER, SPECIFICATION, APPROVED_CONFIG}`. `PLATFORM_DEFAULT` and `TYPE_DEFINITION`
are recordable origins and are **not** permitted origins for a policy — a type may *request*,
never *establish* (Part 8.3).
*Mechanism:* a sweep over the Policy Register asserting each entry's Provenance Origin is one
of the three. A data assertion rather than a code analysis, which is why it is cheap and total.
*Fails today:* three times — the two above, plus `graduation_eligible`'s `True`, whose origin is
a Python default argument.

**Test 3 — "no model output shall become policy": the writer boundary.**
The strongest of the four, and it generalises D-038's import rule from one package to a
capability:

> **No module that may write a policy store imports `jarvis.llm`, and no policy write accepts a
> value derived from a model call.**

*Mechanism:* declare the set of policy-writing modules — small: config loading, provisioning,
and the future owner-settings path. Assert by AST that none imports `jarvis.llm`, directly or
through a re-export; exactly `test_executive_import_boundary.py`'s walk, including its negative
control proving the detector fires and its positive control proving it does not over-fire.
D-013 already establishes the platform's posture — the model proposes, the platform attaches
scope and resolves `needs_approval` — and this applies that posture to policy instead of to
scope.
*Passes today, vacuously:* no module writes a policy store, because there is no owner-settings
path. Recording it now is what stops the first such path being written with an `llm` import in
scope.

**Test 4 — "permitted, required, or prohibited": every action's disposition is resolved.**
Every registry entry carries an Approval Rule from the closed set, and that rule is admissible
for its level (1.2's cross-constraints).
*Mechanism:* the Action Registry's completeness test (Part 9.2).
*Status today:* not applicable — the registry does not exist. It is G1a's first deliverable.

### 2.4 The clause with no mechanism behind it

The owner's definition says policies determine what actions are **permitted, required, or
prohibited**. The platform can express permitted and prohibited. **It has no way to express
required.** Nothing in Jarvis can say "this action MUST happen"; every mechanism is a gate, a
ceiling, or a refusal. The nearest thing is the Finance type's compliance requirements, and
every one of those is a prohibition or a condition, not an obligation.

Flagged rather than filled (**M9-F131**, Part 13.9 T2). Inventing an obligation mechanism now
would be §14 speculation — no finding requires it and no milestone needs it. The recommendation
is that §15.2 carry the owner's wording **unchanged**, with "required" reserved: the definition
is constitutional and should be written for the platform Jarvis will become, while the record
notes that no required-action mechanism exists and that adding one is a decision with its own
evidence. A constitution that names one capability it does not yet have is honest; a platform
that quietly implements obligations to make its constitution true is not.

---

## Part 3 — Provenance

The owner's ninth direction: provenance extends beyond parameters to **everything** — goals,
policies, budgets, thresholds, trading rules, risk limits. Designed once here, applied
everywhere.

### 3.1 The shape

> **Origin → Modified By → Approved By → Executed By**

| Field | Type | Answers |
|---|---|---|
| **Origin** | enum: `OWNER` · `SPECIFICATION` · `APPROVED_CONFIG` · `TYPE_DEFINITION` · `PLATFORM_DEFAULT` | where did this value come from? |
| **Modified By** | actor identifier + timestamp | who last changed it? |
| **Approved By** | approval id, or `OWNER_DIRECT`, or empty | who authorised the change? |
| **Executed By** | *per use* — a lineage node (Part 4) | who acted on it, and when? |

Two of the five origins are **recordable but not permitted for a policy** (Part 2.3, test 2).
`TYPE_DEFINITION` is what a plugin supplies — a *request*, per the owner's trichotomy.
`PLATFORM_DEFAULT` is what a code default supplies, and its presence on a policy is the
violation itself.

### 3.2 The structural finding: provenance is not one record

**Origin, Modified By and Approved By are properties of the value. Executed By is a property of
each use.** A budget ceiling has one origin and thousands of executions. Storing "Executed By"
as a field on the value would overwrite the last executor with the current one, producing a
record that answers *"who used this most recently"* while appearing to answer *"who has used
this"* — a schema that cannot hold its own definition. **M9-F139.**

The resolution is not a compromise; it is the design:

> **Provenance splits into a static head and a dynamic tail. The head — Origin, Modified By,
> Approved By — is stored beside the value. The tail — Executed By — is a Decision Lineage node
> (Part 4). Provenance and lineage are one structure seen from two ends, and they meet at the
> Policy node.**

Provenance answers *"where did this value come from?"*. Lineage answers *"where did this
decision come from?"*. A lineage's Policy node **is** a provenance head, referenced by
identifier. Neither duplicates the other, and every fact lives in exactly one place.

### 3.3 Where it applies, and the register

One register, three sections, one shape:

| Section | Governs | Origin must be |
|---|---|---|
| **Policy Register** | ceilings, windows, gating thresholds, autonomy thresholds, graduation eligibility, authority levels, risk limits, trading rules | one of the three permitted |
| **Parameter Register** | ANNOUNCING values — alert bands, tick intervals, display thresholds | any recordable origin |
| **Goal Register** | KPI targets, goals, compliance requirements | `OWNER` or `TYPE_DEFINITION` (a type may suggest; the owner establishes) |

The Goal Register's row is where revision 1's M8-F6 sequencing constraint becomes structural
rather than a note. A KPI target set by the Executive would carry Origin `OWNER` (via approval);
a type upgrade's Band B refresh proposes Origin `TYPE_DEFINITION`. **Provenance makes the
collision visible in the refresh diff** rather than after an operator accepts a routine-looking
consent screen. The M8-F6 deadlock revision 1 could only *schedule* is, under provenance,
*detectable*.

### 3.4 The precedent the platform already set

This is not a new idea in this codebase. `RuntimeIdentity._source` (M1-R1) stamps a provenance
label — `"activity"` or `"testing"` — into every audit record it touches, precisely so that "a
test-provenance identity appearing in production audit is visibly an incident". That is the
Origin field, built four milestones ago, for one value, with exactly this rationale. Part 3
generalises a mechanism the platform has already proved rather than importing one.

### 3.5 What provenance costs

Stated because it is not free. Every governed value gains three stored fields and every change
path gains a write. `Approved By` is empty for every value on the platform today, because no
approval has ever authorised a configuration change — D-030 deliberately keeps refresh consent
out of §8's queue, and ceilings have no edit surface at all. An empty field that is *honestly*
empty is the correct starting state, and it is how the L3 attribution gap (1.7) becomes visible
instead of merely true.

---

## Part 4 — Decision Lineage

The owner's third condition: every recommendation reconstructable as a proof tree.

> **Observation → Inference → Policy → Authority → Recommendation → Execution**

### 4.1 The principle that makes it storable

The condition arrives with its own hardest constraint attached: lineage must ride the existing
audit and Decision Log architecture, be D-004 and D-011 compatible, and **its nodes must be
stored identifiers, never prose.**

That constraint is not a limitation. It is what makes lineage *proof* rather than narrative:

> **Every lineage node is a reference to something the platform already minted.** No node
> contains a sentence. Reconstruction is a join, not a reading.

| Node | Is a reference to | Already exists as |
|---|---|---|
| **Observation** | a stored reading | `kpi_values.id`, a `budget_ledger` row id, a rollup field key + tick id |
| **Inference** | the rule that fired | a **rule identifier** from Part 7.2's closed vocabulary |
| **Policy** | the constraint applied | a Policy Register key + its provenance head (Part 3) |
| **Authority** | the permission relied on | an Action Registry key (Part 1.4) |
| **Recommendation** | the proposal produced | a `decision_id` — the Decision Log's own key |
| **Execution** | the effect, if any | an `approval_id` + A-001 idempotency key, or an audit row id (4.5) |

Six node types, six identifier spaces, **zero prose.** D-011 holds by construction because there
is nothing for a model to author: a lineage row has no text column. D-004 holds because lineage
rows are written inside activities with recorded results, exactly as every other durable write
already is.

### 4.2 Storage shape

One append-only table, under A-006's application-layer append-only rule:

```
decision_lineage
  lineage_id       stable id for one proof tree
  decision_id      the Recommendation this tree explains   (FK, indexed)
  ordinal          position within the tree
  parent_ordinal   NULL for roots — what makes it a tree rather than a list
  node_type        enum: OBSERVATION | INFERENCE | POLICY | AUTHORITY
                       | RECOMMENDATION | EXECUTION
  node_ref         the identifier, in the space its node_type names
  recorded_at      timestamp
```

`parent_ordinal` is the only structural choice worth defending. A recommendation is not a chain:
several observations feed one inference, and several inferences may feed one recommendation. A
parent pointer gives the DAG for the price of one nullable integer, and reconstruction stays a
single ordered `SELECT`. A separate edge table would buy generality nothing has asked for — §14.

**Reconstruction** is one query by `decision_id`, ordered by `ordinal`. **Verification** is
resolving each `node_ref` in its own store and confirming it exists. That second operation is
the point: a lineage whose Observation node names a `kpi_values` row that does not exist is a
*detectable lie*, which is a property no prose explanation can have.

### 4.3 The invariant that stops lineage becoming decoration

> **A recommendation with an incomplete lineage MUST NOT be presented for approval.**

Five node types are required at proposal time — Observation, Inference, Policy, Authority,
Recommendation. **Execution is appended after the fact**, when the effect lands, closing the
tree.

Without this invariant, lineage is documentation that degrades silently the first time someone
is in a hurry. With it, lineage is a precondition of the approval path — the same structural
position D-011's rendering already occupies: not a feature of the approval, a requirement of it.

### 4.4 Where it anchors, and the field already waiting for it

`ApprovalRow.decision_ref` exists, is written by `ApprovalService.request`, is persisted as a
64-character column — and **has zero readers anywhere in `jarvis/`.** It is the
M7-F21 / M8-F8 / M9-F1 shape for the fourth time: a component built ahead of its caller, found
by reading rather than by failing. It is also exactly the anchor lineage needs — the link from
an approval back to the decision that produced it. **M9-F136**, with a deferred-completion
ledger row owed under `docs/DEPENDENCIES.md`'s own rule.

### 4.5 The gap in the Execution node

An L2 recommendation executes through an approval, so its Execution node is an `approval_id`.
An **L1 action executes with no approval at all** — the breaker trips, a band notice fires, a
reservation is refused — and has no id to reference. **M9-F135.**

Options, with the recommendation stated: mint a firing id per L1 action (uniform, cheap, one
more identifier space); reference the audit record's own row id (free, but couples lineage to
audit's storage); or exclude L1 from lineage (cheapest, and wrong — the halt narrative is
precisely the thing an operator most wants a proof tree for). **Recommendation: the audit record
id.** Every L1 action already carries `AUDIT` as a minimum obligation (1.2), so the identifier
exists by construction for exactly the set of actions that need it, and no new minting appears
anywhere.

### 4.6 What lineage is not

- **Not a replay engine.** D-004 is unchanged: Temporal's history is the replay substrate and
  the audit log is a durable projection. Lineage is a third thing — a *justification index* —
  and it must never become a second execution history. It stores why, not what happened next.
- **Not the operator's narrative.** §11.5 owns prose for humans; lineage owns identifiers for
  proof. Part 7's nine fields are the bridge: **the nine fields are the lineage rendered.**
- **Not optional per action.** Every L2 action carries one. Every L1 action carries one once
  4.5's identifier is settled. L0 computes and produces no decision, so it produces no tree.

---

## Part 5 — Capital: two architectures, two ladders

### 5.1 The capital model

The platform today has one word — "budget" — doing four jobs at four scales, and D-003's
hierarchy relates them by *containment* while saying nothing about their *kind*. That is the
root of M9-F1, of the owner's open cap-window escalation, and of M9-F81's never-settling nag.

Two kinds, and every ceiling in the platform is one or the other:

> **An Operational Budget is a flow.** It is denominated per window, it refills when the window
> rolls, and exhausting one costs *time*. Recovery is automatic and requires no human.
>
> **A Capital Reserve is a stock.** It is denominated per lifetime, it only depletes, and
> exhausting one costs *the company*. Recovery requires a human decision and nothing else can
> produce it.

The owner's fifth refinement names exactly this distinction in operator terms — *"slow down"*
versus *"you literally cannot continue"* — and gives each kind its own ladder. Everything below
follows from that.

| Scope | Kind | Today | Recovery |
|---|---|---|---|
| Per invocation (`max_invocation_budget_usd`) | Operational Budget (window = one invocation) | exists | automatic, next invocation |
| Per wake cycle (`wake_cycle_ceiling_usd`) | Operational Budget (window = one cycle) | exists | automatic, next cycle |
| Per company per day | **Operational Budget (window = 24h)** | **does not exist** (**M9-F129**) | automatic, next day |
| Per company lifetime (`business_cap_usd`) | **Capital Reserve** | exists, mislabelled as a budget | **owner only** |
| Platform per 24h (`platform_rolling_24h_usd`) | Operational Budget (window = 24h) | exists | automatic, next window |
| Executive reasoning sub-ceiling | Operational Budget (window = per evaluation) | Manager-decided, unbuilt | automatic |

The missing row is the finding. A company has a per-invocation flow control, a per-cycle flow
control, and a lifetime stock — **and nothing in between.** The only thing standing between a
company and its entire reserve is how many cycles it is allowed to run in a day.

### 5.2 What the live numbers do to that

Mean cost per recorded cycle, from today's read: Trailhead $1.4500, Summit $0.73843, Portfolio
Watch $0.60637; platform-wide $9.176550 / 12 cycles = **$0.7647**.

Against `max_cycles_per_day = 48` — which **all three live contracts carry, every one of them
the Python default nobody chose** (read from the stored contracts today; see M9-F130):

| Company | Reserve | Cycles of reserve | **Days of permitted work** |
|---|---|---|---|
| Trailhead Gear Reviews | $25.00 | 17.2 | **0.36** |
| Portfolio Watch | $15.00 | 24.7 | **0.51** |
| Summit Trail Gear | $25.00 | 33.9 | **0.71** |

**Every live company's entire lifetime reserve is less than one day of the work the platform
already permits it to do.** M9-F1 found this for Summit on 2026-07-27; on today's data all
three are under the line and Trailhead is at a third of a day. **M9-F119.**

Nothing has burned that way, because all three companies wake on `0 9 * * *` — once a day — so
observed behaviour is roughly one cycle daily plus approval-decided wakes. That is the point:
the platform's *permission* and the platform's *behaviour* differ by a factor of about fifty,
and the only reason no company has vanished is the schedule, which is not a spending control.
Safety by idleness is not safety.

And the platform ceiling: the busiest day ever observed is 2026-07-26 at **$9.18 settled across
three companies — 1.8% of the $500/24h ceiling.** The breaker sits at 54× the largest day the
platform has ever had. At $0.7647/cycle and 48 cycles/day, one company's maximum permitted daily
burn is $36.71, so the platform ceiling first becomes the *binding* constraint at **≈13.6
companies**. Below that, D-003 rule 3's ordering — per-business caps first, platform breaker as
backstop — holds by dimensioning rather than by design. **M9-F120**, carried into Part 8.4.

### 5.3 The operational ladder — "slow down"

> **Healthy → Warning → Limited → Halted**

Applies to every Operational Budget scope: per invocation, per cycle, per company per day,
platform per 24h. Defined against shipped mechanisms rather than against percentages, so each
state names something the platform actually does:

| State | True when | Live mechanism |
|---|---|---|
| **Healthy** | nothing refusing, below the warning bands | — |
| **Warning** | a band crossed (50%, 80% of the window), nothing refusing | `raise_spend_alerts`, `raise_platform_ceiling_alerts` |
| **Limited** | an enclosing scope is refusing *some* work while the company still runs | `BUDGET_EXHAUSTED` ends a cycle early (D-003 rule 5); per-invocation refusals drop plan items |
| **Halted** | new dispatch refused for the whole scope | `CircuitBreakerOpenError`; a company's daily budget exhausted |

**Limited is the state revision 1 was missing**, and it is the owner's refinement earning its
keep immediately. The platform already has a genuine middle condition — a cycle that ends early
because it ran out of per-cycle budget, then wakes again tomorrow and works normally — and
revision 1 had nowhere to put it. It is not Warning (something *is* being refused) and it is
not Halted (the company is still running). It is precisely "slow down", and it has been in the
code since M6-1b with no name.

**Recovery for Limited and Halted is automatic, at window rollover, and the notice says so.**

### 5.4 The financial ladder — "you literally cannot continue"

> **Healthy → Low → Critical → Exhausted**

Applies to the Capital Reserve, per company. Every threshold is a comparison of two numbers the
platform already stores — no invented percentage:

| State | True when | Why this line |
|---|---|---|
| **Healthy** | `runway_cycles ≥ max_cycles_per_day` | more reserve than a day of permitted work |
| **Low** | `runway_cycles < max_cycles_per_day` | by the platform's own configuration, less than one day of permitted work from stopping |
| **Critical** | `lifetime_headroom_usd < wake_cycle_ceiling_usd` | cannot fund even one more full cycle — "will stop" has become "is stopping" |
| **Exhausted** | `lifetime_headroom_usd == 0` | dispatch refused; only a human restarts it |

**Critical is the owner's refinement, and it is the more useful of the two additions.** Revision
1 went from Low straight to Exhausted, which meant the last thing an operator heard before a
company stopped was "you have less than a day" — and then silence until it was over. Critical is
the moment the *next* cycle cannot be funded, computed from two contract-derived numbers, and it
is the last point at which raising the reserve prevents an interruption rather than repairing
one.

**Recovery is a transition, not a state.** Revision 1 proposed a fourth `RECOVERED` state; the
owner's ladder has four states and no recovery state, and the owner's is better. A reserve that
has been raised is simply Healthy or Low again, and the *event* — "you added budget; Summit is
running normally again" — is a transition announcement, which is what Part 5.5 makes every
transition anyway. Carrying a state whose only content is "the previous transition was upward"
is a state that means a fact about history, and states should mean facts about now.

**The live evaluation, and it is the argument for the whole refinement:**

| Company | Runway | Operational | **Financial** |
|---|---|---|---|
| Trailhead Gear Reviews | 16.2 cycles | Healthy | **Low** |
| Summit Trail Gear | 25.9 cycles | Healthy | **Low** |
| Portfolio Watch | 21.7 cycles | Healthy | **Low** |

**Every company on the platform is financially Low and operationally Healthy, right now, and
the census says "healthy 2 · watch 1".** Revision 1 could not express that, because it had one
ladder and the two facts had to be averaged into one word. The owner's separation is not a
presentational preference; it is the difference between a portfolio that reads fine and a
portfolio that is three raises away from stopping.

### 5.5 Thresholds justified, and the states-versus-alerts decision

Following the reaction-time instruction produces a conclusion sharper than a number, and it
decides the alerts question on the way.

**What the platform already assumes about human latency.** §9 sets 24h re-notification and
7-day auto-pause on an unanswered approval. Those are the only recorded assertions the
architecture makes about how fast a human responds, and what they assert is: *24 hours may
elapse before an operator has acted, and that is normal, not an incident.*

**Apply that to a 24h Operational Budget.** For a percentage band to give an operator time to
act, it must leave at least one reaction interval of headroom. On a 24h window, no percentage
can: 50% of a 24h window is at most 12 hours, and the window itself is 24. **No band on a daily
budget is a reaction-time mechanism.** It cannot be, arithmetically.

That is not a reason to remove the bands. It is a reason to be honest about what they are for:

> **The operational ladder explains; it does not protect.** Protection comes from the window
> rolling over. The worst case is losing part of a day, automatically recovered, and the bands
> are how an operator learns *why* today was quiet.

**Now apply the same test to the Capital Reserve.** There is no rollover. The worst case is a
company that never runs again until a human intervenes — and the human may be asleep, or on
holiday, or reading a queue that has said the same thing eleven times. Here reaction time is the
*entire* problem, and a percentage is the wrong unit for it: 80% of a cap says nothing about how
long you have. **Cycles are the unit in which time-to-stop is denominated**, `runway_cycles` is
already a `PortfolioRollup` field, and `max_cycles_per_day` is already the contract's own
statement of how fast a company may consume them.

**Therefore: the operational ladder alerts; the financial ladder is states.**

> **Operational → alerts.** Repetition is acceptable because the condition genuinely recurs and
> genuinely resolves. Yesterday's 80% notice and today's 80% notice describe two different days.
>
> **Financial → states.** A reserve condition does not recur; it *persists*. Announcing a
> persisting condition repeatedly is not information, it is nagging, and the operator learns to
> dismiss the category.

M9-F81 is the live proof and it is exactly this failure: a lifetime breach never settles, so the
deduplication that works correctly for a windowed condition produces a notice that can never
stop being true. The current implementation is not wrong — `has_unread` does what its docstring
says, and `alerts.py` states in its own module comment that the copy will be wrong if the
escalation rules the cap is windowed. It is the *concept* that is wrong: a stock was given a
flow's announcement mechanism.

Under the ladders, M9-F81 dissolves. **Each transition announces exactly once**, into the audit
log and the Decision Log, and the *state* is what the operator's surface renders — so a company
sitting in Exhausted for three weeks shows Exhausted for three weeks and generates one entry,
not twenty-one.

**Alert noise, as a design rule:** the number of notifications a persisting condition may
generate is **one** — one per transition into the state. If the condition changes, that is a new
transition and a new notice. This is Part 9.3's noise defence, and it is a consequence of the
ladders rather than a rule bolted beside them.

### 5.6 The two ladders must be reported separately

The owner's refinement, stated as an invariant because the temptation to merge them is
permanent:

> **Operational state and financial state are reported side by side and never combined into one
> word.**

A company can be operationally **Halted** (today's budget spent; back tomorrow) while
financially **Healthy**. A company can be financially **Exhausted** while operationally
**Healthy**, because nothing was even attempted. Those are opposite situations requiring
opposite operator responses — wait, versus act — and any single word covering both will be wrong
in one of them.

This is D-039's argument in a third place: the census refused a portfolio score because
averaging comparable numbers yields a number comparable to nothing; Part 6.3 refuses a
confidence score for the same reason; and here two *incommensurable* ladders refuse to be one
ladder. **M9-F137** records that the platform has no surface today that could show them
separately — everything spending-related renders as a single "spending" concept.

### 5.7 Mapping, and migration for the three live contracts

| Today | Becomes | What changes |
|---|---|---|
| `business_cap_usd` | **Capital Reserve** | concept renamed, not schema; alerts become the financial ladder |
| 50/80/100 bands on `business_cap_usd` | **financial ladder states** | percentages → runway-in-cycles and headroom-vs-cycle-ceiling; one announcement per transition |
| `platform_rolling_24h_usd` + breaker | **platform Operational Budget** | unchanged; already a flow with automatic recovery |
| 50/80 bands on the platform ceiling | **operational ladder: Warning** | unchanged mechanism, named state |
| `BUDGET_EXHAUSTED` cycle outcome | **operational ladder: Limited** | unchanged mechanism, finally named |
| `CircuitBreakerOpenError` | **operational ladder: Halted** | unchanged |
| `wake_cycle_ceiling_usd` | per-cycle Operational Budget | unchanged |
| `max_invocation_budget_usd` | per-invocation Operational Budget | unchanged, minus its default (Part 2.3) |
| *nothing* | **per-company daily Operational Budget** | new — the one genuinely new mechanism |

Non-negotiable constraint: **Band C is never widened** (D-042, D-029). `business_cap_usd` is a
Band C field, frozen against type upgrades because it is the operator's money, and Summit's
$2.00 per-cycle ceiling is a live example of an explicit operator choice a refresh must never
touch. Nothing here changes that; the migration is additive and every existing byte stays put.

1. **`business_cap_usd` is not renamed and not migrated.** It *is* the Capital Reserve. The
   concept changes; the column, the value, and the Band C freeze do not. Three live contracts
   stay byte-identical — the property M8-6 already proved for the refresh migration.
2. **Both ladder states are computed, never stored.** Derived per evaluation from
   `lifetime_headroom_usd`, `runway_cycles`, `max_cycles_per_day` and `wake_cycle_ceiling_usd` —
   all existing fields. No migration, and it inherits M8-F109's ratified posture that pending
   state is computed rather than stored.
3. **The transition is what persists**, as a Decision Log entry with a structured `action_type`
   (`reserve.state_transition`, `operational.state_transition`). Current state is re-derived on
   read; *history* comes from the log, which is what D-005 makes the log for.
   `_halt_already_explained` already demonstrates the pattern — read the log for a structured
   action type, never parse its prose.
4. **The per-company daily Operational Budget is additive with an explicit "unset".** Unset means
   "bounded only by the reserve and the cycle count", i.e. exactly today's behaviour, so no live
   contract changes meaning on the day the field lands. Set per company by the owner, with **no
   platform default** — it is ENFORCING, and Part 2.3's rule applies.
5. **Ordering, from M8-6's proven sequence:** Summit → Portfolio Watch → Trailhead, one at a
   time, negative control first. Summit is the right first subject for the same reason it was in
   M8-6: most history, and the operator-chosen ceiling that must not move.

**What migration does not do:** it does not answer whether `business_cap_usd` *should* be a
lifetime stock. That is the owner's open escalation and it stays open (Part 13.1). What this
design does is make both answers survivable: if the cap stays a stock, the financial ladder is
its correct mechanism and this design is complete; if the owner rules it windowed,
`business_cap_usd` becomes a per-company Operational Budget, 5.7's new row collapses into it,
and the Reserve concept survives with no field behind it until capital allocation lands.
**Either ruling leaves this architecture standing**, which is the property a design blocked on
an open escalation has to have.

---

## Part 6 — Operational Confidence

### 6.1 Approved, with the owner's fourth state

Revision 1 proposed three states. The owner's sixth direction adds a fourth:
**Current / Limited / Degraded / Blind.** Adopted, and it is a better design than revision 1's,
for a reason worth stating: three states forced two different kinds of imperfect knowledge into
one bucket.

The live record makes the case for the concept better than argument does. At 06:14 today the
platform failed every company simultaneously and every surface reported health (Part 0.1). Trace
*why*, mechanism by mechanism, because the answer is that nothing was broken:

- `reliability` counts unresolved dead letters. There were none — the cycles failed at planning,
  before dispatch. Reliability 100 is **correct**.
- `budget_headroom` reads settled spend. Nothing settled; all nine reservations released.
  Headroom unchanged is **correct**.
- `attainment` reads `kpi_values`. A failed cycle records none. **Correct.**
- The census aggregates those bands. healthy 2 / watch 1 is **correct**.
- The rollup reports $0 rolling 24h spend. **Correct** — $0 was spent.

Five components, five correct answers, and an operator who would have been told nothing. The gap
is not in any component's arithmetic. It is that **the platform has no representation of its own
operational state at all** — only of its companies' business state. Health answers "is this
company doing well?". Nothing answers "is Jarvis working right now?".

### 6.2 The four states

**A note the owner should read before ratifying.** The recorded direction names the four states
and does not record a definition for each. The definitions below are therefore **this document's
proposal, not the owner's words**, written to the axis the four names imply, and they are put
forward for ratification rather than attributed. Flagged as tension T4 (Part 13.9) precisely so
the wording is approved rather than assumed.

The axis the four names imply is a clean one, and it is *what kind of imperfection* the platform
has:

| State | Claim | Kind of imperfection |
|---|---|---|
| **CURRENT** | "I can see everything, and it is fresh." | none |
| **LIMITED** | "I can see everything, but not all of it is current." | knowledge is **incomplete** |
| **DEGRADED** | "I can see, and something I see is wrong." | knowledge is **bad news** |
| **BLIND** | "I cannot see." | knowledge is **absent** |

That is three different things revision 1 collapsed into "DEGRADED", and separating them changes
what an operator does: LIMITED means wait or refresh, DEGRADED means look, BLIND means the
platform itself needs attention before anything it says can be trusted.

**Precedence:** BLIND > DEGRADED > LIMITED > CURRENT. The worst true contributor names the
state.

### 6.3 The contributors — the non-arbitrary part

The design constraint that makes this safe rather than another number to distrust:
**contributors are booleans, enumerated in code, listed to the operator, and never weighted.**
This is D-039's census philosophy turned on the platform itself — the same argument that refused
a portfolio score refuses a confidence score, for the same reason: a weighted number over
incommensurable facts is comparable to nothing, and its only reliable effect is to make a bad
situation average out.

Closed set. Each a boolean over stored values, each independently falsifiable, each mapped to
the state it raises:

| # | Contributor | True when | Raises | Live now |
|---|---|---|---|---|
| C1 | `recent_cycle_failed` | any ACTIVE company's most recent recorded cycle did not complete successfully | DEGRADED | **true** (all three) |
| C2 | `inputs_stale` | an ACTIVE company's last recorded cycle is older than twice its wake period | LIMITED | false |
| C3 | `rollup_unreadable` | the last tick could not compute the rollup or census | BLIND | false |
| C4 | `stuck_work_present` | unresolved dead letters > 0 (§9) | DEGRADED | false |
| C5 | `approvals_aging` | a pending approval is older than §9's 24h re-notification | DEGRADED | **true** (4 rows, 2 days old) |
| C6 | `runway_unknown` | a company has a reserve and no recorded cycles | LIMITED | false |
| C7 | `executive_tick_stale` | no successful tick within N tick intervals | BLIND | **true** (never ticked live) |

**Live state right now: BLIND** — C7 is true because the Executive has never completed a tick
against the live database (zero `SPENDING` notices, zero platform Decision Log rows). That is the
correct reading and it is the design working on its first evaluation: the platform does not know
how its companies are doing, because the thing that would find out has never run.

**Three rules that keep it non-arbitrary**, in order of importance:

1. **BLIND is the startup state.** Not CURRENT. A confidence state that begins at CURRENT before
   its first successful tick is asserting knowledge it does not have — M7-F21's failure applied
   to self-knowledge, where an absence of readings became a reading. C7 makes this fall out for
   free.
2. **Contributors are listed, never counted.** The operator reads *which* contributors are true,
   in D-007 language. "Three contributors" is a score with extra steps.
3. **Confidence is reported beside the census and the two ladders, never folded into any of
   them.** Four signals, four meanings. Part 5.6's invariant, applied once more.

**Presentation, drafted in D-007's language** (rendering belongs to the operator-surface lane per
the M8 precedent; this is the vocabulary constraint, not the design):

| State | Operator sentence |
|---|---|
| CURRENT | "Everything's running." |
| LIMITED | "Some of this is out of date." |
| DEGRADED | "Something needs a look." |
| BLIND | "Jarvis can't check on your companies right now." |

Contributor lines, same register — "Every company's last round of work didn't finish"; "Nothing
has been checked for a while"; "Something is waiting for your OK"; "One company got stuck".
Never "wake cycle", never "business", never "the Executive Layer" — D-007 makes the actor
Jarvis, and `tests/surface_sources.FORBIDDEN` enforces it.

### 6.4 What Confidence must never become

- **Never a number.** The moment it is 0–100 it is a health score for the platform, and D-039's
  argument applies unchanged.
- **Never a gate.** Confidence describes; it does not refuse. A DEGRADED platform still runs.
  Making it a gate would create an automated pause with no owner-set parameter behind it — an L1
  action failing L1's own rule.
- **Never inferred from model output.** Every contributor is a query over stored values, and
  D-038's import rule keeps `jarvis.llm` out of the package that computes it.
- **Never silently extended.** The contributor set is closed, like D-032's type-parameter
  surface. Adding one changes what "CURRENT" means, so it is a decision, not a patch.

---

## Part 7 — The explainability standard

### 7.1 Nine fields

The owner's seventh direction inserts **AUTHORITY** as the fifth field — *"why is Jarvis allowed
to recommend this?"* Every judgment output the platform produces renders through one structure:

| # | Field | Answers | Source |
|---|---|---|---|
| 1 | **Observation** | what was seen | stored values, named with their windows (D-040) |
| 2 | **Reasoning** | which rule connected observation to action | a **rule identifier**, not prose (7.2) |
| 3 | **Evidence** | on what basis | `(source, value, window)` triples, each traceable to a store |
| 4 | **Confidence** | how sure, and about what | Part 6's state + the true contributors |
| 5 | **Authority** | **why Jarvis is allowed to propose this** | the Action Registry entry + the Policy Register key + its provenance head |
| 6 | **Action** | what is proposed | a declared `action_type` + stored parameters |
| 7 | **Expected outcome** | what should change if it works | a named stored metric and its projected value |
| 8 | **Risk** | what could go wrong | the stored downside (§8's fourth fact) |
| 9 | **Required approval** | who must say yes | the Approval Rule → the approval path |

**Fields 5 and 9 are adjacent and are not the same question**, and conflating them is the most
likely misreading of the nine-field structure. Field 5 answers *"by what right is Jarvis
recommending this at all?"* and renders from the Authority Level and the policy that grants it.
Field 9 answers *"who must consent before it happens?"* and renders from the Approval Rule. An
action can have unimpeachable authority to be *proposed* and still require the owner's answer
before it takes effect — that is the normal case for every L2-strategic action, and the two
fields together are what make it legible.

**Field 5 is why the nine fields and the lineage are one thing.** Fields 1, 2, 5, 6 and 9 are
the Observation, Inference, Authority, Recommendation and (pending) Execution nodes of Part 4's
proof tree, rendered. Field 3 is the Observation nodes enumerated. Adding AUTHORITY completed
the correspondence: **revision 1's eight fields could not render the proof tree, because the
tree has an Authority node and the structure had no field for it.** The owner's refinement did
not add a field to a list; it closed a gap between two of this document's own deliverables.

### 7.2 The field that would have broken it, and the fix

**Reasoning cannot be prose.** If a model authors field 2, D-011's threat model is reopened at
full strength: capabilities read untrusted external content, and attacker-influenced text would
sit between a portfolio state and a human authorising money. A nine-field structure whose second
field is free text is a beautifully organised D-011 violation.

> **Reasoning renders from a stored rule identifier plus the stored values that rule consumed.**
> The platform holds a closed set of rule identifiers, each with a fixed sentence template. The
> rule that fired is stored; the sentence is assembled deterministically.

The platform already does exactly this and has live proof it works: `BAND_COPY` in `alerts.py`
is a `dict[int, _BandCopy]` of fixed sentences selected by which band was crossed, with a
docstring recording *why* it is data beside the band — so a test can walk every sentence the
module can ever emit, including bands nothing has crossed. `DROPPED_WAKE_COPY` established the
same discipline for D-035. Field 2 is that pattern applied to judgment instead of to thresholds,
and the rule identifier is simultaneously Part 4's Inference node.

**Evidence has the same hazard and the same fix.** Field 3 is a list of triples, never a
paragraph. Each triple names a store the platform is permitted to read, the value read, and its
window. This makes evidence *checkable*: a reviewer can re-run the read. Prose evidence cannot
be re-run, which is what makes it not evidence.

**Authority has the hazard too, and it is the easiest to miss.** Field 5 must render from the
registry and the register, never from a sentence describing them. "Jarvis is allowed to do this
because it is an L2-strategic action granted at install under policy X, whose origin is Owner" is
assembled from four stored identifiers. If field 5 is ever authored rather than assembled, the
platform can claim an authority it does not have, which is worse than any other field being
wrong.

### 7.3 What the standard makes testable

1. **Every rendered field is reachable from stored columns.** A structural check that the
   renderer's inputs are all stored values — extending `test_operator_render.py`'s existing
   render-boundary discipline.
2. **The rule-identifier set is closed and its sentences are enumerable.** Walk every template;
   assert each is reachable from a rule id and each rule id has a template — the bidirectional
   form `test_design_system.py` uses for rail↔pane and `test_workflow_versioning.py` uses for the
   activity inventory.
3. **Field 5 resolves.** Every rendered Authority field's registry key exists in the Action
   Registry and its policy key exists in the Policy Register. A dangling authority claim fails
   the test.
4. **Every sentence passes §12.5.** `tests/surface_sources.py` is already the single source for
   the forbidden term list (M8-F115's consolidation); the templates join its inputs.

### 7.4 Scope, and the deliberate non-retrofit

**In scope now:** every judgment output the Executive Layer will ever produce, and — under the
owner's first condition — every judgment output any future business type produces, including
M10's trading recommendations. The structure is specified before the first proposal exists,
which is the only moment it is free.

**Not retrofitted:** the Manager's existing proposal path. Unification is scheduled for M10,
where Trading Analysis is the first type whose output is *inherently* a recommendation, so the
unification will have a real second instance to generalise from rather than one instance and an
assumption. M8-1's Part 0 recorded what happens when you generalise from one instance: you get a
framework shaped like that instance.

**One thing the standard must not become:** a required shape for *operator notifications*. A
notification is one sentence with a consequence. Nine fields in a notification is the thing
§12.5 exists to prevent. The standard governs judgment outputs the operator *decides on*, not
things they are *told*.

---

## Part 8 — Scaling review: M10 → M15

Four bottlenecks, each named with the milestone that hits it and the mechanism that gives way.

### 8.1 Platform-scoped approvals — the mechanism to draft (blocks M9's capital allocation, and M10)

This is the second open owner escalation. EXECUTIVE-LAYER.md 5.1 established that capital
allocation is designed and cannot be built: `ApprovalRequest.business_id` is required, A-003
namespaces every action type to a business *type*, and `declared_action_types`' docstring states
that a string outside a company's set authorises nothing. A reallocation belongs to two companies
and to neither.

**The mechanism the owner would approve, drafted:**

1. **A closed platform action-type registry** — now simply the L2-strategic section of Part 1.4's
   Action Registry: `platform.reallocate_capital`, `platform.set_kpi_target`,
   `platform.propose_retirement`. Frozen and enumerated, the way `PLATFORM_HALT_ACTION_TYPE`
   already is.
2. **A platform approval is a distinct row shape with `business_id` NULL** — the same NULL the
   Decision Log already uses for platform scope, and the same NULL
   `raise_platform_ceiling_alerts` already passes to `notify`. No new concept of scope is
   invented; the existing one is reused.
3. **It shares the rendering path and the operator queue.** D-011 unchanged. §8's four facts
   unchanged. The operator's experience of approving a reallocation is the experience of
   approving anything.
4. **Graduation is impossible because there is nowhere to count.**

   > **Platform approvals have no counter table.** `AutonomyCounterRow` is keyed
   > `(business_instance_id, action_type)`. A platform approval has no business instance, so
   > there is no row to advance, no row to set `graduated = True` on, and no schema in which one
   > could exist.

   The incidental guards still hold as defence in depth: `_advance_counter` returns early when
   `contract.autonomy_for(action_type)` is None (there is no contract at all);
   `capital_action = row.amount_usd is not None` refuses a reallocation, which always carries an
   amount; and — new in revision 2 — **the Action Registry's cross-constraint admits only
   `OWNER_APPROVAL` for L2-strategic**, so `GRADUATED` is not a value the entry can hold. **Four
   independent reasons, one of which is the absence of the mechanism itself.**
5. **The security boundary that must be reviewed, and is not this packet's to widen:** a platform
   approval is an authorisation with no derived identity behind it. D-002 makes identity derive
   from the Temporal workflow id, and a platform action has no workflow. Escalated (Part 13.3)
   rather than resolved — and it is the same gap as 1.7's missing L3 actor, arriving from the
   other side.

**Bottleneck named:** without this, §3.1's capital allocation, portfolio balancing, and
cross-business optimisation are all unbuildable — three of the Executive Layer's five stated
responsibilities. The largest blocker in the roadmap after M9.

### 8.2 The Executive budget sub-ceiling scales with N, and its current form does not (M10)

Manager-decided in the M9-1 round: an explicit sub-ceiling within D-003's platform scope, set at
Executive-enablement time, not a fifth scope. Correct, and it has a scaling problem better fixed
before it ships than after.

An Executive judgment cadence reads every company. Its cost is **O(N)**. A sub-ceiling expressed
as dollars-per-day is therefore an N-dependent constant, and the failure mode is the worst kind:
at N=3 it is generous, at N=30 the weekly cadence silently stops finishing, and nothing says so.

**The fix, free to adopt now:** express the sub-ceiling **per evaluation**, and make the number
of evaluations per period its own ENFORCING policy. Two numbers a human can reason about
independently — "each strategic review may cost this much" and "there may be this many" — where
one number conflates them and hides N inside itself.

### 8.3 Plugin governance: request, never possess (M10, and due before M10)

The owner's eighth direction, verbatim and constitutional:

> **Plugins may request authority. Plugins never possess authority. Authority is granted by
> installation.**

**This changes revision 1's design, and improves it.** Revision 1 had a type *declare* an
authority level on its `AutonomyPolicy`. Under the trichotomy the declaration is a **request**,
and the granted level lives in the platform's Action Registry, not in the contract at all. The
consequence is structural rather than cosmetic: **authority is not contract data**, so it cannot
be reached by any path that reaches contract data — not a refresh, not a migration, not a
malformed definition, not an operator edit.

**Shape.** `AutonomyPolicy` gains `requested_authority_level`, **with no default.** The absence
of a default is the whole mechanism — a default is precisely how "undeclared" becomes
"L2-tactical by accident", and the platform has a live instance of that failure mode:
`graduation_eligible: bool = True` (**M9-F115** → **M9-F130**).

**Validation at install**, joining the five checks `ProvisioningService.install` already
performs — a list that has grown by demonstrated need each time (M6-F10's wake loop, M7-F35's
self-measurement, M8-F111's unrefreshable upgrade), which is the precedent for adding more:

1. Every declared `action_type` carries a `requested_authority_level`. Undeclared →
   `ConfigurationError`, refuse the install.
2. The request is L2-tactical or lower. **A type may not request L2-strategic or L3 at all** —
   those are platform-owned, and requesting one is asking to create policy (Part 2).
3. A granted L2-tactical entry requires `graduation_eligible` explicitly set. Not defaulted, not
   inferred.
4. **Namespace enforcement — and the bypass it closes is live.** A-003 says an action type is
   namespaced to the business *type*. **Nothing enforces it.** `AutonomyPolicy.action_type`'s
   pattern is `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`, so a business type today may legally declare
   `platform.reallocate_capital` or `platform.circuit_breaker`, and both would validate, install,
   and enter `declared_action_types`. **M9-F116.** The fix is one comparison at install: the
   prefix must equal the type's own name, and `platform.` is reserved.

   Contained today — `platform_feed()` filters on `business_id IS NULL`, so a company's rows
   cannot masquerade as platform ones, and no platform approval path exists to confuse. But 8.1
   builds exactly that path, and building it against an unreserved namespace is how a plugin
   acquires a platform authority. **Reserve the namespace before the path exists.**
5. **The grant is written to the Action Registry, and a grant is an L3 act.** Which surfaces a
   tension the trichotomy creates: *"authority is granted by installation"*, and a type
   **upgrade** is an installation. So an upgrade could re-grant a different level. Band C freezes
   `autonomy_policies` on the *instance*; the registry is platform-side and Band C does not reach
   it. **M9-F133**, with the fix: a level change discovered at upgrade does not ride the refresh
   consent — it fails the install and requires the pinned-digest owner sign-off (Part 9.2).

**Bottleneck named:** M10's Trading Analysis is the first type whose action types are genuinely
judgment-shaped. If grants are not registry-side before it lands, M10 ships a type whose actions
have no recorded authority and the registry backfills them by inference — which is the autonomy
ratchet arriving through the front door.

### 8.4 The census, the tick, and the queue at N companies (M11, M13–M15)

**The tick is O(N) round trips at a fixed interval.** `compute_portfolio_rollup` performs three
reads per company plus one platform read; `compute_portfolio_health` performs three more plus a
cycle count. At N=3 that is roughly 21 round trips per 60-second tick — invisible. At N=100 it is
~700, and `tick_interval_seconds` is still 60.

The failure mode is what makes this worth naming: the runner has no-overlap protection (M9-1c),
so a tick that outruns its interval does not pile up — **it is skipped, silently.** The Executive
would simply run less often, with no signal.

Except that Part 6 supplies the signal for free: **C7 `executive_tick_stale`** is true exactly
when ticks stop landing, so the platform reports BLIND and says so. That interlock is the reason
to build Confidence *before* N grows, not after.

**The census names one company.** `worst_company` is a single display name. Correct at N=3; at
N=100, "Summit Trail Gear needs a look" out of a hundred is a score in disguise — one number's
worth of information wearing a name. **M9-F122.** Past roughly N=10 the census needs a severity
distribution rather than a single name. D-039 is not threatened: the rule is "no single portfolio
number", and a distribution is the opposite of one.

**The notification queue is O(N) for platform-wide conditions.** `has_unread` deduplicates per
`(business_id, kind, link_ref)`, so a condition true of every company produces N notices. At
N=100 a single platform event fills the queue. The rule, which the live code already follows: **a
platform-wide condition produces one platform-scoped notice** (`business_id=None`), never N
company-scoped ones. `raise_platform_ceiling_alerts` is the worked example. Make it the rule
before a second platform-wide condition is written.

**Milestone map:**

| Milestone | What it adds | What gives way first |
|---|---|---|
| M10 Trading Analysis | judgment-shaped action types; the first nine-field renderer outside the Executive | registry-side grants (8.3); the sub-ceiling's N-dependence (8.2) |
| M11 Additional types | N grows past ~10 | the census's single name (8.4); notification fan-out |
| M12 Live Trading | §8's hardest constraint becomes load-bearing | the Action Registry must be enforcing, not documenting (9.2); L5's reserved row may finally be needed (1.1) |
| M13–M15 | N grows past ~14 | the platform ceiling becomes the *first* binding constraint (**M9-F120**), inverting D-003 rule 3's intent |

That last row is the one nobody would predict from reading the code. D-003 rule 3 puts
per-business caps first and the platform breaker as a backstop, deliberately, so one runaway
company cannot halt healthy ones. Today that ordering is guaranteed by the ceiling being 20× any
single company's entire reserve. At ~14 companies operating at their permitted rate the guarantee
evaporates and the backstop becomes the front line — the precise arrangement D-003 rule 3 exists
to reject. **It is a dimensioning property masquerading as a design property**, and it will fail
quietly, as one company's refusal spreading to all of them.

---

## Part 9 — Safety review: preventative architecture

Six hazards, each with the mechanism that prevents it rather than the fix that would follow it.

### 9.1 Operator surprise

**The hazard.** The operator's model of what the platform is doing diverges from what it is
doing, and they discover the divergence from the consequence.

**Live instance.** 06:14 today (Part 0.1). Every company failed; every surface said healthy; the
operator paused and resumed a company ten minutes later with nothing to go on.

**Preventative mechanisms:**
- **Operational Confidence** (Part 6) — the platform reports its own state, and BLIND is the
  startup default so it never claims knowledge it lacks.
- **The two ladders reported separately** (Part 5.6) — a company that is operationally fine and
  financially Low says both, which is the live situation for all three companies today.
- **The financial ladder's Critical state** (5.4) — the last point at which raising a reserve
  prevents an interruption rather than repairing one.
- **The envelope rule** (1.6) — the platform can never surprise an operator by having *acquired*
  authority, because acquiring authority is not something it can propose.
- **Decision Lineage** (Part 4) — every recommendation answers "why" by reconstruction rather
  than by assertion.

### 9.2 Boundary ambiguity — the Action Registry

**The hazard.** An action's authority is decided implicitly, by which code path happens to reach
it, and two readers disagree about what the platform may do.

**Preventative mechanism.** A single frozen registry, closed-surface like D-032's type-parameter
list, now covering the whole platform (1.4):

```
ACTION_REGISTRY: Mapping[str, ActionEntry]
    action_type -> (level, approval_rule, audit_record, emitting_module)
```

Its guards, all in shapes the suite already proves:

1. **Bidirectional completeness.** Every action type the platform can emit appears in the
   registry, and every registry entry names an action type that exists. The pattern
   `test_workflow_versioning.py` uses for its frozen inventory of the nine schedulable
   activities, and `test_design_system.py` uses for rail↔pane.
2. **Cross-constraint validity.** Every entry's Approval Rule is admissible for its level
   (1.2's table). This is what makes "L2-strategic never graduates" and "L3 is never requestable"
   schema properties instead of review outcomes.
3. **The inheritance sweep.** 1.5's layers 1 and 2 — unique emit site, emitting module's level ≥
   the action's level, no forward emission.
4. **Pinned by digest.** The pin makes "any level change requires owner sign-off" mechanical.
   Changing a level fails the test; the message names the sign-off requirement and the D-entry;
   updating the pin is a visible, reviewable, single-line diff that cannot be mistaken for
   anything else. **This is also M9-F133's fix**: an upgrade that would re-grant authority
   changes the digest and therefore cannot ride a refresh consent.
5. **L4 and L5 are empty.** A test asserting no entry exists at either. Reserved levels that
   something quietly starts using are worse than no reserved levels.
6. **A negative control**, per M8-F120's discipline: a gate that has never failed is
   indistinguishable from a gate that cannot fail. The suite asserts a synthetic level downgrade
   is caught — `test_executive_import_boundary.py` already demonstrates the pattern in both
   directions, including proof the detector is not trigger-happy.

**Why a registry rather than a field on each policy.** A field is per-instance, so N contracts
carry N answers and drift is invisible until two disagree. A registry is one answer, in one
place, that a human can read end to end in a minute — and reading it end to end is the actual
governance act. The owner's plugin trichotomy makes this stronger than revision 1 could: under
"authority is granted by installation", the registry is not a mirror of contract data, it is the
*only* place authority exists.

### 9.3 Alert noise

**The hazard.** The operator learns to dismiss a category of notice, and the one that mattered is
dismissed with the rest.

**Live instance.** M9-F81: a lifetime breach never settles, so its notice can never stop being
true, and `has_unread`'s correct posture re-raises it after every dismissal — indefinitely.

**Preventative mechanism.** Part 5.5's decision, expressed as an invariant:

> **A persisting condition produces exactly one notification: the one announcing the transition
> into it. A recurring condition may notify per occurrence.**

Testable directly: given a condition held true across K evaluations, assert exactly one
notification for a ladder state and at most one per window for a band. The scripted multi-tick
proof `test_executive_runner.py` already performs for band dedup and once-per-halt is the same
shape, extended to states.

### 9.4 Silent policy creep — the Policy Register and the origin clause

**The hazard.** A number that governs what the platform may do drifts from owner-set to
developer-chosen, one reasonable edit at a time, and nobody can say who chose it or why.

**Live instances, four of them, before the Executive's judgment half exists at all:**
`max_cycles_per_day = 48` — **stored in all three live contracts, every one of them the Python
default** — `max_invocation_budget_usd = $0.50`, `graduation_eligible = True`, and the alert
bands as module constants (**M9-F123**).

**Preventative mechanism.** Part 3's register plus Part 2.3's four tests. Under revision 1 this
was a hygiene rule with a good argument behind it. Under the owner's definition it is the
constitution: a value whose Origin is `PLATFORM_DEFAULT` **is not a policy**, and the platform
enforcing it is enforcing something no one authorised. **M9-F130.**

The guard that would have caught all four:

> **No ENFORCING policy is a literal in `jarvis/`.** Every policy resolves to a `Settings` path
> or a defaultless contract field, and carries a permitted Origin.

An AST sweep over the Policy Register's rows. It fails today, three times, which is the right way
for a new guard to arrive: with a list of the debt it found.

### 9.5 Accidental autonomy ratchets

**The hazard.** Autonomy increases without anyone deciding it should. The subtle version is not a
bypass — it is a default, an inference, or a refactor.

**Live instance, and it is a default.** `AutonomyPolicy.graduation_eligible: bool = True`. A type
author who omits the field gets a graduation-eligible action. §8 says approval by default with no
exception at launch; this field defaults the other way. Two of the three live contracts carry
`graduation_eligible: true` with `graduation_threshold: 5`, and Summit's counter row is live at 0
consecutive approvals — the ratchet is armed, correctly at zero, and enabled by a default nobody
chose. **M9-F115** → **M9-F130**. The fix is one character of intent: no default, so a type must
say.

**The invariant, made mechanically checkable:**

> **Autonomy cannot increase accidentally: every increase is a diff a human approved.**

Five assertions under revision 2 — the fifth is new, and it is the owner's inheritance invariant
doing safety work:

1. **One writer.** An AST sweep asserts `AutonomyCounterRow.graduated = True` is assigned in
   exactly one place, and that place is `ApprovalService._advance_counter`. M1-R2's pattern —
   the structural test forbidding a bare `raise ScopeViolationError` outside `_deny` — applied to
   a privilege grant instead of a refusal. (**M9-F127**: the two guards in `_advance_counter` are
   correct and nothing asserts they are the only path.)
2. **Both guards present.** In that one function, the assignment is dominated by both
   `policy.graduation_eligible` and `row.amount_usd is None`. AST-level, in the shape
   `test_manager_determinism.py` already asserts every `execute_activity` carries a timeout.
3. **No L2-strategic or L3 entry can be graduation-eligible** — now a cross-constraint of the
   registry schema (1.2) rather than a separate assertion.
4. **The pinned autonomy inventory.** A frozen snapshot of every
   `(action_type → level, approval_rule, graduation_threshold)` across the built-in catalog and
   the platform registry, compared to the pin, failing on **any** difference — including a safe
   one.

   Failing in both directions is deliberate. A ratchet guard that fires only on dangerous changes
   lets the pin rot on safe ones, and a rotted pin catches nothing. **The asymmetry belongs in
   the message, not the trigger:** a change that lowers required authority, enables graduation,
   or lowers a threshold reports *"this increases autonomy — owner sign-off required (§15,
   D-043)"*; a change in the safe direction reports *"update the pin"*. Every change is
   deliberate; only one kind is escalated.
5. **No upward emission.** 1.5's static sweep. This is the assertion revision 1 could not make,
   because revision 1 had no platform-wide registry to compare a module's level against. It
   catches the ratchet's quietest form: a module that acquires one high-authority responsibility
   and carries that authority into the low-authority paths it already had.

### 9.6 Plugin bypass

**The hazard.** A business type acquires an authority the platform never granted it, by declaring
data the platform trusts.

**Live instance.** A-003's namespace rule is unenforced: a type may declare `platform.*` action
types today and they validate and install (**M9-F116**, 8.3).

**Preventative mechanisms**, in order of strength:
- **Authority is not contract data at all.** The owner's trichotomy — request, never possess,
  granted by installation — means there is no field on a contract that carries authority, so no
  path that reaches contract data can alter it. This is strictly stronger than revision 1's
  declared-level design and it is the single most valuable of the six refinements.
- **Namespace enforcement at install** — the prefix must equal the type's own name; `platform.`
  is reserved. One comparison, refusing at install rather than at first approval.
- **An undeclared request refuses the install** — no default (8.3).
- **A type may not request L2-strategic or L3 at all** — requesting one is asking to create
  policy, which Part 2 forbids categorically.
- **A re-grant at upgrade fails the pinned digest** (M9-F133, 9.2 guard 4).
- **The existing four-layer Band C guard is untouched.** `autonomy_policies` and `graduation` are
  Band C, so a type upgrade cannot alter an existing company's autonomy at all. That guard is
  real (M8-4's audit verdict: "four-layered and real") and nothing here widens it — Part 5.7 keeps
  additivity precisely so it need not be.

---

## Part 10 — Drafted amendments — **the ratification package**

**Drafted, never written.** The spec is owner-held and this document does not edit it. Under the
owner's review these texts return for **final ratification**, so each is presented as approvable
wording with its classification, and every clause the owner dictated appears verbatim.

### 10.1 New §15 — The Authority Model *(constitutional)*

> **§15.1 Authority levels.** Every executable action the platform can take belongs to exactly
> one authority level, determined by its action type. This applies to the Executive Layer,
> Business Managers, business types and their plugins, workflows, scheduled services, tools, and
> every present or future integration. No executable action is outside this model.
>
> **L0 — Deterministic computation.** Computes and reports over stored values. MUST NOT write to
> a Standard Business Contract, call a model, or produce an external effect.
>
> **L1 — Rule execution.** Executes a frozen rule against owner-set parameters. MUST be audited
> on every firing. Code MUST NOT determine a parameter's value; policy MUST.
>
> **L2 — Judgment proposal.** MAY propose; MUST NOT enact. Every L2 output reaches effect only
> through §8 approval. **L2-tactical** actions exercise judgment within a company's existing
> contract and MAY graduate under §8's ladder. **L2-strategic** actions — those that would change
> a company's contract or the portfolio's allocation — **MUST NOT be eligible for autonomy
> graduation under any configuration.**
>
> **L3 — Owner only.** Policy creation, ceilings and windows, autonomy grants, authority-level
> changes, specification changes, credentials, and new integrations. The platform MUST NOT take
> an L3 action and MUST NOT propose one.
>
> **L4 and L5 are reserved.** No action may be registered at either until this section assigns
> them meaning.
>
> **§15.2 Policy, and the policy-execution principle.**
> **A policy is a durable owner-authorized constraint that determines what actions are
> permitted, required, or prohibited. Policies may only originate from: Owner, Approved
> specifications, Approved configuration. No model output shall become policy without explicit
> owner authorization.**
> No automated component of the platform may create policy. The Executive Layer MAY execute
> policy; the Executive Layer MUST NOT create policy. Every policy MUST carry provenance
> (§15.8) and MUST be recorded in a register the platform validates against.
>
> **§15.3 The envelope rule.** An L2 proposal MAY propose an allocation within an owner-set
> envelope. It MUST NOT propose a change to the envelope itself.
>
> **§15.4 The Action Registry, and plugin authority.** Every action type the platform may take
> MUST appear in a platform-owned registry recording its **Authority Level, Approval Rule, and
> Audit Record**. An action type absent from the registry MUST NOT execute.
> **Plugins may request authority. Plugins never possess authority. Authority is granted by
> installation.** A business type MUST NOT request an authority level above L2-tactical. An
> action type presented for installation without a requested authority level MUST refuse
> installation. A change to a granted authority level requires owner authorization and MUST NOT
> ride a configuration-refresh consent.
>
> **§15.5 The never-autonomous list.** [Part 1.3's ten items, enumerated.]
>
> **§15.6 Inheritance.** **Authority is inherited downward and never upward.** A holder of a
> higher authority level MAY perform the actions of every lower level. A holder of a lower level
> MUST NOT perform the actions of a higher one. Escalation occurs only through explicit approval.
>
> **§15.7 Decision Lineage.** Every recommendation MUST be reconstructable as a proof tree:
> **Observation → Inference → Policy → Authority → Recommendation → Execution.** Lineage nodes
> MUST be stored identifiers, never generated text. A recommendation whose lineage is incomplete
> MUST NOT be presented for approval.
>
> **§15.8 Provenance.** Every governed value — goal, policy, budget, threshold, rule, and limit —
> MUST carry provenance: **Origin → Modified By → Approved By → Executed By.** A value whose
> origin is not one of §15.2's three permitted origins is not policy and MUST NOT be enforced as
> one.

*Classification: constitutional.* Adds a section; contradicts no existing MUST. §15.1's
L2-strategic clause generalises §8's existing hard constraint on capital actions rather than
replacing it. §15.2's definition is the owner's, unchanged; see Part 2.4 on the "required" clause
having no mechanism today.

### 10.2 Amendment to §3.1 *(constitutional)*

> Add: The Executive Layer's strategic responsibilities are exercised as proposals under §15.2
> and §15.3, and are L2-strategic under §15.1. The Executive Layer MUST NOT enact a capital
> allocation, KPI target change, or retirement without approval under §8, and these actions MUST
> NOT graduate.

### 10.3 Amendment to §8 *(constitutional; security boundary — security-engineer review)*

> Add: An approval MAY be platform-scoped, belonging to the platform rather than to a single
> business. A platform-scoped approval carries no graduation counter and MUST NOT graduate under
> any configuration. Its action type MUST come from the platform's own registry (§15.4) and MUST
> NOT be requestable by a business type.

*Why:* the second open owner escalation (Part 8.1). *Not this packet's to make* — it widens the
approval path's identity model (Part 13.3).

### 10.4 Amendment to §5 *(architecture)*

> Add to the Standard Business Contract: an **Operational Budget** — a spending ceiling per
> rolling window, recovering automatically on rollover — distinct from the **Capital Reserve** —
> a lifetime allocation recovering only by owner decision. Each autonomy policy MUST declare a
> *requested* authority level; the granted level lives in the registry of §15.4 and is never
> contract data. Neither ceiling MAY carry a platform default.

### 10.5 Amendment to §12.5 *(architecture; operator-visible)*

> Add: The operator MUST be able to determine (a) whether the platform is currently able to
> observe its companies, and (b) for each company, its operational state and its financial state
> **separately**. Each is presented as a state, never as a score, and its contributing reasons are
> listed rather than summarised.

*Why:* Parts 5.6 and 6, and §12.5's own completeness gate. Adds operator-visible concepts beyond
D-007's table → **escalation** (Part 13.2).

### 10.6 Amendment to §11.5 *(architecture)*

> Add: The Decision Log records the operator's narrative. Decision Lineage (§15.7) records the
> proof, as identifiers. Neither substitutes for the other, and lineage MUST NOT be used as a
> second execution history — Temporal's event history remains the replay substrate.

*Why:* Part 4.6, and the D-004 tension (T7).

### 10.7 D-007 table additions *(wording; reversal cost none)*

| Technical term | Operator-facing term |
|---|---|
| Operational Confidence | "Everything's running" / "Some of this is out of date" / "Something needs a look" / "Jarvis can't check on your companies right now" |
| Operational state (ladder) | "Running normally" / "Watch today's spending" / "Doing less today to stay in budget" / "Stopped until tomorrow" |
| Financial state (ladder) | "Running normally" / "Getting low on budget" / "Almost out of budget" / "Out of budget — only you can add more" |
| Authority level | (invisible — "what Jarvis can do on its own", already D-007's autonomy row) |
| Decision Lineage | (invisible — surfaced only as "how Jarvis worked this out") |

---

## Part 11 — Drafted D-entries

Drafted for the Manager to write into `docs/DECISIONS.md` as their mechanisms land. **Not written
here.** D-042 is held pending owner escalation 2, so these begin at D-043. Revision 2 keeps
revision 1's numbering for the eight that carry over and adds two.

- **D-043 — authority is a property of every executable action, and every action is registered.**
  Four levels (L0 / L1 / L2 / L3, L4–L5 reserved), L2 split tactical (graduates per §8) versus
  strategic (never graduates, has no counter). Every action carries the four-tuple **Action →
  Authority Level → Approval Rule → Audit Record**, each field from a closed set, with
  cross-constraints that make "L2-strategic never graduates" and "L3 is never requestable" schema
  properties rather than review outcomes. **Authority is inherited downward and never upward**,
  checked statically by unique-emit-site and no-forward-emission sweeps and, once an execution
  context carries a level, at runtime by refuse-and-audit. Keyed to actions rather than components
  because components get refactored and A-003 already makes the action type the unit of
  authorisation. *Reversal cost: medium — bookkeeping over existing behaviour, but every future
  action is written against it.*

- **D-044 — policy is owner-originated; the platform executes it and may not create it.** The
  owner's definition governs (§15.2, verbatim). Revision 1's effect test survives as the
  *classification* step — is this a policy? — and the owner's origin clause is the *admission*
  rule — may this be one? The envelope rule is the operative half: an approval loop the platform
  can initiate is an autonomy ratchet with a human in it, and the defence is that the proposal
  cannot be generated. Binds every automated component, not only the Executive.
  *Reversal cost: low to record, high to reverse once §3.1's responsibilities are built on it.*

- **D-045 — an Operational Budget and a Capital Reserve are different architectures, with
  different ladders.** A budget is a flow: windowed, automatically recovering, ladder Healthy →
  Warning → **Limited** → Halted, where Limited names the already-shipped condition of a scope
  refusing some work while the company still runs (`BUDGET_EXHAUSTED`). A reserve is a stock:
  lifetime, recovering only by owner decision, ladder Healthy → Low → **Critical** → Exhausted,
  where Low is `runway_cycles < max_cycles_per_day` and Critical is
  `lifetime_headroom_usd < wake_cycle_ceiling_usd` — comparisons of existing numbers, not invented
  percentages. **The two are reported separately and never combined into one word.**
  *Reversal cost: medium — additive, no migration, and it survives either ruling on the open
  cap-window escalation.*

- **D-046 — a persisting condition is a state, announced once; a recurring condition is an
  alert.** Resolves M9-F81. Transitions write one audit record and one Decision Log entry each;
  current state is re-derived on read, never stored (M8-F109's ratified posture).
  *Reversal cost: low.*

- **D-047 — Operational Confidence is a four-state ladder with listed contributors, never a
  score.** Current / Limited / Degraded / Blind over seven enumerated boolean contributors, listed
  to the operator, never weighted; precedence Blind > Degraded > Limited > Current. **Blind is the
  startup state**, because a confidence that begins Current asserts knowledge it does not have.
  Reported beside the census and the two ladders, never folded into any of them. Never a gate.
  *Reversal cost: low.*

- **D-048 — every governed value carries provenance: Origin → Modified By → Approved By →
  Executed By.** Origin is one of five recordable values, of which three are permitted for policy;
  `PLATFORM_DEFAULT` and `TYPE_DEFINITION` are recordable and not permitted. **Provenance splits
  into a static head stored beside the value and a dynamic tail that is a lineage node** — one
  structure seen from two ends, meeting at the Policy node. One register in three sections: Policy,
  Parameter, Goal. Generalises `RuntimeIdentity._source` (M1-R1), which has stamped provenance
  into audit records since M1 for exactly this reason. *Reversal cost: low; it constrains where
  values live and what is recorded beside them, not what they are.*

- **D-049 — a platform-scoped approval has no counter, and therefore cannot graduate.**
  `business_id` NULL, action type from the registry's L2-strategic section, sharing D-011's
  rendering and the operator queue. Graduation is impossible because `AutonomyCounterRow` is keyed
  `(business_instance_id, action_type)` and there is no business instance — the mechanism that
  would have to exist does not. Three further guards hold as defence in depth, one of them now a
  registry cross-constraint. **Gated on owner escalation 2 and security-engineer review of the
  identity question.** *Reversal cost: high — it is a security boundary.*

- **D-050 — plugins request authority; they never possess it; installation grants it.** The
  granted level lives in the platform's Action Registry and is **never contract data**, so no path
  that reaches contract data can alter it. `AutonomyPolicy` gains `requested_authority_level` with
  **no default**. A type may not request above L2-tactical. **A-003's namespace rule becomes
  enforced**: the prefix must equal the type's own name and `platform.` is reserved (M9-F116). A
  level change discovered at upgrade fails the install and requires owner sign-off rather than
  riding a refresh consent (M9-F133). *Reversal cost: low-medium — one field, one validation, one
  namespace comparison, one registry partition.*

- **D-051 — Decision Lineage is a proof tree of stored identifiers, and an incomplete lineage
  blocks an approval.** Six node types — Observation, Inference, Policy, Authority,
  Recommendation, Execution — each a reference into an existing identifier space, with **no text
  column anywhere in the schema**, which is what makes D-011 hold by construction. Stored as one
  append-only table with a parent pointer (a DAG for the price of a nullable integer);
  reconstruction is one ordered query, and verification is resolving each reference in its own
  store, so a lineage that names a row which does not exist is a *detectable* lie. Anchors on
  `ApprovalRow.decision_ref`, which has existed and had zero readers since M3 (M9-F136). **Not a
  replay engine** — D-004 unchanged. *Reversal cost: medium — one migration, and every L2 path is
  written against it.*

- **D-052 — the nine-field structure is the platform's judgment-output standard.** Observation →
  Reasoning → Evidence → Confidence → **Authority** → Action → Expected outcome → Risk → Required
  approval. **Reasoning renders from a stored rule identifier**, never prose (the `BAND_COPY`
  pattern), which is also the lineage's Inference node; Evidence is `(source, value, window)`
  triples, never a paragraph; **Authority renders from the registry and the register, never from a
  sentence describing them** — an authored authority claim is worse than any other field being
  wrong. Fields 5 and 9 answer different questions ("by what right propose?" versus "who must
  consent?"). **The nine fields are the lineage rendered.** Manager-path unification scheduled for
  M10, not retrofitted. *Reversal cost: low to adopt, high to change once two producers exist.*

---

## Part 12 — The deferred-M9 implementation strategy

The ordering principle is unchanged and is the whole argument:

> **Every governance mechanism ships before the capability it governs.** A registry written after
> the actions it registers is an inventory; written before, it is a gate. This is the only
> sequencing rule that distinguishes preventative architecture from documentation.

### 12.1 What the owner's conditions changed in the plan

Revision 1's G1 was four small packets. Under platform-wide authority, **three of the four grow
and one is unchanged**, and two new packets appear. The wave structure holds; the sizing does not.

| Revision 1 | Revision 2 | Change |
|---|---|---|
| G1a Authority Registry (11 Executive-adjacent actions) | **G1a Action Registry — platform-wide** (~25 actions) + the four-tuple cross-constraint test | **grows**; the enumeration is now the whole platform and the cross-constraints are new |
| — | **G1a′ the inheritance sweep** (1.5 layers 1–2) | **new**; could not exist in revision 1, which had no platform-wide registry to compare a module's level against |
| G1b Parameter Register | **G1b Policy / Parameter / Goal Register with provenance heads** + the owner's four tests | **grows**; provenance applies to everything, and the tests become constitutional rather than hygienic |
| G1c ratchet test (4 assertions) | **G1c ratchet test (5 assertions)** | **grows by one** — "no upward emission"; now depends on G1a |
| G1d namespace enforcement | G1d namespace enforcement | **unchanged**, and still must precede any platform-approval path |
| — | **G1e registry partitioning** (platform partition pinned; installed partition drift-detected — M9-F138) | **new**; falls out of "authority is granted by installation" |

G1 still changes no behaviour except refusing things the platform currently permits. It remains
the cheapest wave in the plan and the one that must not be resequenced behind anything — and
under the owner's definition its findings are now rule violations rather than untidiness, which
raises its priority rather than its cost.

### 12.2 The waves

**Wave G1 — governance skeleton. No new capability.**
G1a Action Registry + cross-constraints · G1a′ inheritance sweep · G1b registers + provenance
heads + the four policy tests (closes M9-F117/F130) · G1c ratchet test (closes M9-F115, M9-F127)
· G1d namespace enforcement (closes M9-F116) · G1e registry partitioning (closes M9-F138).

**Wave G2 — self-knowledge. Ships the answer to 06:14.**
G2a Operational Confidence, four states · G2b the two ladders replacing the cap's percentage
bands (closes M9-F81) · G2c the operator surface for both, **rendered separately** (M9-F137) —
operator-surface-engineer, product-reviewer gated, coordinating with packet E's census tile.

**Wave G3 — explanation, before the first judgment output exists.**
G3a Decision Lineage: the table, the node vocabulary, the incomplete-lineage invariant, the
`decision_ref` anchor (closes M9-F136; needs M9-F135's Execution-node ruling first) —
data-engineer, one migration. G3b the nine-field renderer: rule-identifier vocabulary, evidence
triples, the Authority field resolving against G1a's registry, the four tests. G3c
`requested_authority_level` + install validation + catalog backfill.

G3a and G3b ship together or not at all: the nine fields are the lineage rendered, and a renderer
without a lineage is a form, while a lineage without a renderer is a table nobody reads.

**Wave G4 — gated, in dependency order:**

| Deferred item | Gate | Unblocks |
|---|---|---|
| Platform-scoped approvals (D-049) | **owner escalation 2** + security-engineer on identity (13.3) | capital allocation, portfolio balancing, cross-business optimisation |
| Capital allocation (EXECUTIVE-LAYER 5.1) | the above, plus G3 | §3.1 |
| Executive budget sub-ceiling, **per evaluation** (8.2) | Manager-decided; needs an owner-visible surface | the judgment cadences |
| Judgment cadences (M9-F4) | the sub-ceiling, **and a home** — M9-F132 says it is not `jarvis/executive/` | weekly/monthly strategic review |
| KPI target setting | **M8-F6** — lands with per-field refresh provenance, never before (G1b makes the collision detectable) | §3.1 target setting |
| Per-company daily Operational Budget (5.7) | none — additive, defaults to today's behaviour | the missing flow control |
| Per-model cost tracking (M9-F5) | its own evidence; deliberately not a rider | accurate reserve arithmetic |

### 12.3 The three dependencies worth stating separately

1. **The cap-window escalation (13.1) does not block any of this.** Part 5.7 was designed so both
   rulings leave the architecture standing. Do not wait on it.
2. **M8-F6 and Executive target-setting are one event arriving from two directions**
   (EXECUTIVE-LAYER 5.2). Provenance changes this from a sequencing constraint into a detectable
   collision (Part 3.3), but detection is not resolution: the two still land together.
3. **The judgment half needs a package before it needs a budget.** M9-F132: D-038's import rule
   forbids `jarvis.llm` in `jarvis/executive/`, so L2-strategic *generation* has nowhere to live.
   Deciding that home is a dependency-graph question and belongs in a packet before the cadences,
   not inside one.

**Sizing, packet count, and lane assignment are the Manager's.** The dependency edges above are
this document's contribution.

---

## Part 13 — What this document does not decide

### 13.1 – 13.8 Escalations and deliberate non-decisions

1. **The window semantics of `business_cap_usd` (OWNER ESCALATION, open since M9-1, re-surfaced
   per D-037).** Part 5 gives the concept and Part 5.7 makes both rulings survivable. It does not
   rule which a spending limit ought to be, because that changes what a limit *means to the
   operator*. New evidence: all three live companies hold under one day of permitted work in
   reserve (**M9-F119**) and all three evaluate as financially **Low** under the owner's own
   ladder (5.4).
2. **Confidence and the two ladders are new operator-visible concepts (ESCALATION).** §12.5's
   completeness gate and D-007's table are the constraint; Part 10 drafts wording and does not add
   rows. The argument for approving: none of it is new *behaviour* — the platform already goes
   blind, already runs Limited, already sits financially Low, and does all three silently.
3. **Platform-scoped approvals widen the identity model (ESCALATION, security).** D-002 derives
   identity from the Temporal workflow id; a platform action has no workflow. D-049's mechanism is
   drafted and its graduation-impossibility is structural, but *who authorised this, derived how*
   is unanswered. Security-engineer review with an owner-visible argument.
4. **L3 actions have no actor identity to audit (ESCALATION).** 1.7: the platform-wide registry
   has six L3 rows, all requiring `ACTOR_IDENTITY`, and every L3 path today passes `"platform"` or
   `"operator"`. This is the same gap as 13.3 seen from the other side, and it is the largest
   structural hole this document leaves open. Part 3's provenance shape is designed so the field
   exists and is honestly empty.
5. **Whether `affiliate.publish_post` should remain graduation-eligible.** L2-tactical and
   graduating by design; live threshold 5; counter at 0. This document explains why that is
   *coherent*; it does not rule whether it is *desired*.
6. **Any change to D-009's formula, D-039's census rule, or D-011's rendering.** Confidence and
   the ladders sit beside health and never inside it; the nine fields extend D-011's stored-values
   principle and never relax it.
7. **The severity distribution that replaces `worst_company` past N≈10** (M9-F122). Named with its
   threshold; the replacement is a product decision for the milestone that reaches it.
8. **Per-model cost tracking (M9-F5, unchanged).** Still homed here, still deferred: replacing a
   conservative bound with real rates can only let *more* spend pass a ceiling check. Part 5's
   cost-per-cycle figures are over-stated by construction, which is the safe direction and is
   stated rather than smoothed.

### 13.9 Tensions between an owner direction and an existing invariant

Flagged, never silently resolved. Eight, of which T3 and T6 are load-bearing.

| # | Owner direction | Meets | Nature | Handling |
|---|---|---|---|---|
| **T1** | the policy definition (origin-based) | revision 1's effect-based definition | not a conflict — different questions | composed in Part 2.1: effect classifies, origin admits. Recorded so the reconciliation is visible rather than assumed. |
| **T2** | "permitted, **required**, or prohibited" | **§14** (no speculative features) | the platform has no obligation mechanism at all | §15.2 carries the owner's wording unchanged with "required" **reserved**; no mechanism invented. **M9-F131.** |
| **T3** | "authority is inherited downward" | **D-038**'s import rule | *may* versus *can*: L2-capable does not mean permitted to import `jarvis.llm` | both stand; the consequence is that L2-strategic **generation** cannot live in `jarvis/executive/`. **M9-F132**, and it is a dependency-graph decision before the cadences, not inside them. |
| **T4** | "Confidence gains a fourth state… owner's definitions" | the record | the four names are recorded; **per-state definitions are not** | Part 6.2's definitions are proposed by this document and explicitly **not attributed** to the owner. Ratify the wording. |
| **T5** | L4/L5 reserved | **§15.6** (inheritance) | a *constraint* tier (a rule binding even the owner) inherits the wrong way — "L5 may perform L3's actions" is incoherent if L5 is a regulator | L4/L5 reserved as **capability** tiers (delegated human, then multi-party). Regulatory constraints route through `compliance_requirements`, which already binds by construction (D-027.5, owner-signed, injected verbatim). Recommendation, not a decision. |
| **T6** | "authority is granted by installation" | **D-029/D-030** (Band C, refresh consent) and **D-031** (version gate) | a type *upgrade* is an installation, so an upgrade could re-grant authority; Band C protects the **instance**, not the registry | a level change at upgrade **fails the install** and requires the pinned-digest owner sign-off; it never rides a refresh consent. **M9-F133.** |
| **T7** | Decision Lineage | **D-004** (Temporal history is the replay substrate) | a second durable "what happened" store is a correctness hazard, not redundancy | lineage is a *justification* index, stores why and not what-next, and §11.5's amendment says so explicitly (10.6). **M9-F135** records the one gap: L1 actions have no execution identifier. |
| **T8** | "authority granted by installation" | **9.2 guard 4** (registry pinned by digest) | a registry that grows at install time cannot be wholly pinned at build time | two partitions: the **platform partition** (code, pinned) and the **installed partition** (rows, guarded by install-is-L3 plus D-031's existing digest drift detection). **M9-F138.** |

---

## Part 14 — Findings

Revision 1's findings M9-F115…F129 stand. Three are **re-classed** by the owner's policy
definition — from hygiene to rule violation — and are consolidated under M9-F130.

| # | Finding |
|---|---|
| **M9-F115** | `AutonomyPolicy.graduation_eligible` defaults to `True`. §8 requires approval by default with no exception at launch; this field defaults the other way. Live on two of three companies (threshold 5, counter at 0). *Re-classed by M9-F130.* |
| **M9-F116** | A-003's namespace rule is unenforced. A business type may legally declare `platform.reallocate_capital` or `platform.circuit_breaker`. `platform.` is a de-facto reserved namespace (three live uses) with no reservation. Contained today; a live bypass the moment platform-scoped approvals exist. |
| **M9-F117** | Two ENFORCING budget parameters carry code defaults — `max_cycles_per_day = 48` and `max_invocation_budget_usd = $0.50`, the latter D-003's innermost debit scope — while the two the spec insisted be explicit correctly carry none. *Re-classed by M9-F130.* |
| **M9-F118** | **2026-07-28 06:14:46–06:14:53: all three companies woke and all three cycles failed.** Nine reservations opened and released, $0 settled, one Decision Log entry each. Zero notifications, zero dead letters, reliability 100, bands unchanged, census unchanged. Five components each correct; the operator told nothing. |
| **M9-F119** | Every live company's entire Capital Reserve is under one day of permitted work: Trailhead 0.36 days, Portfolio Watch 0.51, Summit 0.71, at $0.7647/cycle against `max_cycles_per_day = 48`. |
| **M9-F120** | The $500/24h platform ceiling is 54× the busiest day the platform has ever had and first becomes binding at ≈13.6 companies. D-003 rule 3's ordering holds by dimensioning, not by design, and inverts quietly at scale. |
| **M9-F121** | The Executive tick is O(N) round trips at a fixed 60s interval (≈21 at N=3; ≈700 at N=100); the runner's no-overlap protection makes the failure mode silently skipped ticks. Confidence contributor C7 is the interlock that makes it visible. |
| **M9-F122** | `PortfolioHealth.worst_company` names exactly one company — correct at N=3, a single number wearing a name at N=100. |
| **M9-F123** | `SPEND_BANDS` and `PLATFORM_BANDS` are module constants, not config. ANNOUNCING, so not policy — but Parameter Register rows regardless. |
| **M9-F124** | `decision_log` still holds **zero** platform-scoped rows. The halt narrative is written, wired, and unproven against live data. |
| **M9-F125** | No notification kind represents operational health; `SPENDING` has never been written live. |
| **M9-F126** | The financial ladder's Low state is uncomputable for a company with no recorded cycles (`runway_cycles is None`). The absent case is a Confidence contributor (C6), not a ladder state — the two mechanisms interlock rather than one papering over the other. |
| **M9-F127** | `_advance_counter`'s two guards are correct, and **nothing asserts they are the only path to `graduated = True`.** The privilege grant has no structural guard where the refusal path has had one since M1-R2. |
| **M9-F128** | The census reports never-measured companies separately but counts a company whose *last cycle failed* as healthy. Live at 06:14 today, in triplicate. |
| **M9-F129** | No per-company windowed spending control exists. The only thing between a company and its whole reserve is a cycle count, which bounds frequency rather than cost. |
| **M9-F130** | **Under the owner's policy definition, the platform is enforcing three constraints that are not legitimate policy.** `max_cycles_per_day = 48`, `max_invocation_budget_usd = $0.50` and `graduation_eligible = True` all have Provenance Origin `PLATFORM_DEFAULT`, which is not one of the three permitted origins. Worse than revision 1 recorded: **`max_cycles_per_day = 48` is not merely a code default, it is stored in all three live contracts** — read from the stored JSON today — so the platform has persisted a policy value nobody authorised into the operator's own data. Re-classes M9-F115 and M9-F117 from hygiene to rule violation. |
| **M9-F131** | The owner's definition covers actions that are **required**. The platform has no obligation mechanism: every control is a gate, a ceiling, or a refusal, and the nearest analogue (compliance requirements) is a set of prohibitions and conditions. §15.2 keeps the wording; the mechanism is reserved, not invented (§14). |
| **M9-F132** | **The judgment half cannot live in `jarvis/executive/`.** D-038's import rule forbids `jarvis.llm` there, and L2-strategic *generation* needs it. Being L2-capable is permission, not capability. Naming the sibling package now is what prevents D-038 being widened later to accommodate the first cadence. |
| **M9-F133** | "Authority is granted by installation" means a type **upgrade** is a grant. Band C freezes `autonomy_policies` on the instance; the Action Registry is platform-side and Band C does not reach it. A re-grant at upgrade must fail the install and require owner sign-off, never ride a refresh consent. |
| **M9-F134** | **The platform has no execution-context authority level.** The downward-inheritance invariant's runtime layer therefore has nothing to compare against; only the two static layers are buildable today. Recorded so the runtime check is scheduled with the registry's first consumer rather than assumed present. |
| **M9-F135** | Decision Lineage's Execution node has no identifier for an **L1** action: the breaker trip, a band notice, a refused reservation execute with no approval and no minted id. Recommendation: use the audit record's own row id, which exists by construction for exactly the set of actions that need it. |
| **M9-F136** | `ApprovalRow.decision_ref` is written by `ApprovalService.request`, persisted as a 64-character column, and has **zero readers anywhere in `jarvis/`** — the M7-F21 / M8-F8 / M9-F1 shape for the fourth time. It is also precisely the anchor Decision Lineage needs. A deferred-completion ledger row is owed under `docs/DEPENDENCIES.md`'s own rule. |
| **M9-F137** | No surface can show the operational and financial ladders separately. Everything spending-related renders today as one "spending" concept, so the live situation — all three companies operationally Healthy and financially Low — is unrepresentable. |
| **M9-F138** | The Action Registry cannot be wholly pinned by digest once plugins install at runtime, because "authority is granted by installation" makes the registry grow. It needs two partitions with different guards: platform (code, pinned) and installed (rows, install-is-L3 plus D-031's existing drift detection). |
| **M9-F139** | **Provenance is not one record.** Origin, Modified By and Approved By are properties of a value; **Executed By is a property of each use**. Storing Executed By as a field would answer "who used this most recently" while appearing to answer "who has used this" — a schema that cannot hold its own definition. It resolves into a static head beside the value and a dynamic tail that is a lineage node. |

---

## Part 15 — Verified versus written

Per the project's standing discipline (M5-F5), stated explicitly.

**Verified by execution, read-only, 2026-07-28:** every figure in Part 0.1 and Part 5.2, and the
ladder evaluations in 5.4. The rollup and census were produced by running the platform's own
`compute_portfolio_rollup` and `compute_portfolio_health` against the live database; the health
scores by `KpiEngine.health`; the stored `max_cycles_per_day = 48`, `wake_conditions` and
`budget` values by reading the three contracts' JSON directly; everything else by direct SQL. The
06:14 event is reconstructed from `budget_ledger` and `decision_log` rows, not inferred. Nothing
was written. $0 spent.

**Read but not executed:** all source-level claims about `alerts.py`, `runner.py`, `rollup.py`,
`health.py`, `contract.py`, `provisioning.py`, `breaker.py`, `approvals/service.py`,
`persistence/models.py` and the executive import-boundary test — read directly, cited by
mechanism, not run beyond the read-only calls above. `decision_ref`'s zero readers were
established by search across `jarvis/` and `tests/`.

**Written, not verified:** every mechanism this document proposes. No test in Part 9 exists; the
Action Registry, the Policy/Parameter/Goal Register, Decision Lineage's table, both ladders,
Operational Confidence, the nine-field renderer, `requested_authority_level` and the namespace
check are all design. **The findings are verified; the remedies are drafted.**

**Not determinable from the database:** *why* the three cycles failed at 06:14. The evidence
establishes that each company's `plan_cycle` was attempted three times, every reservation was
released, nothing settled, and each cycle ended in M6-F9's containment path. The cause —
provider, credential, or configuration — is not in any table this document read, and is not
claimed.

**Not attributable to the owner:** the per-state definitions of Operational Confidence in Part
6.2. The four state *names* are recorded in `docs/DECISIONS.md`; the definitions are this
document's proposal (tension T4).
