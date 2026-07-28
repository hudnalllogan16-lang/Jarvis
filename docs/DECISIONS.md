# Jarvis Implementation Decision Record

Status: **binding on implementation, subordinate to the Architecture Specification v1.4.**

These are not amendments. Spec v1.4 remains the single source of truth (Â§12). Each entry below
records the *smallest reasonable implementation* chosen where v1.4 left a mechanism
unspecified, per the Implementation Directive. Nothing here contradicts a MUST or MUST NOT.

If any decision below is later found to conflict with the spec, the spec wins and the decision
is void â€” flag it, do not silently reconcile.

---

## D-001 â€” Capability invocations always terminate with a result
**Fills:** Â§2.1 (Manager "MUST wait for and synthesize all results") + Â§9 (dead-letter queue)

A capability invocation resolves to exactly one terminal `CapabilityResult` with status
`SUCCEEDED`, `FAILED`, or `DEAD_LETTERED`. Routing an invocation to the dead-letter queue
**also** delivers a `DEAD_LETTERED` result to the awaiting Business Manager. "Synthesize all
results" means all invocations reached a terminal state â€” not that all succeeded.

**Rejected:** dead-lettering as a silent terminal sink. Under the literal reading of Â§2.1 + Â§9
that deadlocks the business permanently.

**Reversal cost:** low. Contained in the capability dispatch layer (Milestone 2).

---

