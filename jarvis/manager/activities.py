"""Business Manager activities (spec §2.1; D-004).

Everything the Manager workflow cannot do itself: clock reads, database access,
and model calls. Each is an activity with a recorded result, which is what makes
the workflow replayable (D-004).

The planning and synthesis activities are where the Manager's judgement lives.
They are model calls on a scheduled cadence, never a continuous loop, which is
the classification §3 requires of every judgement function at every layer.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple, TypeGuard

from temporalio import activity

from jarvis.approvals.models import ApprovalRequest
from jarvis.budget.ledger import reasoning_call_cost_usd, reasoning_call_reservation_usd
from jarvis.capabilities.idempotency import IdempotencyStore, idempotency_key
from jarvis.capabilities.request import (
    PRIOR_RESULTS_KEY,
    CapabilityResult,
    InvocationStatus,
    MemoryScope,
    ScopedRequest,
)
from jarvis.capabilities.tools import DESTINATION_PARAM
from jarvis.domain.contract import (
    BusinessContract,
    CapabilityPermission,
    CapabilityType,
    WakeConditions,
)
from jarvis.domain.kpi import KpiMapping, KpiObservationScope, KpiSource
from jarvis.domain.lifecycle import accepts_dispatch
from jarvis.domain.schedule import next_fire_at
from jarvis.kernel.container import KernelServices, PlatformKernel
from jarvis.kernel.errors import RegistryError, ScopeViolationError
from jarvis.kernel.ids import (
    BusinessId,
    InvocationId,
    new_approval_id,
    new_cycle_id,
    new_decision_id,
    new_invocation_id,
    new_notification_id,
)
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import CompletionRequest, Message, Role
from jarvis.manager.state import CycleOutcome, KpiTargetState, PlanItem, TacticalPlan
from jarvis.manager.types import (
    CycleContext,
    CycleKpiRequest,
    DependentContextRequest,
    DispatchSequence,
    PlanRequest,
    PriorResultGrant,
    ProposedAction,
    SynthesisRequest,
)
from jarvis.notifications.service import NotificationKind, NotificationService

logger = get_logger(__name__)

PLANNER_SYSTEM = (
    "You plan the next round of work for one business. You decide what to do next "
    "within targets you are given; you never set strategy, move money between "
    "businesses, or decide whether a business should exist. Reply only with JSON."
)
"""Encodes §2.1's scope limit in the prompt as well as in code. The code is the
enforcement — there is no field in which the model could return a strategy
change — but a planner told it owns strategy would produce worse tactics."""

SYNTHESIS_SYSTEM = (
    "You summarise what a business just did, for its owner to read. Write plain "
    "sentences a non-technical owner understands. Reply only with JSON."
)

MAX_ITEMS_PER_CYCLE = 3
"""How many pieces of work one plan may propose. Was an unnamed literal; D-023
gives it a second job, because it is also what bounds how deep a dependency
chain can be."""

MAX_DEPENDENCY_WAVES = 3
"""Bound on dependency depth (D-023's platform-side validation).

Three, for two reasons that agree. A cycle proposes at most
`MAX_ITEMS_PER_CYCLE` items, so a chain deeper than that cannot exist without
already exceeding the item cap — the bound is a guard, not a constraint the
planner can feel. And each wave is a *serial* round trip inside a single cycle
that carries one cost ceiling (D-021) and must terminate within itself (D-001):
depth is the one dimension of a plan that trades latency for nothing, so it is
the one that gets an explicit ceiling rather than an implicit one.

Items that would land past the bound are dropped and recorded, like any other
malformed proposal — never re-ordered into something shallower, which would be
guessing at what the model meant."""

MAX_GRANTED_RESULT_CHARS = 8_000
"""How much of one prior result a dependent invocation is granted (D-023 point 3).

Bounded here rather than left to the model's output length: `CompletionRequest`
has an output ceiling but no input ceiling (M6-F15), so an unbounded thread
would let each wave's input grow with the last wave's verbosity, inside a cycle
whose ceiling is a dollar figure rather than a token figure. Eight thousand
characters is roughly two thousand tokens — comfortably above the 400-700 word
drafts the Affiliate flow threads, so the bound truncates a runaway rather than
the normal case."""

CAPABILITY_SUCCEEDED_EVENT = "capability.succeeded"
"""The audit entry a capability invocation writes when it returns usable output
(`CapabilityPool._execute_with_retry`). Named here because D-027.2 makes it a
KPI source: it is where the *completion* of a piece of work is recorded (§11),
and a freshness metric has nowhere else to read one from. Duplicated as a
string rather than imported because `capabilities` writes audit names inline;
`test_cycle_kpi_measurement.py` dispatches through a real pool and reads the
row back, so the two cannot drift apart silently."""

MANAGER_PARKED_SUMMARY = "{name} couldn't start its next round of work and will try again shortly."
MANAGER_PARKED_RATIONALE = (
    "Jarvis couldn't read this company's current setup, so it waited instead of "
    "acting on out-of-date information."
)
MANAGER_PARKED_TITLE = "{name} is waiting to try again"
MANAGER_PARKED_BODY = (
    "Jarvis couldn't read this company's current setup, so nothing was started. "
    "It keeps trying on its own, and nothing it had already done is lost."
)
"""Spec §12.5, for the one record whose text cannot be authored in the workflow.

Every other operator sentence the Manager produces lives beside the branch that
chooses it, in `jarvis/manager/workflow.py`. These four cannot: they name the
company, and the company's display name is exactly what the failed context read
did not deliver (D-034.1). So the workflow decides *that* a park is recorded and
this activity — which can still read the contract — decides what it says.

Same register as the rest: what it means for the company, never what failed
inside the platform. `tests/test_operator_language.py` holds them to it."""


class DroppedWakeCopy(NamedTuple):
    """The two sentences one kind of dropped wake reason produces (D-035)."""

    title: str
    body: str


DROPPED_WAKE_COPY: dict[str, DroppedWakeCopy] = {
    "approval": DroppedWakeCopy(
        title="{name} has an answered approval waiting",
        body=(
            "You answered a request for this company while it was paused, so "
            "nothing has been done about it. Start the company again when you "
            "want your answer carried out."
        ),
    ),
    "capability.result_returned": DroppedWakeCopy(
        title="{name} has a finished piece of work waiting",
        body=(
            "This company finished a piece of work it had already started, "
            "while it was paused, so nobody has looked at it yet. Start the "
            "company again when you want it picked up."
        ),
    ),
    "kpi.threshold_breached": DroppedWakeCopy(
        title="{name} passed a level you set while it was paused",
        body=(
            "One of the numbers you asked Jarvis to watch passed the level "
            "you set while this company was paused, so nothing was done "
            "about it. Start the company again when you want it looked at."
        ),
    ),
}
DROPPED_WAKE_DEFAULT = DroppedWakeCopy(
    title="{name} has something waiting",
    body=(
        "Something this company was set up to respond to arrived while it was "
        "paused, so nothing has been done about it. Start the company again "
        "when you want it looked at."
    ),
)
"""Spec §12.5 for D-035's notice, keyed by what arrived.

D-035 rejected preserving a paused company's wake reasons for automatic
execution at resume — an operator who paused a company to stop it must not be
surprised by a burst of work when they start it — and rejected today's silent
drop just as firmly. What is left is telling them, and telling them usefully
means saying *which* thing is waiting: "you answered a request" and "a number
you watch moved" are different sentences and lead to different decisions.

Keyed rather than templated on the raw reason, because the raw reason is an
internal event name (`capability.result_returned`) and §12.5 forbids that
register reaching an operator at all. An unmapped kind falls back to
`DROPPED_WAKE_DEFAULT`, which says the true thing without naming the mechanism —
so a bus event added later degrades to a vaguer sentence instead of leaking one.

Authored here rather than beside the branch in the workflow for the same reason
the park's records are: the sentence names the company, and the display name is
a contract read. The words themselves are the copy pass's to settle — M8-9's
review tightened `capability.result_returned` (the original's "Work ... had
already started finished" read as a garden-path sentence) and
`kpi.threshold_breached` (matched its "Start the company again" phrasing to
the other three entries, which had drifted to a bare "Start it again"); the
"approval" entry and the default were confirmed as written, no change.

D-035's own resolution ratified that `WAITING_ON_RESUME` is the operator
category (`NotificationKind`, `jarvis/notifications/service.py`) — a value
this file's `record_dropped_wake` activity below writes to on every dropped
reason, deduplicated per company (see `notified` there), distinct from
`PAUSED` (the seven-day sweep's "answer this") for the reason recorded there:
sharing a kind would let the sweep's own unread notice suppress this one."""

LATE_WAKE_TITLE = "{name} missed a scheduled round"
LATE_WAKE_BODY = (
    "Jarvis wasn't running when this company's round was due, so that round was "
    "skipped rather than run late. The next one happens at its usual time, and "
    "nothing it had already done is lost."
)
"""Spec §12.5 for the notice a skipped scheduled round raises (design 4.4).

The operator's question after an outage is "did my company do its work?", and
the honest answer is that one round did not happen and the schedule is
unchanged. It says that without saying why the platform was down, because the
company's situation is what §12.5 asks for and the platform's is what the
record below is for.

Deliberately not "it will catch up". It will not, and that is the design: a
runtime down thirteen hours must never restart into thirteen hours of rounds,
each of which costs money and none of which is worth running — the content of a
missed morning planning round is worthless by that evening. Promising a catch-up
in the copy would be the one sentence here that is false."""

LATE_WAKE_EVENT = "wake.skipped_after_period"
"""The audit entry beside the notice (design 4.4, §11).

Same division as D-035's: the notice is one per company until dismissed, so it
cannot be the count; the audit log keeps every skipped period with the lateness
that caused it. That number is the forensic half — "wakes have been getting
later for a week" is a sentence someone can only write from these rows."""

DROPPED_WAKE_EVENT = "wake.dropped_while_paused"
"""The audit entry D-035 requires beside the notification.

The notification is one per company until it is dismissed; the audit log keeps
every occurrence, with the kind and the ref it carried. Same division as the
park's (§11 is the forensic record, §12.5's queue is what the operator has to
read), and the reason it matters here is that the notice deliberately does not
accumulate — so the record of *how many* things a pause has dropped has to live
somewhere that does."""


class CycleNoticeCopy(NamedTuple):
    """The two sentences one unfinished round produces (M9-F118)."""

    title: str
    body: str


UNFINISHED_ROUND_COPY: dict[str, CycleNoticeCopy] = {
    CycleOutcome.FAILED.value: CycleNoticeCopy(
        title="{name} couldn't finish its last round of work",
        body=(
            "Something it needed didn't answer, so it stopped rather than "
            "press on with half an answer. It will try again on its next "
            "scheduled round, and nothing it had already done is lost."
        ),
    ),
    CycleOutcome.BUDGET_EXHAUSTED.value: CycleNoticeCopy(
        title="{name} reached its spending limit for one round of work",
        body=(
            "It had used the amount set aside for a single round, so it "
            "stopped instead of spending past the limit you set. Its next "
            "scheduled round starts with a fresh allowance."
        ),
    ),
}
"""Spec §12.5 for the notice a cycle that did not finish raises, keyed by how
it ended — and, by being keyed that way, the whole of the policy for *which*
outcomes tell the operator anything at all.

The gap this closes is structural rather than a bug in a notification. Until
M9-7 `record_cycle_decision` wrote a Decision Log entry and stopped there,
while `record_manager_park` — the sibling below, for the *other* way a round
fails to happen — wrote an entry *and* raised a notice. So a Manager that could
not read its context reached the operator without their looking, and a Manager
whose round failed outright did not. M9-F118 is that asymmetry observed live:
all three companies' rounds failed within seven seconds of each other against a
provider returning 404, every containment behaved exactly as designed, and the
operator-visible signal was nothing at all.

Two entries, not one, because D-003 rule 5 already insists these are different
facts everywhere else in the platform: a round that broke sends an operator
looking for a fault, a round that stopped on its ceiling does not. The
workflow's own `CEILING_STOP_*` and `CYCLE_FAILED_*` templates make the same
split for the feed; this makes it for the queue. Every other outcome —
completed, nothing to do, awaiting approval — is absent, which is what makes
absence the answer: a round that ended normally is what the activity feed is
for, and a notice per healthy round is the permanent accumulation §12.5
forbids.

Authored here rather than beside the branch in `jarvis/manager/workflow.py`,
where the feed's own sentences live, for the reason the park's records are: the
sentence names the company, and composing it needs the display name off the
contract. The workflow decides *that* a round ended the way it did — it is
already the thing that chooses the outcome — and this decides what that means
in the operator's language. Keyed on `CycleOutcome` values rather than on free
strings so the two sides cannot drift into a table lookup that silently misses:
an outcome with no row here is silent by construction, never by typo."""

DERIVED_CYCLE_KEY = re.compile(r"cyc_[0-9a-f]{32}_\d{1,9}")
"""The shape a workflow-derived cycle key has (D-034.2, `_cycle_key`).

Matched rather than trusted. The key arrives in an activity payload, and D-002's
rule for a payload is that it says what the caller believes: a key of any other
shape is a mis-assembled request, and the safe answer to one is the behaviour
that predates the field — mint, as D-021 said. This is not the identity check
(`_assert_identity` is), and it does not need to be: a cycle key resolves no
contract, credential, or effect. It only decides which rows the ledger counts
together, so the harm a malformed one could do is a mis-scoped ceiling, and
minting keeps that scope at least correct-per-attempt."""

DEPENDENCY_UNKNOWN_REF = "names a step that is not in this plan"
DEPENDENCY_SELF_REFERENCE = "declares itself as its own input"
DEPENDENCY_CYCLE = "is part of a loop of steps that wait on each other"
DEPENDENCY_BLOCKED = "depends on a step that was not planned"
DEPENDENCY_TOO_DEEP = f"sits more than {MAX_DEPENDENCY_WAVES} steps down a chain"
"""Why a proposed plan item was dropped. These reach the audit log, not the
operator: an item refused at validation was never dispatched and never reaches
synthesis, so what an operator sees is a cycle that did the work that survived
(the same degradation an unpermitted capability name already produces)."""


class ManagerActivities:
    """Activities backing the Business Manager workflow.

    **Every activity here derives its business identity from the Temporal
    runtime and refuses a payload that names a different one (D-002).** Until
    the M6-4 audit this file was the one activity boundary that did not: each
    method took a `business_id` out of its own argument and resolved a contract,
    a credential grant, or an effect from it, while `KernelActivities` — the
    boundary D-002 was written for — derived identity on every path. §10 forbids
    an invocation scoped to one business reaching another's credentials, memory,
    or budget "under any circumstance, including bugs or malformed requests",
    and a payload-carried id is precisely the malformed-request case: the
    workflow that assembled it is the thing being checked.

    The check is not a replacement for anything already here. The bus-scoped
    claim (M6-F21) and the grant check in `prepare_dependent_requests` stay as
    they are; this is the layer underneath them, so a defect in either is caught
    rather than trusted.
    """

    def __init__(self, kernel: PlatformKernel) -> None:
        """Args:
        kernel: Platform Kernel supplying sessions, provider, and services.
        """
        self._kernel = kernel

    @activity.defn(name="load_cycle_context")
    async def load_cycle_context(self, business_id: str) -> dict[str, object]:
        """Load everything a cycle needs from outside the workflow.

        Includes the day ordinal: the workflow needs today's date for wake-rate
        accounting and cannot read a clock itself (D-004).

        **And the schedule, as two absolute instants** (design 4.2): when this
        business next fires, and when the period that fire belongs to ends. Both
        are computed here rather than in the workflow for two reasons that are
        each sufficient — the workflow may not read a clock, and resolving an
        IANA timezone is file-backed I/O that has no business inside the workflow
        sandbox. Because the result is recorded in history, the park the workflow
        computes from it is deterministic on replay by construction. Until M10
        this returned `schedule_interval_seconds`, a flattening of any expression
        to 3600 or 86400 (M10-F4/M10-F13); that field is now written by nothing,
        and `CycleContext` keeps it only so the executions parked on it replay. It also includes
        whether this business's type declares KPI mappings (D-027.2), for the
        same reason one step further out — the workflow has to know whether the
        cycle has a measurement step, and reading a type definition is a
        Registry read.

        The contract's KPI targets travel with it too (M8-F7). They are what the
        planner is asked to work to, and holding them in workflow state meant
        holding whatever they were when the Manager started — up to a hundred
        cycles of drift the moment a contract-refresh path exists (M7-F24).
        Copied, never authored: targets are set by the Executive Layer and the
        Manager has no method to change one.
        """
        identity = RuntimeIdentity.from_activity()
        await self._assert_identity(identity, business_id, reached="contract")
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(BusinessId(business_id))
            state = await svc.registry.get_state(BusinessId(business_id))
            definition = await self._kernel.type_definition(svc, contract.business_type)
            next_fire, period_end = _schedule_instants(contract.wake_conditions, datetime.now(UTC))
            return CycleContext(
                business_id=BusinessId(business_id),
                display_name=contract.display_name,
                dispatchable=accepts_dispatch(state),
                next_fire_at_utc=next_fire,
                period_ends_at_utc=period_end,
                max_cycles_per_day=contract.wake_conditions.max_cycles_per_day,
                wake_cycle_ceiling_usd=contract.budget.wake_cycle_ceiling_usd,
                day_ordinal=datetime.now(UTC).date().toordinal(),
                kpi_targets=tuple(
                    KpiTargetState(
                        key=target.key,
                        target_value=target.target_value,
                        operator_label=target.operator_label,
                    )
                    for target in contract.kpi_targets
                ),
                measures_kpis=bool(_declared_kpi_mappings(definition)),
            ).model_dump(mode="json")

    @activity.defn(name="plan_cycle")
    async def plan_cycle(self, request: PlanRequest) -> dict[str, object]:
        """Decide what to do this cycle and which capabilities to invoke.

        This is also where the wake cycle *begins* (D-021), so the `cycle_id` is
        settled here and stamped onto every request the cycle dispatches. Without
        it every `ScopedRequest.cycle_id` was NULL and the ledger's per-cycle
        check never fired, which left §2.1's cost ceiling structurally
        unenforced (M6-F8).

        **Settled, not necessarily minted (D-034.2).** The workflow now derives
        the cycle's key and sends it in, because minting here made every retry
        of this activity a new cycle scope — a refusal caused by accumulated
        cycle spend passed on the next attempt (M6-F17), and the live ledger
        holds three reservations for one logical cycle to prove it (M7-F25).
        Minting remains for a request that carries no key, which is D-021's
        original path and what every pre-M8-7 caller and captured history has.

        It is also where D-023's dependency graph is validated. The model may
        say that one item consumes another's results; whether it *may* is
        decided here, against the plan's own refs, for cycles, and for depth
        (D-013 — the model proposes, the platform validates). An item whose
        declaration fails any of those checks is dropped and recorded, the same
        degradation an unpermitted capability name already gets: one fewer piece
        of work, never a guess at what was meant.

        Returns:
            The cycle id, the tactical plan, the scoped requests to dispatch,
            and the order to dispatch them in. Requests are built here, not by
            the model: the model proposes intents, and the scopes attached to
            them come from the business's configured permissions. A model that
            could author its own tool and credential scope would make spec
            §2.2's scoping decorative.
        """
        identity = RuntimeIdentity.from_activity()
        # The scopes attached below — tool scope, credential refs, memory,
        # budget — are read off *this* contract, so which contract is the whole
        # of the authorization decision (D-002, §2.2).
        await self._assert_identity(identity, request.business_id, reached="contract")
        cycle_id = _cycle_scope(request.cycle_key)
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(request.business_id)
            targets = (
                "\n".join(
                    f"- {t.operator_label}: target {t.target_value}" for t in request.kpi_targets
                )
                or "- none set yet"
            )
            allowed = [p.capability.value for p in contract.capability_permissions]
            # D-027.5, closing M7-F22: the rules the owner approved for this
            # type were stored on the contract at creation and read by nothing,
            # so a planner has been proposing work with no knowledge of the
            # constraints its company operates under. Included *verbatim* from
            # the stored values — the same discipline D-011 applies to approval
            # text, for the same reason: a rule paraphrased into the prompt is a
            # rule the owner never approved. Bounded by construction (a fixed
            # tuple per type, seven short lines for Finance today, not a
            # per-cycle accumulation), so D-005's bounded working set and
            # D-021's cycle ceiling are unaffected.
            rules = "\n".join(f"- {rule}" for rule in contract.compliance_requirements)
            must_follow = f"Rules it must follow:\n{rules}\n" if rules else ""

            prompt = (
                f"Business: {contract.display_name}\n"
                f"Goals set for it:\n{targets}\n"
                f"{must_follow}"
                f"Woken because: {', '.join(request.wake_reasons) or 'scheduled round'}\n"
                f"Work it can do: {', '.join(allowed) or 'none'}\n\n"
                'Return JSON: {"rationale": str, "items": '
                '[{"ref": str, "intent": str, "capability": str, "depends_on": [str]}]}. '
                f"Return at most {MAX_ITEMS_PER_CYCLE} items. "
                "Return an empty list if nothing needs doing.\n"
                'Give every item a short unique "ref". Items run at the same time '
                'unless you say otherwise: list in "depends_on" the refs of the '
                "items whose results this one needs, and it will run after them "
                "and be given their results. Use it when one piece of work reads "
                "another's output — writing from research, reviewing a draft — and "
                "leave it out otherwise, because work that waits for nothing "
                "finishes sooner. Anything needing sign-off should be reviewed "
                "first. Every ref you name must belong to another item in this "
                "same list."
            )
            # Charged to the cycle this activity is minting, not to no scope at
            # all (M6-F14). The id exists before the call, so the plan call is
            # the first thing the cycle's ceiling sees.
            parsed = await self._ask_model(
                PLANNER_SYSTEM,
                prompt,
                services=svc,
                contract=contract,
                cycle_id=cycle_id,
            )

            raw_items = parsed.get("items")
            if not _is_object_list(raw_items):
                raw_items = []
            proposed = _permitted_items(raw_items[:MAX_ITEMS_PER_CYCLE], contract, allowed)
            graph = _dependency_graph([(p.ref, p.depends_on) for p in proposed])

            for index, reason in sorted(graph.rejected.items()):
                await self._record_dependency_rejection(
                    services=svc,
                    contract=contract,
                    cycle_id=cycle_id,
                    ref=proposed[index].ref,
                    declared=proposed[index].depends_on,
                    reason=reason,
                )

            invocation_ids = {
                index: new_invocation_id()
                for index in range(len(proposed))
                if index not in graph.rejected
            }
            items: list[PlanItem] = []
            requests: list[ScopedRequest] = []
            for index in sorted(invocation_ids):
                item = proposed[index]
                items.append(
                    PlanItem(
                        ref=item.ref,
                        intent=item.intent,
                        depends_on=tuple(proposed[d].ref for d in graph.edges[index]),
                    )
                )
                requests.append(
                    ScopedRequest(
                        invocation_id=invocation_ids[index],
                        declared_business_id=request.business_id,
                        capability=item.capability,
                        prompt_ref=f"{contract.business_type}.{item.capability.value}",
                        prompt_inputs={"intent": item.intent},
                        # Scopes come from the contract, never from the model.
                        tool_scope=item.permission.tool_scope,
                        credential_refs=item.permission.credential_refs,
                        memory_scope=(
                            MemoryScope.READ if item.permission.memory_read else MemoryScope.NONE
                        ),
                        budget_allocation_usd=item.permission.max_invocation_budget_usd,
                        # D-003 tier 2: what the ledger counts this spend against.
                        cycle_id=cycle_id,
                    )
                )

            plan = TacticalPlan(
                items=tuple(items),
                rationale=str(parsed.get("rationale") or "Routine round of work."),
            )
            sequence = DispatchSequence(
                waves=tuple(
                    tuple(invocation_ids[i] for i in layer) for layer in graph.layers if layer
                ),
                grants={
                    invocation_ids[i]: tuple(
                        PriorResultGrant(ref=proposed[d].ref, invocation_id=invocation_ids[d])
                        for d in graph.edges[i]
                    )
                    for i in invocation_ids
                    if graph.edges[i]
                },
                refs={invocation_ids[i]: proposed[i].ref for i in invocation_ids},
            )
            return {
                "cycle_id": cycle_id,
                "plan": plan.model_dump(mode="json"),
                "requests": [r.model_dump(mode="json") for r in requests],
                "dispatch": sequence.model_dump(mode="json"),
            }

    @activity.defn(name="prepare_dependent_requests")
    async def prepare_dependent_requests(
        self, request: DependentContextRequest
    ) -> dict[str, object]:
        """Attach granted prior results to a wave's requests (D-023 point 3).

        The Manager is the only thing that may do this: §2 forbids capabilities
        from calling each other, so a draft reaches a review because the Manager
        threaded it, never because the reviewer fetched it. What the grant
        carries is *content* — same business, same cycle, and no additional tool,
        credential, or memory rights, all of which still come from the contract.

        Three checks, all platform-side. The business this runs for is derived
        from the runtime, not read off the payload — the same-business test
        below compared two caller-supplied ids to each other, which holds only
        while the caller is right, and §10 says isolation must hold when it is
        not. A result from a different business is then refused and recorded.
        And each granted output is truncated to `MAX_GRANTED_RESULT_CHARS`, so a
        chain's input cannot grow without bound inside a cycle whose ceiling is
        denominated in dollars.

        Returns:
            The same requests, with granted results in their scoped context.
            Requests with nothing granted come back untouched.
        """
        identity = RuntimeIdentity.from_activity()
        await self._assert_identity(identity, request.business_id, reached="granted content")
        for scoped in request.requests:
            await self._assert_identity(
                identity, scoped.declared_business_id, reached="granted content"
            )

        results: dict[str, CapabilityResult] = {r.invocation_id: r for r in request.prior_results}
        prepared: list[ScopedRequest] = []
        async with self._kernel.services() as svc:
            for scoped in request.requests:
                granted: list[dict[str, str]] = []
                for grant in request.grants.get(scoped.invocation_id, ()):
                    result = results.get(grant.invocation_id)
                    if result is None or not result.succeeded:
                        continue
                    if result.business_id != scoped.declared_business_id:
                        await svc.audit.record(
                            event_type="capability.context_grant_refused",
                            actor=request.business_id,
                            business_id=request.business_id,
                            payload={
                                "invocation_id": scoped.invocation_id,
                                "cycle_id": request.cycle_id,
                                "reason": "the earlier result belongs to another business (§10)",
                            },
                        )
                        continue
                    granted.append(
                        {
                            "ref": grant.ref,
                            "capability": result.capability.value,
                            "output": result.output[:MAX_GRANTED_RESULT_CHARS],
                        }
                    )

                if not granted:
                    prepared.append(scoped)
                    continue

                prepared.append(
                    scoped.model_copy(
                        update={
                            "prompt_inputs": {
                                **scoped.prompt_inputs,
                                PRIOR_RESULTS_KEY: granted,
                            }
                        }
                    )
                )
                await svc.audit.record(
                    event_type="capability.context_granted",
                    actor=request.business_id,
                    business_id=request.business_id,
                    payload={
                        "invocation_id": scoped.invocation_id,
                        "cycle_id": request.cycle_id,
                        "granted_refs": [g["ref"] for g in granted],
                    },
                )

        return {"requests": [r.model_dump(mode="json") for r in prepared]}

    @activity.defn(name="synthesize_results")
    async def synthesize_results(self, request: SynthesisRequest) -> dict[str, object]:
        """Summarise the cycle and propose an action if one is warranted (§2.1).

        The model names an intent; this decides whether that intent *is* an
        action (D-013). A proposal whose `action_type` is not one the business's
        type declares is degraded to no action and recorded — see
        `_validated_action_type`.

        Returns:
            An operator-readable summary and, optionally, a proposed action. The
            summary is written for the activity feed, so it must read as plain
            language (spec §12.5).
        """
        identity = RuntimeIdentity.from_activity()
        # This contract decides whether the proposed action is declared, whether
        # it still needs approval, and which effect payload gets attached — the
        # whole §8 gate, resolved from one identity.
        await self._assert_identity(identity, request.business_id, reached="contract")
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(request.business_id)
            logger.info(
                "synthesizing cycle results",
                extra={
                    "context": {
                        "business_id": request.business_id,
                        # D-021: carried so every record this cycle produces —
                        # ledger row, log line, decision entry — groups together.
                        "cycle_id": request.cycle_id,
                        "results": len(request.results),
                    }
                },
            )

            outcomes = "\n".join(
                f"- {r.capability.value}: "
                + (
                    r.output[:400]
                    if r.status is InvocationStatus.SUCCEEDED
                    else f"didn't finish ({r.operator_summary})"
                )
                for r in request.results
            )
            # D-023 point 4: a dependent that was never dispatched is a Manager
            # decision, so synthesis is told about it. Without this the summary
            # would describe a cycle that quietly did less than it planned, and
            # the owner's account of the day would be missing its reason.
            not_started = "\n".join(
                f"- {s.capability}: not started. {s.reason}" for s in request.skipped
            )
            # The declared set is given to the model as well as enforced below.
            # The enforcement is what makes it a boundary (D-013); telling the
            # model which actions exist only stops it inventing one, the way
            # `plan_cycle` already lists the capabilities it may name.
            declared = sorted(contract.declared_action_types)
            unstarted = (
                f"What it planned but did not start:\n{not_started}\n\n" if not_started else ""
            )
            prompt = (
                f"Business: {contract.display_name}\n"
                f"It set out to: {request.plan.rationale}\n"
                f"What came back:\n{outcomes}\n\n"
                f"{unstarted}"
                f"Actions it is allowed to propose: {', '.join(declared) or 'none'}\n\n"
                'Return JSON: {"summary": str, "action": null or '
                '{"action_type": str, "action_summary": str, '
                '"triggering_condition": str, "downside": str}}. '
                '"action_type" must be copied exactly from the allowed list above; '
                "if nothing in that list fits, return null for the action. "
                "Summary must be one plain sentence an owner understands, naming "
                "no internal machinery. Propose an action only if one is clearly "
                "warranted."
            )
            parsed = await self._ask_model(
                SYNTHESIS_SYSTEM,
                prompt,
                services=svc,
                contract=contract,
                cycle_id=request.cycle_id,
            )

            summary = str(parsed.get("summary") or "Finished a round of work.")
            raw_action = parsed.get("action")
            action = None
            if _is_object_dict(raw_action) and raw_action.get("action_type"):
                action_type = await self._validated_action_type(
                    str(raw_action["action_type"]),
                    services=svc,
                    contract=contract,
                    cycle_id=request.cycle_id,
                )
                if action_type is not None:
                    approvals = self._kernel.build_approvals(svc)
                    definition = await self._kernel.type_definition(svc, contract.business_type)
                    action = ProposedAction(
                        business_id=request.business_id,
                        action_type=action_type,
                        action_summary=str(raw_action.get("action_summary") or "take an action"),
                        triggering_condition=str(
                            raw_action.get("triggering_condition") or request.plan.rationale
                        ),
                        downside=str(raw_action.get("downside") or "Unclear — worth a look."),
                        # Nor does the model author the payload. What gets
                        # published is the stored output of the work this cycle
                        # already did, attached here only when the action names
                        # a tool the business can actually reach.
                        parameters=(
                            _effect_parameters(request.results)
                            if _effect_binding(action_type, contract, definition)
                            else {}
                        ),
                        # The model does not decide whether it needs permission.
                        # Autonomy is contract state plus the graduation ladder
                        # (spec §8), so it is resolved here against both.
                        needs_approval=await approvals.requires_approval(contract, action_type),
                    ).model_dump(mode="json")

            return {"summary": summary, "action": action}

    @activity.defn(name="request_approval")
    async def request_approval(self, action: ProposedAction) -> str:
        """Raise an approval request and notify the operator (spec §8, §9)."""
        identity = RuntimeIdentity.from_activity()
        # An approval row is what a later wake turns into a credentialled
        # effect, so writing one under another company's identity would put this
        # company's action in front of that company's owner.
        await self._assert_identity(identity, action.business_id, reached="contract")
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(action.business_id)
            approvals = self._kernel.build_approvals(svc)
            approval_id = new_approval_id()

            await approvals.request(
                request=ApprovalRequest(
                    approval_id=approval_id,
                    business_id=action.business_id,
                    action_type=action.action_type,
                    action_summary=action.action_summary,
                    amount_usd=action.amount_usd,
                    counterparty=action.counterparty,
                    triggering_condition=action.triggering_condition,
                    downside=action.downside,
                    parameters=action.parameters,
                ),
                contract=contract,
            )
            await NotificationService(svc.session).notify(
                notification_id=new_notification_id(),
                kind=NotificationKind.NEEDS_APPROVAL,
                title=f"{contract.display_name} needs your OK",
                body=action.action_summary,
                business_id=action.business_id,
                link_ref=approval_id,
            )
            return approval_id

    @activity.defn(name="execute_approved_action")
    async def execute_approved_action(self, payload: dict[str, object]) -> dict[str, object]:
        """Perform an action the operator approved (D-015).

        Runs the operator's *decided* parameters, not the originally requested
        ones — an approval with modifications executes the modified action
        (A-003's correction semantics), never silently the original.

        Everything else about the call is derived rather than accepted: which
        tool runs, which credential it materialises, and where the effect is
        sent all come from the action type, the contract, and Kernel
        configuration. The activity's payload names an approval and nothing
        more, so a caller cannot choose a credential or a destination
        (M6-F29, M6-F30).

        The A-001 key is derived from the *approval*, which is this effect's
        invocation: the id is stable across activity retries and workflow
        replays, so a second run of an approved action replays its recorded
        result instead of publishing twice (spec §6).

        The approval id in the payload *selects* a row, and everything about the
        effect follows from that row — so an id belonging to another company
        would have this Manager perform that company's approved action with a
        credential resolved from that company's contract. The row's business is
        therefore checked against the derived identity before anything is read
        from it (D-002; the M6-4 audit's second finding).
        """
        from jarvis.persistence.models import ApprovalRow

        identity = RuntimeIdentity.from_activity()
        approval_id = str(payload["approval_id"])

        # Whose approval this is, read on its own and first. The check has to
        # happen before the row is used for anything, and its refusal has to be
        # raised outside the transaction that records it — `services()` rolls
        # back on exception, so a denial audited inside the scope it aborts
        # leaves no trace of having happened.
        async with self._kernel.services() as svc:
            owner = await svc.session.get(ApprovalRow, approval_id)
            claim = (owner.business_id, owner.state) if owner is not None else None
        if claim is None or claim[1] != "approved":
            return {"executed": False, "reason": "not approved"}
        await self._assert_identity(identity, claim[0], reached="credential and effect")

        async with self._kernel.services() as svc:
            row = await svc.session.get(ApprovalRow, approval_id)
            if row is None or row.state != "approved":
                return {"executed": False, "reason": "not approved"}

            contract = await svc.registry.get_contract(BusinessId(row.business_id))
            definition = await self._kernel.type_definition(svc, contract.business_type)
            binding = _effect_binding(row.action_type, contract, definition)
            if binding is None:
                return {"executed": False, "reason": "no tool for this action"}

            params = dict(row.decided_parameters or row.parameters)
            destination_param = DESTINATION_PARAM.get(binding.implementation_key)
            endpoint = self._kernel.settings.tool_endpoints.get(binding.credential_handle or "")
            if destination_param:
                # Configuration wins over anything stored on the approval: the
                # destination is not the operator's parameter to correct, and a
                # payload that carried one would be authority the caller wrote
                # for itself.
                params.pop(destination_param, None)
                if endpoint:
                    params[destination_param] = endpoint

            invocation_id = InvocationId(approval_id)
            replayed = (
                await IdempotencyStore(svc.session).existing(
                    idempotency_key(
                        business_id=BusinessId(contract.business_id),
                        invocation_id=invocation_id,
                        action_type=row.action_type,
                        payload=params,
                    )
                )
                is not None
            )

            result = await self._kernel.build_tools(svc).execute(
                contract=contract,
                invocation_id=invocation_id,
                tool_name=binding.tool_name,
                implementation_key=binding.implementation_key,
                action_type=row.action_type,
                params=params,
                credential_handle=binding.credential_handle,
                granted_credentials=binding.granted_credentials,
            )

            # §11.5: the audit log records that a tool ran; this is the sentence
            # an owner reads. Written after the effect, so an entry claiming the
            # action happened only exists once it has.
            await svc.decisions.record(
                decision_id=new_decision_id(),
                business_id=BusinessId(contract.business_id),
                summary=(
                    f"{contract.display_name} had already done this, so it wasn't done again."
                    if replayed
                    else f"{contract.display_name} did what you approved."
                ),
                rationale=row.action_summary,
                action_type=row.action_type,
                inputs_considered={"approval_id": approval_id},
                structured_action={
                    "action": row.action_summary,
                    "amount_usd": str(row.amount_usd) if row.amount_usd is not None else None,
                    "counterparty": row.counterparty,
                },
            )
            return {"executed": True, "replayed": replayed, "result": result}

    @activity.defn(name="record_cycle_kpis")
    async def record_cycle_kpis(self, request: CycleKpiRequest) -> dict[str, str]:
        """Measure what this cycle did against the type's mappings (D-027.1).

        The activity M7-F21 found missing. `KpiEngine.record` existed from M3
        and no production caller ever reached it, so `kpi_values` had never held
        a row: every company's attainment was structurally zero, and §13 Step
        3's "exercises the KPI/dashboard pattern" was a claim nothing tested.

        Two rules make the numbers trustworthy, and they are the whole point of
        doing this here rather than asking the synthesis model for figures:

        1. **Facts only.** Each observation comes from something the platform
           recorded — this cycle's terminal results, the contract, the audit
           log. Nothing on this path reads model output (D-027.2, D-011's
           reasoning applied to numbers; Finance's compliance rule 4 requires
           every reported figure to have a source).
        2. **Declared, not inferred.** A type says which fact each metric is
           (`kpi_mappings`, data — D-014). A type that declares none records
           nothing at all (D-027.3): the negative case is silence, because a
           company scored zero on a metric nobody defined reads as failing
           rather than as unmeasured.

        Called on a NOTHING_TO_DO cycle too, not only a cycle that dispatched
        something (M7-F32, `jarvis.manager.workflow.PATCH_NOTHING_TO_DO_KPIS`):
        `request.results` is empty on that path, and `KpiSource.scope` is what
        keeps a cycle-result-scoped mapping (`reports_delivered`) from being
        recorded as a false zero there while an observation-scoped one
        (`metrics_tracked`, `data_freshness_hours`) still gets re-read, because
        the fact it reads did not stop existing just because this wake found
        nothing to do.

        No `target` is passed to the engine, so this writes a series and
        publishes no threshold breach. Deliberate on both counts. The engine's
        own contract says the caller decides what a breach means "because the
        engine should not guess the direction" — and direction is exactly what
        a `KpiTarget` does not carry, so a caller passing one would be guessing
        on the engine's behalf. Finance's wake conditions are schedule-only by
        owner-approved scope in any case (M7-F2), so a breach event would wake
        nobody today.

        Returns:
            What was written, key to value, so the recorded activity result
            shows the figures rather than only that measurement ran. An
            unmappable metric is absent rather than zero.
        """
        identity = RuntimeIdentity.from_activity()
        # A KPI series is what an owner reads as "is this company working", and
        # the health band the dashboard shows is computed from it — writing one
        # company's numbers under another's identity would misreport both.
        await self._assert_identity(identity, request.business_id, reached="KPI series")
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(request.business_id)
            definition = await self._kernel.type_definition(svc, contract.business_type)
            mappings = _declared_kpi_mappings(definition)
            if not mappings:
                return {}

            engine = self._kernel.build_kpis(svc)
            recorded: dict[str, str] = {}
            for mapping in mappings:
                value = await self._observed(mapping, request, contract, svc)
                if value is None:
                    # No fact, no observation. A metric the platform cannot
                    # measure yet leaves a gap in the series, which is honest;
                    # filling it with a zero would be a measurement nobody made.
                    logger.info(
                        "kpi mapping had nothing to measure",
                        extra={
                            "context": {
                                "business_id": request.business_id,
                                "cycle_id": request.cycle_id,
                                "key": str(mapping.key),
                            }
                        },
                    )
                    continue
                await engine.record(
                    business_id=BusinessId(contract.business_id),
                    key=str(mapping.key),
                    value=value,
                )
                recorded[str(mapping.key)] = str(value)

            logger.info(
                "recorded cycle KPIs",
                extra={
                    "context": {
                        "business_id": request.business_id,
                        "cycle_id": request.cycle_id,
                        "recorded": recorded,
                    }
                },
            )
            return recorded

    async def _observed(
        self,
        mapping: KpiMapping,
        request: CycleKpiRequest,
        contract: BusinessContract,
        services: KernelServices,
    ) -> Decimal | None:
        """Read one platform fact, or None when there is not one yet (D-027.2).

        The whole of the mapping vocabulary lives here, in the platform. A type
        selects a member; it never describes how the member is computed, which
        is what keeps the arithmetic behind a KPI inside the thing being
        audited.
        """
        source = mapping.source

        if source.scope is KpiObservationScope.CYCLE_RESULT and not request.results:
            # A cycle-result-scoped source has nothing to count when this
            # cycle dispatched nothing — the NOTHING_TO_DO case M7-F32 adds a
            # measurement command to. No fact for *this* cycle, no
            # observation: the same silence D-027.3 gives an unmapped metric,
            # applied here to a cycle rather than a company.
            return None

        if source == KpiSource.SUCCEEDED_RESULTS_IN_CYCLE:
            # Filtered to this business, not counted blindly: the results
            # arrive in a payload, and a payload's account of whose work it was
            # is the malformed-request case D-002 exists for. Also filtered to
            # the mapping's own capability when it declares one (M7-F33), so a
            # cycle running research and finance in the same round scores one
            # report for one delivered report rather than one per capability
            # that merely succeeded.
            return Decimal(
                sum(
                    1
                    for result in request.results
                    if result.status is InvocationStatus.SUCCEEDED
                    and result.business_id == contract.business_id
                    and (mapping.capability is None or result.capability == mapping.capability)
                )
            )

        if source == KpiSource.CONFIGURED_KPI_TARGET_COUNT:
            return Decimal(len(contract.kpi_targets))

        if source == KpiSource.HOURS_SINCE_NEWEST_SUCCEEDED_RESULT:
            completed = await services.audit.latest_entry_time(
                BusinessId(contract.business_id), CAPABILITY_SUCCEEDED_EVENT
            )
            if completed is None:
                return None
            if completed.tzinfo is None:
                # SQLite hands back what Postgres stores with an offset. The
                # rows are written from `datetime.now(UTC)` either way, so a
                # naive value is UTC — said here rather than assumed, because
                # the alternative is a `TypeError` in the one dialect the test
                # suite runs on.
                completed = completed.replace(tzinfo=UTC)
            hours = (datetime.now(UTC) - completed).total_seconds() / 3600
            return max(Decimal("0"), Decimal(str(round(hours, 4))))

        # A mapping naming a source this platform does not implement is a
        # definition ahead of its runtime — recorded and skipped, never guessed.
        logger.warning(
            "kpi mapping names an unknown source",
            extra={"context": {"business_id": request.business_id, "source": str(source)}},
        )
        return None

    @activity.defn(name="record_manager_park")
    async def record_manager_park(self, payload: dict[str, str]) -> dict[str, str]:
        """Explain a Manager that cannot read its own context (D-034.1).

        The record M6-F13 had nowhere to put. A failed `load_cycle_context`
        happens before the cycle exists (D-021), so it has no cycle to be filed
        under and, until D-034, no policy either — past its retries it simply
        failed the workflow and the business lost its Manager, which is the
        indefinite pending state §9 forbids and the same containment family as
        M6-F9.

        Two records, one event. The Decision Log entry is what an owner reads in
        the activity feed; the notification is what reaches them without their
        having to look. `cycle_id` is deliberately absent — nothing was planned,
        so counting this as a cycle would inflate the completed-cycle count the
        health band reads (`KpiEngine._completed_cycle_count`), and a park is the
        opposite of a cycle: it is the round that did not happen.

        The notification is raised only when this company has no unread stuck
        notice already. A degraded Manager looks again every
        `DEGRADED_RETRY_INTERVAL`, and while the workflow already records once
        per episode, that guarantee is a loop local — a worker restart resets it,
        and §12.5's "no permanent accumulation" is not satisfied by a queue that
        refills every quarter hour after one. The Decision Log entry has no such
        guard on purpose: the feed is the forensic narrative, and one entry per
        restart is a fact worth keeping.

        Returns:
            The decision id, and whether an operator was notified — recorded, so
            the activity's result says which of the two records this park
            actually produced.
        """
        identity = RuntimeIdentity.from_activity()
        # Same reasoning as `record_cycle_decision`: no contract, credential, or
        # effect is reached, but one company's account of its day is not
        # another's to write (§10, §11.5).
        await self._assert_identity(identity, payload["business_id"], reached="decision record")
        business_id = BusinessId(payload["business_id"])
        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(business_id)
            decision_id = new_decision_id()
            await svc.decisions.record(
                decision_id=decision_id,
                business_id=business_id,
                summary=MANAGER_PARKED_SUMMARY.format(name=contract.display_name),
                rationale=MANAGER_PARKED_RATIONALE,
                action_type="business.manager_parked",
                inputs_considered={"outcome": "parked"},
            )

            notifications = NotificationService(svc.session)
            notified = not await notifications.has_unread(business_id, kind=NotificationKind.STUCK)
            if notified:
                await notifications.notify(
                    notification_id=new_notification_id(),
                    kind=NotificationKind.STUCK,
                    title=MANAGER_PARKED_TITLE.format(name=contract.display_name),
                    body=MANAGER_PARKED_BODY,
                    business_id=business_id,
                )
            logger.warning(
                "manager parked; its context could not be read",
                extra={"context": {"business_id": business_id, "notified": notified}},
            )
            return {"decision_id": decision_id, "notified": str(notified).lower()}

    @activity.defn(name="record_late_wake")
    async def record_late_wake(self, payload: dict[str, str]) -> dict[str, str]:
        """Tell the operator a scheduled round was skipped, and record it (4.4).

        **This is the single emit site for ``business.late_wake_notice``** —
        L1, approval NONE, AUDIT and NOTIFY_ON_TRANSITION, the row design 7.1
        specifies. L1 by the level's own definition: the whole behaviour is a
        comparison of stored values against a schedule the owner set — a wake's
        service time against its own next fire — firing and announcing without
        asking. It mirrors ``business.dropped_wake_notice`` (D-035) exactly and
        invents no governance vocabulary.

        **The registry row itself is composed at merge, not here** (P0-D lane
        note). Adding an `ACTION_REGISTRY` entry also moves
        `REGISTRY_DIGEST_PIN` and `AUTONOMY_PIN`, which the concurrent Phase 0
        lanes each touch, so this lane declares the emit site and its four
        values and leaves the row to the composition that lands them together.
        Until that row exists the action is emitted by a module the registry
        does not yet describe, which is a gap in the constitution's coverage
        rather than in this code — and it is a gap no gate here can catch,
        because the registry's completeness ratchet binds type-declared L2
        actions rather than platform L1 ones.

        The workflow decides *that* a period was missed, because that is a
        comparison of two recorded instants and therefore pure work it may do
        inside D-004; this composes the sentence, because the sentence names the
        company and a display name is a contract read. The same division
        `record_manager_park` and `record_dropped_wake` make.

        **Both records, and they answer different questions.** The audit entry is
        §11's forensic account — every skipped period with the lateness that
        caused it, which is the only place a "wakes have been getting later for a
        week" trend can be read from. The notification is what reaches the
        operator without their looking, deduplicated to one unanswered notice per
        company: a runtime down for a week would otherwise queue seven identical
        notices whose action is the same one, which is the permanent accumulation
        §12.5 forbids. The audit log is where the count lives.

        Its own `NotificationKind`, for the reason `WAITING_ON_RESUME` and
        `UNFINISHED_ROUND` each have one: a company can meet several of these
        conditions inside a single outage, and sharing a kind would let whichever
        notice arrived first swallow the rest under `has_unread`.

        Returns:
            The lateness recorded and whether an operator was notified — so the
            activity's result says which of the two records this skip produced.
        """
        identity = RuntimeIdentity.from_activity()
        # Same reasoning as `record_cycle_decision`: no contract, credential or
        # effect is reached, but one company's account of its day is not
        # another's to write (§10, §11.5).
        await self._assert_identity(identity, payload["business_id"], reached="operator notice")
        business_id = BusinessId(payload["business_id"])
        lateness = payload.get("wake_lateness_seconds") or "0"

        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(business_id)
            await svc.audit.record(
                event_type=LATE_WAKE_EVENT,
                actor=business_id,
                business_id=business_id,
                workflow_id=identity.workflow_id,
                payload={
                    "wake_lateness_seconds": lateness,
                    "schedule_cron": contract.wake_conditions.schedule_cron,
                    "schedule_timezone": contract.wake_conditions.schedule_timezone,
                    "reason": (
                        "the round's own schedule period had already ended when the wake "
                        "was served, so it was skipped rather than replayed (design 4.4)"
                    ),
                },
            )

            notifications = NotificationService(svc.session)
            notified = not await notifications.has_unread(
                business_id, kind=NotificationKind.MISSED_ROUND
            )
            if notified:
                await notifications.notify(
                    notification_id=new_notification_id(),
                    kind=NotificationKind.MISSED_ROUND,
                    title=LATE_WAKE_TITLE.format(name=contract.display_name),
                    body=LATE_WAKE_BODY,
                    business_id=business_id,
                )
            logger.warning(
                "a scheduled round was skipped; its period had already ended",
                extra={
                    "context": {
                        "business_id": business_id,
                        "wake_lateness_seconds": lateness,
                        "notified": notified,
                    }
                },
            )
            return {"wake_lateness_seconds": lateness, "notified": str(notified).lower()}

    @activity.defn(name="record_dropped_wake")
    async def record_dropped_wake(self, payload: dict[str, str]) -> dict[str, str]:
        """Tell the operator what a pause dropped, and record it (D-035).

        The workflow decides *that* a reason was dropped and what kind it was —
        pure string work it can do inside D-004 — and this composes the sentence,
        because the sentence names the company and the display name is a contract
        read. The same division `record_manager_park` makes.

        **Both records, and they answer different questions.** The audit entry is
        §11's forensic account: every dropped reason, with its kind and its ref,
        for anyone reconstructing why a company that was answered did nothing.
        The notification is what reaches the operator without their looking, and
        it is deduplicated to one unanswered notice per company — a paused
        company can accumulate dropped reasons for as long as it stays paused,
        and ninety of them in the queue is the permanent accumulation §12.5
        forbids. The action is the same for all of them ("start it again"), so
        one notice is not a loss of information; the audit log is where the count
        lives.

        `WAITING_ON_RESUME` rather than `PAUSED`: the seven-day sweep's own
        `PAUSED` notice is "answer this", and this one is what the operator needs
        after they have answered — sharing the kind would let the first suppress
        the second under exactly this deduplication.

        The approval row itself is untouched (D-035). Nothing here queues,
        replays or expires anything: the operator's answer is still stored, and
        `link_ref` is what lets the surface point at it.

        Returns:
            The kind reported and whether an operator was notified — recorded, so
            the activity's result says which of the two records this drop
            produced.
        """
        identity = RuntimeIdentity.from_activity()
        # Same reasoning as `record_cycle_decision`: no contract, credential or
        # effect is reached, but one company's account of its day is not
        # another's to write (§10, §11.5).
        await self._assert_identity(identity, payload["business_id"], reached="operator notice")
        business_id = BusinessId(payload["business_id"])
        reason_kind = payload["reason_kind"]
        reason_ref = payload.get("reason_ref") or None
        copy = DROPPED_WAKE_COPY.get(reason_kind, DROPPED_WAKE_DEFAULT)

        async with self._kernel.services() as svc:
            contract = await svc.registry.get_contract(business_id)
            await svc.audit.record(
                event_type=DROPPED_WAKE_EVENT,
                actor=business_id,
                business_id=business_id,
                workflow_id=identity.workflow_id,
                payload={
                    "reason_kind": reason_kind,
                    "reason_ref": reason_ref,
                    "reason": (
                        "the company is paused, so this was dropped rather than "
                        "queued or carried out (D-035)"
                    ),
                },
            )

            notifications = NotificationService(svc.session)
            notified = not await notifications.has_unread(
                business_id, kind=NotificationKind.WAITING_ON_RESUME
            )
            if notified:
                await notifications.notify(
                    notification_id=new_notification_id(),
                    kind=NotificationKind.WAITING_ON_RESUME,
                    title=copy.title.format(name=contract.display_name),
                    body=copy.body,
                    business_id=business_id,
                    link_ref=reason_ref,
                )
            logger.info(
                "a paused company dropped a wake reason",
                extra={
                    "context": {
                        "business_id": business_id,
                        "reason_kind": reason_kind,
                        "notified": notified,
                    }
                },
            )
            return {"reason_kind": reason_kind, "notified": str(notified).lower()}

    @activity.defn(name="record_cycle_decision")
    async def record_cycle_decision(self, payload: dict[str, str]) -> dict[str, str]:
        """Write the cycle's Decision Log entry, and say so when it went wrong.

        Spec §2.1 and §11.5 for the entry; M9-F118 for the notice.

        Reads `cycle_id` defensively: a history captured before D-021 carries a
        payload without it, and replaying that history must write an entry rather
        than raise a `KeyError` inside an activity.

        **The notice is the asymmetry M9-F118 found.** `record_manager_park`
        above writes both records for the round that never started; this wrote
        only the entry for the round that started and failed — so the loudest
        thing a Manager can do was reserved for the quieter failure. A cycle
        that ends `FAILED` or `BUDGET_EXHAUSTED` now reaches the operator
        without their having to look, in the same shape the park's does:
        `UNFINISHED_ROUND_COPY` above holds the sentences, the audit-facing
        record stays the Decision Log entry, and the queue gets one notice.

        Read off the *recorded outcome*, which the payload has carried since
        this activity existed, so the workflow issues exactly the commands it
        issued before — nothing on the cycle path changes shape, no history
        replays differently, and a Manager already parked on its wake timer
        gains the notice on its next real failure rather than at its next
        continuation (D-033's own rule: versioning is for a *changed command*,
        and there is none here).

        Deduplicated per company and per outcome (`link_ref`), for the reason
        the park's dedup exists — §12.5 forbids permanent accumulation, and a
        provider outage produces one failed round per company per wake for as
        long as it lasts — while still letting a ceiling stop be reported over
        an unread breakage notice, because they are different facts.

        Returns:
            The decision id, and whether an operator was notified — recorded,
            like the park's, so the activity's result says which records this
            cycle actually produced.
        """
        identity = RuntimeIdentity.from_activity()
        # No contract, credential, or effect here — but the Decision Log is what
        # an owner reads to know what their company did, and one company's
        # account of its day is not another's to write (§10, §11.5).
        await self._assert_identity(identity, payload["business_id"], reached="decision record")
        business_id = BusinessId(payload["business_id"])
        outcome = payload["outcome"]
        async with self._kernel.services() as svc:
            decision_id = new_decision_id()
            await svc.decisions.record(
                decision_id=decision_id,
                business_id=business_id,
                summary=payload["summary"],
                rationale=payload["rationale"],
                cycle_id=payload.get("cycle_id") or None,
                action_type="business.wake_cycle",
                inputs_considered={
                    "outcome": outcome,
                    "spend_usd": payload["spend_usd"],
                    # Recorded on every round, not only late ones (4.4): a field
                    # that appears only when something is wrong cannot be
                    # trended, and a week of wakes arriving later each day is
                    # the signal that precedes an outage rather than the one
                    # that follows it. `.get`, because a history captured before
                    # this field replays its own recorded payload (spec §11).
                    "wake_lateness_seconds": payload.get("wake_lateness_seconds", "0"),
                },
            )
            notified = await self._notify_unfinished_round(svc, business_id, outcome)
            return {"decision_id": decision_id, "notified": str(notified).lower()}

    async def _notify_unfinished_round(
        self, services: KernelServices, business_id: BusinessId, outcome: str
    ) -> bool:
        """Raise the operator notice for a round that did not finish (M9-F118).

        Returns False without touching the database for every outcome
        `UNFINISHED_ROUND_COPY` has no sentence for, which is every healthy one.
        That ordering is deliberate rather than incidental: a completed round is
        the common case by a wide margin, and it must not pay for a contract
        read and a notification query to be told it has nothing to say.

        **The entry is never lost to the notice.** The sentence needs the
        company's display name, and a name is a contract read — so a company
        whose contract cannot be read would, without the guard below, take the
        Decision Log entry down with the transaction that was writing it. That
        inverts the two: the entry is §11.5's record of what happened, the
        notice is the addition M9-F118 asks for, and losing the primary to
        serve the secondary is not a trade this path may make.

        Args:
            services: The transaction the Decision Log entry was written in, so
                the entry and the notice commit together or not at all.
            business_id: Whose round it was — derived, already checked.
            outcome: The `CycleOutcome` value the workflow recorded.

        Returns:
            Whether a notification was written.
        """
        copy = UNFINISHED_ROUND_COPY.get(outcome)
        if copy is None:
            return False

        notifications = NotificationService(services.session)
        if await notifications.has_unread(
            business_id, kind=NotificationKind.UNFINISHED_ROUND, link_ref=outcome
        ):
            logger.warning(
                "a round did not finish; the operator already has an unread notice",
                extra={"context": {"business_id": business_id, "outcome": outcome}},
            )
            return False

        try:
            contract = await services.registry.get_contract(business_id)
        except RegistryError:
            logger.warning(
                "a round did not finish and could not be named for the operator",
                extra={"context": {"business_id": business_id, "outcome": outcome}},
            )
            return False
        await notifications.notify(
            notification_id=new_notification_id(),
            kind=NotificationKind.UNFINISHED_ROUND,
            title=copy.title.format(name=contract.display_name),
            body=copy.body,
            business_id=business_id,
            # The condition, not the cycle. A per-cycle ref would make every
            # round its own variant and defeat the deduplication entirely —
            # ninety-six notices a day for one outage, which is exactly the
            # accumulation §12.5 forbids.
            link_ref=outcome,
        )
        logger.warning(
            "a round did not finish; the operator was told",
            extra={"context": {"business_id": business_id, "outcome": outcome}},
        )
        return True

    # ── internals ──────────────────────────────────────────────────────────

    async def _assert_identity(
        self,
        identity: RuntimeIdentity,
        declared_business_id: str,
        *,
        reached: str,
    ) -> None:
        """Refuse a payload naming a business other than the calling workflow's.

        D-002: identity is derived from the Temporal workflow id, which the
        server populates from the workflow that scheduled this activity and
        which activity code cannot forge. The id an activity finds in its own
        argument is advisory — it says what the caller believes, and §10's
        "including bugs or malformed requests" clause means the platform cannot
        make that belief load-bearing.

        Refused, never narrowed. The Registry's `_deny` takes the same line for
        capability invocations, and for the same reason: silently substituting
        the derived id would let a mis-assembled payload run to completion
        against a business nobody meant to act for, and leave the defect
        invisible. Audited before it is refused, because a denial nobody can
        see is the signal an operator most needs (§11).

        Called before the activity opens its working transaction, and it opens
        its own for the record. `services()` rolls back on exception, so an
        audit entry written inside the scope this refusal aborts would be
        rolled back with it — a denial that left no trace, which is the one
        thing a denial must not be.

        Args:
            identity: Derived from `RuntimeIdentity.from_activity()`.
            declared_business_id: The id carried in the activity's payload.
            reached: What the declared id would have reached — recorded so the
                trail says how far a mismatch would have got.

        Raises:
            ScopeViolationError: On any mismatch.
        """
        if identity.business_id == declared_business_id:
            return

        async with self._kernel.services() as svc:
            await svc.audit.record(
                event_type="security.scope_violation",
                actor="platform",
                business_id=identity.business_id,
                payload={
                    "reason": "identity_mismatch",
                    "declared": str(declared_business_id)[:200],
                    "reached": reached,
                    "workflow_id": identity.workflow_id,
                    "identity_source": identity.audit_source,
                },
            )
        logger.warning(
            "refused an activity payload naming another business",
            extra={"context": {"business_id": identity.business_id, "reached": reached}},
        )
        raise ScopeViolationError(
            f"payload declared business {declared_business_id!r} but the calling workflow "
            f"identity is {identity.business_id!r} (spec §10, D-002)"
        )

    async def _record_dependency_rejection(
        self,
        *,
        services: KernelServices,
        contract: BusinessContract,
        cycle_id: str,
        ref: str,
        declared: tuple[str, ...],
        reason: str,
    ) -> None:
        """Record a plan item dropped for a bad dependency declaration (D-023).

        Recorded rather than raised, and recorded rather than repaired. D-023
        gives the platform the validation, not the authorship: a plan naming a
        step that does not exist, or a loop, is a proposal the platform cannot
        act on, and inventing the ordering the model *probably* meant would be
        the platform planning the cycle. So the item is dropped and the audit
        log says which one and why — the same shape as an unpermitted capability
        name producing one fewer plan item.
        """
        await services.audit.record(
            event_type="plan.dependency_rejected",
            actor=contract.business_id,
            business_id=contract.business_id,
            payload={
                "cycle_id": cycle_id,
                "ref": ref[:200],
                "declared_depends_on": [name[:200] for name in declared],
                "reason": reason,
            },
        )
        logger.warning(
            "dropped a plan item with an unusable dependency declaration",
            extra={"context": {"business_id": contract.business_id, "cycle_id": cycle_id}},
        )

    async def _validated_action_type(
        self,
        proposed: str,
        *,
        services: KernelServices,
        contract: BusinessContract,
        cycle_id: str | None,
    ) -> str | None:
        """Return ``proposed`` as a declared action type, or None if it is not one.

        D-013 and M6-F11. A-003 gives an action a stable dotted identity, and
        three separate mechanisms key on that string: the graduation counters
        (D-010), the approval rendering an operator reads (D-011), and the tool
        the approved-action path looks up (D-015). The first live run produced
        `affiliate.Hold publication and re-run compliance review` — a sentence
        the platform namespaced and stored as an approvable action.

        Nothing downstream can recover from that. It is not a known action
        awaiting configuration, which §8 would correctly gate behind approval;
        it names no action at all, so approving it authorises nothing and the
        counter it advances belongs to a string the model invented. A proposal
        carrying one is therefore refused here.

        Refused, not raised: a synthesis that crashed on a bad action name would
        lose the cycle's summary too and cost a retried model call for a
        deterministic parse problem, which is the same degrade-rather-than-raise
        posture the rest of this file takes toward model output. The rejection
        is written to the audit log (§11) so a proposal that never reached the
        operator is still visible to whoever asks why the company did nothing.

        Returns:
            The namespaced action type if the business's type declares it,
            otherwise None.
        """
        action_type = _namespaced(proposed, contract.business_type)
        if contract.declares_action(action_type):
            return action_type

        await services.audit.record(
            event_type="action.proposal_rejected",
            actor=contract.business_id,
            business_id=contract.business_id,
            payload={
                "proposed_action_type": action_type[:200],
                "declared_action_types": sorted(contract.declared_action_types),
                "cycle_id": cycle_id,
                "reason": "action type is not declared by this business type (D-013, A-003)",
            },
        )
        logger.warning(
            "rejected a proposed action outside the declared set",
            extra={
                "context": {
                    "business_id": contract.business_id,
                    "cycle_id": cycle_id,
                    "declared": sorted(contract.declared_action_types),
                }
            },
        )
        return None

    async def _ask_model(
        self,
        system: str,
        prompt: str,
        *,
        services: KernelServices,
        contract: BusinessContract,
        cycle_id: str | None,
    ) -> dict[str, object]:
        """Reserve, call the configured provider, settle, and parse a JSON reply.

        The reservation is D-022 point 2 closing M6-F14: the Manager's own
        reasoning is spend like any other, and D-003 debits "every unit of
        spend" against all four scopes. Before this, `plan_cycle` and
        `synthesize_results` — most of a cycle's cost — were charged to nothing,
        so §2.1's per-cycle ceiling bounded only what a cycle *dispatched*.

        The hold is taken and committed *before* the call (D-003 rule 1: refused
        before the spend occurs) and resolved when the call reaches a terminal
        state (D-022 point 3): settled to the provider's reported tokens on any
        answer, released on any failure. A refusal propagates — the cycle ends
        `BUDGET_EXHAUSTED` (D-003 rule 5), which is a different sentence for the
        operator than "it broke".

        A malformed reply degrades to an empty plan rather than raising. A
        Manager that crashed on bad JSON would take its business down for a
        formatting error, and §9's retry discipline would spend the budget
        retrying something deterministic. That degradation happens *after*
        settlement: the tokens were bought either way.
        """
        request = CompletionRequest(
            messages=(Message(role=Role.USER, content=prompt),),
            system=system,
        )
        price = self._kernel.settings.budget.reasoning_token_price_per_million_usd
        ledger = self._kernel.build_ledger(services)
        reservation = await ledger.reserve(
            contract=contract,
            amount_usd=reasoning_call_reservation_usd(request, price_per_million_tokens_usd=price),
            cycle_id=cycle_id,
        )
        try:
            response = await self._kernel.llm.complete(request)
        except BaseException:
            # Includes cancellation: an abandoned call bought nothing, and a
            # hold nobody releases strangles the business by degrees.
            await ledger.release(reservation)
            raise

        actual = reasoning_call_cost_usd(response.usage, price_per_million_tokens_usd=price)
        # Clamped, never refused: the reservation's worst case is an upper bound
        # on a token count, and a provider that reports past it (chat-template
        # overhead, say) must not turn a completed call into an exception.
        await ledger.settle(reservation, min(actual, reservation.amount_usd))

        text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            parsed: object = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("model returned unparseable JSON; treating as no plan")
            return {}
        return parsed if _is_object_dict(parsed) else {}


def _cycle_scope(supplied: str) -> str:
    """Return the cycle id this cycle's spend counts against (D-034.2).

    The workflow's derived key when it sent a well-formed one, a freshly minted
    id otherwise. Both are `cyc_`-prefixed and both are opaque to everything
    downstream; the difference is that the derived key survives an activity
    retry and a minted one does not.
    """
    return supplied if DERIVED_CYCLE_KEY.fullmatch(supplied) else new_cycle_id()


def _declared_kpi_mappings(definition: Any) -> tuple[KpiMapping, ...]:
    """Return the KPI mappings a business type declares (D-027.2/.3).

    Duck-typed, like `_effect_binding`'s read of `tool_registry` and for the
    same reason: `manager` is M4 and `businesses` is M5, so the layering
    invariant forbids importing `BusinessTypeDefinition` here and the Kernel
    hands the definition over as `Any`. What the mappings *mean* is not
    duck-typed — `KpiSource` lives in `domain`, which both sides may read.

    Tolerant of a definition that predates the field or is absent entirely: an
    uninstalled type measures nothing rather than failing a cycle over it.
    """
    if definition is None:
        return ()
    return tuple(getattr(definition, "kpi_mappings", ()) or ())


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Type-guard: is ``value`` a string-keyed dict?

    A plain ``isinstance(value, dict)`` only proves ``dict[Unknown, Unknown]``
    to pyright, since a runtime check cannot recover key/value type
    parameters. The str-keyed claim here is safe because every value this is
    called on originates from ``json.loads`` on a model reply: JSON objects
    only ever have string keys, so any ``dict`` found already has this shape
    at runtime. This replaces the equivalent bare ``isinstance(x, dict)``
    guards this file used before pyright ran; the runtime check is identical.
    """
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Type-guard: is ``value`` a list?

    Every element of any list is trivially compatible with ``object``, so
    unlike the dict case above no data-shape assumption is needed — this
    exists only because ``isinstance(value, list)`` alone proves
    ``list[Unknown]`` rather than ``list[object]`` to pyright.
    """
    return isinstance(value, list)


class _ProposedItem(NamedTuple):
    """One plan item that survived capability validation, before D-023's."""

    ref: str
    intent: str
    capability: CapabilityType
    permission: CapabilityPermission
    depends_on: tuple[str, ...]


class _DependencyGraph(NamedTuple):
    """A validated plan graph: what runs when, on what, and what was dropped."""

    layers: tuple[tuple[int, ...], ...]
    """Item indices in dispatch order. Everything in one layer is independent."""

    edges: dict[int, tuple[int, ...]]
    """Item index -> indices of the items whose results it consumes."""

    rejected: dict[int, str]
    """Item index -> why it cannot be dispatched at all."""


def _permitted_items(
    raw_items: list[object], contract: BusinessContract, allowed: list[str]
) -> list[_ProposedItem]:
    """Return the proposed items whose capability the contract permits.

    Unchanged in substance from before D-023 — a hallucinated or unpermitted
    capability name still produces one fewer item rather than an error (D-013) —
    with two additions. `depends_on` is carried through for the graph pass, and
    an item that supplied no `ref` gets a positional one instead of its
    capability's name, because two research items previously shared a single ref
    and a dependency naming it could not say which was meant.
    """
    items: list[_ProposedItem] = []
    for raw in raw_items:
        if not _is_object_dict(raw):
            continue
        capability = _capability_or_none(raw.get("capability"), allowed)
        if capability is None:
            continue
        permission = contract.permission_for(capability)
        if permission is None:
            continue
        supplied = str(raw.get("ref") or "").strip()
        items.append(
            _ProposedItem(
                ref=supplied or f"{capability.value}-{len(items) + 1}",
                intent=str(raw.get("intent") or "do the next useful thing"),
                capability=capability,
                permission=permission,
                depends_on=_declared_refs(raw.get("depends_on")),
            )
        )
    return items


def _declared_refs(raw: object) -> tuple[str, ...]:
    """Return the dependency refs a plan item declared, de-duplicated.

    A missing or malformed declaration reads as "no dependencies", which is the
    pre-D-023 behaviour and the safe direction: an item that declares nothing is
    dispatched immediately alongside its siblings, exactly as before.
    """
    if not _is_object_list(raw):
        return ()
    seen: list[str] = []
    for name in raw:
        if isinstance(name, str) and name.strip() and name.strip() not in seen:
            seen.append(name.strip())
    return tuple(seen)


def _dependency_graph(declared: list[tuple[str, tuple[str, ...]]]) -> _DependencyGraph:
    """Validate D-023's declarations and lay the plan out in dispatch waves.

    Pure, and deliberately so: it is called from an activity (validation is
    platform work, D-013) but holds no I/O, which is what lets it be tested
    against every malformed shape a model can produce without a database.

    Four ways a declaration is refused, all of them recorded by the caller and
    none of them repaired:

    * it names a ref no item in this plan owns — including a ref two items
      share, which names nothing unambiguously;
    * it names itself;
    * it is part of a cycle (detected, not assumed away: refs are matched in any
      order, because a model listing a reviewer before the draft it reviews has
      declared a valid graph in an inconvenient order, and reordering that is
      reading, not guessing);
    * it would sit deeper than `MAX_DEPENDENCY_WAVES`.

    An item depending on a refused item is refused too. Dispatching it would put
    work in front of a capability with a hole where its input was supposed to be.
    """
    refs = [ref for ref, _ in declared]
    counts = Counter(refs)
    addressable = {ref: index for index, ref in enumerate(refs) if counts[ref] == 1}

    edges: dict[int, tuple[int, ...]] = {}
    rejected: dict[int, str] = {}
    for index, (ref, names) in enumerate(declared):
        resolved: list[int] = []
        for name in names:
            if name == ref:
                rejected[index] = DEPENDENCY_SELF_REFERENCE
                break
            target = addressable.get(name)
            if target is None:
                rejected[index] = DEPENDENCY_UNKNOWN_REF
                break
            resolved.append(target)
        edges[index] = tuple(resolved)

    changed = True
    while changed:
        changed = False
        for index in range(len(declared)):
            if index in rejected:
                continue
            if any(target in rejected for target in edges[index]):
                rejected[index] = DEPENDENCY_BLOCKED
                changed = True

    layers: list[tuple[int, ...]] = []
    placed: set[int] = set()
    remaining = {index for index in range(len(declared)) if index not in rejected}
    while remaining:
        layer = tuple(
            index for index in sorted(remaining) if all(t in placed for t in edges[index])
        )
        if not layer:
            for index in remaining:
                rejected[index] = DEPENDENCY_CYCLE
            break
        if len(layers) >= MAX_DEPENDENCY_WAVES:
            for index in remaining:
                rejected[index] = DEPENDENCY_TOO_DEEP
            break
        layers.append(layer)
        placed.update(layer)
        remaining.difference_update(layer)

    return _DependencyGraph(layers=tuple(layers), edges=edges, rejected=rejected)


def _capability_or_none(raw: object, allowed: list[str]) -> CapabilityType | None:
    """Map a model-supplied capability name onto a permitted capability.

    Returns None for anything unrecognised or unpermitted, so a hallucinated
    capability produces one fewer plan item rather than an error or an
    unauthorised dispatch.
    """
    if not isinstance(raw, str) or raw not in allowed:
        return None
    try:
        return CapabilityType(raw)
    except ValueError:
        return None


def _namespaced(action_type: str, business_type: str) -> str:
    """Return ``action_type`` namespaced to its business type (A-003)."""
    return action_type if "." in action_type else f"{business_type}.{action_type}"


class _EffectBinding(NamedTuple):
    """How one approved action reaches one tool (D-015)."""

    tool_name: str
    implementation_key: str
    credential_handle: str | None
    granted_credentials: frozenset[str]


def _effect_binding(
    action_type: str,
    contract: BusinessContract,
    definition: Any,
) -> _EffectBinding | None:
    """Resolve which tool an approved action runs, and with which credential.

    Every part of this is *derived*, never declared by the caller. A-003 makes
    the action type a stable dotted identifier whose local part names the
    action, D-014 maps that name onto an implementation in the business type's
    `tool_registry`, and the contract says which capability may reach that tool
    and with which credential handles. Before M6-3 the tool name, the credential
    handle, and the set of granted handles all arrived in the activity's payload
    — so whoever called the activity chose the credential to materialise *and*
    certified that it had been granted, which is precisely the self-declared
    authority D-002 and §2.2 exist to remove (M6-F29).

    Returns:
        The binding, or None when the action names no tool this business can
        reach — the same degradation an unpermitted capability name gets.
    """
    tool_name = action_type.rsplit(".", 1)[-1]
    implementation = str(definition.tool_registry.get(tool_name, "")) if definition else ""
    if not tool_name or not implementation:
        return None

    permission = next(
        (p for p in contract.capability_permissions if tool_name in p.tool_scope), None
    )
    if permission is None:
        return None

    # Exactly one, or none: a permission carrying several handles cannot say
    # which one this tool authenticates with, and guessing would materialise a
    # credential nobody chose. None leaves the tool to refuse loudly.
    handle = (
        next(iter(permission.credential_refs)) if len(permission.credential_refs) == 1 else None
    )
    return _EffectBinding(
        tool_name=tool_name,
        implementation_key=implementation,
        credential_handle=handle,
        granted_credentials=frozenset({handle}) if handle else frozenset(),
    )


PUBLISHABLE_CAPABILITIES: tuple[CapabilityType, ...] = (
    CapabilityType.OPERATIONS,
    CapabilityType.CONTENT,
)
"""Which capability's output an effect publishes, most-prepared first.

Operations prepares finished material for publishing and Content drafts it, so
an operations result supersedes the draft it was made from. Anything else in a
cycle — research notes, a compliance verdict — is input to that material rather
than the thing itself."""

MAX_ACTION_TITLE_CHARS = 120


def _effect_parameters(results: tuple[CapabilityResult, ...]) -> dict[str, object]:
    """Compose an approvable action's payload from what the cycle produced.

    The payload is assembled by the platform out of *stored* capability output,
    never re-authored by the synthesis model. That is D-011's reasoning applied
    one step further out: an operator approving a post must be approving the
    draft that was written and reviewed, not a summary model's retelling of it,
    or the bytes published would be text no compliance step ever saw.

    The key names (`title`, `body`) belong to the tool's own parameter contract.
    A declared per-tool parameter schema is the general answer and does not
    exist yet; until it does, this composes the one shape the built-in tools
    take, and an action whose cycle produced no publishable output gets an empty
    payload and fails at the tool boundary rather than silently publishing
    nothing.

    Returns:
        Effect parameters, or an empty mapping when nothing publishable came
        back.
    """
    for capability in PUBLISHABLE_CAPABILITIES:
        latest = next(
            (
                r
                for r in reversed(results)
                if r.capability is capability
                and r.status is InvocationStatus.SUCCEEDED
                and r.output
            ),
            None,
        )
        if latest is None:
            continue
        return {"title": _title_of(latest.output), "body": latest.output}
    return {}


def _title_of(body: str) -> str:
    """Return a title taken from the body's own first line.

    Deterministic string handling of a stored value, so the title an operator
    approves is a line of the draft rather than a second model call's opinion of
    what the draft is called.
    """
    for line in body.splitlines():
        cleaned = line.strip().lstrip("#*_ ").strip()
        if cleaned.lower().startswith("title:"):
            cleaned = cleaned[len("title:") :].strip()
        cleaned = cleaned.strip("*_`\"'").strip()
        if cleaned:
            return cleaned[:MAX_ACTION_TITLE_CHARS]
    return "Untitled"


def _schedule_instants(
    wake_conditions: WakeConditions, now: datetime
) -> tuple[datetime | None, datetime | None]:
    """Return when this business next fires, and when that period ends.

    Two instants rather than one because 4.4's rule needs both: the first is
    what the Manager parks to, the second is the moment that park's period is
    over and a still-unserved wake must be skipped instead of run. A duration
    would not do — cron periods are not uniform, and ``"0 9,16 * * *"`` has a
    seven-hour period and a seventeen-hour one.

    Replaces `_interval_seconds`, which reduced every expression to 3600 or
    86400 (M10-F4) and re-anchored the schedule on every park (M10-F13). Both
    defects are gone at once here, because they were one defect: computing
    against the calendar *is* the anti-drift property.

    Args:
        wake_conditions: The contract's schedule and its timezone.
        now: This activity's own clock read, passed in so the computation itself
            stays a pure function of its inputs.

    Returns:
        The next fire and the fire after it, both UTC, or ``(None, None)`` for a
        business woken only by events.

    Raises:
        ScheduleError: If the stored expression or timezone is one this platform
            cannot execute. Loud rather than degraded, deliberately: contract
            validation refuses these at creation, so reaching one here means a
            value that predates the validation, and the answer to it is a
            Manager that parks visibly (D-034.1) rather than a company that
            quietly stops waking.
    """
    next_fire = next_fire_at(wake_conditions.schedule_cron, wake_conditions.schedule_timezone, now)
    if next_fire is None:
        return None, None
    period_end = next_fire_at(
        wake_conditions.schedule_cron, wake_conditions.schedule_timezone, next_fire
    )
    return next_fire, period_end


def all_manager_activities(kernel: PlatformKernel) -> list[Callable[..., object]]:
    """Return every Manager activity for worker registration."""
    instance = ManagerActivities(kernel)
    return [
        instance.load_cycle_context,
        instance.plan_cycle,
        instance.prepare_dependent_requests,
        instance.synthesize_results,
        instance.request_approval,
        instance.execute_approved_action,
        instance.record_cycle_kpis,
        instance.record_cycle_decision,
        instance.record_manager_park,
        instance.record_dropped_wake,
        instance.record_late_wake,
    ]


__all__ = ["ManagerActivities", "all_manager_activities"]
