"""Business Manager workflow (spec §2.1; D-004, D-005, D-006).

One Manager per business, implemented as a Temporal workflow rather than a
service or a standing process. It wakes on schedule or triggering event,
executes its planning and evaluation logic, and suspends.

**This is not a standing reasoning loop.** The `while` below is a suspension
point, not a spin: between cycles the workflow holds no thread, consumes no
compute, and issues no model call. All reasoning happens inside a bounded cycle
body. §2.1 and §3 forbid persistent reasoning loops at any layer, and a
Temporal workflow parked on a timer is the mechanism that satisfies it.

**This file contains no I/O and no nondeterminism.** No clock read, no UUID, no
HTTP, no database handle, no model call. Every one of those happens in an
activity with a recorded result (D-004), which is what makes §11's replay
requirement achievable. Anything added here that is not pure orchestration
breaks replay silently — the workflow will pass its tests and diverge on
recovery.

**Generality (spec §3.2, §4.1).** Nothing here assumes a business sits directly
under the Executive Layer. The Manager reports to `state.supervisor`, which is
`executive` today and could be a district identifier later without redesign.
Districts are not built and MUST NOT be built speculatively; this is the
forward-compatibility §4.1 asks for, not an implementation of them.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from decimal import Decimal

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from jarvis.capabilities.request import CapabilityResult, ScopedRequest
    from jarvis.manager.state import (
        CycleOutcome,
        CycleResult,
        ManagerState,
        SkippedDispatch,
        TacticalPlan,
    )
    from jarvis.manager.types import (
        CycleContext,
        DependentContextRequest,
        DispatchSequence,
        PlanRequest,
        ProposedAction,
        SynthesisRequest,
    )

CYCLES_BEFORE_CONTINUATION = 100
"""Cycles before `continue_as_new` (D-005). Bounds workflow history so a Manager
running for months does not accumulate its way into a hard failure."""

ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISPATCH_TIMEOUT = timedelta(minutes=15)

STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_attempts=3,
)
"""Bounded retry (spec §9). Manager activities are subject to the same
retry/timeout discipline as any other workflow, so a stuck Manager surfaces
rather than holding its business in an indefinite pending state."""

CEILING_REFUSAL_TYPES = frozenset({"BudgetExceededError", "CircuitBreakerOpenError"})
"""Failure types that mean *a ceiling refused the work*, not that the work failed
(D-003). Matched by name because a workflow sees a serialised failure, never the
original exception object — the alternative, importing the error classes into
workflow code, would put a live type from the I/O side of D-004 in here.

`CircuitBreakerOpenError` is included because it subclasses `BudgetExceededError`
in the kernel taxonomy: from the cycle's point of view both mean the same thing,
that spending stopped it rather than a fault."""

CEILING_STOP_SUMMARY = "{name} stopped early to stay inside its spending limit."
CEILING_STOP_RATIONALE = "It had used the amount set aside for one round of work."
CYCLE_FAILED_SUMMARY = "{name} couldn't finish this round of work and will try again next time."
CYCLE_FAILED_RATIONALE = (
    "Something it needed didn't respond, so it stopped instead of pressing on with half an answer."
)
DEPENDENCY_SKIP_REASON = "The earlier step it builds on didn't finish, so it wasn't started."
"""Spec §12.5. These reach the operator's activity feed, so they say what it
means for the company rather than what failed inside the platform, and they are
authored here rather than lifted from the propagated error's own text.

