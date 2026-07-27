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
        CycleKpiRequest,
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

DEGRADED_RETRY_INTERVAL = timedelta(minutes=15)
"""How long a Manager that cannot read its own context waits before looking
again (D-034.1, closing M6-F13 and M8-F44).

D-034.1 says such a Manager "never dies and never loops hot", and those are two
different requirements answered by two different things. Not dying is the
`ActivityError` handler in `_load_context`. Not looping hot is this bound: a
platform outage otherwise turns a parked Manager into a retry storm that costs
nothing per attempt and never stops.

Fifteen minutes, because the shortest schedule the platform supports is hourly
(`_interval_seconds`): a degraded Manager therefore re-checks four times inside
its own fastest wake period, so it recovers within a quarter of a cycle of the
platform recovering, and a business whose context has been unreadable for a day
has cost 96 bounded activity attempts and no model call.

A wake signal cuts the wait short — see `_park`. Waiting only on a signal was
rejected: a schedule-only business (Finance, M7-F2) subscribes to no events, so
a signal-only park is indistinguishable from death for exactly the businesses
most likely to be parked."""

STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_attempts=3,
)
"""Bounded retry (spec §9). Manager activities are subject to the same
retry/timeout discipline as any other workflow, so a stuck Manager surfaces
rather than holding its business in an indefinite pending state."""

PATCH_POST_WAKE_CONTEXT = "post-wake-cycle-context"
"""Versioning id for the change that moved the cycle's context load after the
wake (M7-F45, scoped to the whole snapshot by audit F-B).

**Changes to a live workflow path are versioned, never shipped bare (M6-F33).**
A Manager parked on its wake timer is a *running history*: deploy a worker whose
cycle body issues one more command than that history recorded and the parked
business fails on recovery, which is the one failure mode D-004 exists to
prevent. M6-3 shipped such a change by terminating and restarting the Manager —
tolerable against a development database, unacceptable for a business with work
in flight, and recorded as unacceptable ever since.

`workflow.patched` is the SDK's own answer and is what this project uses. An
execution that was already running when this shipped carries no marker for this
id, so it replays the single-load path it actually ran; every execution started
since takes the new one. Nothing about the old path is emulated — it is simply
still there, which is why both committed fixtures replay unedited.

Conventions, enforced by `tests/test_workflow_versioning.py` so a slip fails a
gate rather than silently splitting one cohort of histories in two:
one module constant per patch, named `PATCH_*`, its value dash-separated and
descriptive of the change rather than of the milestone; never a bare literal at
the call site; each id used by exactly one `workflow.patched` call.
"""

PATCH_PAUSED_WAKE_NOTICE = "paused-dropped-wake-notice"
"""Versioning id for D-035: a wake reason a pause drops is surfaced, not lost.

The branch this guards is one a *running* execution sits on. A paused company's
Manager is parked in the non-dispatchable wait below, and a paused company is
the ordinary state of a business whose operator has stopped it — so this is
precisely the "history in flight" case D-033 was written for, and the one
`PATCH_POST_WAKE_CONTEXT`'s own record calls out. Without the gate, a Manager
parked on a pause when this shipped would issue a `record_dropped_wake` its
history never recorded, and fail on recovery.

Neither committed fixture can demonstrate that, because neither ever read a
non-dispatchable context — asserted, per fixture, in
`tests/test_workflow_versioning.py` rather than assumed, since "the fixtures
still replay" is a weaker claim when the branch was unreachable in them anyway.
The gate's own evidence is therefore the scripted pair in that file: the same
loop driven with the version decision open and closed, showing the command
appears only on the new path and that the old path is still the silent drop
D-035 describes as today's behaviour.
"""

