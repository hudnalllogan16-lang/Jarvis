# Jarvis Implementation Decision Record

Status: **binding on implementation, subordinate to the Architecture Specification v1.4.**

These are not amendments. Spec v1.4 remains the single source of truth (§12). Each entry below
records the *smallest reasonable implementation* chosen where v1.4 left a mechanism
unspecified, per the Implementation Directive. Nothing here contradicts a MUST or MUST NOT.

If any decision below is later found to conflict with the spec, the spec wins and the decision
is void — flag it, do not silently reconcile.

---

## D-001 — Capability invocations always terminate with a result
**Fills:** §2.1 (Manager "MUST wait for and synthesize all results") + §9 (dead-letter queue)

A capability invocation resolves to exactly one terminal `CapabilityResult` with status
`SUCCEEDED`, `FAILED`, or `DEAD_LETTERED`. Routing an invocation to the dead-letter queue
**also** delivers a `DEAD_LETTERED` result to the awaiting Business Manager. "Synthesize all
results" means all invocations reached a terminal state — not that all succeeded.

**Rejected:** dead-lettering as a silent terminal sink. Under the literal reading of §2.1 + §9
that deadlocks the business permanently.

**Reversal cost:** low. Contained in the capability dispatch layer (Milestone 2).

---

## D-002 — Invoking identity is derived, never declared
**Fills:** §2.2 (scoped request "supplied by the calling Business Manager") + §10 ("under any
circumstance, including bugs or malformed requests")

The `business_id` on an inbound scoped request is **advisory and ignored for authorization**.
The capability pool derives the true invoking identity from the Temporal workflow's registered
business identifier, resolves it through the Business Registry (§0.1), and validates the
requested memory / credential / tool scopes against that business's configured
capability-invocation permissions (§5). Any mismatch is rejected and audited — never narrowed,
never silently corrected.

**Rejected:** trusting the requester's declared scope. §10's "including bugs" clause makes a
requester-declared model unsatisfiable by construction.

**Reversal cost:** high once businesses exist. This is why it is decided at Milestone 1.

---

## D-003 — Budget debits are hierarchical
**Fills:** §2.1 (wake-cycle ceiling), §2.2 (per-invocation allocation), §5 (business Budget),
§9 (platform $500 / rolling 24h)

Every unit of spend (model tokens and metered tool calls) debits, in order, all four scopes:

    invocation allocation -> wake-cycle ceiling -> business budget -> platform rolling 24h

Rules:
1. A debit that would breach **any** enclosing ceiling is refused *before* the spend occurs.
   Ceilings are pre-flight checks, not post-hoc alarms.
2. Breaching the **business** ceiling halts dispatch for that business only.
3. Breaching the **platform** ceiling halts new dispatch platform-wide (§9), but resolves the
   §9 / §10 tension by tripping only after the offending business has already been halted by
   rule 2. Per-business caps are the first line; the platform breaker is the backstop.
4. In-flight invocations are never killed mid-execution by a ceiling breach; queued and
   undispatched invocations are cancelled and surfaced as stuck work (§12.5).
5. Exhausting a wake-cycle ceiling mid-cycle ends the cycle in `BUDGET_EXHAUSTED`, writes a
   Decision Log entry explaining it, and does not re-dispatch.

**Reversal cost:** high. The ledger is Milestone 1 infrastructure (§13 Step 1).

---

## D-004 — Temporal history is the replay substrate; the audit log is a durable projection
**Fills:** §2 and §11 ("replayable from the audit log alone")

Temporal's own event history is authoritative for workflow replay. The audit log is a
complete, append-only projection written through activities — sufficient for forensic
reconstruction and for satisfying §11's auditability requirement, but not a second execution
engine.

Consequently — and this is the part §11 requires but never states — **all nondeterminism MUST
occur inside activities with recorded results**: model calls, tool calls, HTTP, clock reads,
random draws, and UUID generation. Workflow code is pure orchestration.

**Rejected:** a bespoke replay engine reading the audit log independently. Two execution
engines with divergent histories is a correctness hazard, not redundancy.

**Reversal cost:** total. Every workflow written after Milestone 1 depends on this.

---

## D-005 — Decision history lives in the Decision Log, not in workflow state
**Fills:** §2.1 ("owns, as durable workflow state: ... decision history") + §11.5

Business Manager workflow state holds only a bounded working set: the current tactical plan,
active KPI targets, and identifiers of the current cycle's in-flight invocations. The decision
history itself is persisted to the Decision Log (§11.5), which §11.5 already establishes as a
first-class queryable store. Manager workflows use `continue_as_new` on a configured cycle
count.

§2.1 says the Manager *owns* decision history; it does not say the history must be resident in
workflow state. Ownership is preserved — the Manager is the sole writer of its own entries.

**Rejected:** literal accumulation in workflow state. Temporal history size limits make this a
production failure that surfaces after months of operation, not in test.

**Reversal cost:** high.

---

## D-006 — Approval uses the continuation model, not the blocking model
**Fills:** §2.1 (wake cycle), §8 (approval), §9 (7-day pending window)

A Business Manager that needs approval writes its Decision Log entry, emits the approval
request, and **ends the wake cycle**. The operator's decision arrives later as an
`approval.decided` event, which is an explicitly configured wake condition (§2.1) and starts a
*new* cycle that reloads context from durable state.

Therefore:
- The cost ceiling is scoped to a single cycle and is never spread across a 7-day wait.
- "Stuck Manager" detection (§9) measures cycle duration, now bounded in minutes, not days. A
  pending approval is tracked by the approval subsystem's own 24h/7d timers, not by a parked
  workflow.
- Approval context MUST be reconstructable from the Decision Log entry alone (§11.5).

**Rejected:** blocking the cycle on an approval signal for up to 7 days — it makes the §2.1
cost ceiling undefined, inflates open workflow count, and conflates two different timeout
regimes.

**Reversal cost:** high.

---

## D-007 — Operator-facing terms for components added in v1.3 and v1.4
**Fills:** §12.5's own completeness gate, which v1.4 currently fails

| Technical term | Operator-facing term (UI) |
|---|---|
| Platform Kernel | (invisible — "Jarvis" itself) |
| Business Registry | "Your companies" / the company list |
| Business type (plugin) | "Company template" |
| Business instance | "Company" |
| Lifecycle: `PROVISIONING` | "Setting up" |
| Lifecycle: `ACTIVE` | "Running" |
| Lifecycle: `PAUSED` | "Paused by you" |
| Lifecycle: `RETIRING` / `RETIRED` | "Closing down" / "Closed" |
| Executive Layer | (invisible — "Jarvis moved budget between companies, here's why") |
| Capital reallocation | "Budget moved" |
| Business budget cap reached | "[Company] hit its spending limit" |
| Wake-cycle budget exhausted | "[Company] stopped early to stay in budget" |
| Memory promotion | "Lesson shared with your other companies" |
| Autonomy level (per action type) | "What [Company] can do without asking" |
| LLM provider / model | (invisible — never surfaced) |

**Reversal cost:** none. Wording.

---

## D-008 — Business lifecycle state machine
**Fills:** §0.1 ("active, paused, retired" — named, never defined)

    PROVISIONING --> ACTIVE <-> PAUSED --> RETIRING --> RETIRED
          |                                   ^
          +-----------------------------------+

`RETIRED` is terminal. Identifiers are permanent and never reused (§0.1).

Invariants enforced on every transition:
- **I-1** Leaving `ACTIVE` cancels all scheduled wake timers; it never cancels an in-flight
  wake cycle mid-flight. The cycle runs to its terminal state, then the business settles.
- **I-2** Pausing never strands a pending approval. Pending approvals survive the pause and
  remain answerable; answering one does *not* wake a paused Manager — the decision is recorded
  and applied on resume.
- **I-3** No dispatched capability invocation is ever left without a consumer. On pause or
  retire, in-flight invocations terminate and their results are recorded.
- **I-4** `RETIRING` accepts no new dispatch; it exists solely to drain in-flight work.
- **I-5** Credential grants are revoked on entry to `RETIRED`, not before — a draining business
  still needs its credentials to finish idempotent work.
- **I-6** Every transition writes both an audit entry (§11) and a Decision Log entry (§11.5).

**Reversal cost:** medium.

---

# Smaller documented assumptions

**A-001 — Idempotency key (§6).** `sha256(business_id | invocation_id | action_type |
canonical_json(action_payload))`. Derived from the invocation, not the attempt, so retries and
replays collapse to one external effect.

**A-002 — Event delivery (§2).** At-least-once with consumer-side deduplication by
`(event_id, consumer_id)`. Duplicate delivery MUST NOT produce a duplicate wake cycle or a
duplicate approval request.

**A-003 — Action-type identity (§5, §8).** `action_type` is a stable dotted string namespaced
to the business *type*, not the instance: `affiliate.publish_post`. Graduation counters are
keyed `(business_instance_id, action_type)`. Changing a business type's plugin **major**
version resets its counters; minor versions do not. A "correction" is any operator approval
where submitted parameters differ from requested parameters — it counts as a denial for
graduation purposes.

**A-004 — Contention policy (§2.2).** v1 default is weighted fair queueing with
budget-proportional weights **and a guaranteed minimum share per active business**, so a
low-budget company cannot be starved indefinitely. Not FIFO (§2.2 prohibits it as a default).

**A-005 — Provider coverage.** The seven named providers are served by three transports: native
Anthropic, native Gemini, and one OpenAI-compatible client covering OpenAI, OpenRouter, LM
Studio, Kimi, and Ollama via `base_url`. Provider and model are config values; no model
identifier is hardcoded anywhere in the codebase.

**A-006 — Log write isolation (§10, §11).** Audit and Decision Log tables are append-only at the
application layer (no update or delete path exists) and every write is stamped with the derived
business identity from D-002.

---

# Milestone 1 review amendments (post-inspection)

Four findings from the pre-merge inspection. All are defects against decisions already
recorded above, not new decisions.

**M1-R1 — D-002 was documented, not enforced.** `authorize_invocation` accepted a plain
`BusinessId` for the workflow identity, so any caller could pass any value; the derivation was a
docstring convention. Now enforced by `jarvis/kernel/runtime.RuntimeIdentity`, which cannot be
built from a bare string in calling code. Production identities come from
`RuntimeIdentity.from_activity()`, which reads Temporal's `activity.info().workflow_id` — a value
the server sets from the *calling workflow* and activity code cannot forge. Test-constructed
identities are labelled `_source="testing"` and that label is written into every audit record, so
a test-provenance identity appearing in production audit is visibly an incident.

**M1-R2 — four of five security rejections were silent.** Only the identity-mismatch path wrote
an audit record; capability, tool-scope, credential-scope, and lifecycle rejections raised
without one. All five now route through `BusinessRegistry._deny`, which audits and then raises.
A structural test asserts `authorize_invocation` contains no bare
`raise ScopeViolationError`, so a future check cannot be added without an audit record.

**M1-R3 — the transition matrix was spot-checked, not exhausted.** 2 of 18 illegal pairs were
covered. Now all 25 pairs are parametrised against an independently maintained expected set, plus
an equality assertion between that set and the implementation's table, so adding a transition
without updating the expectation fails.

**M1-R4 — `stop_reason` leaked vendor values.** The field was a raw pass-through, so
`end_turn` / `stop` / `STOP` reached callers untranslated and any branch on it would have been
vendor-coupled. Now normalised to a `StopReason` enum with a per-provider mapping; the vendor's
own string is preserved as `raw_stop_reason` for the audit log only. Unknown values degrade to
`OTHER` rather than raising or masquerading as a clean stop.

Not changed: `max_tokens` and `stop_sequences` keep names that read as Anthropic-flavoured, but
the concepts are common to all three transports and the values carry no vendor semantics.
Renaming would be churn, not decoupling.

---

# Milestone 2 status: execution spine

§13 Step 1 lists thirteen infrastructure components. Milestone 2 delivers the subset needed to
run one capability invocation safely end to end. The rest is Milestone 3, listed below rather
than left implicit.

**Delivered and wired to a caller:** event bus with per-consumer deduplication (§2, A-002);
budget ledger with the full D-003 hierarchy; platform circuit breaker (§9) including the
Decision Log narrative §12.5 promises and v1.4 assigns to no writer; capability pool dispatch
with authorization (D-002), bounded retry and backoff (§9), dead-lettering that still returns a
terminal result (D-001); stateless execution shell (§6); idempotency guarding external-facing
actions (A-001); the Temporal activity boundary (D-004).

**Delivered without a production caller — deliberately, and flagged rather than disguised:**

- `CredentialManager` (§10) resolves handles to secrets at the tool-execution boundary. Nothing
  executes tools yet: the capability shell calls a model and returns text. Wiring it now would
  mean materialising secrets with no consumer, which is the opposite of what §10 asks for. It is
  built because the *boundary* had to be decided before any tool code exists to put on the wrong
  side of it.
- `FairQueue` (§2.2, A-004) decides who dispatches next under contention. The pool currently
  dispatches synchronously, so there is no contention to arbitrate. It is built and tested now
  because §2.2 makes the policy a MUST and forbids FIFO as a default; retrofitting fairness after
  concurrency exists is how FIFO becomes the default by accident.

Both are covered by tests. Neither should be read as working in production until M3 gives them a
caller.

**Deferred to Milestone 3 (remainder of §13 Step 1):** approval subsystem (§8) with the 24h
re-notification and 7-day auto-pause timers (§9); scheduler and wake-condition evaluation (§2.1);
KPI engine (§5, named only in §13 and specified nowhere); notification system; operator-facing
dashboard surfaces (§12.5). Then Milestone 4 is the Affiliate Business (§13 Step 2).

## Milestone 2 findings

**M2-F1 — spend attribution is approximate.** `CapabilityPool._cost_of` settles a reservation at
its full reserved amount unless the provider reports a cost, because per-model pricing is not
configured until the Executive Layer's cost tracking exists. The approximation is deliberately
biased toward over-reporting spend: it can only understate remaining headroom, never overstate
it, so no D-003 ceiling can be silently exceeded by it. Revisit when pricing config lands.

**M2-F2 — `for_testing` now validates identifier format.** Test business ids previously did not
match the production pattern, so the M1-R1 derivation path was only ever exercised against input
no real business would produce. `RuntimeIdentity.for_testing` now applies the production pattern
and the fixtures use realistic identifiers.

**M2-F3 — idempotency is scoped to actions, not queries.** Only invocations carrying an
`action_type` are guarded. §6 scopes idempotency to external-facing and state-changing actions;
caching a research query would return stale findings for a question deliberately asked again.

---

# Milestone 3 status: operator surface

This milestone exists because §12.5 states that a technically correct implementation which fails
it "is a spec violation, not a 'polish later' item". After M2 the platform was correct and
completely unusable: nothing an operator could see, approve, or act on.

**Delivered:** approval subsystem with the autonomy ladder (§8); 24h re-notification and 7-day
auto-pause timers (§9); notification service; KPI engine and Health Score (§5); operator HTTP API;
and the Sims-style dashboard §12.5 requires as the default view.

## D-009 — Health Score is computed by the platform, not by each business

**Fills:** §5 (Health Score is a per-business contract field) vs §3 (health score aggregation is a
deterministic COO function) — v1.4 never says which side computes it.

The platform computes it, from contract primitives, in `jarvis/kpi/engine.py`. A score must be
comparable across businesses to be aggregatable at all; per-business implementations would make
two companies' scores mean different things while looking identical on the dashboard.

Composition: reliability 45%, budget headroom 30%, KPI attainment 25%. Reliability is weighted
heaviest because a company that cannot finish its work is broken in a way budget headroom cannot
compensate for. Components are returned alongside the score, not just the number, because §12.5
requires the operator be able to ask why and §11.5 forbids the audit log being the first answer.

**Reversal cost:** low. One module, no persisted derivation.

## D-010 — A correction resets the graduation streak

**Fills:** §8 requires "no denials or corrections in that window" and never defines a correction.

A correction is an approval where the operator changed the parameters before approving (A-003).
It advances the action but resets the streak to zero.

The alternative — treating an edited approval as an endorsement — would graduate an action the
operator actually rejected the original form of. Given graduation reduces friction on future
actions of that type, the conservative reading is the only safe one.

Enforced with two independent guards: the policy's `graduation_eligible` flag *and* the action's
own amount. A policy misconfigured as eligible still cannot graduate an action that moves money,
which is §8's hard v1 constraint.

**Reversal cost:** low.

## D-011 — Approval text is rendered from stored values, never model-authored

**Fills:** §8 (display the specific action, exact amount, triggering condition, downside) and
§12.5 (plain operator language, generated fresh per request).

The four facts are stored as structured columns and assembled into language by deterministic
string formatting in `jarvis/approvals/rendering.py`.

This is a safety property, not tidiness. Capabilities read untrusted external content — §13
Step 5 includes news analysis — and a Manager synthesizes those results into decisions. If the
amount an operator approves were prose regenerated by a model, attacker-influenced text would sit
between the decision and the human authorising money. The operator reads language; the numbers in
that language are the stored values.

This closes item 18 from the architecture review.

**Reversal cost:** low, but reversing it reopens a real attack path.

## Milestone 3 findings

**M3-F1 — §12.5 is now an executable gate.** `tests/test_operator_language.py` asserts that none
of §12.5's fifteen forbidden concepts appear in the dashboard markup, its script copy, the
lifecycle labels, the approval labels, or any rendered approval or failure string. §12.5 was
previously enforceable only by review, which catches a violation once; this catches it on every
commit. The test also asserts the detector itself fires, because a guard that never fires reads
as coverage while providing none.

**M3-F2 — expiry is the highest-stakes assertion in the subsystem.** §9 requires an unresolved
approval to auto-pause and explicitly never auto-approve. An implementation that drifted to
auto-approve would hand an unattended platform the authority to spend. It is tested directly and
should be treated as a regression tripwire.

**M3-F3 — the scheduler is still absent.** `due_for_renotification` and `expire_stale` are
implemented and tested but nothing calls them on a timer yet; they need the scheduler, which
arrives with the Business Manager in M4. Until then the 24h/7d timers are correct but dormant.
Same honest caveat as `CredentialManager` and `FairQueue` in M2.

---

# Milestone 4 status: Business Manager runtime + scheduler

Roadmap revision 2 split this out of the Affiliate Business milestone. See
`docs/ROADMAP.md` for the dependency argument.

**Delivered:** the generic Business Manager Temporal workflow (§2.1); its activity boundary;
bounded durable state (D-005); the continuation approval model (D-006); the scheduler driving
§9's 24h and 7-day timers and §2.1's event-based wakes; and a concurrency gate that finally gives
`FairQueue` a caller.

**Dormancy retired.** Two of the three components carried since M2/M3 now have production callers:

| Component | Was dormant since | Caller now |
|---|---|---|
| `FairQueue` | M2 | `CapabilityGate`, consulted by every pool dispatch |
| Approval 24h/7d timers | M3 | `Scheduler.sweep`, looped by the worker |
| `CredentialManager` | M2 | **still dormant** — nothing executes tools until M5 |

## D-012 — The scheduler is not a workflow

**Fills:** §13 Step 1 lists a scheduler; §2.1 and §3 forbid standing reasoning loops.

The timer sweep runs as a plain async loop in the worker process, not as a Temporal workflow.
It is deterministic bookkeeping over rows with no reasoning in it, and putting it in the workflow
layer would place a permanently-running loop there for no benefit. §2.1's prohibition is on
*reasoning* loops; a sweep that reads timestamps and writes notifications is not one, and keeping
it out of the workflow layer makes that distinction visible in the code rather than argued in a
comment.

A failed sweep logs and retries on the next tick rather than killing the loop: an approval
expiring five minutes late is a nuisance, a scheduler that stops means approvals never expire.

**Reversal cost:** low.

## D-013 — The model proposes intents; the platform attaches scopes

**Fills:** §2.2 (scoped requests) meeting §2.1 (the Manager plans by model call).

The planning activity asks the model for intents and capability names. It does **not** let the
model author the resulting `ScopedRequest`. Tool scope, credential refs, memory scope, and budget
allocation are read from the business's configured `CapabilityPermission` and attached by the
platform.

If a model could author its own scope, §2.2's scoping would be decorative and §10's isolation
would rest on a language model's discretion. A hallucinated or unpermitted capability name
produces one fewer plan item rather than an error or an unauthorised dispatch.

Similarly, the model does not decide whether an action needs approval. `needs_approval` is
resolved against the contract and the graduation ladder (§8) in the synthesis activity, and
`ProposedAction.needs_approval` defaults to `True` so a Manager that omitted it asks rather
than acts.

**Reversal cost:** high. This is a security boundary, not a convenience.

## Milestone 4 findings

**M4-F1 — parallel dispatch was silently sequential (fixed).** The first draft of
`_dispatch_all` awaited activity handles in a list comprehension, which serialises them. §2.1
explicitly permits dispatching multiple capability requests in parallel, and the bug would have
made a cycle's latency the sum of its parts while passing every functional test. Replaced with
`asyncio.gather` and covered by a regression assertion in `test_manager_determinism.py`.

**M4-F2 — `__all__` import-laundering recurred (fixed).** I flagged this pattern in M2, fixed it
in `runtime/activities.py`, and then reproduced it in `manager/activities.py` — listing otherwise
unused imports in `__all__` to quiet a linter. Removed, and the unused imports deleted. Worth
recording because it is a habit, not an accident: the correct response to an unused-import
warning is to delete the import.

**M4-F3 — determinism is now a source-level gate.** `test_manager_determinism.py` asserts against
the workflow module's AST that it contains no clock read, no identifier minting, no I/O import,
and no `execute_activity` call without a timeout. Determinism is a property of what the code *may*
do; a runtime test only covers what one execution did, and a replay divergence appears during
recovery, which is when it is least affordable.

**M4-F4 — cron support is deliberately partial.** `_interval_seconds` handles daily and hourly
schedules only. §14 asks that expansion be driven by demonstrated need; a business requiring a
schedule this cannot express is that need. Unsupported expressions return None, which makes the
Manager event-driven rather than silently mis-scheduled.

---

# Milestone 5 status: Affiliate Business + reconciliation

## D-014 (amended) — a business type is data, persisted in the Registry

Original D-014 said a type is data, not code. Milestone 5 surfaced a second, concurrent
implementation of the same idea (see M5-F1) whose design was better on the axis that matters:
**where the data lives**. The canonical answer is now:

- The artifact is `jarvis/businesses/definition.py::BusinessTypeDefinition` — pure data, no
  Manager subclass, no logic. `tests/test_affiliate_type.py` asserts the affiliate module's AST
  contains zero functions and zero classes.
- Definitions persist as Registry metadata (§0.1), installed via `ProvisioningService.install`,
  which refuses a type whose permitted capabilities lack prompt templates.
- Instance creation is `ProvisioningService.create_company`: definition + display name + optional
  budget numbers. That signature *is* §4's "configuration only" requirement.
- Activation publishes `business.activated` on the bus rather than starting a Manager directly
  (§2 forbids direct worker calls; A-002 dedup means a replayed activation cannot start two
  Managers for one business).

Rejected (my own first cut): an in-process `INSTALLED_DEFINITIONS` dict populated by import side
effect. It failed on restart (M5-F3) and made installation invisible to the audit log.

## D-015 — tools run only on the approved-action path

Capabilities *produce content*; tools *perform effects*; effects execute only after §8's gate
(approval or graduated autonomy), via `ToolExecutor`. A model call can therefore never cause a
side effect directly. Credentials materialise inside the tool implementation's call and nowhere
else (§10) — this is the boundary `CredentialManager` waited for since M2. Every effect is
idempotent under the A-001 key, so a retried or replayed approved action replays its recorded
result instead of publishing twice. The executor runs the operator's *decided* parameters, never
the originally requested ones (A-003 correction semantics).

## Milestone 5 findings

**M5-F1 — concurrent divergence, and how it was resolved.** Between working sessions, a parallel
implementation of the business-type mechanism appeared in `jarvis/businesses/` alongside the one
I was building in `jarvis/plugins/`: two `BusinessTypeDefinition` classes, two creation paths,
and duplicate `POST /api/companies` routes (the later-registered one silently dead). Resolution:
reconciled onto `jarvis/businesses/` because it was better where it counted — persistence and
bus-mediated activation — and ported the two pieces it lacked (`tool_registry`, the data-only AST
gate). `jarvis/plugins/` is deleted. One mechanism remains. The layering gate then correctly
rejected the reconciled code itself (`api` importing `businesses` forward), fixed by routing
construction through the kernel composition root rather than by widening the exemption list.

**M5-F2 — silent patch no-ops.** Several of my edits used `str.replace` without asserting the
target existed; one (the layering-table update) silently did nothing because the concurrent work
had already changed the region. A patch that cannot fail is a patch that cannot be trusted to
have happened. Later patches in this milestone assert before replacing.

**M5-F3 — the empty-templates defect.** My original dispatch path gave the executor a
kernel-wide empty template source, so every real dispatch would have dead-lettered with "unknown
prompt reference" — a company that looks healthy and can never do anything. Fixed: the dispatch
activity loads the invoking type's templates from Registry metadata per dispatch. The concurrent
implementation's persistence choice is what made this fixable.

**M5-F4 — credited: the open D-006 loop.** The concurrent work found that `approval.decided`
existed as an *audit* event name but was never *published* to the bus — the Manager's
continuation model looked closed and was not; a business that asked for approval would never
resume. Fixed by them (`events/types.py` + publish in the approval service + a closure test).
Recorded here because the lesson generalises: two logs and a bus sharing a naming style means a
grep proves nothing about where a message went. Bus event types now live in one module.

**Deferred-completion ledger:** `CredentialManager` retired (caller: `ToolExecutor`). The
Business Manager workflow's first live Temporal exercise remains open, now targeted at M6.


---

## D-016 — the Shell is topology, not architecture

**Fills:** nothing in v1.4 — the spec is silent on process layout, which is exactly why this is
an implementation decision and not an amendment.

`python -m jarvis` runs the API, the Temporal worker, and the scheduler in one process for
development. The architecture's boundaries are untouched: the worker and API remain separately
runnable (`jarvis.runtime.worker`, `jarvis.api.server`) and production deploys them separately.
The launcher is a composition root — it starts components and prints their health; any behaviour
found in it is a defect (`test_composition_roots_hold_no_logic`).

Degradation ladder, in operator language throughout: database down → attempt Docker start,
re-check, refuse only if still unreachable; Temporal down → serve everything, banner says
"companies can't act right now", worker retries in the background and attaches when the runtime
appears; no LLM key → serve everything, banner says "companies can't think yet". A developer who
starts Jarvis before Docker finishes booting watches it assemble itself rather than restarting
processes by hand.

**Reversal cost:** none. Deleting the shell package restores the previous manual topology.

---

## D-017 — one application: supervision, window, and subsystem toggles

**Fills:** nothing in v1.4 — process behaviour and desktop packaging are operational surface the
spec is silent on. Classification: operational; no layer, responsibility, or invariant changes.

**Supervision.** Every long-lived part (dashboard server, company runner, timers) runs under
`jarvis/shell/supervisor.py`: crash → log → exponential backoff (1s doubling to 60s, reset after
30s of stability) → restart. Part states surface in `/api/health` under plain labels — a crashed
worker appears in the app as "Company runner — restarting itself", never as a dead terminal. The
supervisor is a component, not launcher logic, so the entrypoint no-logic gate still holds.

**Window.** With the `desktop` extra (`uv sync --extra desktop`), the dashboard opens in a native
window and closing it quits Jarvis — the window is the app. Without it, the default browser opens.
`JARVIS_HEADLESS=1` disables both. The desktop module knows only a URL; internal modularity is
invisible through it by construction. A single-file executable (PyInstaller) is the eventual end
of this path; deferred until the shell stabilises, recorded here so it is a decision rather than
an omission.

**Subsystem toggles.** "Enable or disable subsystems through the UI" maps onto existing
architecture rather than new machinery: a subsystem is a business type, and the toggle is an
`enabled` flag on the Registry's type row (migration 0005). Disabled types disappear from the
create-a-company flow. Deliberately *not* touched: existing companies, which keep their own
pause state — one switch that silently paused running businesses would violate the operator's
mental model and the audit story. Both toggle and separation are stated in the settings panel.

**Reversal cost:** none for window and toggles; low for supervision (restore plain gather).

---

## M5-F5 — the launcher never started the dashboard on a fresh database (fixed)

**Reported by the user**, with an exemplary trace: Docker healthy, all containers confirmed
running, kernel initialising cleanly, `curl localhost:8000` refusing the connection, and the
launcher's log stopping dead after `"starting services"` with nothing further.

**Root cause.** `check_database` (preflight) ran two probes — connectivity (`SELECT 1`) and a
schema check (`SELECT count(*) FROM business_instances`) — and tried to tell them apart by
matching the failing exception's class name against `"UndefinedTable"` and its message against
`"no such table"`. Both patterns are SQLite's shape. On Postgres, SQLAlchemy wraps the driver
error in `ProgrammingError` (the class name never matches) and the message reads `relation
"business_instances" does not exist` (the text never matches either). Every fresh Postgres
database — the ordinary state on a first-ever launch, before migrations run — was therefore
reported `DOWN` instead of `DEGRADED`.

That single misclassification explains the entire observed symptom: the launcher re-ran `docker
compose up -d` against containers already healthy (matching the log line exactly), then retried
the same unwinnable check silently for up to two minutes, then exited — all before the Supervisor
or the FastAPI app were ever constructed. The dashboard was never reached, so there was nothing
to crash and nothing to bind port 8000.

**Fix — structure over string-matching.** The two probes are now independent and their meaning is
determined by *which query failed*, not by inspecting the failure: a failure on `SELECT 1` is a
genuine connectivity problem (`DOWN`); any failure on the schema probe — reached only once
connectivity has already succeeded — means "reachable, not migrated yet" (`DEGRADED`), regardless
of driver, wrapper class, or wording. This closes the door the original bug walked through and
cannot be reopened by a future driver change producing yet another message shape.

**Secondary defect found while tracing this.** `_try_start_services()` called `subprocess.run`
directly inside the async event loop — unlike `_apply_migrations()`, three lines below it, which
was correctly offloaded via `asyncio.to_thread`. That blocked the entire loop, including Ctrl-C
handling, for the duration of the `docker compose` call. Fixed to match its neighbour.

**Also fixed:** the retry loop gave zero output for up to two minutes, which is indistinguishable
from a hang — it now prints a heartbeat every ~15 seconds. And the `"Dashboard: ..."` banner
printed unconditionally at the very top of `launch()`, before preflight had run at all — an
aspirational claim stated as fact. It now prints only once startup has actually reached the point
of serving it.

**Verification.** `tests/test_preflight.py` reproduces the exact reported shape (a wrapper
exception named `ProgrammingError`, Postgres's "does not exist" wording) and asserts `DEGRADED`,
plus a connectivity-failure case asserting `DOWN`, a healthy case asserting `OK`, and a
wording-independent case using a wholly invented exception class — closing the mechanism, not one
instance of it. All four run against the real, unmodified `preflight.py` in this session (with
`sqlalchemy` stubbed, since it isn't installed in this sandbox) and pass.

---

## M5-F6 — the app window ran on the wrong thread (fixed)

**Found by the owner on the first real-hardware launch.** The launcher started correctly —
preflight classified a fresh database as "reachable but not set up yet" (confirming the M5-F5
fix), migrations applied, the dashboard bound and reported ready — and then the window thread
died with `WebViewException: pywebview must be run on a main thread`.

**Root cause: inverted thread ownership.** `desktop.open_window` ran `webview.start()` on a
daemon thread while asyncio held the main thread. Native GUI toolkits own the main thread's
message loop and pywebview refuses to start anywhere else. This is a platform constraint, not
something to work around, so the ownership had to invert: **the window takes the main thread
and the asyncio event loop runs on a background thread.**

Nothing in the architecture changed — this is process topology (D-016, D-017), and the
separately-runnable API and worker entrypoints are untouched.

**A second defect, in the first version of the fix.** `main()` used `Thread.is_alive()` to
decide whether startup had succeeded. That is a race: a launch that raises leaves its thread
briefly alive, so the window opened onto a backend that had already died. Replaced with an
explicit `StartupOutcome` (in `jarvis/shell/supervisor.py`) carrying `done` — set on every exit
path, so a waiting thread is never stranded — and `serving`, set True only once the dashboard
port is actually bound. Success is now stated, not inferred.

**A third defect found while fixing it.** The window previously opened immediately after the
supervisor started its parts, before anything had bound port 8000, so the operator's first
impression could be a connection-error page. Both window and browser now wait on
`desktop.wait_for_dashboard`, a plain TCP connect probe — it tests exactly the property that
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
does. The window itself still has not been opened on real hardware — that remains the owner's
next check.

---

## M5-F7 — duplicate request model shadowed the create-company contract (fixed)

**Found by the owner** on the first end-to-end create-company attempt, once the desktop window
made the flow reachable: the UI sent `{template, name, budget_usd}` and the API rejected it,
demanding `type_name` and `display_name`.

**Root cause: two classes named `CreateCompanyBody` in `jarvis/api/app.py`.** A leftover from
the M5 reconciliation (finding M5-F1) — when the parallel implementations were merged, the
duplicate *route* was removed but both *request models* survived. Python binds the name to the
second definition, so `type_name`/`display_name` silently shadowed the correct
`template`/`name` model. The route body read `body.template` (the first model); FastAPI
validated against the second. The validator and the route disagreed because they referenced
different classes with the same name.

This is the exact hazard M5-F1 warned about: two writers in one file, and a name collision that
no test caught because both classes were individually valid. Fixed by deleting the shadowing
duplicate. A static check now asserts the three sides of the contract agree (below).

**Also addressed — raw validation errors reached the operator (§12.5).** FastAPI's default 422
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

## M5-F8 — duplicate "New company" control, and a template dead-end (fixed)

**Owner UX review after the desktop app reached the create flow on hardware.**

**Duplicate action.** The dashboard exposed two "New company" buttons — one in the header beside
Settings, one in the "Your companies" section header — performing the same action. Removed the
section-header one; the header button is the single persistent control. The empty state now
carries a one-time call-to-action, which is the empty state doing its job of inviting the first
action rather than a duplicate of a standing control.

**Template dead-end.** When no templates were installed, the create dialog said "None installed"
and stopped — a first-run dead end if `ensure_builtin_types` was ever skipped or a database
reset. Added `POST /api/company-templates/install-builtin` (idempotent; installs only what's
missing) and wired the empty-template state to an "Install starter template" button that calls
it and reopens the dialog. First-run onboarding no longer terminates in a message.

Both are operational/§12.5 UI work, no architecture impact. The friendly-validation-error work
requested in the same review was already delivered under M5-F7.

## Roadmap revision 4 — recorded

M6 reframed from "Finance Tracking (second business type)" to "Affiliate vertical slice (prove
the platform end to end)"; Finance moves to M7. Full justification in `docs/ROADMAP.md`.
Classification: structural — the order in which milestones exercise existing code changes, and
M6's definition of done becomes a working end-to-end transaction rather than a new component; no
layer, responsibility, or invariant moves. The prior M6 packets are in `docs/packets/archive/`.

---

## D-018 — product experience is a governed, first-class objective

**Decision.** Product quality is established as a first-class engineering objective with its own
governance, parallel to architectural governance and subordinate to correctness. A read-only
`product-reviewer` agent reviews operator experience and reports directly to the Engineering
Manager, gating any milestone with an operator-facing surface. The product constitution is
`docs/PRODUCT.md`; the standing priority order (correctness → vertical slices → workflow →
product experience → polish) is recorded in `docs/ROADMAP.md`.

**Why.** Correctness and delight are different questions optimising for different outcomes, and
a milestone can satisfy one while failing the other. Left ungoverned, product quality becomes
the thing perpetually deferred — so it is given the same machinery that keeps architecture
honest: an independent, read-only reviewer that cannot implement or decide, only report. The
objective is deliberately long-term (premium desktop software) while the current UI is
explicitly a functional prototype; the reviewer judges movement toward the objective, not
arrival, so the prototype is free to look plain but not to confuse or dead-end.

**Boundaries.** The product-reviewer never edits code, never makes implementation decisions, and
never issues pixel- or colour-level prescriptions — it describes experience problems and desired
outcomes and leaves implementation to the Manager and the operator-surface-engineer. It is to
product what the architecture-auditor is to correctness, including the rule that it reports to
the Manager and never sits under the delivery-coordinator.

**Classification: operational/process.** No layer, responsibility, or invariant in the running
system changes. This governs how work is reviewed, not what the software is.


---

## D-019 — the engineering process is stable by default

**Decision.** As of the Claude Code transition, the engineering system — governance, delegation,
reviewers, gates, manifest pipeline — is considered complete and stable by default. New
governance, reviewers, or process is introduced only when the existing process *demonstrably
fails*, not preemptively. The focus shifts from building the factory to building the product:
every milestone must move Jarvis toward being a useful AI operating system, and the process
exists to enable that rather than to become the project.

**Why.** The process matured quickly and well, but process has no natural stopping point — there
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

## D-020 — unresolved stuck work caps the health band below "healthy"
**Fills:** §5 (Health Score), §9 (dead-letter visibility), §12.5 ("[Company] got stuck — here's
what happened")

A company with one or more unresolved dead-lettered jobs MUST NOT present a `healthy` band,
regardless of its weighted score. The weighted formula (headroom 0.30 / reliability 0.45 /
attainment 0.25) remains the score; the band computation gains a hard override: `stuck > 0`
caps the band at `watch`.

**Why.** Found during M6-0, the suite's first real execution: `test_stuck_work_dominates_the_score`
asserts a company with 3 stuck jobs is not healthy, but full budget headroom and full attainment
outvote a reliability of 40 (score 73 ≥ HEALTHY 70). The engine's own comment states reliability
is weighted heaviest "because a company that cannot finish its work is broken in a way that budget
headroom cannot compensate for" — the weights fail to deliver that stated intent at full headroom.
The test and the comment agree; the arithmetic is what's wrong. An override encodes the intent
directly instead of chasing it with weight tuning, and keeps §9's dead-letter visibility
consistent with what the health card tells the operator.

**Rejected:** re-tuning weights (fragile — any future component re-opens the same gap);
relaxing the test (would weaken an assertion both artifacts intend).

**Reversal cost:** low. One band computation, one test.

---

## M6-F1 — dispatch authorization read lifecycle state from a stale contract snapshot (fixed)

Found by M6-0, the first real execution of the suite. `Registry.authorize_invocation`
(`jarvis/registry/registry.py`) derived lifecycle state from the `BusinessContract` JSON written
once at `register_instance` and never updated; `transition()` updates only the
`BusinessInstanceRow.lifecycle_state` column. Every business therefore evaluated as
`PROVISIONING` forever on the dispatch-acceptance check, and all dispatch was denied with
`not_dispatchable` regardless of activation. Failed closed — no unauthorized dispatch was
possible, but no authorized dispatch was either. Caused 13 of the 14 real test failures
(all of `test_capability_pool.py`, `test_valid_invocation_authorized`, and 3 of 4 cases of
`test_every_rejection_path_is_audited`, which the spurious check pre-empted). Two tests passed
by coincidence (`PROVISIONING` and `PAUSED` both fail `accepts_dispatch`). Fix: authorization
reads live state via `get_state()`. Security-relevant path (D-002), routed to security-engineer
on Opus with audit.

## M6-F2 — health banding contradicted the engine's stated intent (fixed)

See D-020, which records the arbitration. The suite's first execution surfaced it; the fix
implements the band cap.

## M6-F3 — `set_type_enabled` raised an undefined name (fixed)

Found by ruff's first real run (F821). `jarvis/registry/registry.py` raised `RegistryError` for
an uninstalled type, but the name was never imported — the class existed in
`jarvis/kernel/errors.py` all along; the bug was a missing import, so the real runtime behaviour
was `NameError`. Fixed with the import plus a regression test in `tests/test_registry.py`.
Illustrative of the M6-0 theme: code written without an interpreter fails in ways only execution
finds.

## M6-F4 — a workflow-less activity produced `TypeError`, not the documented refusal (fixed)

Found by pyright's first real run. temporalio types `Info.workflow_id` as `str | None` (None
when an activity was not started by a workflow); `RuntimeIdentity.from_activity` passed it
straight into the workflow-id regex, so the promised `ScopeViolationError` was actually a bare
`TypeError`. Manager decision (resolving the M6-0g escalation): a workflow-less activity has no
derivable business identity and is refused with `ScopeViolationError` — D-002, fail closed. The
guard only adds a refusal; it removes no check. Regression tests in
`tests/test_runtime_identity_boundary.py`, including the negative control.

## D-021 — the wake cycle is bounded by planning; `cycle_id` is minted in `plan_cycle`
**Fills:** §2.1 (wake-cycle cost ceiling), D-003 tier 2, D-004 (ids minted in activities)

Found live in M6-1 (M6-F8): every `ScopedRequest` carried a NULL `cycle_id`, so the per-cycle
budget check (`if cycle_id is not None`) never fired — §2.1's ceiling was structurally
unenforced and `BUDGET_EXHAUSTED` unreachable. Decision: a cycle begins when planning begins.
`plan_cycle` (an activity — D-004 keeps minting out of the workflow) mints the `cycle_id` and it
threads through dispatch, synthesis, and the decision record. Rejected: minting in
`load_cycle_context`, which would open the cycle before the wake actually starts reasoning — a
Manager parked for 20 hours would hold a 20-hour-old cycle id, making the ceiling's window
meaningless.

**Reversal cost:** low-medium — a field on three payloads, all internal to the Manager path.

**Implemented in M6-1b.** Three notes the implementation forced, none of which change the
decision above:

1. `BUDGET_EXHAUSTED` now comes from the ledger's refusal, not from a guess. The workflow
   previously inferred it (`any result dead-lettered AND spend >= ceiling`) because no real
   signal existed. With the id threaded, D-003 refuses the reservation *before* the spend and
   the refusal arrives as a failed `dispatch_capability`; the workflow reads the failure type
   and ends the cycle `BUDGET_EXHAUSTED` (D-003 rule 5). Keeping the heuristic alongside the
   real signal would have left two disagreeing definitions of the same outcome.
2. The workflow reads `plan_payload.get("cycle_id")`, and `record_cycle_decision` reads its
   payload key the same way. A history captured before D-021 carries neither, and §11 requires
   it to still replay — verified: the committed fixture replays unchanged, so no re-capture and
   no model spend was needed.
3. A cycle can fail *before* it has an id, since D-021 puts the cycle's start at planning's
   start. That is recorded with an empty cycle id rather than suppressed.

## M6-F5 … M6-F11 — the first live run's harvest

What only a live run could find (M6-F5/F6 hit during the first interrupted attempt, fixed and
re-verified; F7–F11 found by the completed run):

- **M6-F5 (fixed):** Temporal's default data converter cannot encode the pydantic payloads — no
  cycle could ever run. Pydantic data converter wired in the container.
- **M6-F6 (fixed):** every LLM transport sent a default `temperature`, which current models
  reject → HTTP 400 in `plan_cycle`. Now optional, omitted unless set.
- **M6-F7 (open):** `python -m jarvis.api.server` 500s on every DB route —
  `asyncio.run(ensure_builtin_types())` closes the loop the asyncpg pool bound to before
  `uvicorn.run()` opens a new one. The launcher path does it correctly.
- **M6-F8 (fixed, M6-1b):** the NULL `cycle_id` above; resolved by D-021. `plan_cycle` mints the
  id and stamps every request it builds; ledger rows, the synthesis payload, and the Decision Log
  entry all carry it. See M6-F12 for the part of the ceiling that is still not enforced.
- **M6-F9 (fixed, M6-1b):** an activity failure fails the whole Manager workflow
  (`WORKFLOW_EXECUTION_FAILED`) — the business is left Manager-less and `CycleOutcome.FAILED`
  is unreachable, contra §9's requirement that a stuck Manager surface rather than vanish.
  Fixed for the cycle body: an exhausted activity ends the cycle `FAILED` (or
  `BUDGET_EXHAUSTED` when a ceiling refused it), writes an operator-language Decision Log entry,
  counts against the daily wake allowance, and returns to the wake loop. See M6-F13 for the
  remaining unguarded call.
- **M6-F10 (open):** self-sustaining wake loop: the Affiliate type subscribes to
  `capability.result_returned`, but under D-001 every result is already awaited and consumed
  *inside* the cycle that requested it — so each cycle's own output re-wakes the business,
  bounded only by `max_cycles_per_day`. Decision (config, not architecture): remove
  `capability.result_returned` from the Affiliate wake conditions; schedule and
  `approval.decided` remain. A result arriving outside its requesting cycle cannot exist under
  D-001; if a future business type needs result-driven wakes, that is a D-001 conversation, not
  a config default.
- **M6-F11 (open):** the live model authored a prose `action_type`
  ("affiliate.Hold publication and re-run compliance review") where A-003 requires a stable
  dotted identifier — and graduation counters key on that string. The platform must validate
  proposed action types against the business type's declared set and reject/degrade prose
  (D-013: the model proposes, the platform validates). Routed to the approval path work (M6-2).

## D-022 — budget reservations are committed before spend and serialized per scope
**Fills:** D-003 rule 1 ("refused *before* the spend occurs") under concurrency; resolves M6-F12
and M6-F14

Mechanism:
1. **Reserve, committed, first.** Before any model call or dispatch spends, a reservation row is
   written and committed in its own short transaction. Within that transaction the headroom
   check runs under a per-scope serialization (advisory transaction lock on the scope key, or
   `FOR UPDATE` on a scope row — implementer's choice), counting committed spend *plus* live
   reservations. Two concurrent reservations against the same headroom can no longer both pass.
   The long-running work itself never holds the lock — parallel dispatch stays parallel
   (M4-F1 guard).
2. **Reservation amount** = the invocation's §2.2 budget allocation (dispatches), or the call's
   bounded worst-case cost (Manager reasoning calls, M6-F14 — derived from the request's token
   ceiling, not guessed). `plan_cycle` and `synthesize_results` reserve against the same cycle
   ceiling as dispatches; the Manager's own reasoning is spend like any other (D-003 "every
   unit of spend").
3. **Terminality releases.** A reservation resolves when its invocation/call reaches a terminal
   state — finalized to actual cost on success/failure-with-cost, released on refusal — riding
   D-001's guarantee that every invocation terminates. No TTL heuristics; a dead-lettered
   invocation's terminal result releases its reservation on the same path.

**Rejected:** SERIALIZABLE isolation for all ledger transactions (retry storms, penalizes reads);
relying on activity-end commit timing (the M6-F12 race, observed live: 1.40 committed against a
1.00 ceiling).

**Reversal cost:** medium. Ledger schema gains a reservation table/state; all spend paths route
through it. But D-003's semantics don't change — this is enforcement, not policy.

## M6-F12 … M6-F14 — found while implementing D-021 (M6-1b)

- **M6-F12 (open, escalated):** every D-003 ceiling is under-enforced across *concurrent*
  debits. Each `dispatch_capability` activity holds its own session and `kernel.services()`
  commits only when the activity finishes, so the pre-flight `SELECT sum(...)` in one dispatch
  cannot see a sibling's uncommitted reservation. Verified against the running Postgres, not
  inferred: two reservations of one cycle each read a spend of 0.00, both passed, and the
  committed cycle spend was 1.40 against a 1.00 ceiling. This is why the wake-cycle ceiling is
  proven here on sequential dispatch only — a cycle's three parallel dispatches can still
  overshoot it. Pre-existing (it applies to the business cap and the platform breaker equally);
  D-021 only made it observable, because before this the per-cycle branch never ran at all.
  D-003 says reservations exist precisely so "two concurrent invocations cannot both pass a
  check against the same remaining headroom", so the intent is settled and the mechanism is
  not: isolation level, row lock, or committing reservations in their own transaction are
  different trade-offs. **Not decided here** — it needs its own packet.
- **M6-F13 (open):** `load_cycle_context` is still unguarded. It runs *before* the cycle exists
  (D-021), so its failure has no cycle to record, and surviving it needs a policy for a Manager
  that cannot read its own context — park, back off, or reuse the last context — which is an
  unspecified mechanism, not an implementation detail. M6-F9's fix therefore covers the cycle
  body only; a load failure past its retries still fails the workflow.
- **M6-F14 (open):** the Manager's own reasoning is not charged to any ceiling. `plan_cycle` and
  `synthesize_results` call the provider directly through `_ask_model`, with no ledger
  reservation — but D-003 says "every unit of spend (model tokens and metered tool calls)"
  debits all four scopes, and those two calls are most of a cycle's cost. §2.1's per-cycle
  ceiling therefore bounds only what a cycle *dispatches*, not what it costs.

## M6-F15 … M6-F19 — found while implementing D-022 (M6-1d)

- **M6-F15 (bounded):** `CompletionRequest` has an output token ceiling but no input ceiling;
  reasoning-call reservations bound input by encoded byte length (strict upper bound, loose in
  the safe direction). A real input ceiling belongs with pricing work (M6-F16).
- **M6-F16 (open):** no per-token pricing exists — `Usage.cost_usd` is populated by none of the
  transports. Reasoning calls settle on reported tokens × the configured price bound
  ($50/M in `BudgetSettings`, deliberately conservative); dispatch settles its reservation in
  full. Two settlement rules coexist; unify when real cost tracking lands.
- **M6-F17 (open):** activity retries of `plan_cycle` re-mint `cycle_id`, so a refusal caused by
  *accumulated* cycle spend can pass on retry against a fresh cycle scope. Candidate fix
  (deferred, D-021 amendment): derive the cycle key deterministically in the workflow as
  run-id + cycle counter — deterministic derivation, not minting, so D-004 holds. Bundle with
  M6-F13.
- **M6-F18 (open):** a worker dying between `reserve` and `settle`/`release` orphans a RESERVED
  row forever; D-022's terminality principle assumes a terminal result arrives, which process
  death defeats. Needs a reconciliation sweep (§9 territory). Bundle with M6-F13.
- **M6-F19 (config, resolved for dev):** with reasoning correctly charged, the $1.00 dev
  wake-cycle ceiling against $0.50 dispatch allocations admits one dispatch per cycle — a
  three-dispatch plan ends `BUDGET_EXHAUSTED`. Correct enforcement, wrong dev ratio. Manager
  call: local `.env` ceiling raised $1.00 → $2.00 (a three-dispatch cycle fits at ~$1.53).
  Per-business production ceilings remain the owner's explicit choice at company creation
  (spec Defaults in Force), and the platform $500/24h breaker is untouched (owner-adjustable
  only).

## D-023 — a cycle's plan may sequence dependent dispatches
**Fills:** §2.1 ("the Manager MAY dispatch multiple capability requests in parallel" — silent on
dependencies; "workflow orchestration" and "capability coordination" are Manager duties);
resolves M6-F24

Found live in M6-2: every dispatch in a cycle is independent, so Compliance never sees
Content's draft, and the Affiliate type's only declared action (`affiliate.publish_post`) is
legitimately unreachable — the model's prose action types in M6-1 were it routing around this
gap. Decision:

1. The plan (model-proposed, platform-validated like everything else per D-013) may declare
   that an invocation consumes the results of named earlier invocations in the same cycle.
2. The workflow dispatches in dependency waves; invocations within a wave stay parallel
   (M4-F1 guard holds per wave). Cycles with no declared dependencies behave exactly as today.
3. A dependent invocation receives the declared prior results in its scoped request context —
   same business, same memory scope, an explicit grant per §2.2. Capabilities still never call
   each other (§2); only the Manager threads results between them.
4. D-001 (all invocations terminate within the cycle), D-021/D-022 (ceiling binds across all
   waves), and synthesis-waits-for-all are unchanged. A dependency on a FAILED/DEAD_LETTERED
   result makes the dependent invocation's dispatch a Manager decision recorded in the plan
   semantics: it is not dispatched, and synthesis sees why.

**Rejected:** capabilities invoking capabilities (§2 MUST NOT, worker-to-worker); synthesizing
an approvable action from results no compliance capability reviewed (that is the gap's shape,
not its fix).

**Reversal cost:** medium — plan schema + dispatch loop + prompts; no schema migration.

## M6-F20 … M6-F24 — found while proving the approval roundtrip (M6-2)

- **M6-F20 (fixed):** the operator API built `ApprovalService` without an event bus, so
  approve/deny published no `approval.decided` — D-006's loop was open at the only place a
  human closes it. All construction now routes through `kernel.build_approvals`, with a
  structural test forbidding direct construction.
- **M6-F21 (fixed):** `EventBus.claim` filtered by type only; the scheduler could hand one
  company another's events (§10 isolation; each leaked event is a paid wake). Claims are now
  business-scoped.
- **M6-F22 (fixed for affiliate):** `ensure_builtin_types` is version-gated, so config fixes
  never reached the Registry without a version bump; affiliate bumped 1.0.0 → 1.0.1 (minor —
  A-003 resets graduation on major only). General staleness detection remains open.
- **M6-F23 (fixed, M6-2b — entry corrected per M6-4 audit):** the default-ceiling setting now
  has its reader (`container.build_provisioning` → `ProvisioningService`) and the create-company
  API accepts an explicit ceiling. The residual gap is M6-F25 only (no per-company ceiling edit
  after creation).
- **M6-F24 (open → resolved by D-023):** independent dispatches make the declared approvable
  action unreachable; see D-023.

## M6-F25 … M6-F27 — found while implementing D-023 (M6-2b)

Manager ratification first: M6-2b's latitude choices stand — 3-wave depth bound (cannot exceed
the plan item cap; depth is serial round-trips inside one ceiling), 8,000-char granted-output
truncation (pending a real input ceiling, M6-F15), any-order refs with explicit cycle
detection, ambiguous duplicate refs unaddressable (dependents dropped, the items themselves
run), positional refs when the model supplies none.

- **M6-F25 (open):** the ceiling reader is forward-looking only — the live Trailhead contract
  keeps its $1.00; no backfill or per-company ceiling-edit path exists. Fine for M6 (Summit
  Trail Gear at $2.00 is the live-run vehicle); a per-company edit surface is future operator
  work.
- **M6-F26 (open, widens M6-F16):** dependent invocations carry granted context that raises
  real input cost, but dispatch settles at the flat §2.2 allocation — the settlement gap grows
  with chained cycles. Unify at the pricing pass (M6-F16).
- **M6-F27 (accepted):** `idempotency_key` now varies with granted content — a publish derived
  from a different draft is a different action. Correct under A-001; noted as behaviour change.

## D-024 — the approved-action effect binding
**Fills:** D-015/§10 execution mechanics left open until M6-3; ratifies the three mechanisms
M6-3 introduced

1. **The effect payload is platform-composed from stored capability output** — the
   compliance-reviewed draft the cycle recorded — never re-authored by a model at execution
   time. Extends D-011/D-013's stored-values principle across the execution boundary.
2. **The effect destination is deployment configuration keyed by credential handle**
   (`JARVIS_TOOL_ENDPOINTS__*`), deliberately not an approval parameter an operator can correct
   nor anything a model can propose. Where an effect lands is an ops decision, not a runtime one.
3. **The A-001 idempotency key derives from the approval id** — stable across activity retries
   and workflow replays; one approval, at most one effect.

**Rejected:** payload re-authoring at execution (model prose crossing the §8 gate); destination
as an action parameter (M6-F30 — an operator "correction" could redirect an effect);
per-attempt invocation ids in the key (M6-F32 — a retry would publish twice).

**Reversal cost:** medium; these are now load-bearing for every future tool.

## M6-F28 … M6-F34 — found while closing the execution loop (M6-3)

- **M6-F28 (fixed):** no entrypoint ever fed secrets to the Kernel — `CredentialManager` was
  empty in production and the publish tool degraded to an unauthenticated POST (now it refuses).
- **M6-F29 (fixed):** `execute_approved_action` took tool, credential handle, and granted set
  from its own payload — the caller certified its own grant. Now derived from action type ×
  registry × contract.
- **M6-F30 (fixed):** the destination came from operator-editable approval parameters
  (see D-024.2).
- **M6-F31 (fixed):** nothing called `execute_approved_action` — every approval since M6-2 was
  a row and nothing else. The approval-decided wake now executes before planning.
- **M6-F32 (fixed):** per-attempt invocation ids made the A-001 key vary — a Temporal retry
  would have published twice (see D-024.3).
- **M6-F33 (open, escalated):** no workflow-versioning convention — adding a command to a live
  path breaks replay of running histories; M6-3 terminated and restarted the Manager to ship.
  Needs `workflow.patched()` or equivalent as policy before any production posture.
- **M6-F34 (open):** an executed approval reaches the next planning prompt as raw
  `approval:<id>` text with no executed-signal — the model plans work to "clear" it. Prompt/
  context shaping needed.

## M6-4 / M6-5 verdicts and the REVISE round

M6-4 (architecture audit): **MERGE WITH FOLLOW-UPS** — slice verified against the live DB and
the pristine pre-M6 tree; no invariant test weakened; no decision contradicts the spec. Its two
code findings are packeted (M6-4a): the approval surface must show the effect payload the
operator is authorizing (D-011's threat model now covers `parameters` since D-024.1 made them
the published bytes; graduation must not fire on sight-unseen approvals), and Manager
activities must assert derived identity (D-002) where a payload-selected id reaches a
contract/credential/effect. Doc rot (HANDOFF, DEPENDENCIES) and the M6-F23 entry are corrected
this round. §12.5-at-runtime and M6-F34 are bundled into the pending resilience/prompt packet.

M6-5 (product review): **REVISE** — packeted (M6-5a). Blocking item: the dashboard renders
blank (a listener bound to a nonexistent element id halts all subsequent script, including the
initial paint). Re-review required after fixes.

**D-020 amendment (Manager decision, from M6-5 finding 5):** sustained zero goal-attainment
must pull the health *band* down, not just the score — a business with configured KPI targets,
attainment 0, and at least 5 completed cycles since activation caps at `watch`. A company that
ships nothing is not "healthy" no matter how untouched its budget is; same principle as the
stuck-work cap, same mechanism.

## D-025 — audited refusals commit independently; Postgres-backed tests gate what SQLite cannot see
**Fills:** §10/§11 (a denial that leaves no record is invisible); ratifies M6-4b's mechanism;
resolves M6-F38/M6-F40's decision

1. **Own-transaction denial writes** (M6-4b, ratified): an audit record of a refusal commits in
   its own short transaction before the refusal propagates — same pattern family as D-022's
   reservation transactions. A failed denial-write is logged and swallowed: losing the record
   is bad; losing the refusal is a §10 breach. Sites that raise only after their session scope
   closes cleanly are exempt and allowlisted in the AST sweep test, with reasons.
2. **Postgres test lane** (resolves M6-F40): SQLite substitution cannot observe independent
   commits (StaticPool sweeps the caller's work in; file-backed locks block the write), so
   correctness of D-022 and D-025.1 is gated by Postgres-backed tests (marker-gated, running
   against the local stack — the pattern `test_budget_reservation_concurrency.py` already
   uses). conftest's "nothing depends on a Postgres-only feature" claim is corrected to name
   this exception explicitly. When the stack is down those tests skip visibly — skipped is
   reported, never counted as verified (M5-F5 discipline). Implementation folded into the
   resilience packet.

## M6-F39 … M6-F42 — found while fixing denial persistence (M6-4b)

- **M6-F39 (fixed):** `ToolExecutor`'s unpermitted-tool refusal was never audited at all — a
  §10 refusal indistinguishable from a cycle that quietly did less.
- **M6-F40 (open → resolved by D-025.2):** the SQLite suite cannot observe independent-commit
  behaviour; Postgres lane decided.
- **M6-F41 (fixed):** two tests silently stopped testing their stated property when the new
  refusal fired first (M5-F5 class); fixtures corrected with reasons in-test.
- **M6-F42 (open):** `CredentialManager` refuses without any audit (holds no session by
  design); defence-in-depth behind the pool's audited check. Give credential refusals a record
  or document sufficiency — resilience packet.

## M6-F43 / M6-F44 — found in the REVISE round (M6-5a)

- **M6-F43 (fixed):** the Registry wrote raw lifecycle enum values into operator-visible
  Decision Log text ("moved from provisioning to active") — fixed at the write path with
  D-007's labels, plus the new render-boundary guard catches the class.
- **M6-F44 (accepted for now):** `/api/health` existed only under the shell topology; fixed for
  `jarvis.api.server` by duplicating the three checks locally, because sharing `shell/preflight`
  would be a milestone-layering violation (shell is M5, api is M3). Accepted as a flagged
  duplication; unifying it (moving the checks down a milestone) is a future architecture call.
- The M6-5 "mojibake" finding was investigated to the bytes (hex dump of the live row, JSON
  encoding, static charset, fetched bytes — all clean UTF-8): a reviewer-terminal rendering
  artifact, not a product defect. No fix applied; recorded so nobody chases it again.

## M6 closure — both gates cleared

M6-4 (architecture): **MERGE** — follow-ups closed by M6-4a/M6-4b or formally recorded.
M6-5 re-review (product): **SHIP WITH FOLLOW-UPS** — the blocking blank-dashboard defect is
gone; the slice is walkable end to end against real data. Milestone report:
`docs/reports/M6.md`.

Product follow-ups carried into the next surface milestone (from the re-review, in its
priority order — F1 first, it is the second round on the same complaint):
- **F1:** notification queue must reconcile against reality on read (approval-linked notes
  whose approval isn't pending don't render); today only the decide route resolves them, so
  the expiry path strands notifications permanently.
- **F2:** drop stripped ids with their parenthetical ("(something)" reads as a bug).
- **F3:** "Doing now" renders past-tense post-mortems under a present-tense label; cap at word
  boundary + rename or render present activity.
- **F4:** create-dialog error styled as a timestamp; use the existing `.formErr`.
- **F5:** sub-stall healthy band shows a green bar over "Behind on its goals" — wording must
  agree with the band.
- **F6:** notification bodies bypass the render boundary (a 40-word model paragraph renders
  raw); route the strip through the same laundering as cards and feed.
- Runtime §12.5 guard term list needs morphological coverage ("woken" vs "wake cycle",
  "business" vs "company") — fold into the same packet as F1/F6.

Open engineering ledger at closure (all recorded above, none blocking a dev-posture slice):
M6-F13, F16, F17, F18, F25, F26, F33 (must close before production posture), F34, F42, F44,
D-025.2 implementation (Postgres test lane).

## M6 notes — accepted during the typing pass, not defects

- M6-0f's `TypeGuard` narrowing in `jarvis/manager/activities.py` means malformed-shape LLM
  JSON (e.g. a non-dict list element) now degrades (skip/empty) instead of crashing. Accepted:
  consistent with the file's stated degrade-rather-than-raise philosophy and with D-013 (the
  model proposes; the platform validates). No test exercised the old behaviour.
- Suite size: HANDOFF's "229 tests" was a count of test functions; pytest collects 394 (now 399
  with M6-0 regression tests) because of parametrization. The larger number is the real one.
- Flagged for the M6-4 audit: `execute_approved_action` derives its business from the approval
  row rather than `RuntimeIdentity` — audit against D-002.