`DEPENDENCY_SKIP_REASON` is D-023 point 4's sentence: a step the cycle chose not
to start because the work it consumes never arrived. It travels into synthesis,
so the summary an owner reads can say a post was not written because the
research came back empty — rather than omitting the step and reading as if
nothing was ever planned."""


@workflow.defn(name="BusinessManager")
class BusinessManagerWorkflow:
    """Tactical execution for exactly one business (spec §2.1)."""

    def __init__(self) -> None:
        self._state: ManagerState | None = None
        self._wake_reasons: list[str] = []
        self._last_cycle: CycleResult | None = None

    # ── signals and queries ────────────────────────────────────────────────

    @workflow.signal(name="wake")
    def wake(self, reason: str) -> None:
        """Request a wake cycle (spec §2.1 event-based wake conditions).

        Signals queue rather than interrupt. Duplicate delivery of the same event
        is deduplicated upstream by the event bus (A-002); this only records that
        *a* reason arrived, so two distinct triggers arriving together produce one
        cycle that knows about both rather than two competing cycles.
        """
        self._wake_reasons.append(reason)

    @workflow.signal(name="approval_decided")
    def approval_decided(self, approval_id: str) -> None:
        """Resume after an operator answered (D-006).

        The previous cycle ended when the request was raised. This starts a new
        one, which reloads context rather than resuming a parked frame.
        """
        self._wake_reasons.append(f"{APPROVAL_REASON_PREFIX}{approval_id}")

    @workflow.query(name="state")
    def current_state(self) -> ManagerState | None:
        """Return durable state, for the dashboard and for tests."""
        return self._state

    @workflow.query(name="last_cycle")
    def last_cycle(self) -> CycleResult | None:
        """Return the most recent cycle's outcome."""
        return self._last_cycle

    # ── main ───────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, state: ManagerState) -> ManagerState:
        """Wake, act, suspend — until it is time to continue as new.

        Args:
            state: Durable state, carried across continuations (D-005).

        Returns:
            Final state, when the workflow is cancelled rather than continued.
        """
        self._state = state

        while True:
            context = await workflow.execute_activity(
                "load_cycle_context",
                state.business_id,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
            ctx = CycleContext.model_validate(context)

            if not ctx.dispatchable:
                # Paused, retiring, or retired (D-008 I-4). Wait to be woken
                # rather than polling: a paused company must cost nothing.
                await workflow.wait_condition(lambda: bool(self._wake_reasons))
                self._wake_reasons.clear()
                continue

            fired = await self._await_wake(ctx)
            reasons = list(self._wake_reasons)
            self._wake_reasons.clear()
            if not fired and not reasons:
                continue

            state = await self._run_cycle(state, ctx, reasons)
            self._state = state

            if state.cycles_completed >= CYCLES_BEFORE_CONTINUATION:
                workflow.continue_as_new(state)

    async def _await_wake(self, ctx: CycleContext) -> bool:
        """Suspend until a scheduled interval elapses or a signal arrives.

        Returns:
            True if the schedule fired, False if a signal arrived first.
        """
        if ctx.schedule_interval_seconds is None:
            await workflow.wait_condition(lambda: bool(self._wake_reasons))
            return False

        timer = timedelta(seconds=ctx.schedule_interval_seconds)
        try:
            await workflow.wait_condition(lambda: bool(self._wake_reasons), timeout=timer)
        except TimeoutError:
            return True
        return False

    # ── one wake cycle ─────────────────────────────────────────────────────

    async def _run_cycle(
        self, state: ManagerState, ctx: CycleContext, reasons: list[str]
    ) -> ManagerState:
        """Plan, dispatch, synthesize, decide — once (spec §2.1).

        Every activity call in the cycle body is wrapped, because §9 requires a
        Manager that gets stuck to *surface* rather than vanish. Before this, an
        activity that exhausted its retries failed the whole workflow: the
        business was left without a Manager at all, and `CycleOutcome.FAILED` was
        unreachable (M6-F9). Now the failure ends this cycle, is written to the
        Decision Log in language the operator can read, and the workflow returns
        to its wake loop for the next round.

        This changes nothing about retry policy. The activities keep their own
        bounded retries; this is only what happens once those are spent.

        `load_cycle_context` is deliberately *not* covered: it runs before the
        cycle exists, so there is no cycle to record, and surviving it needs a
        policy for a Manager that cannot read its own context. That is M6-F13,
        open — do not paper over it here.
        """
        day = ctx.day_ordinal

        # The effect the operator authorised runs *first*, before this cycle
        # plans anything. D-006 ends the requesting cycle at the request, so the
        # answer arrives as a wake reason on a later cycle and there is no
        # parked frame to resume — without this the approval was recorded, the
        # Manager woke, and the thing the human agreed to never happened
        # (M6-F31). It runs ahead of planning because the plan should be made by
        # a Manager whose approved work is already done — and ahead of the daily
        # wake allowance below, because that allowance bounds how often a
        # business *reasons*, and refusing to carry out a decision a human has
        # already made is not a rate limit, it is a lost authorisation.
        try:
            for approval_id in _approvals_decided(reasons):
                await workflow.execute_activity(
                    "execute_approved_action",
                    {"approval_id": approval_id},
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=STANDARD_RETRY,
                )
        except ActivityError as error:
            # Retries are safe (the effect is idempotent under A-001) but not
            # unlimited; once they are spent the cycle ends visibly rather than
            # continuing as though the action had run.
            return await self._end_in_failure(state, ctx, "", error)

        if state.wake_budget_exhausted(ctx.max_cycles_per_day, day_ordinal=day):
            # §2.1's cost ceiling bounds one cycle; this bounds their frequency.
            # Without it a Manager woken by its own capability results can
            # oscillate indefinitely while every individual cycle stays in budget.
            self._last_cycle = CycleResult(
                outcome=CycleOutcome.NOTHING_TO_DO,
                summary="Already did its rounds for today.",
            )
            await workflow.wait_condition(lambda: bool(self._wake_reasons))
            return state

        # Planning is where the cycle begins (D-021), so a failure here has no
        # cycle id to file itself under — the id does not exist until the
        # activity that mints it returns.
        try:
            plan_payload = await workflow.execute_activity(
                "plan_cycle",
                PlanRequest(
                    business_id=state.business_id,
                    wake_reasons=tuple(reasons),
                    current_plan=state.plan,
                    kpi_targets=state.kpi_targets,
                    pending_approval_id=state.pending_approval_id,
                ),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
        except ActivityError as error:
            return await self._end_in_failure(state, ctx, "", error)

        # `.get`, not `[...]`: a history captured before D-021 has no cycle id in
        # this payload, and replaying it must not raise (spec §11).
        cycle_id = str(plan_payload.get("cycle_id") or "")
        plan = TacticalPlan.model_validate(plan_payload["plan"]).bounded()
        requests = tuple(ScopedRequest.model_validate(r) for r in plan_payload["requests"])
        # `.get`, again for spec §11: every history captured before D-023 has no
        # dispatch sequence, and an empty one means "one wave, everything in it"
        # — the behaviour those histories recorded.
        sequence = DispatchSequence.model_validate(plan_payload.get("dispatch") or {})
        state = state.model_copy(update={"plan": plan, "pending_approval_id": None})

        try:
            return await self._execute_cycle(state, ctx, cycle_id, plan, requests, sequence)
        except ActivityError as error:
            return await self._end_in_failure(state, ctx, cycle_id, error)

    async def _execute_cycle(
        self,
        state: ManagerState,
        ctx: CycleContext,
        cycle_id: str,
        plan: TacticalPlan,
        requests: tuple[ScopedRequest, ...],
        sequence: DispatchSequence,
    ) -> ManagerState:
        """Dispatch the plan, synthesize what came back, and record it (§2.1)."""
        day = ctx.day_ordinal

        if not requests:
            self._last_cycle = CycleResult(
                outcome=CycleOutcome.NOTHING_TO_DO,
                summary=plan.rationale or "Nothing needed doing.",
            )
            await self._record(state, self._last_cycle, cycle_id=cycle_id)
            return state.with_cycle_recorded(day_ordinal=day)

        results, skipped, failure = await self._dispatch_in_waves(
            state, cycle_id, requests, sequence
        )
        spend = sum((r.usage.cost_usd for r in results), Decimal("0"))

        if failure is not None:
            if not isinstance(failure, ActivityError):
                # Cancellation and anything else unexpected keep travelling: this
                # handler exists for exhausted activities, not to swallow the
                # signal that this workflow is being shut down.
                raise failure
            return await self._end_in_failure(
                state,
                ctx,
                cycle_id,
                failure,
                dispatched=requests,
                results=results,
                skipped=skipped,
            )

        # §2.1 requires waiting for and synthesizing *all* results before
        # deciding. D-001 makes that terminating: a dead-lettered invocation
        # returns a DEAD_LETTERED result rather than never returning, so
        # "all results" is reachable even when work failed.
        synthesis = await workflow.execute_activity(
            "synthesize_results",
            SynthesisRequest(
                business_id=state.business_id,
                plan=plan,
                results=results,
                cycle_id=cycle_id or None,
                skipped=skipped,
            ),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=STANDARD_RETRY,
        )

        action = (
            ProposedAction.model_validate(synthesis["action"]) if synthesis.get("action") else None
        )
        summary = synthesis.get("summary", "Finished a round of work.")

        if action is not None and action.needs_approval:
            approval_id = await workflow.execute_activity(
                "request_approval",
                action,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
            # D-006: the cycle ends here. It does not park for up to seven days
            # waiting for an answer — that would spread one cost ceiling across a
            # week and turn "stuck Manager" detection into a week-long timer.
            state = state.model_copy(update={"pending_approval_id": approval_id})
            self._last_cycle = CycleResult(
                outcome=CycleOutcome.AWAITING_APPROVAL,
                dispatched=requests,
                results=results,
                skipped=skipped,
                spend_usd=spend,
                summary=summary,
            )
            await self._record(state, self._last_cycle, cycle_id=cycle_id)
            return state.with_cycle_recorded(day_ordinal=day)

        self._last_cycle = CycleResult(
            outcome=CycleOutcome.COMPLETED,
            dispatched=requests,
            results=results,
            skipped=skipped,
            spend_usd=spend,
            summary=summary,
        )
        await self._record(state, self._last_cycle, cycle_id=cycle_id)
        return state.with_cycle_recorded(day_ordinal=day)

    async def _end_in_failure(
        self,
        state: ManagerState,
        ctx: CycleContext,
        cycle_id: str,
        error: ActivityError,
        *,
        dispatched: tuple[ScopedRequest, ...] = (),
        results: tuple[CapabilityResult, ...] = (),
        skipped: tuple[SkippedDispatch, ...] = (),
    ) -> ManagerState:
        """End a cycle whose activities ran out of retries (spec §9, M6-F9).

        The cycle is *recorded*, not lost: a business whose Manager vanished into
        a failed workflow has no way to tell its operator anything, which is the
        indefinite pending state §9 forbids. Counting it also matters — a Manager
        failing every cycle must still consume its daily wake allowance rather
        than looping on a fault for free.

        `BUDGET_EXHAUSTED` rather than `FAILED` when a ceiling refused the work:
        D-003 refuses a reservation *before* the spend, so the cycle did not
        break, it stopped. Those are different sentences for the operator.
        """
        refused = _refused_by_a_ceiling(error)
        outcome = CycleOutcome.BUDGET_EXHAUSTED if refused else CycleOutcome.FAILED
        template = CEILING_STOP_SUMMARY if refused else CYCLE_FAILED_SUMMARY
        rationale = CEILING_STOP_RATIONALE if refused else CYCLE_FAILED_RATIONALE

        self._last_cycle = CycleResult(
            outcome=outcome,
            dispatched=dispatched,
            results=results,
            skipped=skipped,
            spend_usd=sum((r.usage.cost_usd for r in results), Decimal("0")),
            summary=template.format(name=ctx.display_name),
        )
        # The log entry is how this surfaces, but it is not worth the business:
        # if even the write is exhausted, the Manager still returns to its wake
        # loop instead of dying alongside it. The activity's own failure remains
        # visible in the platform's records either way.
        with suppress(ActivityError):
            await self._record(state, self._last_cycle, cycle_id=cycle_id, rationale=rationale)
        return state.with_cycle_recorded(day_ordinal=ctx.day_ordinal)

    async def _dispatch_in_waves(
        self,
        state: ManagerState,
        cycle_id: str,
        requests: tuple[ScopedRequest, ...],
        sequence: DispatchSequence,
    ) -> tuple[tuple[CapabilityResult, ...], tuple[SkippedDispatch, ...], BaseException | None]:
        """Dispatch a cycle's requests in dependency order (D-023 point 2).

        One wave at a time, everything inside a wave in parallel. A cycle whose
        plan declared no dependencies has exactly one wave holding every
        request, so it issues the same single batch of commands it issued before
        D-023 existed — which is what keeps captured histories replayable
        (spec §11) and why the empty sequence is not a special case here but the
        ordinary one.

        Waves are walked, not computed: `plan_cycle` validated the graph and
        laid it out, because the declarations come from a model and checking
        them is platform work (D-013).

        Two rules make this terminate inside the cycle, as D-001 requires:
        a dependent whose grant did not succeed is *not* dispatched — it is
        recorded as skipped, and the skip carries forward because nothing
        downstream of it can succeed either — and the first failure stops the
        walk rather than starting a wave whose inputs are unknown.

        Returns:
            Results in dispatch order, dispatches skipped for want of a
            dependency, and the first failure if one occurred.
        """
        by_id: dict[str, ScopedRequest] = {r.invocation_id: r for r in requests}
        waves = sequence.waves or (tuple(r.invocation_id for r in requests),)

        results: list[CapabilityResult] = []
        skipped: list[SkippedDispatch] = []
        landed: set[str] = set()

        for wave in waves:
            ready: list[ScopedRequest] = []
            for invocation_id in wave:
                request = by_id.get(invocation_id)
                if request is None:
                    continue  # a sequence naming an id no request carries
                blocked = tuple(
                    grant.ref
                    for grant in sequence.grants.get(invocation_id, ())
                    if grant.invocation_id not in landed
                )
                if blocked:
                    skipped.append(
                        SkippedDispatch(
                            invocation_id=invocation_id,
                            capability=request.capability.value,
                            ref=sequence.refs.get(invocation_id, ""),
                            blocked_by=blocked,
                            reason=DEPENDENCY_SKIP_REASON,
                        )
                    )
                    continue
                ready.append(request)

            if not ready:
                continue

            if any(sequence.grants.get(r.invocation_id) for r in ready):
                # Composing the granted context is activity work: which results,
                # how much of each, and the record that the grant happened.
                prepared = await workflow.execute_activity(
                    "prepare_dependent_requests",
                    DependentContextRequest(
                        business_id=state.business_id,
                        cycle_id=cycle_id or None,
                        requests=tuple(ready),
                        grants={
                            r.invocation_id: sequence.grants[r.invocation_id]
                            for r in ready
                            if r.invocation_id in sequence.grants
                        },
                        prior_results=tuple(results),
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=STANDARD_RETRY,
                )
                ready = [ScopedRequest.model_validate(r) for r in prepared["requests"]]

            wave_results, failure = await self._dispatch_all(tuple(ready))
            results.extend(wave_results)
            if failure is not None:
                return tuple(results), tuple(skipped), failure
            landed.update(r.invocation_id for r in wave_results if r.succeeded)

        return tuple(results), tuple(skipped), None

    async def _dispatch_all(
        self, requests: tuple[ScopedRequest, ...]
    ) -> tuple[tuple[CapabilityResult, ...], BaseException | None]:
        """Dispatch one wave in parallel and wait for all of it (§2.1).

        Parallel because §2.1 permits it and serial dispatch would make a cycle's
        latency the sum of its parts. D-023 sequences *between* waves and changes
        nothing here: a plan with no declared dependencies is one wave, so this
        still sees the whole cycle at once. Safe because every invocation terminates
        with a result (D-001) — under a silent dead-letter sink this gather would
        hang forever on the first exhausted retry.

        Returns:
            The results that came back, and the first failure if any dispatch
            raised instead of returning. `return_exceptions=True` is what makes
            "wait for *all* results" true even then: the default abandons the
            surviving dispatches mid-flight the moment one fails, and the cycle
            would record its outcome while work it started was still running.
        """
        handles = [
            workflow.execute_activity(
                "dispatch_capability",
                request,
                start_to_close_timeout=DISPATCH_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            for request in requests
        ]
        # maximum_attempts=1: the pool already owns bounded retry and
        # dead-lettering (spec §9). Retrying at this layer too would multiply
        # attempts and spend the budget several times over for one invocation.
        settled = await asyncio.gather(*handles, return_exceptions=True)

        results: list[CapabilityResult] = []
        failure: BaseException | None = None
        for item in settled:
            if isinstance(item, BaseException):
                failure = failure or item
                continue
            results.append(CapabilityResult.model_validate(item))
        return tuple(results), failure

    async def _record(
        self,
        state: ManagerState,
        cycle: CycleResult,
        *,
        cycle_id: str,
        rationale: str | None = None,
    ) -> None:
        """Write this cycle's Decision Log entry (spec §2.1, §11.5).

        Written at the time the decision is made, not batched at cycle end, so a
        cycle that fails afterwards still leaves an explained action.

        Args:
            state: Current durable state, for the business id and standing plan.
            cycle: The cycle being recorded.
            cycle_id: Groups this entry with the ledger rows and results of the
                same cycle (D-021). Empty only when planning itself failed.
            rationale: Overrides the plan's own rationale, for a cycle that ended
                for a reason the plan does not explain.
        """
        await workflow.execute_activity(
            "record_cycle_decision",
            {
                "business_id": state.business_id,
                "cycle_id": cycle_id,
                "summary": cycle.summary,
                "rationale": rationale or state.plan.rationale or cycle.summary,
                "outcome": cycle.outcome.value,
                "spend_usd": str(cycle.spend_usd),
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=STANDARD_RETRY,
        )


APPROVAL_REASON_PREFIX = "approval:"
"""How an answered approval names itself in a wake reason (see
`approval_decided`). The scheduler signals the approval id; the signal handler
turns it into a reason so one cycle can carry several of them."""


def _approvals_decided(reasons: list[str]) -> list[str]:
    """Return the approval ids this cycle was woken by, in order, deduplicated.

    Deduplicated because A-002 guarantees at-least-once delivery *per consumer*,
    and a duplicate that slipped past it must not turn into a second attempt at
    the effect. The A-001 key would collapse the second attempt into a replay
    anyway; this stops it before it costs a round trip.
    """
    seen: list[str] = []
    for reason in reasons:
        if not reason.startswith(APPROVAL_REASON_PREFIX):
            continue
        approval_id = reason[len(APPROVAL_REASON_PREFIX) :]
        if approval_id and approval_id not in seen:
            seen.append(approval_id)
    return seen


def _refused_by_a_ceiling(error: ActivityError) -> bool:
    """Return whether an activity failed because a budget ceiling refused it.

    Read off the serialised failure rather than the exception type, because by
    the time a workflow sees an activity failure the original exception is gone
    (D-004: the activity ran on the other side of the boundary). Temporal records
    the class name, which is what `type` holds here.
    """
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type in CEILING_REFUSAL_TYPES