## D-002 â€” Invoking identity is derived, never declared
**Fills:** Â§2.2 (scoped request "supplied by the calling Business Manager") + Â§10 ("under any
circumstance, including bugs or malformed requests")

The `business_id` on an inbound scoped request is **advisory and ignored for authorization**.
The capability pool derives the true invoking identity from the Temporal workflow's registered
business identifier, resolves it through the Business Registry (Â§0.1), and validates the
requested memory / credential / tool scopes against that business's configured
capability-invocation permissions (Â§5). Any mismatch is rejected and audited â€” never narrowed,
never silently corrected.

**Rejected:** trusting the requester's declared scope. Â§10's "including bugs" clause makes a
requester-declared model unsatisfiable by construction.

**Reversal cost:** high once businesses exist. This is why it is decided at Milestone 1.

---

## D-003 â€” Budget debits are hierarchical
**Fills:** Â§2.1 (wake-cycle ceiling), Â§2.2 (per-invocation allocation), Â§5 (business Budget),
Â§9 (platform $500 / rolling 24h)

Every unit of spend (model tokens and metered tool calls) debits, in order, all four scopes:

    invocation allocation -> wake-cycle ceiling -> business budget -> platform rolling 24h

Rules:
1. A debit that would breach **any** enclosing ceiling is refused *before* the spend occurs.
   Ceilings are pre-flight checks, not post-hoc alarms.
2. Breaching the **business** ceiling halts dispatch for that business only.
3. Breaching the **platform** ceiling halts new dispatch platform-wide (Â§9), but resolves the
   Â§9 / Â§10 tension by tripping only after the offending business has already been halted by
   rule 2. Per-business caps are the first line; the platform breaker is the backstop.
4. In-flight invocations are never killed mid-execution by a ceiling breach; queued and
   undispatched invocations are cancelled and surfaced as stuck work (Â§12.5).
5. Exhausting a wake-cycle ceiling mid-cycle ends the cycle in `BUDGET_EXHAUSTED`, writes a
   Decision Log entry explaining it, and does not re-dispatch.

**Reversal cost:** high. The ledger is Milestone 1 infrastructure (Â§13 Step 1).

---

## D-004 â€” Temporal history is the replay substrate; the audit log is a durable projection
**Fills:** Â§2 and Â§11 ("replayable from the audit log alone")

Temporal's own event history is authoritative for workflow replay. The audit log is a
complete, append-only projection written through activities â€” sufficient for forensic
reconstruction and for satisfying Â§11's auditability requirement, but not a second execution
engine.

Consequently â€” and this is the part Â§11 requires but never states â€” **all nondeterminism MUST
occur inside activities with recorded results**: model calls, tool calls, HTTP, clock reads,
random draws, and UUID generation. Workflow code is pure orchestration.

**Rejected:** a bespoke replay engine reading the audit log independently. Two execution
engines with divergent histories is a correctness hazard, not redundancy.

**Reversal cost:** total. Every workflow written after Milestone 1 depends on this.

---

## D-005 â€” Decision history lives in the Decision Log, not in workflow state
**Fills:** Â§2.1 ("owns, as durable workflow state: ... decision history") + Â§11.5

Business Manager workflow state holds only a bounded working set: the current tactical plan,
active KPI targets, and identifiers of the current cycle's in-flight invocations. The decision
history itself is persisted to the Decision Log (Â§11.5), which Â§11.5 already establishes as a
first-class queryable store. Manager workflows use `continue_as_new` on a configured cycle
count.

Â§2.1 says the Manager *owns* decision history; it does not say the history must be resident in
workflow state. Ownership is preserved â€” the Manager is the sole writer of its own entries.

**Rejected:** literal accumulation in workflow state. Temporal history size limits make this a
production failure that surfaces after months of operation, not in test.

**Reversal cost:** high.

---

## D-006 â€” Approval uses the continuation model, not the blocking model
**Fills:** Â§2.1 (wake cycle), Â§8 (approval), Â§9 (7-day pending window)

A Business Manager that needs approval writes its Decision Log entry, emits the approval
request, and **ends the wake cycle**. The operator's decision arrives later as an
`approval.decided` event, which is an explicitly configured wake condition (Â§2.1) and starts a
*new* cycle that reloads context from durable state.

Therefore:
- The cost ceiling is scoped to a single cycle and is never spread across a 7-day wait.
- "Stuck Manager" detection (Â§9) measures cycle duration, now bounded in minutes, not days. A
  pending approval is tracked by the approval subsystem's own 24h/7d timers, not by a parked
  workflow.
- Approval context MUST be reconstructable from the Decision Log entry alone (Â§11.5).

**Rejected:** blocking the cycle on an approval signal for up to 7 days â€” it makes the Â§2.1
cost ceiling undefined, inflates open workflow count, and conflates two different timeout
regimes.

**Reversal cost:** high.

---

## D-007 â€” Operator-facing terms for components added in v1.3 and v1.4
**Fills:** Â§12.5's own completeness gate, which v1.4 currently fails

| Technical term | Operator-facing term (UI) |
|---|---|
| Platform Kernel | (invisible â€” "Jarvis" itself) |
| Business Registry | "Your companies" / the company list |
| Business type (plugin) | "Company template" |
| Business instance | "Company" |
| Lifecycle: `PROVISIONING` | "Setting up" |
| Lifecycle: `ACTIVE` | "Running" |
| Lifecycle: `PAUSED` | "Paused by you" |
| Lifecycle: `RETIRING` / `RETIRED` | "Closing down" / "Closed" |
| Executive Layer | (invisible â€” "Jarvis moved budget between companies, here's why") |
| Capital reallocation | "Budget moved" |
| Business budget cap reached | "[Company] hit its spending limit" |
| Wake-cycle budget exhausted | "[Company] stopped early to stay in budget" |
| Memory promotion | "Lesson shared with your other companies" |
| Autonomy level (per action type) | "What [Company] can do without asking" |
| LLM provider / model | (invisible â€” never surfaced) |

**Reversal cost:** none. Wording.

---

## D-008 â€” Business lifecycle state machine
**Fills:** Â§0.1 ("active, paused, retired" â€” named, never defined)

    PROVISIONING --> ACTIVE <-> PAUSED --> RETIRING --> RETIRED
          |                                   ^
          +-----------------------------------+

`RETIRED` is terminal. Identifiers are permanent and never reused (Â§0.1).

Invariants enforced on every transition:
- **I-1** Leaving `ACTIVE` cancels all scheduled wake timers; it never cancels an in-flight
  wake cycle mid-flight. The cycle runs to its terminal state, then the business settles.
- **I-2** Pausing never strands a pending approval. Pending approvals survive the pause and
  remain answerable; answering one does *not* wake a paused Manager â€” the decision is recorded
  and applied on resume.
- **I-3** No dispatched capability invocation is ever left without a consumer. On pause or
  retire, in-flight invocations terminate and their results are recorded.
- **I-4** `RETIRING` accepts no new dispatch; it exists solely to drain in-flight work.
- **I-5** Credential grants are revoked on entry to `RETIRED`, not before â€” a draining business
  still needs its credentials to finish idempotent work.
- **I-6** Every transition writes both an audit entry (Â§11) and a Decision Log entry (Â§11.5).

**Reversal cost:** medium.

---

# Smaller documented assumptions

**A-001 â€” Idempotency key (Â§6).** `sha256(business_id | invocation_id | action_type |
canonical_json(action_payload))`. Derived from the invocation, not the attempt, so retries and
replays collapse to one external effect.

**A-002 â€” Event delivery (Â§2).** At-least-once with consumer-side deduplication by
`(event_id, consumer_id)`. Duplicate delivery MUST NOT produce a duplicate wake cycle or a
duplicate approval request.

**A-003 â€” Action-type identity (Â§5, Â§8).** `action_type` is a stable dotted string namespaced
to the business *type*, not the instance: `affiliate.publish_post`. Graduation counters are
keyed `(business_instance_id, action_type)`. Changing a business type's plugin **major**
version resets its counters; minor versions do not. A "correction" is any operator approval
where submitted parameters differ from requested parameters â€” it counts as a denial for
graduation purposes.

**A-004 â€” Contention policy (Â§2.2).** v1 default is weighted fair queueing with
budget-proportional weights **and a guaranteed minimum share per active business**, so a
low-budget company cannot be starved indefinitely. Not FIFO (Â§2.2 prohibits it as a default).

**A-005 â€” Provider coverage.** The seven named providers are served by three transports: native
Anthropic, native Gemini, and one OpenAI-compatible client covering OpenAI, OpenRouter, LM
Studio, Kimi, and Ollama via `base_url`. Provider and model are config values; no model
identifier is hardcoded anywhere in the codebase.

**A-006 â€” Log write isolation (Â§10, Â§11).** Audit and Decision Log tables are append-only at the
application layer (no update or delete path exists) and every write is stamped with the derived
business identity from D-002.

---

# Milestone 1 review amendments (post-inspection)

Four findings from the pre-merge inspection. All are defects against decisions already
recorded above, not new decisions.

**M1-R1 â€” D-002 was documented, not enforced.** `authorize_invocation` accepted a plain
`BusinessId` for the workflow identity, so any caller could pass any value; the derivation was a
docstring convention. Now enforced by `jarvis/kernel/runtime.RuntimeIdentity`, which cannot be
built from a bare string in calling code. Production identities come from
`RuntimeIdentity.from_activity()`, which reads Temporal's `activity.info().workflow_id` â€” a value
the server sets from the *calling workflow* and activity code cannot forge. Test-constructed
identities are labelled `_source="testing"` and that label is written into every audit record, so
a test-provenance identity appearing in production audit is visibly an incident.

**M1-R2 â€” four of five security rejections were silent.** Only the identity-mismatch path wrote
an audit record; capability, tool-scope, credential-scope, and lifecycle rejections raised
without one. All five now route through `BusinessRegistry._deny`, which audits and then raises.
A structural test asserts `authorize_invocation` contains no bare
`raise ScopeViolationError`, so a future check cannot be added without an audit record.

**M1-R3 â€” the transition matrix was spot-checked, not exhausted.** 2 of 18 illegal pairs were
covered. Now all 25 pairs are parametrised against an independently maintained expected set, plus
an equality assertion between that set and the implementation's table, so adding a transition
without updating the expectation fails.

**M1-R4 â€” `stop_reason` leaked vendor values.** The field was a raw pass-through, so
`end_turn` / `stop` / `STOP` reached callers untranslated and any branch on it would have been
vendor-coupled. Now normalised to a `StopReason` enum with a per-provider mapping; the vendor's
own string is preserved as `raw_stop_reason` for the audit log only. Unknown values degrade to
`OTHER` rather than raising or masquerading as a clean stop.

Not changed: `max_tokens` and `stop_sequences` keep names that read as Anthropic-flavoured, but
the concepts are common to all three transports and the values carry no vendor semantics.
Renaming would be churn, not decoupling.

---

# Milestone 2 status: execution spine

Â§13 Step 1 lists thirteen infrastructure components. Milestone 2 delivers the subset needed to
run one capability invocation safely end to end. The rest is Milestone 3, listed below rather
than left implicit.

**Delivered and wired to a caller:** event bus with per-consumer deduplication (Â§2, A-002);
budget ledger with the full D-003 hierarchy; platform circuit breaker (Â§9) including the
Decision Log narrative Â§12.5 promises and v1.4 assigns to no writer; capability pool dispatch
with authorization (D-002), bounded retry and backoff (Â§9), dead-lettering that still returns a
terminal result (D-001); stateless execution shell (Â§6); idempotency guarding external-facing
actions (A-001); the Temporal activity boundary (D-004).

**Delivered without a production caller â€” deliberately, and flagged rather than disguised:**

- `CredentialManager` (Â§10) resolves handles to secrets at the tool-execution boundary. Nothing
  executes tools yet: the capability shell calls a model and returns text. Wiring it now would
  mean materialising secrets with no consumer, which is the opposite of what Â§10 asks for. It is
  built because the *boundary* had to be decided before any tool code exists to put on the wrong
  side of it.
- `FairQueue` (Â§2.2, A-004) decides who dispatches next under contention. The pool currently
  dispatches synchronously, so there is no contention to arbitrate. It is built and tested now
  because Â§2.2 makes the policy a MUST and forbids FIFO as a default; retrofitting fairness after
  concurrency exists is how FIFO becomes the default by accident.

Both are covered by tests. Neither should be read as working in production until M3 gives them a
caller.

**Deferred to Milestone 3 (remainder of Â§13 Step 1):** approval subsystem (Â§8) with the 24h
re-notification and 7-day auto-pause timers (Â§9); scheduler and wake-condition evaluation (Â§2.1);
KPI engine (Â§5, named only in Â§13 and specified nowhere); notification system; operator-facing
dashboard surfaces (Â§12.5). Then Milestone 4 is the Affiliate Business (Â§13 Step 2).

## Milestone 2 findings

**M2-F1 â€” spend attribution is approximate.** `CapabilityPool._cost_of` settles a reservation at
its full reserved amount unless the provider reports a cost, because per-model pricing is not
configured until the Executive Layer's cost tracking exists. The approximation is deliberately
biased toward over-reporting spend: it can only understate remaining headroom, never overstate
it, so no D-003 ceiling can be silently exceeded by it. Revisit when pricing config lands.

**M2-F2 â€” `for_testing` now validates identifier format.** Test business ids previously did not
match the production pattern, so the M1-R1 derivation path was only ever exercised against input
no real business would produce. `RuntimeIdentity.for_testing` now applies the production pattern
and the fixtures use realistic identifiers.

**M2-F3 â€” idempotency is scoped to actions, not queries.** Only invocations carrying an
`action_type` are guarded. Â§6 scopes idempotency to external-facing and state-changing actions;
caching a research query would return stale findings for a question deliberately asked again.

---

# Milestone 3 status: operator surface

This milestone exists because Â§12.5 states that a technically correct implementation which fails
it "is a spec violation, not a 'polish later' item". After M2 the platform was correct and
completely unusable: nothing an operator could see, approve, or act on.

**Delivered:** approval subsystem with the autonomy ladder (Â§8); 24h re-notification and 7-day
auto-pause timers (Â§9); notification service; KPI engine and Health Score (Â§5); operator HTTP API;
and the Sims-style dashboard Â§12.5 requires as the default view.

## D-009 â€” Health Score is computed by the platform, not by each business

**Fills:** Â§5 (Health Score is a per-business contract field) vs Â§3 (health score aggregation is a
deterministic COO function) â€” v1.4 never says which side computes it.

The platform computes it, from contract primitives, in `jarvis/kpi/engine.py`. A score must be
comparable across businesses to be aggregatable at all; per-business implementations would make
two companies' scores mean different things while looking identical on the dashboard.

Composition: reliability 45%, budget headroom 30%, KPI attainment 25%. Reliability is weighted
heaviest because a company that cannot finish its work is broken in a way budget headroom cannot
compensate for. Components are returned alongside the score, not just the number, because Â§12.5
requires the operator be able to ask why and Â§11.5 forbids the audit log being the first answer.

**Reversal cost:** low. One module, no persisted derivation.

## D-010 â€” A correction resets the graduation streak

**Fills:** Â§8 requires "no denials or corrections in that window" and never defines a correction.

A correction is an approval where the operator changed the parameters before approving (A-003).
It advances the action but resets the streak to zero.

The alternative â€” treating an edited approval as an endorsement â€” would graduate an action the
operator actually rejected the original form of. Given graduation reduces friction on future
actions of that type, the conservative reading is the only safe one.

Enforced with two independent guards: the policy's `graduation_eligible` flag *and* the action's
own amount. A policy misconfigured as eligible still cannot graduate an action that moves money,
which is Â§8's hard v1 constraint.

**Reversal cost:** low.

## D-011 â€” Approval text is rendered from stored values, never model-authored

**Fills:** Â§8 (display the specific action, exact amount, triggering condition, downside) and
Â§12.5 (plain operator language, generated fresh per request).

The four facts are stored as structured columns and assembled into language by deterministic
string formatting in `jarvis/approvals/rendering.py`.

This is a safety property, not tidiness. Capabilities read untrusted external content â€” Â§13
Step 5 includes news analysis â€” and a Manager synthesizes those results into decisions. If the
amount an operator approves were prose regenerated by a model, attacker-influenced text would sit
between the decision and the human authorising money. The operator reads language; the numbers in
that language are the stored values.

This closes item 18 from the architecture review.

**Reversal cost:** low, but reversing it reopens a real attack path.

## Milestone 3 findings

**M3-F1 â€” Â§12.5 is now an executable gate.** `tests/test_operator_language.py` asserts that none
of Â§12.5's fifteen forbidden concepts appear in the dashboard markup, its script copy, the
lifecycle labels, the approval labels, or any rendered approval or failure string. Â§12.5 was
previously enforceable only by review, which catches a violation once; this catches it on every
commit. The test also asserts the detector itself fires, because a guard that never fires reads
as coverage while providing none.

**M3-F2 â€” expiry is the highest-stakes assertion in the subsystem.** Â§9 requires an unresolved
approval to auto-pause and explicitly never auto-approve. An implementation that drifted to
auto-approve would hand an unattended platform the authority to spend. It is tested directly and
should be treated as a regression tripwire.

**M3-F3 â€” the scheduler is still absent.** `due_for_renotification` and `expire_stale` are
implemented and tested but nothing calls them on a timer yet; they need the scheduler, which
arrives with the Business Manager in M4. Until then the 24h/7d timers are correct but dormant.
Same honest caveat as `CredentialManager` and `FairQueue` in M2.

---

# Milestone 4 status: Business Manager runtime + scheduler

Roadmap revision 2 split this out of the Affiliate Business milestone. See
`docs/ROADMAP.md` for the dependency argument.

**Delivered:** the generic Business Manager Temporal workflow (Â§2.1); its activity boundary;
bounded durable state (D-005); the continuation approval model (D-006); the scheduler driving
Â§9's 24h and 7-day timers and Â§2.1's event-based wakes; and a concurrency gate that finally gives
`FairQueue` a caller.

**Dormancy retired.** Two of the three components carried since M2/M3 now have production callers:

| Component | Was dormant since | Caller now |
|---|---|---|
| `FairQueue` | M2 | `CapabilityGate`, consulted by every pool dispatch |
| Approval 24h/7d timers | M3 | `Scheduler.sweep`, looped by the worker |
| `CredentialManager` | M2 | **still dormant** â€” nothing executes tools until M5 |

## D-012 â€” The scheduler is not a workflow

**Fills:** Â§13 Step 1 lists a scheduler; Â§2.1 and Â§3 forbid standing reasoning loops.

The timer sweep runs as a plain async loop in the worker process, not as a Temporal workflow.
It is deterministic bookkeeping over rows with no reasoning in it, and putting it in the workflow
layer would place a permanently-running loop there for no benefit. Â§2.1's prohibition is on
*reasoning* loops; a sweep that reads timestamps and writes notifications is not one, and keeping
it out of the workflow layer makes that distinction visible in the code rather than argued in a
comment.

A failed sweep logs and retries on the next tick rather than killing the loop: an approval
expiring five minutes late is a nuisance, a scheduler that stops means approvals never expire.

**Reversal cost:** low.

## D-013 â€” The model proposes intents; the platform attaches scopes

**Fills:** Â§2.2 (scoped requests) meeting Â§2.1 (the Manager plans by model call).

The planning activity asks the model for intents and capability names. It does **not** let the
model author the resulting `ScopedRequest`. Tool scope, credential refs, memory scope, and budget
allocation are read from the business's configured `CapabilityPermission` and attached by the
platform.

If a model could author its own scope, Â§2.2's scoping would be decorative and Â§10's isolation
would rest on a language model's discretion. A hallucinated or unpermitted capability name
produces one fewer plan item rather than an error or an unauthorised dispatch.

Similarly, the model does not decide whether an action needs approval. `needs_approval` is
resolved against the contract and the graduation ladder (Â§8) in the synthesis activity, and
`ProposedAction.needs_approval` defaults to `True` so a Manager that omitted it asks rather
than acts.

**Reversal cost:** high. This is a security boundary, not a convenience.

## Milestone 4 findings

**M4-F1 â€” parallel dispatch was silently sequential (fixed).** The first draft of
`_dispatch_all` awaited activity handles in a list comprehension, which serialises them. Â§2.1
explicitly permits dispatching multiple capability requests in parallel, and the bug would have
made a cycle's latency the sum of its parts while passing every functional test. Replaced with
`asyncio.gather` and covered by a regression assertion in `test_manager_determinism.py`.

**M4-F2 â€” `__all__` import-laundering recurred (fixed).** I flagged this pattern in M2, fixed it
in `runtime/activities.py`, and then reproduced it in `manager/activities.py` â€” listing otherwise
unused imports in `__all__` to quiet a linter. Removed, and the unused imports deleted. Worth
recording because it is a habit, not an accident: the correct response to an unused-import
warning is to delete the import.

**M4-F3 â€” determinism is now a source-level gate.** `test_manager_determinism.py` asserts against
the workflow module's AST that it contains no clock read, no identifier minting, no I/O import,
and no `execute_activity` call without a timeout. Determinism is a property of what the code *may*
do; a runtime test only covers what one execution did, and a replay divergence appears during
recovery, which is when it is least affordable.

**M4-F4 â€” cron support is deliberately partial.** `_interval_seconds` handles daily and hourly
schedules only. Â§14 asks that expansion be driven by demonstrated need; a business requiring a
schedule this cannot express is that need. Unsupported expressions return None, which makes the
Manager event-driven rather than silently mis-scheduled.

---

# Milestone 5 status: Affiliate Business + reconciliation

## D-014 (amended) â€” a business type is data, persisted in the Registry

Original D-014 said a type is data, not code. Milestone 5 surfaced a second, concurrent
implementation of the same idea (see M5-F1) whose design was better on the axis that matters:
**where the data lives**. The canonical answer is now:

- The artifact is `jarvis/businesses/definition.py::BusinessTypeDefinition` â€” pure data, no
  Manager subclass, no logic. `tests/test_affiliate_type.py` asserts the affiliate module's AST
  contains zero functions and zero classes.
- Definitions persist as Registry metadata (Â§0.1), installed via `ProvisioningService.install`,
  which refuses a type whose permitted capabilities lack prompt templates.
- Instance creation is `ProvisioningService.create_company`: definition + display name + optional
  budget numbers. That signature *is* Â§4's "configuration only" requirement.
- Activation publishes `business.activated` on the bus rather than starting a Manager directly
  (Â§2 forbids direct worker calls; A-002 dedup means a replayed activation cannot start two
  Managers for one business).

Rejected (my own first cut): an in-process `INSTALLED_DEFINITIONS` dict populated by import side
effect. It failed on restart (M5-F3) and made installation invisible to the audit log.

## D-015 â€” tools run only on the approved-action path

Capabilities *produce content*; tools *perform effects*; effects execute only after Â§8's gate
(approval or graduated autonomy), via `ToolExecutor`. A model call can therefore never cause a
side effect directly. Credentials materialise inside the tool implementation's call and nowhere
else (Â§10) â€” this is the boundary `CredentialManager` waited for since M2. Every effect is
idempotent under the A-001 key, so a retried or replayed approved action replays its recorded
result instead of publishing twice. The executor runs the operator's *decided* parameters, never
the originally requested ones (A-003 correction semantics).

## Milestone 5 findings

**M5-F1 â€” concurrent divergence, and how it was resolved.** Between working sessions, a parallel
implementation of the business-type mechanism appeared in `jarvis/businesses/` alongside the one
I was building in `jarvis/plugins/`: two `BusinessTypeDefinition` classes, two creation paths,
and duplicate `POST /api/companies` routes (the later-registered one silently dead). Resolution:
reconciled onto `jarvis/businesses/` because it was better where it counted â€” persistence and
bus-mediated activation â€” and ported the two pieces it lacked (`tool_registry`, the data-only AST
gate). `jarvis/plugins/` is deleted. One mechanism remains. The layering gate then correctly
rejected the reconciled code itself (`api` importing `businesses` forward), fixed by routing
construction through the kernel composition root rather than by widening the exemption list.

**M5-F2 â€” silent patch no-ops.** Several of my edits used `str.replace` without asserting the
target existed; one (the layering-table update) silently did nothing because the concurrent work
had already changed the region. A patch that cannot fail is a patch that cannot be trusted to
have happened. Later patches in this milestone assert before replacing.

**M5-F3 â€” the empty-templates defect.** My original dispatch path gave the executor a
kernel-wide empty template source, so every real dispatch would have dead-lettered with "unknown
prompt reference" â€” a company that looks healthy and can never do anything. Fixed: the dispatch
activity loads the invoking type's templates from Registry metadata per dispatch. The concurrent
implementation's persistence choice is what made this fixable.

**M5-F4 â€” credited: the open D-006 loop.** The concurrent work found that `approval.decided`
existed as an *audit* event name but was never *published* to the bus â€” the Manager's
continuation model looked closed and was not; a business that asked for approval would never
resume. Fixed by them (`events/types.py` + publish in the approval service + a closure test).
Recorded here because the lesson generalises: two logs and a bus sharing a naming style means a
grep proves nothing about where a message went. Bus event types now live in one module.

**Deferred-completion ledger:** `CredentialManager` retired (caller: `ToolExecutor`). The
Business Manager workflow's first live Temporal exercise remains open, now targeted at M6.


---

## D-016 â€” the Shell is topology, not architecture

**Fills:** nothing in v1.4 â€” the spec is silent on process layout, which is exactly why this is
an implementation decision and not an amendment.

`python -m jarvis` runs the API, the Temporal worker, and the scheduler in one process for
development. The architecture's boundaries are untouched: the worker and API remain separately
runnable (`jarvis.runtime.worker`, `jarvis.api.server`) and production deploys them separately.
The launcher is a composition root â€” it starts components and prints their health; any behaviour
found in it is a defect (`test_composition_roots_hold_no_logic`).

Degradation ladder, in operator language throughout: database down â†’ attempt Docker start,
re-check, refuse only if still unreachable; Temporal down â†’ serve everything, banner says
"companies can't act right now", worker retries in the background and attaches when the runtime
appears; no LLM key â†’ serve everything, banner says "companies can't think yet". A developer who
starts Jarvis before Docker finishes booting watches it assemble itself rather than restarting
processes by hand.

**Reversal cost:** none. Deleting the shell package restores the previous manual topology.

---

## D-017 â€” one application: supervision, window, and subsystem toggles

**Fills:** nothing in v1.4 â€” process behaviour and desktop packaging are operational surface the
spec is silent on. Classification: operational; no layer, responsibility, or invariant changes.

**Supervision.** Every long-lived part (dashboard server, company runner, timers) runs under
`jarvis/shell/supervisor.py`: crash â†’ log â†’ exponential backoff (1s doubling to 60s, reset after
30s of stability) â†’ restart. Part states surface in `/api/health` under plain labels â€” a crashed
worker appears in the app as "Company runner â€” restarting itself", never as a dead terminal. The
supervisor is a component, not launcher logic, so the entrypoint no-logic gate still holds.

**Window.** With the `desktop` extra (`uv sync --extra desktop`), the dashboard opens in a native
window and closing it quits Jarvis â€” the window is the app. Without it, the default browser opens.
`JARVIS_HEADLESS=1` disables both. The desktop module knows only a URL; internal modularity is
invisible through it by construction. A single-file executable (PyInstaller) is the eventual end
of this path; deferred until the shell stabilises, recorded here so it is a decision rather than
an omission.

**Subsystem toggles.** "Enable or disable subsystems through the UI" maps onto existing
architecture rather than new machinery: a subsystem is a business type, and the toggle is an
`enabled` flag on the Registry's type row (migration 0005). Disabled types disappear from the
create-a-company flow. Deliberately *not* touched: existing companies, which keep their own
pause state â€” one switch that silently paused running businesses would violate the operator's
mental model and the audit story. Both toggle and separation are stated in the settings panel.

**Reversal cost:** none for window and toggles; low for supervision (restore plain gather).

---

## M5-F5 â€” the launcher never started the dashboard on a fresh database (fixed)

**Reported by the user**, with an exemplary trace: Docker healthy, all containers confirmed
running, kernel initialising cleanly, `curl localhost:8000` refusing the connection, and the
launcher's log stopping dead after `"starting services"` with nothing further.

**Root cause.** `check_database` (preflight) ran two probes â€” connectivity (`SELECT 1`) and a
schema check (`SELECT count(*) FROM business_instances`) â€” and tried to tell them apart by
matching the failing exception's class name against `"UndefinedTable"` and its message against
`"no such table"`. Both patterns are SQLite's shape. On Postgres, SQLAlchemy wraps the driver
error in `ProgrammingError` (the class name never matches) and the message reads `relation
"business_instances" does not exist` (the text never matches either). Every fresh Postgres
database â€” the ordinary state on a first-ever launch, before migrations run â€” was therefore
reported `DOWN` instead of `DEGRADED`.

That single misclassification explains the entire observed symptom: the launcher re-ran `docker
compose up -d` against containers already healthy (matching the log line exactly), then retried
the same unwinnable check silently for up to two minutes, then exited â€” all before the Supervisor
or the FastAPI app were ever constructed. The dashboard was never reached, so there was nothing
to crash and nothing to bind port 8000.

**Fix â€” structure over string-matching.** The two probes are now independent and their meaning is
determined by *which query failed*, not by inspecting the failure: a failure on `SELECT 1` is a
genuine connectivity problem (`DOWN`); any failure on the schema probe â€” reached only once
connectivity has already succeeded â€” means "reachable, not migrated yet" (`DEGRADED`), regardless
of driver, wrapper class, or wording. This closes the door the original bug walked through and
cannot be reopened by a future driver change producing yet another message shape.

**Secondary defect found while tracing this.** `_try_start_services()` called `subprocess.run`
directly inside the async event loop â€” unlike `_apply_migrations()`, three lines below it, which
was correctly offloaded via `asyncio.to_thread`. That blocked the entire loop, including Ctrl-C
handling, for the duration of the `docker compose` call. Fixed to match its neighbour.

**Also fixed:** the retry loop gave zero output for up to two minutes, which is indistinguishable
from a hang â€” it now prints a heartbeat every ~15 seconds. And the `"Dashboard: ..."` banner
printed unconditionally at the very top of `launch()`, before preflight had run at all â€” an
aspirational claim stated as fact. It now prints only once startup has actually reached the point
of serving it.

**Verification.** `tests/test_preflight.py` reproduces the exact reported shape (a wrapper
exception named `ProgrammingError`, Postgres's "does not exist" wording) and asserts `DEGRADED`,
plus a connectivity-failure case asserting `DOWN`, a healthy case asserting `OK`, and a
wording-independent case using a wholly invented exception class â€” closing the mechanism, not one
instance of it. All four run against the real, unmodified `preflight.py` in this session (with
`sqlalchemy` stubbed, since it isn't installed in this sandbox) and pass.

---

## M5-F6 â€” the app window ran on the wrong thread (fixed)

**Found by the owner on the first real-hardware launch.** The launcher started correctly â€”
preflight classified a fresh database as "reachable but not set up yet" (confirming the M5-F5
fix), migrations applied, the dashboard bound and reported ready â€” and then the window thread
died with `WebViewException: pywebview must be run on a main thread`.

**Root cause: inverted thread ownership.** `desktop.open_window` ran `webview.start()` on a
daemon thread while asyncio held the main thread. Native GUI toolkits own the main thread's
message loop and pywebview refuses to start anywhere else. This is a platform constraint, not
something to work around, so the ownership had to invert: **the window takes the main thread
and the asyncio event loop runs on a background thread.**

Nothing in the architecture changed â€” this is process topology (D-016, D-017), and the
separately-runnable API and worker entrypoints are untouched.

**A second defect, in the first version of the fix.** `main()` used `Thread.is_alive()` to
decide whether startup had succeeded. That is a race: a launch that raises leaves its thread
briefly alive, so the window opened onto a backend that had already died. Replaced with an
explicit `StartupOutcome` (in `jarvis/shell/supervisor.py`) carrying `done` â€” set on every exit
path, so a waiting thread is never stranded â€” and `serving`, set True only once the dashboard
port is actually bound. Success is now stated, not inferred.

**A third defect found while fixing it.** The window previously opened immediately after the
supervisor started its parts, before anything had bound port 8000, so the operator's first
impression could be a connection-error page. Both window and browser now wait on
`desktop.wait_for_dashboard`, a plain TCP connect probe â€” it tests exactly the property that
matters rather than a uvicorn internal.

**The layering gate earned its keep here.** The first fix put the `StartupOutcome` dataclass in
`launcher.py`, and `test_entrypoint_roots_hold_no_logic` failed it: entrypoint roots hold no
logic. The right response was to move the type into a component, not to widen the exemption.
That is the gate doing the job it was written for, on its author.

**Verification.** All five startup paths exercised against the shipped code: healthy start
(window on `MainThread`, services on `jarvis-services`, closing the window shuts services
down), preflight refusal, launch raising during startup, port never binding, and a window that
cannot open falling back to the browser while the application keeps serving. A negative control
confirms that calling `run_window_blocking` from a worker thread raises exactly as pywebview
does. The window itself still has not been opened on real hardware â€” that remains the owner's
next check.

---

## M5-F7 â€” duplicate request model shadowed the create-company contract (fixed)

**Found by the owner** on the first end-to-end create-company attempt, once the desktop window
made the flow reachable: the UI sent `{template, name, budget_usd}` and the API rejected it,
demanding `type_name` and `display_name`.

**Root cause: two classes named `CreateCompanyBody` in `jarvis/api/app.py`.** A leftover from
the M5 reconciliation (finding M5-F1) â€” when the parallel implementations were merged, the
duplicate *route* was removed but both *request models* survived. Python binds the name to the
second definition, so `type_name`/`display_name` silently shadowed the correct
`template`/`name` model. The route body read `body.template` (the first model); FastAPI
validated against the second. The validator and the route disagreed because they referenced
different classes with the same name.

This is the exact hazard M5-F1 warned about: two writers in one file, and a name collision that
no test caught because both classes were individually valid. Fixed by deleting the shadowing
duplicate. A static check now asserts the three sides of the contract agree (below).

**Also addressed â€” raw validation errors reached the operator (Â§12.5).** FastAPI's default 422
handler returns the full Pydantic error list to the browser, which is diagnostic output in the
operator's face. Added a `RequestValidationError` handler that logs the field-level detail at
warning (where a developer needs it) and returns one plain sentence. The dashboard's create
flow now renders that sentence inline instead of a raw `alert()`, and is defensive about the
shape of `detail` regardless of what any handler sends.

**Verification.** A static contract check confirms the frontend POST body, the surviving
`CreateCompanyBody` fields, and the attributes the route reads off `body` are the same set:
`{template, name, budget_usd}`. The create flow no longer contains an `alert()`. Not yet
verified on hardware: an actual successful creation round-trip, which is the owner's next check.

---

## M5-F8 â€” duplicate "New company" control, and a template dead-end (fixed)

**Owner UX review after the desktop app reached the create flow on hardware.**

**Duplicate action.** The dashboard exposed two "New company" buttons â€” one in the header beside
Settings, one in the "Your companies" section header â€” performing the same action. Removed the
section-header one; the header button is the single persistent control. The empty state now
carries a one-time call-to-action, which is the empty state doing its job of inviting the first
action rather than a duplicate of a standing control.

**Template dead-end.** When no templates were installed, the create dialog said "None installed"
and stopped â€” a first-run dead end if `ensure_builtin_types` was ever skipped or a database
reset. Added `POST /api/company-templates/install-builtin` (idempotent; installs only what's
missing) and wired the empty-template state to an "Install starter template" button that calls
it and reopens the dialog. First-run onboarding no longer terminates in a message.

Both are operational/Â§12.5 UI work, no architecture impact. The friendly-validation-error work
requested in the same review was already delivered under M5-F7.

## Roadmap revision 4 â€” recorded

M6 reframed from "Finance Tracking (second business type)" to "Affiliate vertical slice (prove
the platform end to end)"; Finance moves to M7. Full justification in `docs/ROADMAP.md`.
Classification: structural â€” the order in which milestones exercise existing code changes, and
M6's definition of done becomes a working end-to-end transaction rather than a new component; no
layer, responsibility, or invariant moves. The prior M6 packets are in `docs/packets/archive/`.

---

## D-018 â€” product experience is a governed, first-class objective

**Decision.** Product quality is established as a first-class engineering objective with its own
governance, parallel to architectural governance and subordinate to correctness. A read-only
`product-reviewer` agent reviews operator experience and reports directly to the Engineering
Manager, gating any milestone with an operator-facing surface. The product constitution is
`docs/PRODUCT.md`; the standing priority order (correctness â†’ vertical slices â†’ workflow â†’
product experience â†’ polish) is recorded in `docs/ROADMAP.md`.

**Why.** Correctness and delight are different questions optimising for different outcomes, and
a milestone can satisfy one while failing the other. Left ungoverned, product quality becomes
the thing perpetually deferred â€” so it is given the same machinery that keeps architecture
honest: an independent, read-only reviewer that cannot implement or decide, only report. The
objective is deliberately long-term (premium desktop software) while the current UI is
explicitly a functional prototype; the reviewer judges movement toward the objective, not
arrival, so the prototype is free to look plain but not to confuse or dead-end.

**Boundaries.** The product-reviewer never edits code, never makes implementation decisions, and
never issues pixel- or colour-level prescriptions â€” it describes experience problems and desired
outcomes and leaves implementation to the Manager and the operator-surface-engineer. It is to
product what the architecture-auditor is to correctness, including the rule that it reports to
the Manager and never sits under the delivery-coordinator.

**Classification: operational/process.** No layer, responsibility, or invariant in the running
system changes. This governs how work is reviewed, not what the software is.


---

## D-019 â€” the engineering process is stable by default

**Decision.** As of the Claude Code transition, the engineering system â€” governance, delegation,
reviewers, gates, manifest pipeline â€” is considered complete and stable by default. New
governance, reviewers, or process is introduced only when the existing process *demonstrably
fails*, not preemptively. The focus shifts from building the factory to building the product:
every milestone must move Jarvis toward being a useful AI operating system, and the process
exists to enable that rather than to become the project.

**Why.** The process matured quickly and well, but process has no natural stopping point â€” there
is always another reviewer or gate that could be added, and each carries real cost in ceremony
and Manager attention. Left unchecked, refining the factory becomes a substitute for shipping the
product. Declaring stability makes expansion the exception that must justify itself against
evidence, which is the correct default once the machinery works.

**Consequences.**
- The two reviewers hold their charters and do not expand them. The architecture-auditor protects
  correctness; the product-reviewer judges experience progress (not perfection). Neither grows
  scope without a demonstrated gap.
- A proposal to add process must cite a specific failure of the current process. "This might
  help" is insufficient; "this milestone broke because we lacked X" is the bar.
- The baseline review (`docs/BASELINE_REVIEW.md`) is the last process-focused review. Subsequent
  reviews are the per-milestone auditor and product verdicts, which are product-focused.

**Classification: operational/process.** Governs how the project evolves, not what the software
is.

---

## D-020 â€” unresolved stuck work caps the health band below "healthy"
**Fills:** Â§5 (Health Score), Â§9 (dead-letter visibility), Â§12.5 ("[Company] got stuck â€” here's
what happened")

A company with one or more unresolved dead-lettered jobs MUST NOT present a `healthy` band,
regardless of its weighted score. The weighted formula (headroom 0.30 / reliability 0.45 /
attainment 0.25) remains the score; the band computation gains a hard override: `stuck > 0`
caps the band at `watch`.

**Why.** Found during M6-0, the suite's first real execution: `test_stuck_work_dominates_the_score`
asserts a company with 3 stuck jobs is not healthy, but full budget headroom and full attainment
outvote a reliability of 40 (score 73 â‰¥ HEALTHY 70). The engine's own comment states reliability
is weighted heaviest "because a company that cannot finish its work is broken in a way that budget
headroom cannot compensate for" â€” the weights fail to deliver that stated intent at full headroom.
The test and the comment agree; the arithmetic is what's wrong. An override encodes the intent
directly instead of chasing it with weight tuning, and keeps Â§9's dead-letter visibility
consistent with what the health card tells the operator.

**Rejected:** re-tuning weights (fragile â€” any future component re-opens the same gap);
relaxing the test (would weaken an assertion both artifacts intend).

**Reversal cost:** low. One band computation, one test.

---

## M6-F1 â€” dispatch authorization read lifecycle state from a stale contract snapshot (fixed)

Found by M6-0, the first real execution of the suite. `Registry.authorize_invocation`
(`jarvis/registry/registry.py`) derived lifecycle state from the `BusinessContract` JSON written
once at `register_instance` and never updated; `transition()` updates only the
`BusinessInstanceRow.lifecycle_state` column. Every business therefore evaluated as
`PROVISIONING` forever on the dispatch-acceptance check, and all dispatch was denied with
`not_dispatchable` regardless of activation. Failed closed â€” no unauthorized dispatch was
possible, but no authorized dispatch was either. Caused 13 of the 14 real test failures
(all of `test_capability_pool.py`, `test_valid_invocation_authorized`, and 3 of 4 cases of
`test_every_rejection_path_is_audited`, which the spurious check pre-empted). Two tests passed
by coincidence (`PROVISIONING` and `PAUSED` both fail `accepts_dispatch`). Fix: authorization
reads live state via `get_state()`. Security-relevant path (D-002), routed to security-engineer
on Opus with audit.

## M6-F2 â€” health banding contradicted the engine's stated intent (fixed)

See D-020, which records the arbitration. The suite's first execution surfaced it; the fix
implements the band cap.

## M6-F3 â€” `set_type_enabled` raised an undefined name (fixed)

Found by ruff's first real run (F821). `jarvis/registry/registry.py` raised `RegistryError` for
an uninstalled type, but the name was never imported â€” the class existed in
`jarvis/kernel/errors.py` all along; the bug was a missing import, so the real runtime behaviour
was `NameError`. Fixed with the import plus a regression test in `tests/test_registry.py`.
Illustrative of the M6-0 theme: code written without an interpreter fails in ways only execution
finds.

## M6-F4 â€” a workflow-less activity produced `TypeError`, not the documented refusal (fixed)

Found by pyright's first real run. temporalio types `Info.workflow_id` as `str | None` (None
when an activity was not started by a workflow); `RuntimeIdentity.from_activity` passed it
straight into the workflow-id regex, so the promised `ScopeViolationError` was actually a bare
`TypeError`. Manager decision (resolving the M6-0g escalation): a workflow-less activity has no
derivable business identity and is refused with `ScopeViolationError` â€” D-002, fail closed. The
guard only adds a refusal; it removes no check. Regression tests in
`tests/test_runtime_identity_boundary.py`, including the negative control.

## D-021 â€” the wake cycle is bounded by planning; `cycle_id` is minted in `plan_cycle`
**Fills:** Â§2.1 (wake-cycle cost ceiling), D-003 tier 2, D-004 (ids minted in activities)

Found live in M6-1 (M6-F8): every `ScopedRequest` carried a NULL `cycle_id`, so the per-cycle
budget check (`if cycle_id is not None`) never fired â€” Â§2.1's ceiling was structurally
unenforced and `BUDGET_EXHAUSTED` unreachable. Decision: a cycle begins when planning begins.
`plan_cycle` (an activity â€” D-004 keeps minting out of the workflow) mints the `cycle_id` and it
threads through dispatch, synthesis, and the decision record. Rejected: minting in
`load_cycle_context`, which would open the cycle before the wake actually starts reasoning â€” a
Manager parked for 20 hours would hold a 20-hour-old cycle id, making the ceiling's window
meaningless.

**Reversal cost:** low-medium â€” a field on three payloads, all internal to the Manager path.

**Implemented in M6-1b.** Three notes the implementation forced, none of which change the
decision above:

1. `BUDGET_EXHAUSTED` now comes from the ledger's refusal, not from a guess. The workflow
   previously inferred it (`any result dead-lettered AND spend >= ceiling`) because no real
   signal existed. With the id threaded, D-003 refuses the reservation *before* the spend and
   the refusal arrives as a failed `dispatch_capability`; the workflow reads the failure type
   and ends the cycle `BUDGET_EXHAUSTED` (D-003 rule 5). Keeping the heuristic alongside the
   real signal would have left two disagreeing definitions of the same outcome.
2. The workflow reads `plan_payload.get("cycle_id")`, and `record_cycle_decision` reads its
   payload key the same way. A history captured before D-021 carries neither, and Â§11 requires
   it to still replay â€” verified: the committed fixture replays unchanged, so no re-capture and
   no model spend was needed.
3. A cycle can fail *before* it has an id, since D-021 puts the cycle's start at planning's
   start. That is recorded with an empty cycle id rather than suppressed.

## M6-F5 â€¦ M6-F11 â€” the first live run's harvest

What only a live run could find (M6-F5/F6 hit during the first interrupted attempt, fixed and
re-verified; F7â€“F11 found by the completed run):

- **M6-F5 (fixed):** Temporal's default data converter cannot encode the pydantic payloads â€” no
  cycle could ever run. Pydantic data converter wired in the container.
- **M6-F6 (fixed):** every LLM transport sent a default `temperature`, which current models
  reject â†’ HTTP 400 in `plan_cycle`. Now optional, omitted unless set.
- **M6-F7 (open):** `python -m jarvis.api.server` 500s on every DB route â€”
  `asyncio.run(ensure_builtin_types())` closes the loop the asyncpg pool bound to before
  `uvicorn.run()` opens a new one. The launcher path does it correctly.
- **M6-F8 (fixed, M6-1b):** the NULL `cycle_id` above; resolved by D-021. `plan_cycle` mints the
  id and stamps every request it builds; ledger rows, the synthesis payload, and the Decision Log
  entry all carry it. See M6-F12 for the part of the ceiling that is still not enforced.
- **M6-F9 (fixed, M6-1b):** an activity failure fails the whole Manager workflow
  (`WORKFLOW_EXECUTION_FAILED`) â€” the business is left Manager-less and `CycleOutcome.FAILED`
  is unreachable, contra Â§9's requirement that a stuck Manager surface rather than vanish.
  Fixed for the cycle body: an exhausted activity ends the cycle `FAILED` (or
  `BUDGET_EXHAUSTED` when a ceiling refused it), writes an operator-language Decision Log entry,
  counts against the daily wake allowance, and returns to the wake loop. See M6-F13 for the
  remaining unguarded call.
- **M6-F10 (open):** self-sustaining wake loop: the Affiliate type subscribes to
  `capability.result_returned`, but under D-001 every result is already awaited and consumed
  *inside* the cycle that requested it â€” so each cycle's own output re-wakes the business,
  bounded only by `max_cycles_per_day`. Decision (config, not architecture): remove
  `capability.result_returned` from the Affiliate wake conditions; schedule and
  `approval.decided` remain. A result arriving outside its requesting cycle cannot exist under
  D-001; if a future business type needs result-driven wakes, that is a D-001 conversation, not
  a config default.
- **M6-F11 (open):** the live model authored a prose `action_type`
  ("affiliate.Hold publication and re-run compliance review") where A-003 requires a stable
  dotted identifier â€” and graduation counters key on that string. The platform must validate
  proposed action types against the business type's declared set and reject/degrade prose
  (D-013: the model proposes, the platform validates). Routed to the approval path work (M6-2).

## D-022 â€” budget reservations are committed before spend and serialized per scope
**Fills:** D-003 rule 1 ("refused *before* the spend occurs") under concurrency; resolves M6-F12
and M6-F14

Mechanism:
1. **Reserve, committed, first.** Before any model call or dispatch spends, a reservation row is
   written and committed in its own short transaction. Within that transaction the headroom
   check runs under a per-scope serialization (advisory transaction lock on the scope key, or
   `FOR UPDATE` on a scope row â€” implementer's choice), counting committed spend *plus* live
   reservations. Two concurrent reservations against the same headroom can no longer both pass.
   The long-running work itself never holds the lock â€” parallel dispatch stays parallel
   (M4-F1 guard).
2. **Reservation amount** = the invocation's Â§2.2 budget allocation (dispatches), or the call's
   bounded worst-case cost (Manager reasoning calls, M6-F14 â€” derived from the request's token
   ceiling, not guessed). `plan_cycle` and `synthesize_results` reserve against the same cycle
   ceiling as dispatches; the Manager's own reasoning is spend like any other (D-003 "every
   unit of spend").
3. **Terminality releases.** A reservation resolves when its invocation/call reaches a terminal
   state â€” finalized to actual cost on success/failure-with-cost, released on refusal â€” riding
   D-001's guarantee that every invocation terminates. No TTL heuristics; a dead-lettered
   invocation's terminal result releases its reservation on the same path.

**Rejected:** SERIALIZABLE isolation for all ledger transactions (retry storms, penalizes reads);
relying on activity-end commit timing (the M6-F12 race, observed live: 1.40 committed against a
1.00 ceiling).

**Reversal cost:** medium. Ledger schema gains a reservation table/state; all spend paths route
through it. But D-003's semantics don't change â€” this is enforcement, not policy.

## M6-F12 â€¦ M6-F14 â€” found while implementing D-021 (M6-1b)

- **M6-F12 (open, escalated):** every D-003 ceiling is under-enforced across *concurrent*
  debits. Each `dispatch_capability` activity holds its own session and `kernel.services()`
  commits only when the activity finishes, so the pre-flight `SELECT sum(...)` in one dispatch
  cannot see a sibling's uncommitted reservation. Verified against the running Postgres, not
  inferred: two reservations of one cycle each read a spend of 0.00, both passed, and the
  committed cycle spend was 1.40 against a 1.00 ceiling. This is why the wake-cycle ceiling is
  proven here on sequential dispatch only â€” a cycle's three parallel dispatches can still
  overshoot it. Pre-existing (it applies to the business cap and the platform breaker equally);
  D-021 only made it observable, because before this the per-cycle branch never ran at all.
  D-003 says reservations exist precisely so "two concurrent invocations cannot both pass a
  check against the same remaining headroom", so the intent is settled and the mechanism is
  not: isolation level, row lock, or committing reservations in their own transaction are
  different trade-offs. **Not decided here** â€” it needs its own packet.
- **M6-F13 (open):** `load_cycle_context` is still unguarded. It runs *before* the cycle exists
  (D-021), so its failure has no cycle to record, and surviving it needs a policy for a Manager
  that cannot read its own context â€” park, back off, or reuse the last context â€” which is an
  unspecified mechanism, not an implementation detail. M6-F9's fix therefore covers the cycle
  body only; a load failure past its retries still fails the workflow.
- **M6-F14 (open):** the Manager's own reasoning is not charged to any ceiling. `plan_cycle` and
  `synthesize_results` call the provider directly through `_ask_model`, with no ledger
  reservation â€” but D-003 says "every unit of spend (model tokens and metered tool calls)"
  debits all four scopes, and those two calls are most of a cycle's cost. Â§2.1's per-cycle
  ceiling therefore bounds only what a cycle *dispatches*, not what it costs.

## M6-F15 â€¦ M6-F19 â€” found while implementing D-022 (M6-1d)

- **M6-F15 (bounded):** `CompletionRequest` has an output token ceiling but no input ceiling;
  reasoning-call reservations bound input by encoded byte length (strict upper bound, loose in
  the safe direction). A real input ceiling belongs with pricing work (M6-F16).
- **M6-F16 (open):** no per-token pricing exists â€” `Usage.cost_usd` is populated by none of the
  transports. Reasoning calls settle on reported tokens Ã— the configured price bound
  ($50/M in `BudgetSettings`, deliberately conservative); dispatch settles its reservation in
  full. Two settlement rules coexist; unify when real cost tracking lands.
- **M6-F17 (open):** activity retries of `plan_cycle` re-mint `cycle_id`, so a refusal caused by
  *accumulated* cycle spend can pass on retry against a fresh cycle scope. Candidate fix
  (deferred, D-021 amendment): derive the cycle key deterministically in the workflow as
  run-id + cycle counter â€” deterministic derivation, not minting, so D-004 holds. Bundle with
  M6-F13.
- **M6-F18 (open):** a worker dying between `reserve` and `settle`/`release` orphans a RESERVED
  row forever; D-022's terminality principle assumes a terminal result arrives, which process
  death defeats. Needs a reconciliation sweep (Â§9 territory). Bundle with M6-F13.
- **M6-F19 (config, resolved for dev):** with reasoning correctly charged, the $1.00 dev
  wake-cycle ceiling against $0.50 dispatch allocations admits one dispatch per cycle â€” a
  three-dispatch plan ends `BUDGET_EXHAUSTED`. Correct enforcement, wrong dev ratio. Manager
  call: local `.env` ceiling raised $1.00 â†’ $2.00 (a three-dispatch cycle fits at ~$1.53).
  Per-business production ceilings remain the owner's explicit choice at company creation
  (spec Defaults in Force), and the platform $500/24h breaker is untouched (owner-adjustable
  only).

## D-023 â€” a cycle's plan may sequence dependent dispatches
**Fills:** Â§2.1 ("the Manager MAY dispatch multiple capability requests in parallel" â€” silent on
dependencies; "workflow orchestration" and "capability coordination" are Manager duties);
resolves M6-F24

Found live in M6-2: every dispatch in a cycle is independent, so Compliance never sees
Content's draft, and the Affiliate type's only declared action (`affiliate.publish_post`) is
legitimately unreachable â€” the model's prose action types in M6-1 were it routing around this
gap. Decision:

1. The plan (model-proposed, platform-validated like everything else per D-013) may declare
   that an invocation consumes the results of named earlier invocations in the same cycle.
2. The workflow dispatches in dependency waves; invocations within a wave stay parallel
   (M4-F1 guard holds per wave). Cycles with no declared dependencies behave exactly as today.
3. A dependent invocation receives the declared prior results in its scoped request context â€”
   same business, same memory scope, an explicit grant per Â§2.2. Capabilities still never call
   each other (Â§2); only the Manager threads results between them.
4. D-001 (all invocations terminate within the cycle), D-021/D-022 (ceiling binds across all
   waves), and synthesis-waits-for-all are unchanged. A dependency on a FAILED/DEAD_LETTERED
   result makes the dependent invocation's dispatch a Manager decision recorded in the plan
   semantics: it is not dispatched, and synthesis sees why.

**Rejected:** capabilities invoking capabilities (Â§2 MUST NOT, worker-to-worker); synthesizing
an approvable action from results no compliance capability reviewed (that is the gap's shape,
not its fix).

**Reversal cost:** medium â€” plan schema + dispatch loop + prompts; no schema migration.

## M6-F20 â€¦ M6-F24 â€” found while proving the approval roundtrip (M6-2)

- **M6-F20 (fixed):** the operator API built `ApprovalService` without an event bus, so
  approve/deny published no `approval.decided` â€” D-006's loop was open at the only place a
  human closes it. All construction now routes through `kernel.build_approvals`, with a
  structural test forbidding direct construction.
- **M6-F21 (fixed):** `EventBus.claim` filtered by type only; the scheduler could hand one
  company another's events (Â§10 isolation; each leaked event is a paid wake). Claims are now
  business-scoped.
- **M6-F22 (fixed for affiliate):** `ensure_builtin_types` is version-gated, so config fixes
  never reached the Registry without a version bump; affiliate bumped 1.0.0 â†’ 1.0.1 (minor â€”
  A-003 resets graduation on major only). General staleness detection remains open.
- **M6-F23 (fixed, M6-2b â€” entry corrected per M6-4 audit):** the default-ceiling setting now
  has its reader (`container.build_provisioning` â†’ `ProvisioningService`) and the create-company
  API accepts an explicit ceiling. The residual gap is M6-F25 only (no per-company ceiling edit
  after creation).
- **M6-F24 (open â†’ resolved by D-023):** independent dispatches make the declared approvable
  action unreachable; see D-023.

## M6-F25 â€¦ M6-F27 â€” found while implementing D-023 (M6-2b)

Manager ratification first: M6-2b's latitude choices stand â€” 3-wave depth bound (cannot exceed
the plan item cap; depth is serial round-trips inside one ceiling), 8,000-char granted-output
truncation (pending a real input ceiling, M6-F15), any-order refs with explicit cycle
detection, ambiguous duplicate refs unaddressable (dependents dropped, the items themselves
run), positional refs when the model supplies none.

- **M6-F25 (open):** the ceiling reader is forward-looking only â€” the live Trailhead contract
  keeps its $1.00; no backfill or per-company ceiling-edit path exists. Fine for M6 (Summit
  Trail Gear at $2.00 is the live-run vehicle); a per-company edit surface is future operator
  work.
- **M6-F26 (open, widens M6-F16):** dependent invocations carry granted context that raises
  real input cost, but dispatch settles at the flat Â§2.2 allocation â€” the settlement gap grows
  with chained cycles. Unify at the pricing pass (M6-F16).
- **M6-F27 (accepted):** `idempotency_key` now varies with granted content â€” a publish derived
  from a different draft is a different action. Correct under A-001; noted as behaviour change.

## D-024 â€” the approved-action effect binding
**Fills:** D-015/Â§10 execution mechanics left open until M6-3; ratifies the three mechanisms
M6-3 introduced

1. **The effect payload is platform-composed from stored capability output** â€” the
   compliance-reviewed draft the cycle recorded â€” never re-authored by a model at execution
   time. Extends D-011/D-013's stored-values principle across the execution boundary.
2. **The effect destination is deployment configuration keyed by credential handle**
   (`JARVIS_TOOL_ENDPOINTS__*`), deliberately not an approval parameter an operator can correct
   nor anything a model can propose. Where an effect lands is an ops decision, not a runtime one.
3. **The A-001 idempotency key derives from the approval id** â€” stable across activity retries
   and workflow replays; one approval, at most one effect.

**Rejected:** payload re-authoring at execution (model prose crossing the Â§8 gate); destination
as an action parameter (M6-F30 â€” an operator "correction" could redirect an effect);
per-attempt invocation ids in the key (M6-F32 â€” a retry would publish twice).

**Reversal cost:** medium; these are now load-bearing for every future tool.

## M6-F28 â€¦ M6-F34 â€” found while closing the execution loop (M6-3)

- **M6-F28 (fixed):** no entrypoint ever fed secrets to the Kernel â€” `CredentialManager` was
  empty in production and the publish tool degraded to an unauthenticated POST (now it refuses).
- **M6-F29 (fixed):** `execute_approved_action` took tool, credential handle, and granted set
  from its own payload â€” the caller certified its own grant. Now derived from action type Ã—
  registry Ã— contract.
- **M6-F30 (fixed):** the destination came from operator-editable approval parameters
  (see D-024.2).
- **M6-F31 (fixed):** nothing called `execute_approved_action` â€” every approval since M6-2 was
  a row and nothing else. The approval-decided wake now executes before planning.
- **M6-F32 (fixed):** per-attempt invocation ids made the A-001 key vary â€” a Temporal retry
  would have published twice (see D-024.3).
- **M6-F33 (open, escalated):** no workflow-versioning convention â€” adding a command to a live
  path breaks replay of running histories; M6-3 terminated and restarted the Manager to ship.
  Needs `workflow.patched()` or equivalent as policy before any production posture.
- **M6-F34 (open):** an executed approval reaches the next planning prompt as raw
  `approval:<id>` text with no executed-signal â€” the model plans work to "clear" it. Prompt/
  context shaping needed.

## M6-4 / M6-5 verdicts and the REVISE round

M6-4 (architecture audit): **MERGE WITH FOLLOW-UPS** â€” slice verified against the live DB and
the pristine pre-M6 tree; no invariant test weakened; no decision contradicts the spec. Its two
code findings are packeted (M6-4a): the approval surface must show the effect payload the
operator is authorizing (D-011's threat model now covers `parameters` since D-024.1 made them
the published bytes; graduation must not fire on sight-unseen approvals), and Manager
activities must assert derived identity (D-002) where a payload-selected id reaches a
contract/credential/effect. Doc rot (HANDOFF, DEPENDENCIES) and the M6-F23 entry are corrected
this round. Â§12.5-at-runtime and M6-F34 are bundled into the pending resilience/prompt packet.

M6-5 (product review): **REVISE** â€” packeted (M6-5a). Blocking item: the dashboard renders
blank (a listener bound to a nonexistent element id halts all subsequent script, including the
initial paint). Re-review required after fixes.

**D-020 amendment (Manager decision, from M6-5 finding 5):** sustained zero goal-attainment
must pull the health *band* down, not just the score â€” a business with configured KPI targets,
attainment 0, and at least 5 completed cycles since activation caps at `watch`. A company that
ships nothing is not "healthy" no matter how untouched its budget is; same principle as the
stuck-work cap, same mechanism.

## D-025 â€” audited refusals commit independently; Postgres-backed tests gate what SQLite cannot see
**Fills:** Â§10/Â§11 (a denial that leaves no record is invisible); ratifies M6-4b's mechanism;
resolves M6-F38/M6-F40's decision

1. **Own-transaction denial writes** (M6-4b, ratified): an audit record of a refusal commits in
   its own short transaction before the refusal propagates â€” same pattern family as D-022's
   reservation transactions. A failed denial-write is logged and swallowed: losing the record
   is bad; losing the refusal is a Â§10 breach. Sites that raise only after their session scope
   closes cleanly are exempt and allowlisted in the AST sweep test, with reasons.
2. **Postgres test lane** (resolves M6-F40): SQLite substitution cannot observe independent
   commits (StaticPool sweeps the caller's work in; file-backed locks block the write), so
   correctness of D-022 and D-025.1 is gated by Postgres-backed tests (marker-gated, running
   against the local stack â€” the pattern `test_budget_reservation_concurrency.py` already
   uses). conftest's "nothing depends on a Postgres-only feature" claim is corrected to name
   this exception explicitly. When the stack is down those tests skip visibly â€” skipped is
   reported, never counted as verified (M5-F5 discipline). Implementation folded into the
   resilience packet.

## M6-F39 â€¦ M6-F42 â€” found while fixing denial persistence (M6-4b)

- **M6-F39 (fixed):** `ToolExecutor`'s unpermitted-tool refusal was never audited at all â€” a
  Â§10 refusal indistinguishable from a cycle that quietly did less.
- **M6-F40 (open â†’ resolved by D-025.2):** the SQLite suite cannot observe independent-commit
  behaviour; Postgres lane decided.
- **M6-F41 (fixed):** two tests silently stopped testing their stated property when the new
  refusal fired first (M5-F5 class); fixtures corrected with reasons in-test.
- **M6-F42 (open):** `CredentialManager` refuses without any audit (holds no session by
  design); defence-in-depth behind the pool's audited check. Give credential refusals a record
  or document sufficiency â€” resilience packet.

## M6-F43 / M6-F44 â€” found in the REVISE round (M6-5a)

- **M6-F43 (fixed):** the Registry wrote raw lifecycle enum values into operator-visible
  Decision Log text ("moved from provisioning to active") â€” fixed at the write path with
  D-007's labels, plus the new render-boundary guard catches the class.
- **M6-F44 (accepted for now):** `/api/health` existed only under the shell topology; fixed for
  `jarvis.api.server` by duplicating the three checks locally, because sharing `shell/preflight`
  would be a milestone-layering violation (shell is M5, api is M3). Accepted as a flagged
  duplication; unifying it (moving the checks down a milestone) is a future architecture call.
- The M6-5 "mojibake" finding was investigated to the bytes (hex dump of the live row, JSON
  encoding, static charset, fetched bytes â€” all clean UTF-8): a reviewer-terminal rendering
  artifact, not a product defect. No fix applied; recorded so nobody chases it again.

## M6 closure â€” both gates cleared

M6-4 (architecture): **MERGE** â€” follow-ups closed by M6-4a/M6-4b or formally recorded.
M6-5 re-review (product): **SHIP WITH FOLLOW-UPS** â€” the blocking blank-dashboard defect is
gone; the slice is walkable end to end against real data. Milestone report:
`docs/reports/M6.md`.

Product follow-ups carried into the next surface milestone (from the re-review, in its
priority order â€” F1 first, it is the second round on the same complaint):
- **F1:** notification queue must reconcile against reality on read (approval-linked notes
  whose approval isn't pending don't render); today only the decide route resolves them, so
  the expiry path strands notifications permanently.
- **F2:** drop stripped ids with their parenthetical ("(something)" reads as a bug).
- **F3:** "Doing now" renders past-tense post-mortems under a present-tense label; cap at word
  boundary + rename or render present activity.
- **F4:** create-dialog error styled as a timestamp; use the existing `.formErr`.
- **F5:** sub-stall healthy band shows a green bar over "Behind on its goals" â€” wording must
  agree with the band.
- **F6:** notification bodies bypass the render boundary (a 40-word model paragraph renders
  raw); route the strip through the same laundering as cards and feed.
- Runtime Â§12.5 guard term list needs morphological coverage ("woken" vs "wake cycle",
  "business" vs "company") â€” fold into the same packet as F1/F6.

Open engineering ledger at closure (all recorded above, none blocking a dev-posture slice):
M6-F13, F16, F17, F18, F25, F26, F33 (must close before production posture), F34, F42, F44,
D-025.2 implementation (Postgres test lane).

## M6 notes â€” accepted during the typing pass, not defects

- M6-0f's `TypeGuard` narrowing in `jarvis/manager/activities.py` means malformed-shape LLM
  JSON (e.g. a non-dict list element) now degrades (skip/empty) instead of crashing. Accepted:
  consistent with the file's stated degrade-rather-than-raise philosophy and with D-013 (the
  model proposes; the platform validates). No test exercised the old behaviour.
- Suite size: HANDOFF's "229 tests" was a count of test functions; pytest collects 394 (now 399
  with M6-0 regression tests) because of parametrization. The larger number is the real one.
- Flagged for the M6-4 audit: `execute_approved_action` derives its business from the approval
  row rather than `RuntimeIdentity` â€” audit against D-002.

---

## D-026 â€” the development organization runs on lanes, worktrees, and a merge queue

**Fills:** nothing architectural â€” a process amendment under the D-019 bar, justified by a
demonstrated failure: M6 ran ~95% serialized because the environment (single tree, single live
stack, shared gate state) forced it, as measured in `docs/reports/SUBAGENT-ORG.md`.

Adopted, owner-approved: (1) implementation packets run in per-lane git worktrees with lane
gates before merge and main gates after (a packet is done only when the merged result passes);
(2) live verification parameterizes the shared stack per lane (database, Temporal namespace,
API port) via `scripts/lane_env.py`, with Postgres-backed tests marker-gated and visibly
skipping when the stack is down (implements D-025.2); (3) the Manager merges one lane at a
time in dependency order, and serial resources (migration numbers, finding-number ranges,
shared conftest, dependency manifests, the static dashboard file) are allocated at
packet-writing time. Full protocol: DELEGATION.md "Lanes, worktrees, and the merge queue".

**Rejected:** repository restructuring for parallelism (no evidence of file-level contention;
Â§14/D-019 forbid the speculation). M7 pilots the workflow at 2 implementation lanes.

**Reversal cost:** none â€” process only; reverting is a DELEGATION.md edit.

---

## M7-F1 â€¦ M7-F4 â€” the D-014 verdict (M7-1, wave 0 of the pilot)

The Finance Tracking type is pure data and passes the same AST gate as Affiliate â€” D-014
holds for the type itself. The gaps are in the platform, exactly where a second type would
find them:

- **M7-F1 (escalated â†’ Manager decision):** `ensure_builtin_types` hardcodes AFFILIATE; a
  second built-in cannot reach automatic startup install. Decision: minimal composition-root
  fix in wave 1 (a BUILTIN_TYPES tuple iterated with the existing version gate) â€” container.py
  is a permitted exception (DEPENDENCIES layering), and this is demonstrated need, not
  framework speculation. The general multi-type installer remains M8 design input.
- **M7-F2 (informational):** KPI_THRESHOLD_BREACHED would suit this type but is excluded per
  the owner-approved schedule-only scope. Revisit only with an owner scope change.
- **M7-F3 (open, routed to M7-3):** no contract/create field for per-instance "which metrics
  to track" or KPI overrides. M7-3 uses existing contract KPI-target mechanisms; if no path
  exists, that is an escalation and M8 evidence â€” not a schema to invent mid-milestone.
- **M7-F4 (confirmed by test):** same-version reinstall raises DuplicateBusinessError; the
  version gate correctly lives in the caller (reinforces M6-F22).

Naming ratified: `finance_tracking` (avoids colliding with CapabilityType.FINANCE). The
compliance_requirements draft awaits owner sign-off before any Finance company launches â€”
recorded in the M7-1 report; launch is blocked on it, merge was not.

## M7-F10 â€¦ M7-F14 â€” surface follow-ups round (M7-2, wave 0)

F1/F2/F6 and the term-guard morphology are fixed and live-verified (the strip showed 3
phantom "needs your OK" rows against an empty approval queue before; empty and truthful
after). Worker latitude ratified: bare "wake"/"wakes" stays allowed (ordinary English, no
demonstrated failure); D-007 concepts enforced by construction are not text-matched.

- **M7-F10 (open):** two live notification link_refs point at approvals that never persisted â€”
  symptom fixed by reconciliation-on-read; provenance unexplained. Watch item.
- **M7-F11 (open):** ProviderError.default_operator_message contains raw "retrying", never
  guard-tested.
- **M7-F12 (open):** scripts/gates.sh gate 2 carries its own copy of the FORBIDDEN vocabulary,
  now out of sync with the 17-term test list â€” single-source it in a future packet.
- **M7-F13 (open):** health_reason bypasses the render boundary via _company_payload; whether
  it can carry model prose is unverified (kpi/ was out of M7-2 scope).
- **M7-F14 (ratified):** narrow term-list scope was the right call; blanket-banning D-007
  component words risks false positives beyond demonstrated need.

Wave-0 pilot data (D-026 meta-goal): two lanes ran concurrently (M7-1 ~11 min, M7-2 ~24 min,
fully overlapping); merge conflicts: 0; both merges composed green on first try (643 â†’ 660).

---

## M7 owner decision â€” compliance requirements approved (revised), launch unblocked

The owner approved the Finance compliance requirements 2026-07-26 with revisions that scope
the restrictions to M7 rather than defining the type permanently: observation-only during M7
(collect data, calculate KPIs, evaluate portfolio health, produce research reports); no orders,
order modifications, fund transfers, or brokerage writes during M7; figures cite a source,
come from an approved provider, or are marked estimated/unavailable; access only what the
architecture and isolation rules authorize; M7 reports are informational, not financial/
investment/legal/tax advice. The owner explicitly directed that "Finance will never recommend
trades" NOT be permanently encoded â€” the long-term roadmap includes recommendation, brokerage
management, and execution.

Manager flag, recorded so it is not forgotten: rule 3's condition ("once the architecture
explicitly enables those capabilities") is the operative gate. The spec currently routes
recommendation/execution through the Trading Analysis (Step 5) and Live Trading (Step 7)
types, and Â§8's hard constraints (approval-by-default for capital actions; no autonomy
graduation for trade execution in v1; live trading last) bind any future Finance evolution.
Enabling Finance to recommend or execute is therefore a Â§12 spec amendment owned by the owner
when its milestone arrives â€” not something a packet may infer from this approval.