PATCH_NOTHING_TO_DO_KPIS = "nothing-to-do-cycle-kpis"
"""Versioning id for M7-F32 (the D-027 amendment pass, M8-5): a NOTHING_TO_DO
cycle measures itself too, for a type whose mappings include an
observation-scoped source.

Before this, `record_cycle_kpis` was scheduled only on the branch that
dispatched something, so a cycle that planned and found nothing to do left
`data_freshness_hours` and `metrics_tracked` unread even though both are
facts the platform can state independent of this cycle's own results
(`KpiSource.scope`, `jarvis.domain.kpi`) — freshness in particular stops being
re-observed exactly when a company goes idle, which is when staleness starts
to matter. The branch this guards is one a *running* execution reaches every
time planning decides there is nothing to dispatch, so the new command ships
behind this id rather than bare, for the same reason `PATCH_POST_WAKE_CONTEXT`
does: a Manager parked on its wake timer when this shipped is a running
history, and one more command on a path it can still take fails it on
recovery.

Neither committed fixture ever takes the NOTHING_TO_DO branch at all — both
dispatch every cycle they recorded — so, like `PATCH_PAUSED_WAKE_NOTICE`, this
patch has no fixture to diverge on and is proven by the scripted pair in
`tests/test_workflow_versioning.py` instead: the same wake loop driven with
the version decision open and closed, over a script whose plan proposes
nothing to dispatch.
"""

CEILING_REFUSAL_TYPES = frozenset({"BudgetExceededError", "CircuitBreakerOpenError"})
"""Failure types that mean *a ceiling refused the work*, not that the work failed
(D-003). Matched by name because a workflow sees a serialised failure, never the
original exception object — the alternative, importing the error classes into
workflow code, would put a live type from the I/O side of D-004 in here.

`CircuitBreakerOpenError` is included because it subclasses `BudgetExceededError`
in the kernel taxonomy: from the cycle's point of view both mean the same thing,
that spending stopped it rather than a fault."""