---

## D-027 â€” KPI values are measured by the cycle, from platform facts, per type-declared mappings
**Fills:** Â§5 (KPIs as a contract field with no writer), Â§13 Step 3 ("exercises KPI/dashboard
pattern"); resolves M7-F21, the M7 live run's central finding: `kpi_values` has never held a
row â€” targets are set at creation and never measured, so attainment is structurally zero.

1. A dedicated Manager-cycle activity (`record_cycle_kpis`, after synthesis, before the
   decision record) writes KPI observations on every completed cycle. An activity, so D-004
   holds; recorded results, so replay holds.
2. Observations derive ONLY from platform facts â€” cycle outcomes, capability result metadata,
   ledger rows, an in-activity clock read â€” selected per **mappings declared in the type
   definition as data** (D-014 preserved). Model prose never becomes a KPI value (D-011
   spirit; Finance compliance rule 4: figures cite a source or are marked estimated).
3. A type with no declared mappings records nothing. This packet authors Finance's mappings;
   Affiliate's are a recorded follow-up, not silent scope.
4. With measurement real, health wording must agree with the band on young companies: below
   the stall threshold the summary reads as "just getting started", not "Behind on its goals"
   (closes M6-5 F5 recurrence, M7-F26).
5. Minimal M7-F22 closure rides along: the planning prompt includes the business type's
   stored compliance_requirements verbatim â€” owner-approved stored values, not model prose.

**Rejected:** deferring measurement to M8 (would close M7 against Â§13 Step 3's stated purpose
with an empty kpi_values table); capability-result contract changes (Â§2.2 surgery not needed
for v1 measurement); model-reported KPI numbers (unauditable, violates compliance rule 4).

**Reversal cost:** low-medium â€” one activity, type-data mappings, no schema change
(`kpi_values` exists and is empty).

## M7-F20 â€¦ M7-F27 â€” the wave-1 live run (M7-3)

- **M7-F20 (blocking, environmental):** the Anthropic credential is rejected (401, verified at
  the API level; $0 spent). Likely the recommended rotation occurring â€” the owner replaces the
  key in `.env` directly; it must never transit chat again. Live cycle re-run (M7-3c) waits.
- **M7-F21 (open â†’ resolved by D-027):** no production caller of `KpiEngine.record`, ever.
- **M7-F22 (open â†’ minimally closed by D-027.5):** compliance_requirements were stored and
  read by nothing.
- **M7-F23 (fixed, M7-3):** pre-approval "never recommends" survived in the type description
  and docstring; corrected to present-tense fact, guarded by a no-"never" test.
- **M7-F24 (closed):** per-instance KPI-target path confirmed absent; suggested-target copy
  works and is the v1 mechanism (M7-F3 resolved).
- **M7-F25 (open, corroborates M6-F17):** retry re-mints cycle_id â€” now observed live (three
  reservations RESERVEDâ†’RELEASED across three plan_cycle attempts).
- **M7-F26 (open â†’ resolved by D-027.4):** healthy band beside "Behind on its goals" on a
  zero-cycle company.
- **M7-F27 (verified good):** M6-F9 cycle-failure containment held for a second business type
  â€” FAILED cycle recorded in operator language, Manager parked alive on its wake timer.

## M7-F40 â€¦ M7-F44 â€” reserve surface round (M7-R1)

F3/F4 from the M6-5 re-review closed: word-boundary truncation with a "more in Details"
affordance, the card label renamed "Latest update" (content and label now agree â€” the
present-activity alternative would have crossed into jarvis/manager/, correctly declined),
and the create-dialog error now uses the risk-coloured .formErr above the buttons. All
live-verified on :8110. M7-F44 (open, trivial): a stale "Doing now" comment near
jarvis/api/app.py:506 â€” one-line cleanup for whichever lane next touches app.py.

## D-027 implementation notes (ratified) and M7-F30 â€¦ M7-F36 (M7-3b)

Ratified into D-027: the mapping vocabulary is `KpiSource` (an enumeration of platform facts)
+ `KpiMapping`, living in `jarvis/domain/kpi.py` so M4 and M5 packages can share it without a
forward import; `CycleContext.measures_kpis` gates the cycle activity and is a recorded
result, which is what makes old histories replay honestly (negative control proves the gate
is load-bearing). A source is an enum, not an expression â€” the platform owns the arithmetic.

- **M7-F30 (open, scheduled M7-3d):** attainment is direction-blind â€” `data_freshness_hours`
  is lower-is-better, so fresher data scores *worse* (1h against a 24h target reads 4%).
  Needs a direction on `KpiTarget` + engine comparison + finance data update. Pinned by a
  characterization test that fails when fixed.
- **M7-F31 (open):** mature-company partial attainment still reads "Behind on its goals."
  beside a healthy badge â€” M7-F26's class, outside D-027.4's young-company wording.
- **M7-F32 (open):** idle/failed cycles record nothing, so freshness stops being re-observed
  exactly when staleness sets in. Watch item; a measurement-on-idle policy is a D-027
  amendment if it bites.
- **M7-F33 (open, judgement):** `reports_delivered` counts every SUCCEEDED result â€” a
  research+finance cycle scores 2 for one report. Capability-scoped mappings would change the
  metric's meaning; deliberately not decided inside the packet.
- **M7-F34 (fixed):** `KpiEngine.record` was never in the deferred-completion ledger â€” four
  milestones of invisible debt; row added and retired.
- **M7-F35 (informational hazard):** a future type declaring mappings AND subscribing to
  KPI_THRESHOLD_BREACHED would re-wake itself from its own measurement (M6-F10's shape). Not
  reachable today; install-time validation is the candidate guard.
- **M7-F36 (verified good):** the version gate held for the second type â€” 1.0.1 bump required
  for the live registry to adopt mappings, exactly as designed.

## M7-F55 â€¦ M7-F59 â€” attainment direction round (M7-3d)

M7-F30 closed: `KpiDirection` on `KpiTarget` (additive, default ABOVE â€” stored contracts
proven compatible by snapshot test, no migration), direction-aware attainment, Finance
freshness declared BELOW, type at 1.0.2 (version gate held a third time, M7-F57). Zero-actual
on a BELOW target scores full attainment â€” ratified: zero is the best possible reading for a
lower-is-better metric (M7-F56). M7-F31 (mature partial-attainment wording) and M7-F33
(reports_delivered semantics) remain the two open KPI items, deliberately.

## M7-F45 â€¦ M7-F54 â€” the live Finance cycle (M7-3c)

The milestone's live proof: two COMPLETED cycles on Portfolio Watch, the first kpi_values
rows ever (reports_delivered 3, data_freshness_hours 0.0005, metrics_tracked 3), attainment
0 â†’ 45 on the dashboard, 7/7 compliance rules asserted at the outbound prompt boundary,
zero approvals, affiliate evidence checksum-identical, live history captured as a second
replay fixture with its own negative control. Spend $0.1169. D-023 waves and D-013
degradation held for a second business type (M7-F54); version gate held on the upgrade path
(M7-F47).

- **M7-F45 (open, defect â€” Manager direction recorded):** cycle context loads BEFORE the
  wake, so the first cycle after any type upgrade runs on a snapshot up to a wake-period old
  (observed: cycle 1 measured nothing; cycle 2 measured). Direction: load context after the
  wake â€” D-021 already says the cycle begins when planning begins, and a pre-wake load
  contradicts that spirit. Workflow-shape change with two replay fixtures to keep honest â†’
  its own packet, scheduled by the M7-4 audit's verdict (REVISE item or early-M8).
- **M7-F48 (open, trivial):** `installed_at` not refreshed on upgrade; one-liner for the next
  registry lane.
- **M7-F49 (open, judgement):** `metrics_tracked` measures the contract's own target count
  against a target of 5 â€” structurally capped at 60% as shipped. What it should measure is a
  D-027.2 meaning question; with M7-F33 for the D-027 amendment pass.
- **M7-F50 (open, Â§12.5-adjacent):** model prose reaches the operator feed unfiltered and now
  echoes internal framing ("the M7 targets"). Joins the runtime-Â§12.5 thread (M6 audit
  finding 5, M6-F34): whether Decision Log narrative should be platform-rendered is a D-011
  extension question for M8.
- **M7-F46/F47/F51â€“F54 (verified good):** D-027 end-to-end; upgrade-path version gate;
  M7-F30/F31/F33 confirmed live exactly as predicted (F30 since fixed in M7-3d).

---

## M7-4 / M7-5 verdicts, and audit-required corrections to this record

M7-4 (architecture): **MERGE with follow-ups** â€” D-014 survived as "a type is data" (three
generic changes landed, all data-shaped, all demonstrated need â€” the honest phrasing, vs the
plan's "zero changes"); D-027 sound; compliance framing holds in code (approvals/capabilities/
security untouched across the whole span); the D-026 pilot strengthened rather than weakened
discipline (8 merges, 3 unplanned lanes each packeted before code).

M7-5 (product): **REVISE** â€” packeted as M7-5a: (1) a company's kind and the Finance
read-only sentence are invisible after creation (all three companies render identically);
(2) `health_parts` â€” the plain-language KPI components the API computes on every card
request â€” is consumed by nothing in the repo; the first measured KPIs reach the operator
nowhere.

**Correction (audit F-A) â€” M7-F55 overstated "M7-F30 closed":** the direction field applies
only to companies created after type 1.0.2. Contracts snapshot `default_kpi_targets` at
creation and no refresh path exists (M7-F24), so Portfolio Watch's stored targets carry no
direction and its freshness still scores ~0% â€” the live "attainment 45" is the UNFIXED
arithmetic ((0.6 + 0.00002 + 0.75)/3); with direction it would be 78. Contract-refresh-on-
upgrade is an open design question for M8 (with M7-F45); no refresh mechanism is to be
invented inside M7.

**Correction (audit F-B) â€” M7-F45 is the whole pre-wake snapshot:** the stale load also
carries `day_ordinal` (drives D-021's daily wake allowance) and `wake_cycle_ceiling_usd`,
not just `measures_kpis`. Not an authorization hole (lifecycle re-checked in-activity,
M6-F1's fix). The fix packet must scope to the full snapshot.

**Correction (audit F-C) â€” M7-F50's cause:** D-027.5 injects the owner's rules verbatim and
four begin "During M7", so the milestone label reaches operator prose BY CONSTRUCTION. The
term guard cannot and should not catch the rules themselves; M8 weighs both ends (prompt
shaping vs platform-rendered narrative, the D-011 extension).

**M7-F60 (new, from M7-5):** "Finishing its work: 100" rendered beside three consecutive
failure narratives â€” invocation-success is not useful-output. Honest by the metric's
definition, misleading to a human. D-027-amendment / capability-result-semantics input for
M8; display-side wording may mitigate but must not fake a metric that does not exist.

## M7-F61 â€¦ M7-F66 â€” the REVISE round (M7-5a)

Both REVISE defects fixed and live-verified: company kind on cards + read-only sentence in
Details (stored type data, no new write path); health parts + goals drill-down rendered in
Details (card keeps one meter, one sentence â€” ratified). F53's root cause was _summarise
never seeing the overall score (M7-F61, fixed: "Healthy overall â€” goals need attention.").
"Rounds completed" replaces "Finishing its work" (M7-F60 wording half; metric semantics
untouched). Guard gains word-boundary M6/M7/M8/KPI/KPIs, model-prose paths only â€” a
regression pin proves the owner's stored compliance rules stay OFF the guard path (they
legitimately contain "During M7"). M7-F44 closed in passing.

Newly *visible*, not newly created, both recorded for M8's contract-refresh design: M7-F62
(Portfolio Watch's pre-1.0.2 stored target renders "goal is at least 24 hours" â€” backwards
for freshness), M7-F63 (the 3-of-5 structural cap now shows as measured-vs-goal). M7-F65:
two of three companies necessarily share a kind label until a third type exists.

## M7 closure â€” both gates cleared

M7-4 (architecture): **MERGE with follow-ups** â€” the one tag-blocking item (correct the
M7-F55 overstatement) is recorded above. M7-5 (product): after two narrow REVISE rounds,
final verdict **SHIP** â€” all fixes live-verified, no regressions, M7-F62 explicitly ruled
non-gating. Fix-round findings M7-F67 (false "Rounds completed" label â†’ dynamic stuck-work
reading), M7-F68 (scale + stutter), M7-F69 (escaping + card/drill-down agreement) all fixed.
Milestone report: docs/reports/M7.md.

Open ledger at closure, all scheduled: M8 design inputs â€” general builtin installer (M7-F1),
pre-wake snapshot staleness (M7-F45+F-B), contract-refresh-on-upgrade (F-A/M7-F62/M7-F24),
D-027 amendment pass (M7-F33/F49 metric semantics, M7-F32 idle-cycle measurement, M7-F60
result-usefulness), D-011 extension for feed prose (M7-F50/F-C), M7-F48 (installed_at),
M7-F65 (third type resolves naturally). Carried M6 ledger unchanged; M6-F33 workflow
versioning remains required before any production posture.

---

## D-028 â€” M8 approved: spec v1.5 (Manager personas), experience-engineer, design system as artifact

Owner approved the M8 plan (docs/reports/M8-PLAN.md) 2026-07-27 with amendments, all applied:
1. **Spec v1.4 â†’ v1.5, owner-authorized:** Â§12.5's Business Manager row changes from
   "invisible" to "MAY be represented as a named operational persona" (responsibility,
   ownership, current activity, health, workload) â€” an abstraction layer; internal worker
   architecture (workers/capabilities/prompts/workflows and all Â§12.5 forbidden vocabulary)
   remains invisible. D-007's manager row is superseded accordingly. Target experience:
   "supervising a team of executives, not monitoring background processes."
2. **experience-engineer** joins the roster: owns design system, application shell, workspace
   layout, interaction patterns, information hierarchy, visual consistency, motion, premium
   polish â€” architecture-aware. operator-surface-engineer retains operator copy, D-007
   translation, rendering boundaries, Â§12.5 implementation, presentation correctness. The
   split is deliberate and stays.
3. **The Design System is a permanent platform artifact** (docs/design/): principles, color,
   typography, components, layout, spacing, iconography, motion, accessibility, interaction
   patterns â€” carrying architecture-documentation weight; future UI extends it, never
   reinvents.
4. **Product identity framing:** M8 establishes Jarvis's permanent product identity (how
   operators understand the platform, how companies and managers are experienced); the
   Premium UI Concept is the north star for craftsmanship, not a pixel spec.
5. **Engineering discipline unchanged** â€” all D-026 practices, reviewer independence,
   escalation discipline, and governance carry forward at full strength.

## M8-F1 â€¦ M8-F8 â€” the framework design round (M8-1, Lane A)

Design merged: docs/design/PLUGIN-FRAMEWORK.md (614 lines) â€” injected catalog, three
refresh bands (live / consented / never), packaging unchanged (D-014 stands), the closed
type-parameter surface enumerated. D-029â€¦D-032 drafts await Manager review at wave-1
packet-cutting; both escalations correctly frozen for v1 (permission/autonomy refresh = Â§10
widening, security-engineer's call; A-003 graduation-reset implementation = its own decision).

- **M8-F8 (open, ledger miss):** A-003's major-version graduation reset is documented in four
  places, schema-backed (`plugin_major_version` column), and has ZERO readers/writers â€” the
  M7-F21 shape again, and again absent from the deferred-completion ledger. Ledger row to be
  added; implementation belongs with the refresh mechanism packet.
- **M8-F1 (open):** `ensure_builtin_types` catches `RegistryError` but `install()` raises
  sibling `ConfigurationError` â€” one bad built-in aborts the loop; containment intent
  unachieved. Wave-1 catalog packet.
- **M8-F3 (open):** live affiliate v1.0.1 definition JSON predates D-027 (no kpi_mappings
  key) â€” M6-F22's drift, now concrete; the refresh mechanism's second live subject.
- **M8-F7 (routed cross-lane):** planner reads kpi_targets from ManagerState seeded at start
  â€” stale up to 100 cycles under refresh; folded into M8-3's post-wake CycleContext work
  mid-flight (warm relay).
- M8-F2 silent install skips; M8-F4 (M10's real dependency is KpiSource membership, not
  packaging); M8-F5 (prose-in-Python future trigger); M8-F6 (Band B target rule expires with
  per-instance editing). All scheduled in the design's Part 9 packet cut.

---

## D-033 â€” changes to a live workflow path are versioned, not restarted
**Fills:** M6-F33 (the standing pre-production requirement); ratifies M8-3's convention

Any change to the commands `BusinessManagerWorkflow` issues on a path a running execution can
reach ships behind `workflow.patched`, id declared as a `PATCH_*` constant, one id per branch,
never a literal. Recorded-result gating (D-023/D-025/D-027) remains correct where the
platform's own answer for an old history is still the old one; versioning is what remains when
it is not. Terminating and restarting a Manager to ship (as M6-3 did) is not available once a
business has work in flight. Enforced by `tests/test_workflow_versioning.py`, including a
frozen inventory of the nine activities the workflow may schedule. Retroactive audit: exactly
one shipped change would have required it â€” M6-3's `execute_approved_action` wiring, the one
that forced the restart. First patch in force: `PATCH_POST_WAKE_CONTEXT` (M8-3).
**M6-F33 is closed.**

## M8-F40 â€¦ M8-F48 â€” workflow hardening round (M8-3, Lane C)

M7-F45 fixed at FULL scope (F-B): the wake reads what the wake needs; the cycle reads its own
snapshot after the wake â€” a type upgrade applies on the first post-upgrade cycle (tested);
a pause landing mid-wait no longer buys a paid planning round (M8-F41); M8-F7 folded in
mid-flight (kpi_targets ride the post-wake context; M8-F43). Both fixtures replay unedited;
negative controls name their divergence. Tests 734 â†’ 754.

Open, scheduled: **M8-F44** (the reload doubles M6-F13's reachable surface â€” the context-load
failure policy is now due, resilience wave); **M8-F45** (wake reasons dropped for a
non-dispatchable business, incl. a decided approval â€” D-008/D-024 question, needs a decision
before the refresh surface lands); **M8-F46** (ManagerState.kpi_targets vestigial â€” retire
with the refresh mechanism, D-005 note); **M8-F42** (CycleContext.wake_cycle_ceiling_usd read
by nothing â€” drop at next touch); **M8-F48** (first patch: deprecation only after no
pre-M8-3 execution remains queryable).

## M8-F20 â€¦ M8-F27 â€” design system round (M8-2, Lane B)

UI Phase 1 merged: twelve docs/design/ documents (permanent artifact per D-028.3), three-tier
token architecture (components fenced to semantic tokens BY TEST â€” the mechanism that keeps
both themes true), 620-line monolith â†’ 12 ES modules behind a 46-line shell, delegated event
handling, four-tile stat row. Dark-first with light as a complete alternate â€” ratified.
No build step (Phase-2 retrospective decides, per plan). Persona components ship as spec+CSS
with a test asserting nothing emits them until persona data exists.

- **M8-F26 (fixed, process-grade):** after decomposition the Â§12.5 static gate would have
  passed VACUOUSLY â€” three consumers regexed a now-absent inline script.
  tests/surface_sources.py centralizes the surface definition and asserts non-empty inputs;
  both failure modes proven by execution. This also subsumes M7-F12's single-sourcing need
  for the term list's consumers.
- **M8-F20/F22/F24/F25 (fixed):** light-theme AA failures corrected by measurement; reduced-
  motion now covers transitions; three unescaped fields closed; the "Full details" toggle had
  been binding the wrong element and never loading.
- **M8-F21 (open):** webfonts from a third-party CDN in a local-first app â€” self-host at M8-4.
- **M8-F23 (open, deferred to M8-4):** modal traps no focus, no restore â€” a real WCAG 2.4.3
  failure, owned by the shell packet. **M8-F27:** 26px small buttons, same home.
- Tile copy is placeholder-quality â€” operator-surface pass owed (the D-028 split working as
  designed).

---

## D-029 â€¦ D-032 â€” the plugin framework decisions (ratified from the M8-1 design)

Ratified as drafted in docs/design/PLUGIN-FRAMEWORK.md Part 8 (authoritative for detail):
**D-029** type data reaches a company through three bands â€” A live-by-installation, B
snapshot-refreshed-with-operator-consent (kpi_targets, type-owned wake_conditions,
compliance_requirements), C never (identity, budget, capability_permissions,
autonomy_policies, graduation); the line is authority. **D-030** refresh consent happens on
the company, never through Â§8's approval queue â€” an action_type would attach a graduation
counter to configuration changes. **D-031** the built-in catalog is an injected sequence and
that injection is the whole plugin extension path; validation generalizes to the three
evidence-backed checks; same-version drift is detected, never auto-installed. **D-032** the
type-parameter surface is closed and enumerated (design Part 1); a type field requiring the
platform to execute type-authored logic reopens D-014 and is an escalation.

## UI Phase-1 gate: PROCEED

Product reviewer verified the token discipline is real (zero raw hex, zero tier-1 reaches in
components.css), both themes complete, the tile row honest (the concept's milestone tile was
DROPPED rather than faked â€” principle 3 surviving contact), and every M7 surface outcome
intact. Three contract debts fold into M8-4: ten inline style sites off the 4px scale in the
JS modules; 06-components.md documents `.entry__why` which exists nowhere (doc-vs-code
mismatch in an "extend, don't reinvent" system); naming half-migrated (BEM beside flat
legacy). All invisible to the operator; all inherited first by the Shell.

## D-034 â€” resilience policies (resolving the deferred ledger for wave 1)

1. **Context-load failure (M6-F13, M8-F44):** past retries, the Manager parks in a recorded
   degraded state â€” best-effort Decision Log entry in operator language, notification
   surfaced, waits for its next wake. It never dies and never loops hot. Same containment
   family as M6-F9.
2. **Cycle key on retry (M6-F17, M7-F25):** the cycle key derives deterministically in the
   workflow (run id + cycle ordinal) â€” derivation, not minting, so D-004 holds â€” and
   activity retries share the cycle's budget scope. Amends D-021's minting note; plan_cycle
   keeps minting only the audit-facing id if the two must differ, but the LEDGER scope key is
   the deterministic one.
3. **Orphaned reservations (M6-F18):** a scheduler-owned reconcile releases-and-audits
   RESERVED rows whose invocation reached a terminal state, with an age bound as backstop â€”
   a D-022 addendum: terminality remains the principle; the reconcile is the safety net for
   process death.
4. **Credential refusals (M6-F42):** audited via the D-025 independent-commit path from the
   pool side, closing the last unaudited Â§10 refusal.

## M8-F60 â€¦ M8-F62 â€” catalog and drift round (M8-1b, wave 1 Lane A)

D-031 implemented per the design: injected catalog (jarvis/businesses/catalog.py), JarvisError
containment with audited skips, the three validations, digest-based drift detection
(detection only), installed_at on upgrade (M7-F48 closed). Worker latitude ratified: digest
stored inside plugin_metadata (no schema change); plain audit-event/field naming. Tests 784.

- **M8-F60:** the live affiliate drift case confirmed read-only â€” the detector will flag it
  on first post-merge sweep; packet C's refresh is the fix path.
- **M8-F61 (open):** not_ready_count has no UI consumer â€” packet D wires the operator view.
- **M8-F62 (note):** SQLite tz-preservation quirk on DateTime(timezone=True) â€” Postgres
  unaffected; note for future timestamp tests.

## M8-F79 â€¦ M8-F84 â€” Application Shell round (M8-4, wave 1 Lane B)

UI Phase 2 merged (790 tests on main): rail + routing + focus containment, four REAL
workspaces (Command Center, Companies, Approvals, Settings); Managers/Goals/Activity/Audit
reserved in the design doc and emitting nothing â€” "a nav item is a promise that a
destination exists," enforced by a bidirectional railâ†”pane test. Single-active-workspace
painting eliminates duplicate-id risk on approval corrections. All six inherited debts paid;
M8-F79â€“F82 fixed in-lane.

Manager rulings on the two flagged items: (1) **Audit stays level 3** â€” Â§11.5's ladder is
architecture, not preference; a top-level Audit destination would invert it. Reserved slot
remains reserved. (2) **Font vendoring needs owner sign-off** (M8-F21 closed by deleting the
CDN; the display face currently rests on fallback+weight â€” vendoring the OFL binaries is a
one-commit follow-up the owner must approve since it ships third-party assets into the repo).

Open: **M8-F83** (background not inert behind an open sheet â€” assistive-tech audit follow-up);
operator-surface pass owed on new placeholder copy (top-bar status words, notification-center
and parts-of-app empty states, "Updates" label); cross-company Goals/Activity read endpoints
are an API-surface question for the workspace phase (M8-F70-series context in the report).

## M8-F85 â€¦ M8-F94 â€” resilience round (M8-7, wave 1 Lane C)

D-034 fully implemented (847 tests on main): context-load failure parks recorded/surfaced/
deduped and never dies (D-034.1); the deterministic cycle key ends the retry-scope leak
(D-034.2 â€” M6-F17/M7-F25 closed); the reservation reconcile runs in the sweep with release+
audit committing together (D-034.3 â€” M6-F18 closed); credential refusals audited
independently (D-034.4 â€” M6-F42 closed). D-025.1 gained its Postgres-lane proof; conftest's
substitution claim now names both exceptions. No new patches needed â€” recorded-result gating
sufficed, correctly applied under D-033's own rule. Postgres-marked tests 6 â†’ 9, all executed.

Fixed in-lane: M8-F85 (park-loop spin, pinned), M8-F86 (activity inventory now tied to worker
registration). Open, scheduled for wave 2 as Manager decisions within existing decision
scope: **M8-F87** (cycles_completed never resets after the first continue-as-new â€” from cycle
100 every cycle continues; D-005 mechanism fix), **M8-F88** (cancelled dispatch orphans its
hold â€” cancellation handler per _ask_model's own pattern, D-022). Recorded: M8-F89 (parks
don''t count against the daily allowance â€” deliberate), M8-F90 (failed-planning cycles now
visible to the health count â€” a band may move; honest), M8-F92 (in practice the age backstop,
not terminality, does the reconcile work â€” D-022 expectation inverted, noted in its record),
M8-F93 (credential audit lives at the sole caller), M8-F94 (M8-F45 unchanged, pending owner).
Park operator copy owed to the product reviewer with the next surface pass.

---

## D-035 â€” pause is absolute; dropped wake reasons are surfaced, never silently lost
**Fills:** M8-F45/M8-F94 (D-008/D-024 interaction the spec leaves open)

A paused business's wake reasons are dropped, not queued â€” "Paused by you" means nothing
happens, full stop. But a dropped decided-approval reason generates an operator notification
("[Company] has an answered approval waiting â€” resume it to proceed") and an audit record.
The approval row persists unchanged, so resume + next wake acts on durable state (D-006
reload) and nothing is lost. **Rejected:** preserve-and-execute-at-resume (surprises an
operator who paused precisely to stop things); silent drop (today's behaviour â€” loses
information). Owner reviewed the options at the M8 wave-1 report and directed M8 completion;
decided within D-008/D-024 authority, conservative option.

Also decided for wave 2 (mechanism within existing decisions): **M8-F87** â€” continuation
resets the cycle ordinal at continue-as-new (D-005 state shape); **M8-F88** â€” dispatch gains
the cancellation handler `_ask_model` already has (D-022). Retrospective adopted as M9
operating model (owner directive): DELEGATION amendment AFTER m8-baseline, not during M8.

## Owner ratifications (M8 wave 2)

D-035 confirmed as Option B, scope broadened to ANY actionable wake reason arriving while
paused (not only decided approvals) â€” relayed to the running M8-10 lane mid-flight. Font
vendoring approved and done: three OFL families committed with license texts and provenance
(jarvis/api/static/fonts/); page hookup deferred one merge to avoid lane conflicts
(M8-F21 fully closes there).

## M8-F100 â€¦ M8-F111 â€” refresh mechanism round (M8-8, wave 2 Lane A)

Merged at 893 tests. Ratified: **M8-F100** A-003 graduation reset happens at INSTALL time
(Part 7.2''s open question â€” a reset deferred to consent leaves a graduated action running
unattended under changed behaviour); **M8-F106** the plan''s `withheld` list (observable
guards). M8-F101 fixed (counters now stamp the installed major version; unreadable â†’ 1,
erring toward more human approval). Band B âˆª Band C partition the contract by test.

Open, routed: **M8-F102** decline persistence needs storage (data-engineer, with M8-9''s
surface or wave 3); **M8-F103** gates.sh lines 81/89 default-encoding read (with M7-F12''s
single-sourcing); **M8-F104** M8-F46''s workflow half waits on M8-F48''s condition (workflow
packet, post-M8); **M8-F108** diff copy needs the product pass (M8-9); **M8-F110** three
definition readers to consolidate; **M8-F111** install-time validation should refuse an
upgrade whose Band B projection is invalid (installer follow-up). M8-6''s migration order
stands: Summit â†’ Portfolio Watch â†’ Trailhead, all minor-version, counter-neutral, provable.

## M8-F130 â€¦ M8-F139 â€” workflow closeout round (M8-10, wave 2 Lane C)

Merged at 926 tests. M8-F87 fixed (ordinal resets at continue-as-new; daily allowance
crosses intact â€” F139 pinned the careless version; safe BECAUSE D-034.2 namespaces keys by
run id); M8-F88 fixed (finally-guarded hold release; cancellation inside settle deliberately
defers to the reconcile â€” F138 recorded as intent, not gap); D-035 implemented broadened,
behind PATCH_PAUSED_WAKE_NOTICE at BOTH drop sites (F130), via a new activity and new
NotificationKind.WAITING_ON_RESUME (needed: the approval kinds reconcile against pending and
would filter the notice out â€” F133). Worker latitude ratified on both additions.

Notable: **F131** â€” no behavioural test had ever reached a continuation; that is how F87
survived two milestones. **F136** â€” dispatch_events signals ACTIVE companies only, so the
D-035 notice''s live path is auto-pause â†’ operator answers â†’ drop; rare today, matches the
owner''s nothing-silently-lost intent (flagged to owner in report). F134 (reason-kind not a
stored notification field â€” schema change if the surface needs it) and F132 (kindâ†’copy
wiring) routed to M8-9 mid-flight.

## M8-F115 â€¦ M8-F121 â€” surface round + the queue''s first conflict (M8-9, wave 2 Lane B)

Merged at 956 tests after the merge queue''s FIRST conflict in 22 merges â€” the healthy shape:
the lane''s correctly-withdrawn D-035 draft colliding with main''s real mechanism in three
files; bounced to the lane per protocol, resolved main-wins, both Manager-approved copy
replacements applied in passing, gates 0. Landed: the Part 6 field-to-sentence surface
(11 sentences, deterministic, unrenderable=unrefreshable), pending-update component +
apply/dismiss routes (honest 409 until wired), not_ready_count consumer (M8-F61 closed),
forbidden-term list single-sourced into tests/surface_sources.py â€” gates.sh''s stale copy was
missing "woken"/"business" (M7-F12 + M8-F103 closed).

- **M8-F115 (open, wave 3):** plan_refresh unreachable from api by layering â€” wire through
  the kernel builder at composition, the M6-F20 pattern; the surface is an honest seam.
- **M8-F120 (recorded as norm):** the worker flagged Manager mid-flight relays as an
  unrecognized channel and verified against git before acting â€” that verify-first behaviour
  is CORRECT and now the documented expectation for any mid-packet instruction; relays are
  legitimate but never self-authenticating.
- **M8-F119 closed** (copy applied during resolution). Grid-level pending-update indicator:
  deferred as a product decision for the workspace phase.

## M8-F160 â€¦ M8-F165 â€” the live migration (M8-6, wave 3b)

M8 live-proven at 975 tests, $0 spend: Summit''s negative control held (409 on empty plan;
the affiliate stored-vs-source drift correctly did NOT leak into a contract diff â€” M8-F163);
Portfolio Watch applied (attainment 45 â†’ 91, both M8-5 corrections riding one refresh â€”
M8-F161 supersedes the design''s pre-M8-5 78 prediction; health 82 â†’ 93, recomputed on read,
no wake needed); Trailhead applied (capability.result_returned gone from stored wake
conditions â€” M6-F10 healed, preventive; dispatch_events re-reads per sweep, no restart).
Band C byte-identical everywhere incl. both operator-chosen ceilings; the one graduation
counter untouched; D-030 live (decision rows carry NULL action_type). M8-F160 fixed (one
target derivation for create AND refresh â€” the diff side was the subtle half).

- **M8-F162 (URGENT ops, blocking any future worker start):** ~445 orphaned test
  BusinessManager workflows on the live `default` namespace beside the three real Managers â€”
  a worker start would execute them all against the live DB and the real key. Packeted
  (M8-12): surgical terminate of everything except the three protected bm-biz_ ids + route
  tests off `default` permanently (lane_env exists for exactly this). Until it merges, no
  packet may start a Temporal worker.
- **M8-F164 (note):** apply consents to "whatever is pending now", digest-guarded inside
  apply_refresh; a plan_key-bound consent is a future surface hardening. **M8-F165:**
  cosmetic default materialization. **M8-F102** decline persistence remains deferred (M9).

---

## D-036 â€” the D-027 amendments as decided mechanism (audit Finding 2 recording commit)

Ratifies M8-5''s implemented rulings as the record CLAUDE.md requires: (1) KpiMapping carries
an optional capability filter (data, D-014-safe) â€” a metric counts what its capability
produced, not everything the cycle ran; (2) CONFIGURED_KPI_TARGET_COUNT''s target derives
from the type''s own target count once, at provisioning AND refresh (one derivation â€”
M8-F160''s fix; the in-code cite "M8-F153" refers to this same fact, recorded here so the
cross-reference resolves); (3) KpiSource carries a platform-owned scope â€” CYCLE_RESULT
sources skip (not zero) resultless cycles; OBSERVATION sources record on any completed wake,
including NOTHING_TO_DO behind PATCH_NOTHING_TO_DO_KPIS (D-033-proven with a scripted
boundary pair, since no fixture reaches that branch); (4) M7-F60 (result-usefulness vs
invocation-success) is formally deferred to M9/M10 where Trading Analysis shapes
capability-result semantics.

## Recording corrections (audit Finding 2, continued)

- **M8-F115 is CLOSED** (M8-11): api reaches refresh through kernel.build_refresh â€” the
  earlier "(open, wave 3)" line is superseded.
- **M8-11 round (M8-F140â€“F149):** no findings opened â€” the wiring, font hookup (M8-F21
  closed, document.fonts proof), and installer guards (M8-F110/F111 closed) landed without
  surprises; the duplicate Part-6 sentence table in api/pending_update.py is recorded here
  as a consolidation candidate, not a defect.
- **M8-5 round (M8-F150â€“F153):** F150 platform-vs-workflow territory tension for KPI-adjacent
  workflow edits (reconcile in the M9 DELEGATION amendment); F151 fixed in-lane; F152
  capability filter is silently inert on non-result sources (install-time validation
  candidate); F153 = the dual-derivation risk, closed by M8-6''s Part 0.
- **M8-F105/F107/F109** from the M8-8 report are hereby in the record: two write paths with
  the Band-C guard as the difference; target_value''s lossless argument expires with
  per-instance editing; pending state is computed, never stored â€” by design.
- **Audit Finding 3:** "Not now" writes a Decision Log row but suppresses nothing â€” an inert
  control on a shipping surface (design 4.3''s rejected loop), pinned by test, routed to the
  product verdict for the REVISE round alongside M8-F102''s storage.

## M8 closure â€” both gates cleared

M8-4 audit: **MERGE** (Band-C guard four-layered and real; discipline "real, not asserted";
recording commit 4657733 closed its Finding 2). M8-5 product: **SHIP WITH FOLLOW-UPS** â€”
the shell holds, both themes â‰¥5.04 contrast everywhere measured, fonts in real use, Â§12.5
catching live prose. Milestone report: docs/reports/M8.md.

**M9 surface backlog** (product follow-ups 1â€“8 + audit Finding 3, none gating): teaching
empty state for the Approvals route; install-failure surfacing in newco.js; tile-vs-card
severity tone mismatch (watch escalating to risk-red); healthy-labelled companies whose
sentences say nothing was achieved (not-yet-measured maybe shouldn''t score attainment);
"Working â€” details inside." reading as in-progress; up-to-date vs uncomputable both silent;
freshness value/unit copy; in-app theme toggle (Settings); stale tokens.css M8-F21 comment;
the inert "Not now" + decline persistence (M8-F102, data-engineer).

**Sole remaining tag-gate:** M8-F162 (namespace purge) â€” paused by owner mid-packet; three
options presented; no worker starts until resolved.

---

## Owner authorization on record â€” M8-F162 cleanup and the lane-namespace fix

Chronology, recorded verbatim in intent so the M8-F120 verify-first norm can be satisfied
from git alone:

1. The owner first chose Option 1 (dry-run audit, "After I review the audit, I''ll give
   explicit approval before any cleanup occurs").
2. In a SUBSEQUENT message, before the audit completed, the owner superseded that gate with
   a standing delegation: "Approved. Proceed with the orphaned Temporal workflow cleanup
   under delegated authority. You may terminate only workflows that are positively
   identified as orphaned test artifacts. Before cleanup, generate and save a complete audit
   of every workflow to be removed, including why it qualified. If there is any ambiguity,
   do not terminate it â€” leave it in place and report it separately. After cleanup, tag and
   push the M8 baseline." The same message delegates operational/implementation decisions
   generally â€” including infrastructure maintenance, test cleanup, and bug fixes â€” with
   stops reserved for vision/architecture/security-model/integrations/user-facing changes.
3. The dry-run audit (lane/m8-12 commit ae124ab, docs/reports/M8-F162-DRYRUN.md) satisfies
   the owner''s conditions, verified by the Manager: 475 orphans positively identified by
   absence from the live business_instances table (3 rows total, all protected, exact ids
   quoted), zero ambiguous cases flagged, non-BusinessManager types absent, script
   protection-filter-first with --execute required.

**Authorized on that basis, by the Manager under the owner''s recorded delegation:** execute
the audit''s Â§5 script; append the execution outcome to the audit report; and fix the
routing defect the audit found (JARVIS_TEMPORAL__NAMESPACE double-underscore form in
scripts/lane_env.py, .env.example, DELEGATION.md''s line, plus a round-trip guard) â€” an
infrastructure-maintenance item squarely inside the delegation. Ambiguity rule stands: any
id that errors is listed and left, never blind-retried. The worker''s refusal to act on an
unverifiable relay (its report of 2026-07-27) was CORRECT under M8-F120 and is part of why
this entry exists.

## M8-F162 closed; M8-F176 â€¦ M8-F179 (M8-13); D-037 â€” the M9 operating model

**M8-F162 CLOSED:** 497/497 audited orphans terminated by the Manager under the recorded
authorization (da3ba5d), then 11 diagnostic-run leaks terminated under the same evidence
class (ids in the audit''s Â§7 and the M8-13 report); exactly the three protected Managers
remain RUNNING, individually verified. The real leak path was tests/test_reservation_
reconcile.py''s unmocked kernel fixture (M8-F177 â€” the DRYRUN Â§6 survey had missed it);
fixed with the capturing-client pattern; the round-trip guard proven red/green; a full gates
run now leaves the namespace flat (before/after proof in the M8-13 report). M8-F176
(HOST/TASK_QUEUE same bug class, masked by defaults) and M8-F179 (historical packet doc
spelling) â†’ M9 backlog.

**D-037 â€” the M9 operating model (owner-adopted from docs/reports/FABLE-RETRO.md):** rolling
dispatch replaces lockstep waves (a merged lane''s ready successor dispatches immediately);
packet prep pipelines into wave runtime; warm-agent continuity is the default for
same-territory chains; concurrency cap 4 lanes; owner-decision items surfaced at discovery
and re-surfacedæ¯ report until ruled. Two lessons added from execution: (1) **mandate
reversals mid-task are the trust anti-pattern** â€” a changed mandate goes to a fresh agent
whose founding packet carries the authority (the M8-F162 refusals, both correct, are the
evidence); (2) M8-F150 reconciled: a packet may name files outside an agent''s default
territory explicitly, and the agent proceeds-and-flags rather than escalating. Measured
against the retro''s +25â€“35% prediction through M9.

---

## D-038 … D-041 ratified; M9-F1 … M9-F5; two owner escalations open (M9-1)

Executive Layer design merged (docs/design/EXECUTIVE-LAYER.md — authoritative). Ratified as
drafted: **D-038** the deterministic half computes and reports, never writes a contract —
enforced by the import rule (executive imports registry/budget/kpi/observability/
notifications and nothing else; importing jarvis.llm IS the violation event); **D-039** a
portfolio has a census, not a score (live data is the argument: means read healthy while
Summit sits on watch); **D-040** every Executive figure names its window; runway in cycles;
absent is not zero; **D-041** the Executive runs on its own timer at runtime/worker.py —
never a workflow, never Scheduler.sweep. **D-042 held** pending owner escalation 2.

Findings: **M9-F1** the business cap sums lifetime while the platform breaker is rolling —
Summit''s $25 lifetime cap ≈ 30 cycles, less than one day''s allowance; **M9-F2**
CircuitBreaker.trip() has no caller and §12.5''s "Jarvis paused spending" has never been
written (0 platform decision rows); **M9-F3** nothing sets KPI targets — Executive
target-setting and M8-F6 are the same event from opposite directions and must land together;
**M9-F4** Executive reasoning has no budget scope (why the judgment half is deferred);
**M9-F5** per-model cost tracking explicitly homed here, deferred with rationale.

**OWNER ESCALATIONS (D-037: re-surfaced until ruled):** (1) `business_cap_usd` window —
lifetime vs rolling — changes what a spending limit MEANS to the operator (user-facing);
(2) a platform-scoped approval action_type for capital allocation — §8/D-013 security
boundary. **Manager-decided:** escalation 3 (Executive budget scope) = an explicit
sub-ceiling within D-003''s platform scope, set at Executive-enablement time, NOT a fifth
scope — recorded now so packet D can wire the seam; the judgment half stays deferred until
the sub-ceiling has an owner-visible surface anyway. Cross-lane rule active: the census
wording and M9-3''s never-measured item must agree before either ships.

## M9-F50 … M9-F51 — decline persistence (M9-4); M8-F102 and audit Finding 3 CLOSED

Migration 0007 (contract_refresh_declines, upsert-per-business) scratch-proven both
directions then applied live (only write; companies byte-identical). Suppression is
VERSION-keyed, deliberately not digest-keyed — a digest key cannot distinguish a version
bump from same-version drift and would silently reopen M8-F3''s class (M9-F50, ratified:
exactly the right call within data-engineer authority). "Not now" is now real: decline
suppresses, a new version re-offers, same-version drift does not (proven by reproducing
M8-F3''s historical shape via direct row mutation — M9-F51 records that drift is latent,
unreachable via normal install today). 980 tests. Stale scratch DB jarvis_migcheck noted as
litter for a future hygiene pass.

## M9-F20 … M9-F29 — company workspaces (M9-2); UI Phase 3 foundation merged

Merged at 983. Ratified: the workspace REPLACES the Details sheet (three-level ladder
preserved — a fourth level was refused); navigation controls are links (reload-survival,
linkability); a detail pane names a rail parent that stays lit. M9-F20–F24 fixed in-lane
(naming regrowth, details-preserving repaint rule now documented, orphan-route empty state,
duplicate accessible name, anchor button metrics). Open → routed: M9-F25 transition smear
(m9-3''s theme toggle must address), M9-F26 the 15s poll re-runs plan_refresh (successor
candidate: cache or lighter read), M9-F27 grid pending-indicator (product gate input),
M9-F28 copy pass owed, M9-F29 raw floats in goal readings (m9-3 freshness-copy item covers).
The kpi-series endpoint is specified exactly in the M9-2 report (labels never keys; empty
points never omitted; KpiEngine.series reused) → packet M9-2a dispatched under rolling
dispatch; trend render follows via warm continuation; product-reviewer gates the phase after
trends land.