CYCLE_KEY_PREFIX = "cyc_"
"""Shared with the id-minting helper in `jarvis/kernel/ids.py`, so a derived key
and a minted one are the same kind of thing to everything downstream (D-034.2).
Spelled out here rather than imported, because the determinism gate reads this
module's source for the minting helpers by name and a bare import would look
exactly like a workflow that mints.

They stay distinguishable by shape — a derived key carries its cycle ordinal
after the run's hex, a minted one does not — which is what lets a ledger row or
a Decision Log entry say, at a glance and years later, whether the cycle it
belongs to was scoped deterministically or by a `plan_cycle` that minted a fresh
id on every attempt (M6-F17, observed live as M7-F25)."""


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

        The loop reads its context twice per round, and the two reads answer
        different questions. The first answers *whether and how long to wait*:
        whether this business accepts dispatch at all (D-008 I-4) and what its
        schedule interval is. The second, taken once the wake has fired, is the
        snapshot the cycle itself reasons on.

        Until M8-3 there was one read, before the wait, so a woken cycle ran on
        a context up to a full wake period old (M7-F45; audit F-B scoped it to
        the whole snapshot rather than to `measures_kpis` alone). Two observed
        consequences: a business whose type gained KPI mappings measured nothing
        on its first cycle after the upgrade and only started on its second, and
        `day_ordinal` — which is the *whole* of the wake-rate accounting's idea
        of today — could be yesterday's by the time the cycle it bounds began.
        D-021 already fixes the start of a cycle at the start of planning; a
        context loaded before the wait belongs to no cycle at all.

        The second read is behind `PATCH_POST_WAKE_CONTEXT` (M6-F33), so a
        Manager that was already parked when this shipped replays the one-read
        path it ran, and every execution started since runs this one.

        **Either read can fail, and neither failure is fatal (D-034.1).** Both
        happen before planning, so there is no cycle to file the failure under
        (D-021) — which is why M6-F13 sat open for two milestones and why M8-3
        widened it by putting a second unguarded read on the path (M8-F44).
        D-034.1 settles it: the Manager records the park, waits out
        `DEGRADED_RETRY_INTERVAL` or a wake signal, and looks again. `degraded`
        is a loop local, not durable state — it exists only to keep one outage
        from writing an activity-feed entry every quarter hour, and a
        `continue_as_new` cannot happen inside a park because a park never
        completes a cycle.

        **A pause drops what woke it, and says so (D-035).** "Paused by you"
        means nothing happens, so the reasons are dropped rather than queued
        for automatic execution at resume — an operator who paused a company
        precisely to stop it must not be surprised by a burst of work when they
        start it again. Dropping them silently is the other half of the same
        mistake, and it is what this loop did until now: an answer the operator
        had already given simply vanished. So each dropped reason is reported
        (`_report_dropped_wakes`) before the queue is cleared. Two places do the
        dropping — the pause the loop starts on, and a pause that lands while it
        waits — and both report.

        **The ordinal resets at the continuation (M8-F87).** `cycles_completed`
        counts what this execution's history holds, so the generation that
        starts with an empty history starts at zero. Carrying the count over
        made `CYCLES_BEFORE_CONTINUATION` bind exactly once per Manager.

        Args:
            state: Durable state, carried across continuations (D-005).

        Returns:
            Final state, when the workflow is cancelled rather than continued.
        """
        self._state = state
        degraded = False

        while True:
            wake_ctx = await self._load_context(state.business_id)
            if wake_ctx is None:
                degraded = await self._park(state.business_id, recorded=degraded)
                continue
            degraded = False

            if not wake_ctx.dispatchable:
                # Paused, retiring, or retired (D-008 I-4). Wait to be woken
                # rather than polling: a paused company must cost nothing.
                await workflow.wait_condition(lambda: bool(self._wake_reasons))
                # Taken and cleared without an await between them, so a signal
                # arriving while the reports are being written stays queued for
                # the next turn round this loop rather than being cleared
                # unreported — which is the same silent drop one layer in.
                dropped = list(self._wake_reasons)
                self._wake_reasons.clear()
                await self._report_dropped_wakes(state.business_id, dropped)
                continue

            fired = await self._await_wake(wake_ctx)
            reasons = list(self._wake_reasons)
            self._wake_reasons.clear()
            if not fired and not reasons:
                continue

            ctx = wake_ctx
            if _reloads_context_after_wake():
                reloaded = await self._load_context(state.business_id)
                if reloaded is None:
                    # The same answer as a failed wake read, deliberately: both
                    # are "this Manager cannot see the company it runs", and a
                    # cycle planned on the pre-wait snapshot instead would be
                    # M7-F45 reintroduced as a failure-path shortcut.
                    degraded = await self._park(state.business_id, recorded=degraded)
                    continue
                ctx = reloaded
                if not ctx.dispatchable:
                    # Stopped while it waited. Back to the top, which parks on a
                    # signal instead of planning work for a business that has
                    # been paused — the same answer D-008 I-4 gives above, now
                    # also available for a pause that lands mid-wait. This is
                    # not the authorization boundary: the activities re-derive
                    # and re-check lifecycle themselves (M6-F1's fix, and audit
                    # F-B confirms the stale read was never a hole). It is the
                    # planning call it saves.
                    #
                    # The reasons that woke it are already out of the queue, so
                    # this is the *second* place a pause drops one and it drops
                    # them just as silently — D-035 applies here for the same
                    # reason it applies above, and the same gate covers both.
                    await self._report_dropped_wakes(state.business_id, reasons)
                    continue

            state = await self._run_cycle(
                state, ctx, reasons, cycle_key=_cycle_key(state.cycles_completed)
            )
            self._state = state

            if state.cycles_completed >= CYCLES_BEFORE_CONTINUATION:
                # `continued()`, not `state`: the ordinal counts what *this*
                # history holds, and the next generation starts with an empty
                # one. Handing the count over intact made the threshold bind
                # once in a Manager's life — from cycle 100 on, every single
                # cycle continued as new (M8-F87).
                workflow.continue_as_new(state.continued())

    async def _load_context(self, business_id: str) -> CycleContext | None:
        """Read this business's current snapshot, or None if it cannot be read.

        One call site for both reads, so the wake's context and the cycle's are
        the same question asked at two moments rather than two payloads that
        could drift apart. Everything in it is I/O or a clock read, which is why
        it is an activity with a recorded result and not a lookup here (D-004).

        Returns:
            The snapshot, or None once the activity's bounded retries are spent
            (D-034.1). None rather than a raise, because the caller's answer is
            a park and a park is not an error condition to be handled somewhere
            further out — there is nowhere further out. This is the only
            `execute_activity` in the file whose failure is not a *cycle*
            failure, because it is the only one that runs before a cycle exists.
        """
        try:
            payload = await workflow.execute_activity(
                "load_cycle_context",
                business_id,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
        except ActivityError:
            return None
        return CycleContext.model_validate(payload)

    async def _park(self, business_id: str, *, recorded: bool) -> bool:
        """Record a degraded Manager and wait before looking again (D-034.1).

        Three things, in the order D-034.1 lists them. The park is *recorded*,
        so an owner asking why nothing happened reads a sentence rather than
        silence — best-effort, because a platform that cannot answer
        `load_cycle_context` may well not be able to write the entry either, and
        failing to explain a park must not escalate into failing the Manager
        (the M6-F9 posture, one layer earlier). It is recorded once per episode:
        `recorded` stays False until the entry actually lands, so a write that
        failed is retried on the next attempt rather than lost, and a write that
        succeeded is not repeated every quarter hour into the activity feed.
        Then it waits — bounded, and cut short by a wake signal, so an operator
        resuming a company does not wait out the remainder of a timer.

        **A *new* signal, not any pending one.** Waiting on `self._wake_reasons`
        being non-empty looks equivalent and is not: a reason that arrived during
        the previous park is still queued, so the condition is already true when
        the next park begins and the wait returns instantly. One signal to an
        unreadable Manager would then spin the loop at the speed of a failing
        activity — the hot loop D-034.1 forbids, reached by the ordinary path of
        being woken while degraded. Comparing against the count taken here gives
        each new signal exactly one extra look, and — unlike clearing the queue —
        loses no reason: an answered approval that arrives while the Manager is
        parked is still in the list when it recovers, and D-024's effect still
        runs (M6-F31).

        Args:
            business_id: Whose Manager is parked.
            recorded: Whether this episode's entry has already been written.

        Returns:
            Whether the episode is now recorded.
        """
        if not recorded:
            recorded = await self._record_park(business_id)
        already = len(self._wake_reasons)
        with suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: len(self._wake_reasons) > already, timeout=DEGRADED_RETRY_INTERVAL
            )
        return recorded

    async def _record_park(self, business_id: str) -> bool:
        """Ask the platform to explain this park to the operator (D-034.1).

        One activity for both records — the Decision Log entry and the
        notification — because they describe one event and because the sentence
        needs the company's display name, which is precisely the fact the failed
        read could not deliver. Composing it there rather than here is the same
        trade the rest of this file makes for `record_cycle_decision`: the
        workflow decides *that* something is recorded, the activity knows what
        the company is called.

        Returns:
            True if the record landed, False if its own retries were spent.
        """
        try:
            await workflow.execute_activity(
                "record_manager_park",
                {"business_id": business_id},
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
        except ActivityError:
            return False
        return True

    async def _report_dropped_wakes(self, business_id: str, reasons: list[str]) -> None:
        """Surface the wake reasons a pause is about to drop (D-035).

        D-035 settles M8-F45 conservatively: a paused company's wake reasons are
        dropped, not queued — preserve-and-execute-at-resume was rejected
        because it surprises the operator who paused precisely to stop things —
        but a dropped reason that something or someone was waiting on generates
        an operator notification and an audit record instead of vanishing. The
        durable state behind it is untouched either way: the approval row still
        holds the operator's answer, the results and measurements are still in
        their tables, so resume plus the next wake acts on all of it (D-006
        reload). What was being lost was not the fact, it was the *knowing*.

        Every reason is reported, not only the approval ones. The signal a
        Manager can receive is either an answered approval or a bus event this
        company subscribed to — a piece of its work finishing, a tracked number
        crossing a bound — and each of those means the company would have acted
        had it not been stopped. The reason kind travels into the activity so
        the notice can say which it was; composing that sentence is the
        activity's job, because it needs the company's display name (§12.5, and
        the same division `_record_park` makes).

        Best-effort, per reason. A notice that could not be written must not
        take down the Manager of a company that is only paused — the posture
        `_end_in_failure` and `_record_park` already take for records — and
        because the reasons are reported one at a time, a failure on the first
        does not silence the rest.

        Args:
            business_id: Whose Manager is dropping them.
            reasons: The wake reasons about to be discarded.
        """
        dropped = _dropped_wake_reasons(reasons)
        if not dropped or not _surfaces_dropped_wakes():
            return
        for kind, ref in dropped:
            with suppress(ActivityError):
                await workflow.execute_activity(
                    "record_dropped_wake",
                    {"business_id": business_id, "reason_kind": kind, "reason_ref": ref},
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=STANDARD_RETRY,
                )

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
        self,
        state: ManagerState,
        ctx: CycleContext,
        reasons: list[str],
        *,
        cycle_key: str = "",
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

        Neither read of `load_cycle_context` is covered here, and that is still
        deliberate: both happen before planning, which is where a cycle begins
        (D-021), so there is no cycle to record them against. What changed is
        that they are no longer *uncovered* — D-034.1 gives them the park in
        `run`, which closes M6-F13 and M8-F44 without pretending a failed
        context read is a failed cycle.

        Args:
            state: Durable state.
            ctx: This cycle's snapshot, taken after the wake.
            reasons: What woke it.
            cycle_key: This cycle's budget scope key, derived in `run` from the
                run id and the cycle ordinal (D-034.2). Empty for a caller with
                no run to derive from — a `_run_cycle`-level test, or any future
                caller that is not the wake loop — in which case `plan_cycle`
                mints as D-021 originally specified.
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
            return await self._end_in_failure(state, ctx, cycle_key, error)

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

        # M8-F7: the targets the planner works to come from this cycle's own
        # context when it has them, and from carried state only for a history
        # that predates the field. `is None` rather than a falsy check, because
        # an empty tuple is a live answer — a business with no targets set — and
        # falling back to carried state on it would make a future refresh unable
        # to express the removal of the last target. Nothing is written back:
        # the contract is the authority, and a second copy in workflow state is
        # what made the planner stale in the first place.
        kpi_targets = state.kpi_targets if ctx.kpi_targets is None else ctx.kpi_targets

        # Planning is where the cycle begins (D-021) — but the scope its spend
        # counts against no longer waits for planning to return. `cycle_key`
        # travels *into* the activity, so all three attempts of a retried
        # `plan_cycle` reserve against one cycle ceiling instead of one each
        # (M6-F17; observed live as M7-F25's three $0.16 reservations for one
        # logical cycle). Derivation, not minting: D-004 holds because the key
        # is a function of the run id and the cycle ordinal, both of which
        # replay identically.
        try:
            plan_payload = await workflow.execute_activity(
                "plan_cycle",
                PlanRequest(
                    business_id=state.business_id,
                    wake_reasons=tuple(reasons),
                    current_plan=state.plan,
                    kpi_targets=kpi_targets,
                    pending_approval_id=state.pending_approval_id,
                    cycle_key=cycle_key,
                ),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=STANDARD_RETRY,
            )
        except ActivityError as error:
            # D-021 note 3 recorded this as a cycle that fails "before it has an
            # id", filed under an empty one. It has one now — the key its
            # released reservations already carry — so the entry an operator
            # reads and the ledger rows behind it group together for the first
            # time. An empty key means no run to derive from, which is D-021's
            # original case and keeps its behaviour.
            return await self._end_in_failure(state, ctx, cycle_key, error)

        # `.get`, not `[...]`: a history captured before D-021 has no cycle id in
        # this payload, and replaying it must not raise (spec §11). Read from the
        # *recorded result* rather than from `cycle_key`, which is the D-023 /
        # D-027 compatibility hinge and not an oversight: a history captured
        # before D-034 carries a minted id, its ledger rows and audit entries are
        # filed under that id, and the platform's own answer for that history is
        # therefore still the old one (D-033). For an execution started since,
        # the recorded id *is* the derived key — `plan_cycle` returns what it
        # scoped against — so the two agree without the workflow choosing.
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
            # M7-F32: this cycle dispatched nothing, but an observation-scoped
            # mapping (freshness, the contract's own target count) reads a
            # fact that exists independent of that — `record_cycle_kpis`
            # itself is what tells a cycle-result-scoped one (reports
            # delivered) apart and leaves it unmeasured (`KpiSource.scope`).
            # Behind a patch because a Manager parked on its wake timer can
            # still take this branch (D-033) — no captured fixture ever does,
            # so this is proven in `tests/test_workflow_versioning.py` rather
            # than by replay.
            if ctx.measures_kpis and workflow.patched(PATCH_NOTHING_TO_DO_KPIS):
                await workflow.execute_activity(
                    "record_cycle_kpis",
                    CycleKpiRequest(business_id=state.business_id, cycle_id=cycle_id or None),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=STANDARD_RETRY,
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

        # D-027.1: the cycle measures itself, after synthesis and before the
        # decision record. An activity, because every number it writes comes
        # from a database read or a clock (D-004) — and a recorded result, so a
        # replayed cycle re-reads the figures it wrote rather than re-measuring
        # a company as it is today.
        #
        # Conditional because D-027.3 makes "no declared mappings" mean "records
        # nothing", and `measures_kpis` is how that answer reaches the workflow
        # without reading a type definition here. The condition is also what
        # keeps captured histories replayable (spec §11): a history from before
        # this field carries no measurement command and deserialises to False,
        # which is the same answer the platform gives that history's business
        # today — its type declares no mappings either.
        #
        # Not suppressed on failure, unlike the failure-path decision record: a
        # cycle whose measurement exhausted its retries is a cycle whose figures
        # nobody has, and M7-F21 is what silent non-measurement looks like after
        # a milestone. The `ActivityError` reaches `_run_cycle`, which ends the
        # cycle `FAILED` with an operator-language entry and returns the Manager
        # to its wake loop (M6-F9) rather than losing it.
        if ctx.measures_kpis:
            await workflow.execute_activity(
                "record_cycle_kpis",
                CycleKpiRequest(
                    business_id=state.business_id,
                    cycle_id=cycle_id or None,
                    results=results,
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


APPROVAL_REASON_KIND = "approval"
"""How an answered approval names its *kind* to the reporting activity (D-035).

Distinct from `APPROVAL_REASON_PREFIX`, which is the wire format of the reason
itself. The kind is what selects the operator sentence; the ref is the approval
id, which is what the notice links to."""


def _dropped_wake_reasons(reasons: list[str]) -> list[tuple[str, str]]:
    """Return the (kind, ref) pairs a pause is dropping, in order, deduplicated.

    Kind first because it is what the operator's sentence is chosen by: an
    answered approval reads differently from a piece of work that finished
    while the company was stopped, and D-035's notice is only useful if it says
    which happened. An approval reason carries its id as the ref, so the notice
    can point at the thing that is waiting; a bus-event reason is its own kind
    (`capability.result_returned` and the rest) and carries no ref, because the
    event is not a row an operator can open.

    Deduplicated on the pair, for the same reason `_approvals_decided` is: A-002
    guarantees at-least-once delivery per consumer, and one delivery slip must
    not become two notices. String work only — no clock, no id, no I/O — so it
    stays inside D-004.
    """
    seen: list[tuple[str, str]] = []
    for reason in reasons:
        if reason.startswith(APPROVAL_REASON_PREFIX):
            approval_id = reason[len(APPROVAL_REASON_PREFIX) :]
            if not approval_id:
                continue
            pair = (APPROVAL_REASON_KIND, approval_id)
        else:
            if not reason:
                continue
            pair = (reason, "")
        if pair not in seen:
            seen.append(pair)
    return seen


def _cycle_key(ordinal: int) -> str:
    """Return the budget scope key for the cycle about to begin (D-034.2).

    Derived, never minted — which is what keeps it inside D-004. `run_id` is
    assigned by the Temporal server and replays identically for the life of a
    run; `ordinal` is the Manager's own completed-cycle count, which advances
    exactly once per cycle that reaches planning and is therefore unique within
    a run. A `continue_as_new` changes the run id, so uniqueness survives it
    without the ordinal having to.

    This is the fix for the defect D-021's implementation left behind:
    `plan_cycle` minted the id, so each of an activity's three attempts opened a
    *fresh* cycle scope and a refusal caused by accumulated cycle spend passed on
    retry (M6-F17). M7-F25 is that defect in the live record — three
    RESERVED→RELEASED reservations across three `plan_cycle` attempts, one
    logical cycle, three ceilings' worth of headroom.

    Args:
        ordinal: Cycles this Manager has completed in this run so far.

    Returns:
        A key of the same shape as a minted cycle id, with the ordinal appended
        so the two remain distinguishable in the record (`CYCLE_KEY_PREFIX`).
    """
    return f"{CYCLE_KEY_PREFIX}{workflow.info().run_id.replace('-', '')}_{ordinal}"


def _reloads_context_after_wake() -> bool:
    """Return whether this execution reads its cycle context after the wake.

    False for any history captured before M8-3, which is what lets both
    committed fixtures replay unedited (spec §11) — see
    `PATCH_POST_WAKE_CONTEXT`. True for everything started since.

    A named function rather than an inline call so the decision has one place a
    negative control can force open: `tests/test_workflow_versioning.py` replays
    the real captured histories with this pinned True and requires the replayer
    to reject them. Without that, a gate that never opens and a gate that never
    closes look identical from a green suite (the D-025/D-027 negative-control
    discipline).
    """
    return workflow.patched(PATCH_POST_WAKE_CONTEXT)


def _surfaces_dropped_wakes() -> bool:
    """Return whether this execution reports the wake reasons a pause drops.

    False for any execution that was already running when D-035 shipped —
    including the one case that matters most here, a Manager parked on the
    non-dispatchable wait because its company is paused, which is a live history
    sitting on exactly the branch this changes. True for everything started
    since. See `PATCH_PAUSED_WAKE_NOTICE`.

    A named function rather than an inline call for two reasons. It is the shape
    `_reloads_context_after_wake` established, so a test can force the decision
    open and closed without touching a fixture — which is the only evidence
    available for this gate, since neither committed history ever reached the
    paused branch. And it keeps one `workflow.patched` call for one id while the
    two drop sites share the branch: they are one behavioural change in two
    places, not two cohorts of history, and giving each its own id would split
    one cohort in two for no reason anybody could reconstruct later.
    """
    return workflow.patched(PATCH_PAUSED_WAKE_NOTICE)


def _refused_by_a_ceiling(error: ActivityError) -> bool:
    """Return whether an activity failed because a budget ceiling refused it.

    Read off the serialised failure rather than the exception type, because by
    the time a workflow sees an activity failure the original exception is gone
    (D-004: the activity ran on the other side of the boundary). Temporal records
    the class name, which is what `type` holds here.
    """
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type in CEILING_REFUSAL_TYPES
