"""The Manager under failure: parking, and one cycle key across retries.

D-034 points 1 and 2; spec §2.1, §9, §11, §12.5; amends D-021.

Two findings that sat open for two milestones each, both of them about what
happens *around* a cycle rather than inside one.

**M6-F13 / M8-F44 — the Manager that cannot read itself.** `load_cycle_context`
runs before planning, so a failure past its retries had no cycle to be recorded
against (D-021) and no policy to survive under: it failed the whole workflow and
the business was left with no Manager at all — the indefinite pending state §9
forbids and precisely what M6-F9's fix already refused to allow *inside* a cycle.
M8-3 then put a second unguarded read on the path (M8-F44). D-034.1 settles it:
the Manager records the park, waits, and looks again.

**M6-F17 / M7-F25 — the cycle that was three cycles.** `plan_cycle` minted the
`cycle_id`, and Temporal retries an activity by re-running it: three attempts,
three cycle scopes, three ceilings' worth of headroom for one logical cycle. The
live ledger holds the evidence — three RESERVED→RELEASED rows across three
attempts of one cycle (M7-F25). D-034.2 derives the key in the workflow instead,
from facts that replay identically, and sends it *in*.

**M8-F87 — the continuation that continued every time.** `cycles_completed` was
handed to the next generation intact, so generation two met
`CYCLES_BEFORE_CONTINUATION` on its first cycle and every cycle after that: the
bound D-005 exists to enforce held for a Manager's first hundred cycles and for
nothing afterwards. Also around a cycle rather than inside one, which is why it
sits here.

**D-035 — what a pause drops.** A paused company's wake reasons are dropped
rather than queued, and the drop is now reported. The workflow half is in
`test_workflow_versioning.py`, because the change is version-gated; the records
it produces are here, beside the park's, for the same reason the park's are —
they need a company with a name.

**P0-D (design 4.4) — what an outage skips.** A scheduled round whose period
ended before the wake was served is skipped rather than replayed, and announced.
Same split for the same reason: the decision is a workflow one and version-gated,
the two records it produces need a contract to name the company.

All of it is proved the same way: the defect is kept as an executable test
beside its fix, because a fix whose defect nobody can still reproduce is a fix
nobody can check.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from temporalio.exceptions import ActivityError, ApplicationError

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import BudgetExceededError
from jarvis.kernel.ids import BusinessId
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager import workflow as workflow_module
from jarvis.manager.activities import (
    DROPPED_WAKE_COPY,
    DROPPED_WAKE_DEFAULT,
    DROPPED_WAKE_EVENT,
    LATE_WAKE_BODY,
    LATE_WAKE_EVENT,
    LATE_WAKE_TITLE,
    MANAGER_PARKED_SUMMARY,
    ManagerActivities,
)
from jarvis.manager.state import ManagerState, TacticalPlan
from jarvis.manager.types import CycleContext, PlanRequest
from jarvis.manager.workflow import (
    CYCLES_BEFORE_CONTINUATION,
    DEGRADED_RETRY_INTERVAL,
    BusinessManagerWorkflow,
    _cycle_key,
)
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.persistence.models import (
    AuditLogRow,
    Base,
    BudgetLedgerRow,
    DecisionLogRow,
    NotificationRow,
)
from tests.conftest import as_business

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")
RUN_ID = "1656651d-16c1-4ca6-91e6-9ee3411042ae"
RUN_HEX = RUN_ID.replace("-", "")
TODAY = 739_900


def _exhausted(activity: str) -> ActivityError:
    """Build the failure a workflow sees once an activity's retries are spent.

    The same shape `test_manager_cycle_outcomes` uses: an `ActivityError` whose
    cause is a serialised `ApplicationError`. The workflow never sees the
    original exception, which is why nothing in the park path inspects one.
    """
    failure = ActivityError(
        "activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type=activity,
        activity_id="1",
        retry_state=None,
    )
    failure.__cause__ = ApplicationError(
        "the detail an operator never sees", type="OperationalError"
    )
    return failure


def _ctx(**over: Any) -> CycleContext:
    fields: dict[str, Any] = {
        "business_id": BIZ,
        "display_name": "Summit Trail Gear",
        "dispatchable": True,
        "schedule_interval_seconds": 3600,
        "max_cycles_per_day": 48,
        "wake_cycle_ceiling_usd": Decimal("2.00"),
        "day_ordinal": TODAY,
    }
    return CycleContext(**(fields | over))


class _ScriptEndedError(Exception):
    """The scripted Manager reached a point the script has nothing to say about."""


class _ContinuedError(_ScriptEndedError):
    """The scripted Manager continued as new, which ends this execution."""


class _Loop:
    """Scripted activity boundary for the wake loop, including its failures.

    `loads` is consumed one per `load_cycle_context` and may hold either a
    context or an exception, so a test states what the platform answers at each
    read and the workflow decides what to do about it. Running out ends the run:
    the script has nothing left to say. Every wait is recorded with the timeout
    it asked for, which is how "never loops hot" is checked rather than assumed.
    """

    def __init__(
        self,
        loads: list[CycleContext | BaseException],
        *,
        park_failures: int = 0,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.waits: list[Any] = []
        self.predicates: list[Callable[[], bool]] = []
        self.manager: BusinessManagerWorkflow | None = None
        self.signal_on_wait: str | None = None
        """A wake reason delivered during the *first* wait, the way a scheduler
        signalling a parked Manager delivers one."""

        self.continued: list[ManagerState] = []
        """The states handed to the next generation at `continue_as_new`."""

        self._loads = list(loads)
        self._park_failures = park_failures

    async def execute_activity(self, name: str, arg: object = None, **kwargs: object) -> Any:
        assert "start_to_close_timeout" in kwargs, "spec §9: every call is bounded"
        self.calls.append((name, arg))
        if name == "load_cycle_context":
            if not self._loads:
                raise _ScriptEndedError("the script ran out of context reads")
            answer = self._loads.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer.model_dump(mode="json")
        if name == "record_manager_park":
            if self._park_failures > 0:
                self._park_failures -= 1
                raise _exhausted("record_manager_park")
            return {"decision_id": "dec_park", "notified": "true"}
        if name == "plan_cycle":
            return {
                "cycle_id": "cyc_scripted",
                "plan": {"items": [], "rationale": "Nothing needed doing."},
                "requests": [],
            }
        return "dec_scripted"

    async def wait_condition(
        self,
        predicate: Any,
        *,
        timeout: Any = None,  # noqa: ASYNC109 — this mirrors the API being stubbed
    ) -> None:
        self.waits.append(timeout)
        self.predicates.append(predicate)
        if predicate():
            # The real one returns at once when its condition already holds.
            return
        if self.signal_on_wait is not None and self.manager is not None:
            self.manager.wake(self.signal_on_wait)
            self.signal_on_wait = None
        if timeout is None:
            raise _ScriptEndedError("parked on a signal with no scheduled wake")
        raise TimeoutError  # the timer fired, which is what the caller reads

    def patched(self, patch_id: str) -> bool:
        return True

    def continue_as_new(self, state: ManagerState) -> None:
        """Record what the next generation starts from, and end this one.

        The real call raises rather than returning — the execution is over — so
        the stub does too. That is not a detail: a stub that returned would let
        the loop run on past a continuation it had already taken, and the count
        this file is about would keep climbing in a history that no longer
        exists.
        """
        self.continued.append(state)
        raise _ContinuedError("this generation ended at continue_as_new")

    def info(self) -> Any:
        return SimpleNamespace(run_id=RUN_ID)

    def scheduled(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payload(self, name: str) -> Any:
        return next(arg for called, arg in reversed(self.calls) if called == name)


async def _drive(
    loads: list[CycleContext | BaseException],
    *,
    park_failures: int = 0,
    signal_on_wait: str | None = None,
    signals: list[str] | None = None,
    state: ManagerState | None = None,
) -> tuple[_Loop, BusinessManagerWorkflow]:
    """Run the wake loop against a script until the script runs out.

    The run always ends on one read past the script — the loop asks for a
    context the script has no answer for — so a script of *n* reads produces
    *n + 1* `load_cycle_context` calls. Stated here because the counts below
    depend on it. A run that continues as new ends there instead.

    `signals` are queued before the run begins; `signal_on_wait` delivers one
    during the first wait. Two different moments, and the difference is the
    whole of what `_park`'s "a *new* signal" comparison is about.
    """
    loop = _Loop(loads, park_failures=park_failures)
    manager = BusinessManagerWorkflow()
    for reason in signals or []:
        manager.wake(reason)
    loop.manager = manager
    loop.signal_on_wait = signal_on_wait
    original = workflow_module.workflow
    workflow_module.workflow = loop  # type: ignore[assignment]
    try:
        with pytest.raises(_ScriptEndedError):
            await manager.run(state or ManagerState(business_id=BIZ))
    finally:
        workflow_module.workflow = original  # type: ignore[assignment]
    return loop, manager


# ── D-034.1: the Manager parks rather than dying ───────────────────────────


async def test_a_manager_that_cannot_read_its_context_parks_and_carries_on() -> None:
    """M6-F13's fix, stated as the behaviour it was reported as.

    Before this, the `ActivityError` travelled out of `run` and Temporal failed
    the execution: the company had no Manager, `CycleOutcome.FAILED` was not
    even reachable, and §9's "a stuck Manager surfaces" was satisfied by nothing
    at all. Now the read fails, the park is recorded, the Manager waits, and the
    next read finds a healthy platform and plans a round.
    """
    loop, _ = await _drive([_exhausted("load_cycle_context"), _ctx(), _ctx()])

    assert loop.scheduled().count("record_manager_park") == 1
    assert loop.waits[0] == DEGRADED_RETRY_INTERVAL, "the park waits, bounded"
    assert "plan_cycle" in loop.scheduled(), "and the next round happens normally"


async def test_the_park_never_loops_hot() -> None:
    """D-034.1's second requirement, which is not the same as the first.

    "Never dies" is the handler; "never loops hot" is the bound. A park that
    looped straight back to the read would satisfy every other test in this
    file while turning a platform outage into a retry storm — cheap per attempt,
    unbounded in aggregate, and invisible until someone reads a log.
    """
    loop, _ = await _drive([_exhausted("load_cycle_context")] * 3)

    assert loop.waits == [DEGRADED_RETRY_INTERVAL] * 3, "one bounded wait per failed read"
    assert all(wait is not None for wait in loop.waits), "and never an unbounded one"


async def test_a_wake_signal_cuts_the_park_short() -> None:
    """The park waits on a *condition* with a timeout, not on a bare timer.

    An operator who resumes a company, or an event that arrives while the
    platform recovers, must not have to wait out the remainder of a fifteen
    minute wait. Checked by evaluating the predicate the workflow handed over,
    because that is the only observable difference between the two.
    """
    loop, manager = await _drive([_exhausted("load_cycle_context")])

    predicate = loop.predicates[0]
    assert predicate() is False, "nothing has arrived yet"
    manager.wake("schedule")
    assert predicate() is True, "a signal ends the wait early"


async def test_a_signal_delivered_while_parked_does_not_spin_the_next_park() -> None:
    """The first draft of this park had a hot loop in it, so it is pinned here.

    Waiting on "there is a wake reason" rather than "a *new* wake reason has
    arrived" is a one-word difference and looks equivalent. It is not: the reason
    that ended one park is still queued when the next begins, so the condition is
    already true and the wait returns instantly. One signal to a Manager whose
    context stays unreadable then spins the loop at the speed of a failing
    activity — which is the hot loop D-034.1 forbids, reached by the most
    ordinary path there is, being woken while degraded.

    Checked on the predicate the second park handed over, because that is where
    the difference lives: a park that would return immediately and a park that
    would wait are otherwise identical from outside.
    """
    loop, manager = await _drive(
        [_exhausted("load_cycle_context")] * 2, signal_on_wait="approval:apr_1"
    )

    assert manager._wake_reasons == ["approval:apr_1"], "the reason is queued, not consumed"
    assert loop.predicates[0]() is True, "the signal did end the park it arrived during"
    assert loop.predicates[1]() is False, "and the next park waits rather than spinning on it"


async def test_a_reason_that_arrived_during_a_park_survives_it() -> None:
    """The reason the fix is a comparison and not a `clear()`.

    Emptying the queue would also stop the spin, and would drop the wake with it
    — including `approval:` reasons, which are how an answered approval reaches
    D-024's effect at the head of the next cycle. A Manager that recovered would
    then never carry out something a human had already agreed to, which is M6-F31
    reintroduced through the failure path.
    """
    loop, _ = await _drive(
        [_exhausted("load_cycle_context"), _ctx(), _ctx()], signal_on_wait="approval:apr_1"
    )

    request = loop.payload("plan_cycle")
    assert isinstance(request, PlanRequest)
    assert request.wake_reasons == ("approval:apr_1",)
    assert loop.payload("execute_approved_action") == {"approval_id": "apr_1"}


async def test_the_park_is_recorded_once_per_episode() -> None:
    """§12.5: an outage is one thing that happened, not ninety-six.

    A Manager parked for a day looks again every quarter hour. Writing the same
    activity-feed entry every time would bury everything else the operator has
    to read under one repeated sentence — the permanent accumulation §12.5
    forbids, self-inflicted.
    """
    loop, _ = await _drive([_exhausted("load_cycle_context")] * 4)

    assert loop.scheduled().count("record_manager_park") == 1
    assert len(loop.waits) == 4, "four looks, four waits, one entry"


async def test_a_park_record_that_could_not_be_written_is_retried() -> None:
    """The other half of "once per episode": once it has actually happened.

    The write is best-effort, and the likeliest reason for a failed context read
    is a platform that also cannot write. Treating a failed record as done would
    lose the only explanation the operator was ever going to get; retrying it on
    the next look lands the entry as soon as the platform can take it.
    """
    loop, _ = await _drive([_exhausted("load_cycle_context")] * 3, park_failures=1)

    assert loop.scheduled().count("record_manager_park") == 2, "failed, then landed, then quiet"


async def test_a_recovered_manager_reports_a_second_outage() -> None:
    """Once per *episode*, not once per Manager.

    A company that recovers and later parks again is a new thing to tell the
    operator about. Latching the flag for the life of the workflow would make
    every outage after the first one silent.
    """
    loop, _ = await _drive(
        [
            _exhausted("load_cycle_context"),
            _ctx(),
            _ctx(),
            _exhausted("load_cycle_context"),
        ]
    )

    assert loop.scheduled().count("record_manager_park") == 2


async def test_a_reload_failure_after_the_wake_parks_too() -> None:
    """M8-F44: M8-3 put a second uncovered read on the path per round.

    The cycle's own snapshot is read after the wake (`PATCH_POST_WAKE_CONTEXT`),
    and that read can fail exactly as the first can. Falling back to the
    pre-wait snapshot would be M7-F45 reintroduced as a failure-path shortcut —
    a cycle reasoning on a context up to a full wake period old, which is the
    defect M8-3 existed to remove.
    """
    loop, _ = await _drive([_ctx(), _exhausted("load_cycle_context")])

    assert loop.scheduled().count("record_manager_park") == 1
    assert "plan_cycle" not in loop.scheduled(), "no cycle runs on the stale snapshot"


async def test_a_healthy_manager_records_no_park() -> None:
    """Negative control. A park that fired on everything would pass every test
    above and stop every company on the platform."""
    loop, _ = await _drive([_ctx(), _ctx()])

    assert "record_manager_park" not in loop.scheduled()
    assert loop.waits[0] == timedelta(seconds=3600), "the ordinary wake wait, not a degraded one"


# ── D-034.2: one cycle key, derived, across every attempt ──────────────────


def test_the_cycle_key_is_a_function_of_the_run_and_the_ordinal() -> None:
    """Derivation, not minting — which is the whole of why D-004 still holds.

    Two calls with the same inputs give the same key, so a replayed workflow
    computes what the original computed. Two ordinals give different keys, so a
    cycle ceiling is a per-cycle ceiling and not a lifetime cap.
    """
    original = workflow_module.workflow
    workflow_module.workflow = SimpleNamespace(  # type: ignore[assignment]
        info=lambda: SimpleNamespace(run_id=RUN_ID)
    )
    try:
        assert _cycle_key(7) == _cycle_key(7)
        assert _cycle_key(7) == f"cyc_{RUN_HEX}_7"
        assert _cycle_key(7) != _cycle_key(8)
    finally:
        workflow_module.workflow = original  # type: ignore[assignment]


async def test_the_derived_key_travels_into_planning() -> None:
    """The mechanism: the key goes *in*, so a retry re-runs with the same one.

    Temporal re-delivers a failed activity's original input on every attempt, so
    a key computed once in the workflow is the one thing about a `plan_cycle`
    attempt that cannot differ between attempts.
    """
    loop, _ = await _drive([_ctx(), _ctx()])

    request = loop.payload("plan_cycle")
    assert isinstance(request, PlanRequest)
    assert request.cycle_key == f"cyc_{RUN_HEX}_0"


async def test_each_cycle_of_a_run_gets_its_own_key() -> None:
    """The ordinal advances with the Manager's own completed-cycle count."""
    loop, _ = await _drive([_ctx(), _ctx(), _ctx(), _ctx()])

    keys = [arg.cycle_key for name, arg in loop.calls if name == "plan_cycle"]
    assert keys == [f"cyc_{RUN_HEX}_0", f"cyc_{RUN_HEX}_1"]


# ── D-034.2 in the ledger, which is where M7-F25 was observed ──────────────


class _StubProvider:
    """Provider returning one canned reply, so no live model is involved."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls = 0

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        self.calls += 1
        return CompletionResponse(text=self._reply, usage=Usage(input_tokens=120, output_tokens=80))

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    """`_env_file=None`: the repository holds a real `.env`, and a test that read
    it would reach a live provider."""
    return Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        _env_file=None,
    )


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    """A real Kernel with real commit semantics and a real ledger.

    `StaticPool` shares one connection, which is what lets the reservation's own
    committed transaction (D-022) be observed from the caller's — the same
    substrate `test_denial_persistence` uses.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(
        _settings(),
        engine=engine,
        provider=_StubProvider(json.dumps({"rationale": "A quiet round.", "items": []})),  # type: ignore[arg-type]
    )
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def company(kernel: PlatformKernel) -> BusinessId:
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        return await provisioning.create_company(
            definition=AFFILIATE, display_name="Summit Trail Gear"
        )


async def _ledger_rows(kernel: PlatformKernel) -> list[BudgetLedgerRow]:
    async with kernel.services() as svc:
        return list((await svc.session.scalars(select(BudgetLedgerRow))).all())


async def test_two_attempts_of_one_cycle_reserve_against_one_scope(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M6-F17's fix, in the ledger rows that recorded the defect (M7-F25).

    Two calls of `plan_cycle` with the *same* request are what an activity retry
    is: Temporal re-delivers the original input on every attempt. Both
    reservations land in one cycle scope, so §2.1's per-cycle ceiling sees one
    cycle's spend rather than one attempt's — which is the whole property.

    The live record of the defect is the same read taken on the running database:
    three RESERVED→RELEASED rows carrying three different cycle ids across three
    attempts of one logical cycle.
    """
    activities = ManagerActivities(kernel)
    request = PlanRequest(business_id=company, cycle_key=f"cyc_{RUN_HEX}_0")

    first = await as_business(company, activities.plan_cycle, request)
    await as_business(company, activities.plan_cycle, request)

    assert first["cycle_id"] == f"cyc_{RUN_HEX}_0", (
        "the activity scoped against the key it was sent"
    )
    rows = await _ledger_rows(kernel)
    assert len(rows) == 2, "two attempts, two holds"
    assert {row.cycle_id for row in rows} == {f"cyc_{RUN_HEX}_0"}, "and one ceiling between them"


async def test_without_a_derived_key_each_attempt_opens_its_own_scope(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M7-F25 itself, kept executable beside its fix.

    The same two calls with no key supplied — which is exactly what every
    `plan_cycle` attempt did before D-034.2. Each mints its own cycle id, so the
    two attempts of one logical cycle are two cycles as far as every ceiling can
    tell.

    Kept rather than deleted with the defect, because it is the only thing that
    distinguishes a derived key that binds the scope from one that is merely
    carried around.
    """
    activities = ManagerActivities(kernel)
    request = PlanRequest(business_id=company)

    first = await as_business(company, activities.plan_cycle, request)
    second = await as_business(company, activities.plan_cycle, request)

    assert first["cycle_id"] != second["cycle_id"]
    rows = await _ledger_rows(kernel)
    assert len({row.cycle_id for row in rows}) == 2, "one logical cycle, two ceilings"


async def _spend_the_cycle_ceiling(
    kernel: PlatformKernel, company: BusinessId, cycle_id: str
) -> None:
    """Record an earlier attempt of ``cycle_id`` having used the whole ceiling.

    Seeded rather than driven by repeated model calls, so the assertion is about
    which scope the ceiling counts and not about how many stub tokens fit inside
    it. The amount is read off the contract, so this stays exact if a default
    ever changes.
    """
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        svc.session.add(
            BudgetLedgerRow(
                business_id=company,
                cycle_id=cycle_id,
                amount_usd=contract.budget.wake_cycle_ceiling_usd,
                state="SETTLED",
            )
        )


async def test_accumulated_cycle_spend_still_refuses_the_retry(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M6-F17's sentence, executable: the consequence of sharing the scope.

    An earlier attempt of this cycle has already used the ceiling. The retry
    arrives with the same derived key, so the ledger counts that spend against
    it and refuses *before* the model call — D-003 rule 1, holding across a
    retry for the first time. The provider is asserted untouched, because a
    check that ran after the tokens were bought is the post-hoc alarm D-003
    rejects.
    """
    key = f"cyc_{RUN_HEX}_0"
    await _spend_the_cycle_ceiling(kernel, company, key)
    provider = kernel.llm

    with pytest.raises(BudgetExceededError) as caught:
        await as_business(
            company,
            ManagerActivities(kernel).plan_cycle,
            PlanRequest(business_id=company, cycle_key=key),
        )

    assert caught.value.scope == "wake_cycle"
    assert provider.calls == 0  # type: ignore[attr-defined]


async def test_a_minted_id_let_that_same_retry_straight_through(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The defect, in one line: "a refusal caused by *accumulated* cycle spend
    can pass on retry against a fresh cycle scope" (M6-F17).

    Identical seeded spend, identical retry, no key — and the ceiling that just
    refused the call does not even see it, because the attempt mints a scope
    nothing has ever spent against. Without this beside the test above, "the
    retry was refused" would be equally true of a ceiling that refuses
    everything.
    """
    await _spend_the_cycle_ceiling(kernel, company, f"cyc_{RUN_HEX}_0")
    provider = kernel.llm

    payload = await as_business(
        company, ManagerActivities(kernel).plan_cycle, PlanRequest(business_id=company)
    )

    assert payload["cycle_id"] != f"cyc_{RUN_HEX}_0"
    assert provider.calls == 1, "the model call the ceiling should have stopped"  # type: ignore[attr-defined]


async def test_a_malformed_cycle_key_is_not_trusted(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-002's posture applied to the one field that travels inward.

    The key arrives in an activity payload, so it says what the caller believes.
    A key of the wrong shape is a mis-assembled request, and the answer to one is
    the behaviour that predates the field — mint, as D-021 said — never to write
    whatever arrived into the ledger's scope column.
    """
    activities = ManagerActivities(kernel)
    payload = await as_business(
        company,
        activities.plan_cycle,
        PlanRequest(business_id=company, cycle_key="../../someone-elses-cycle"),
    )

    cycle_id = str(payload["cycle_id"])
    assert cycle_id.startswith("cyc_")
    assert "someone-elses-cycle" not in cycle_id
    assert {row.cycle_id for row in await _ledger_rows(kernel)} == {cycle_id}


# ── D-034.1's records, written where the company still has a name ──────────


async def test_the_park_record_reaches_the_operator_twice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§11.5 and §9: the feed entry explains it, the notification surfaces it.

    Both, because they answer different questions. The Decision Log entry is
    what an owner reads when they ask what this company has been doing; the
    notification is what tells them without their having to ask.
    """
    await as_business(
        company, ManagerActivities(kernel).record_manager_park, {"business_id": company}
    )

    async with kernel.services() as svc:
        entries = list((await svc.session.scalars(select(DecisionLogRow))).all())
        notices = list((await svc.session.scalars(select(NotificationRow))).all())

    parked = [e for e in entries if e.action_type == "business.manager_parked"]
    assert len(parked) == 1
    assert parked[0].summary == MANAGER_PARKED_SUMMARY.format(name="Summit Trail Gear")
    assert parked[0].cycle_id is None, "a park is the round that did not happen"
    assert [n.kind for n in notices] == [NotificationKind.STUCK.value]


async def test_a_second_park_does_not_queue_a_second_notice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§12.5's "no permanent accumulation", against a condition that recurs.

    The workflow already records once per episode, but that guarantee is a loop
    local: a worker restart resets it. The queue must not refill every quarter
    hour after one restart, so the notice is raised only when nothing unread of
    its kind is already waiting.
    """
    activities = ManagerActivities(kernel)
    for _ in range(3):
        await as_business(company, activities.record_manager_park, {"business_id": company})

    async with kernel.services() as svc:
        notices = list((await svc.session.scalars(select(NotificationRow))).all())
        entries = list((await svc.session.scalars(select(DecisionLogRow))).all())

    assert len(notices) == 1, "one unanswered notice per company"
    assert len([e for e in entries if e.action_type == "business.manager_parked"]) == 3, (
        "the feed keeps every occurrence; the queue keeps one"
    )


async def test_a_dismissed_notice_can_be_raised_again(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Negative control on the deduplication: it is *unread*, not *ever*.

    An operator who dismissed the notice has said they know. A company still
    unable to run an hour later is worth saying again — and a check that looked
    for any past notice would silence it permanently after the first outage.
    """
    activities = ManagerActivities(kernel)
    await as_business(company, activities.record_manager_park, {"business_id": company})
    async with kernel.services() as svc:
        notifications = NotificationService(svc.session)
        for row in await notifications.unread():
            await notifications.mark_read(row.notification_id)

    await as_business(company, activities.record_manager_park, {"business_id": company})

    async with kernel.services() as svc:
        notices = list((await svc.session.scalars(select(NotificationRow))).all())
    assert len(notices) == 2


# ── M9-F118's records: the round that started and failed ──────────────────


async def _record_round(
    kernel: PlatformKernel, company: BusinessId, outcome: str, summary: str = "It didn't finish."
) -> None:
    """Write one cycle's Decision Log entry the way the workflow does."""
    await as_business(
        company,
        ManagerActivities(kernel).record_cycle_decision,
        {
            "business_id": company,
            "cycle_id": "cyc_unfinished",
            "summary": summary,
            "rationale": "It stopped instead of pressing on.",
            "outcome": outcome,
            "spend_usd": "0",
        },
    )


async def _notices(kernel: PlatformKernel) -> list[NotificationRow]:
    """Every notification in the queue. Shared with D-035's section below, which
    asks the same question of a different condition."""
    async with kernel.services() as svc:
        return list((await svc.session.scalars(select(NotificationRow))).all())


async def _round_entries(kernel: PlatformKernel) -> list[DecisionLogRow]:
    """Only the cycle entries: creating the company writes one of its own."""
    async with kernel.services() as svc:
        entries = (await svc.session.scalars(select(DecisionLogRow))).all()
    return [entry for entry in entries if entry.action_type == "business.wake_cycle"]


async def test_a_round_that_did_not_finish_reaches_the_operator_twice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M9-F118, stated as the asymmetry it was found as.

    `record_manager_park` above writes an entry *and* a notice for the round
    that never started; this wrote only an entry for the round that started and
    failed. So the quieter failure was the loud one, and on the morning all
    three companies' rounds failed within seven seconds of each other the
    operator-visible signal was nothing at all — not a failed notification, no
    notification at all.
    """
    await _record_round(kernel, company, "failed")

    entries = await _round_entries(kernel)
    notices = await _notices(kernel)

    assert len(entries) == 1
    assert [n.kind for n in notices] == [NotificationKind.UNFINISHED_ROUND.value]
    assert "Summit Trail Gear" in notices[0].title, "the notice names the company, not the platform"


async def test_a_round_that_finished_says_nothing_in_the_queue(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The negative control, and the reason the copy table *is* the policy.

    Every healthy outcome is absent from `UNFINISHED_ROUND_COPY`, so silence is
    what a table lookup returns rather than what a second list has to remember.
    A notice per completed round is the permanent accumulation §12.5 forbids,
    and the activity feed is where a normal round is already recorded.
    """
    for outcome in ("completed", "nothing_to_do", "awaiting_approval"):
        await _record_round(kernel, company, outcome, summary="It finished.")

    assert len(await _round_entries(kernel)) == 3, "every round is still recorded in the feed"
    assert await _notices(kernel) == []


async def test_a_second_failed_round_does_not_queue_a_second_notice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§12.5's "no permanent accumulation", against the condition that produces
    the most of it.

    A provider outage fails one round per company per wake for as long as it
    lasts. The feed keeps every occurrence — that is the forensic record — and
    the queue keeps one, because the operator's action is the same for all of
    them.
    """
    for _ in range(3):
        await _record_round(kernel, company, "failed")

    assert len(await _round_entries(kernel)) == 3, "the feed keeps every occurrence"
    assert len(await _notices(kernel)) == 1, "the queue keeps one"


async def test_a_ceiling_stop_is_not_swallowed_by_an_unread_breakage(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Deduplicated per company *and* per condition (D-003 rule 5).

    "It couldn't finish" sends an operator looking for a fault; "it stopped to
    stay inside its spending limit" does not. A bare per-kind check would let
    the first, still unread, swallow the second — the same information loss
    `WAITING_ON_RESUME` exists to prevent, arriving through the deduplication
    instead of through a shared kind, and closed the same way the spend bands
    close it: the thing that differs is part of what is compared.
    """
    await _record_round(kernel, company, "failed")
    await _record_round(kernel, company, "budget_exhausted")

    notices = await _notices(kernel)
    assert sorted(n.link_ref or "" for n in notices) == ["budget_exhausted", "failed"]
    assert len({n.title for n in notices}) == 2, "two conditions, two sentences"


async def test_a_company_that_cannot_be_named_still_gets_its_entry(
    kernel: PlatformKernel,
) -> None:
    """The notice must never cost the record it was added beside.

    The sentence names the company, and a name is a contract read — so a
    company whose contract cannot be read would take the Decision Log entry
    down with the transaction writing it. That inverts the two: §11.5's record
    of what happened is the primary, and M9-F118's notice is the addition.
    Pinned with an unknown company, which is the shape the failure would have.
    """
    unknown = BusinessId("biz_ffffffffffffffffffffffffffffffff")
    await as_business(
        unknown,
        ManagerActivities(kernel).record_cycle_decision,
        {
            "business_id": unknown,
            "cycle_id": "cyc_unnamed",
            "summary": "It didn't finish.",
            "rationale": "It stopped instead of pressing on.",
            "outcome": "failed",
            "spend_usd": "0",
        },
    )

    assert len(await _round_entries(kernel)) == 1, "the entry survives an unnameable company"
    assert await _notices(kernel) == []


async def test_the_notice_does_not_share_a_kind_with_the_park(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Why `UNFINISHED_ROUND` is not `STUCK`, proved rather than argued.

    A company meets both conditions inside one outage — the incident that
    motivated this notice is three Managers failing against an unreachable
    provider, which is exactly when a context read fails too. On a shared kind
    the park's ref-less check would suppress whichever arrived second, and this
    notice exists because a silence suppressed the first one.
    """
    activities = ManagerActivities(kernel)
    await _record_round(kernel, company, "failed")
    await as_business(company, activities.record_manager_park, {"business_id": company})

    notices = await _notices(kernel)
    assert sorted(n.kind for n in notices) == [
        NotificationKind.STUCK.value,
        NotificationKind.UNFINISHED_ROUND.value,
    ]


# ── M8-F87: the ordinal resets, so the bound binds every generation ────────


def _running_ctx() -> CycleContext:
    """A healthy context whose daily allowance cannot end the run first.

    `max_cycles_per_day` is deliberately far above `CYCLES_BEFORE_CONTINUATION`:
    the allowance and the continuation bound are different mechanisms, and a
    script that hit the allowance at 48 would never reach the one under test.
    """
    return _ctx(max_cycles_per_day=CYCLES_BEFORE_CONTINUATION * 10)


def _generation(cycles: int) -> list[CycleContext | BaseException]:
    """Enough context reads for ``cycles`` complete rounds, and then some.

    Two reads per round on the post-M8-3 path — the wake's and the cycle's — so
    a generation of *n* rounds consumes 2n, and the spares are what let a test
    that expects no continuation run past the point one would have happened.
    """
    return [_running_ctx() for _ in range(cycles * 2 + 4)]


async def test_a_manager_continues_as_new_at_the_bound() -> None:
    """D-005's mechanism, which nothing had ever driven to its threshold.

    The loop had no behavioural test that reached a continuation at all — which
    is how M8-F87 survived two milestones in code that is read closely. Every
    `continue_as_new` assertion in the suite was a source-level one
    (`test_continuation_is_bounded`), and a source check cannot see what the
    state handed over looks like.
    """
    loop, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION))

    assert len(loop.continued) == 1
    assert loop.scheduled().count("plan_cycle") == CYCLES_BEFORE_CONTINUATION


async def test_the_generation_it_starts_holds_no_cycles_of_its_own() -> None:
    """M8-F87's fix, stated as the state the next execution begins from.

    The ordinal counts what *this* history holds, and the next history is empty.
    Handing the count over intact is the defect: generation two's first cycle
    took it to 101, met the threshold, and continued as new again.
    """
    loop, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION))

    assert loop.continued[0].cycles_completed == 0


async def test_the_second_generation_gets_a_whole_hundred_cycles_too() -> None:
    """The property in full, driven rather than inferred from one field.

    Generation two starts from exactly what generation one handed over and runs
    its own hundred rounds before continuing. Asserting on the handed-over state
    alone would leave the claim a step short: what matters is that the bound
    binds again, not that a field reads zero.
    """
    first, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION))
    second, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION), state=first.continued[0])

    assert second.scheduled().count("plan_cycle") == CYCLES_BEFORE_CONTINUATION
    assert len(second.continued) == 1


async def test_without_the_reset_the_next_generation_continues_every_cycle() -> None:
    """M8-F87 itself, kept executable beside its fix.

    The state generation one used to hand over, driven as generation two: one
    cycle, then a continuation, and the same again for as long as the company
    exists. `CYCLES_BEFORE_CONTINUATION` would be a bound that fires once in a
    Manager's life and never afterwards.

    Kept rather than deleted with the defect, because it is the only thing that
    distinguishes a reset that restores the bound from a field nobody reads.
    """
    unreset = ManagerState(business_id=BIZ, cycles_completed=CYCLES_BEFORE_CONTINUATION)

    loop, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION), state=unreset)

    assert loop.scheduled().count("plan_cycle") == 1, "one cycle bought a whole continuation"
    assert len(loop.continued) == 1


async def test_the_daily_allowance_survives_the_continuation() -> None:
    """The half a careless reset would break, and nothing else would catch.

    `cycles_today` and `day_ordinal` bound how often a *company* reasons (D-021),
    not how much history one execution holds. Clearing them alongside the ordinal
    would hand every Manager a fresh day's allowance every hundred cycles — the
    rate limit quietly removing itself, and passing every other test here.
    """
    loop, _ = await _drive(_generation(CYCLES_BEFORE_CONTINUATION))

    handed_over = loop.continued[0]
    assert handed_over.cycles_today == CYCLES_BEFORE_CONTINUATION
    assert handed_over.day_ordinal == TODAY


def test_the_working_set_crosses_the_continuation_intact() -> None:
    """D-005's other fields, asserted on the state shape itself.

    A pending approval that spans a continuation is a roundtrip in flight
    (D-006), and the plan and targets are the working set §2.1 says the Manager
    owns. `continued` touches one field; this is what "one" means.
    """
    before = ManagerState(
        business_id=BIZ,
        plan=TacticalPlan(rationale="Carry on."),
        cycles_completed=CYCLES_BEFORE_CONTINUATION,
        cycles_today=7,
        day_ordinal=TODAY,
        pending_approval_id="apr_inflight",
    )

    after = before.continued()

    assert after.cycles_completed == 0
    assert after == before.model_copy(update={"cycles_completed": 0})


def test_the_reset_ordinal_cannot_collide_across_generations() -> None:
    """Why resetting the ordinal is safe at all (D-034.2), checked not assumed.

    The cycle key is the budget scope key and the ordinal is half of it. Reset it
    and generation two's cycle 0 carries the same ordinal as generation one's —
    which would be two cycles sharing one ceiling if the ordinal were the whole
    key. It is not: `continue_as_new` assigns a new run id and the key namespaces
    by it. That is the property the reset leans on, so it is asserted here rather
    than left as a sentence in a docstring.
    """
    other_run = "11e3a4ab-097d-4f33-aef4-0ef25ed82895"
    original = workflow_module.workflow
    try:
        workflow_module.workflow = SimpleNamespace(  # type: ignore[assignment]
            info=lambda: SimpleNamespace(run_id=RUN_ID)
        )
        first_generation = _cycle_key(0)
        workflow_module.workflow = SimpleNamespace(  # type: ignore[assignment]
            info=lambda: SimpleNamespace(run_id=other_run)
        )
        second_generation = _cycle_key(0)
    finally:
        workflow_module.workflow = original  # type: ignore[assignment]

    assert first_generation != second_generation
    assert first_generation.endswith("_0")
    assert second_generation.endswith("_0")


# ── D-035's records, written where the company still has a name ────────────


async def _audited_drops(kernel: PlatformKernel) -> list[AuditLogRow]:
    async with kernel.services() as svc:
        return list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == DROPPED_WAKE_EVENT)
                )
            ).all()
        )


async def test_a_dropped_reason_reaches_the_operator_twice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-035: an operator notification and an audit record, per dropped reason.

    Both, because they answer different questions. The audit entry is the
    forensic account of what a pause swallowed, with the kind and the ref it
    carried (§11); the notification is what reaches the operator without their
    looking, and it is what turns "I answered that and nothing happened" into a
    sentence they can act on.
    """
    await as_business(
        company,
        ManagerActivities(kernel).record_dropped_wake,
        {"business_id": company, "reason_kind": "approval", "reason_ref": "apr_9"},
    )

    audited = await _audited_drops(kernel)
    notices = await _notices(kernel)

    assert len(audited) == 1
    assert audited[0].payload["reason_kind"] == "approval"
    assert audited[0].payload["reason_ref"] == "apr_9"
    assert [n.kind for n in notices] == [NotificationKind.WAITING_ON_RESUME.value]
    assert notices[0].title == DROPPED_WAKE_COPY["approval"].title.format(name="Summit Trail Gear")
    assert notices[0].link_ref == "apr_9", "the answer the operator gave is still there to open"


async def test_the_notice_says_which_kind_of_thing_is_waiting(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The owner's breadth, at the surface.

    An answered request and a finished piece of work are different situations
    and lead an operator to different decisions. One sentence covering both
    would be the vague copy §12.5 exists to prevent, so the kind selects the
    words and the kind is a platform fact, never prose (D-011's posture).
    """
    await as_business(
        company,
        ManagerActivities(kernel).record_dropped_wake,
        {
            "business_id": company,
            "reason_kind": "capability.result_returned",
            "reason_ref": "",
        },
    )

    expected = DROPPED_WAKE_COPY["capability.result_returned"]
    notices = await _notices(kernel)
    assert notices[0].title == expected.title.format(name="Summit Trail Gear")
    assert notices[0].body == expected.body
    assert notices[0].link_ref is None, "an event is not a row an operator can open"


async def test_a_kind_nobody_has_words_for_still_says_something_true(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The fallback, which is a §12.5 guard rather than a convenience.

    A bus event added later would otherwise reach the operator's queue under its
    own internal name. The default sentence says the true thing without naming
    the mechanism, so an unmapped kind degrades to vaguer copy instead of
    leaking the register §12.5 forbids.
    """
    await as_business(
        company,
        ManagerActivities(kernel).record_dropped_wake,
        {"business_id": company, "reason_kind": "something.new", "reason_ref": ""},
    )

    notices = await _notices(kernel)
    assert notices[0].title == DROPPED_WAKE_DEFAULT.title.format(name="Summit Trail Gear")
    assert "something.new" not in notices[0].title + notices[0].body


async def test_a_paused_company_does_not_fill_the_queue(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§12.5's "no permanent accumulation", against a company that stays paused.

    A pause can drop reasons for as long as it lasts, and the operator's action
    is the same for all of them — start the company again. One unanswered notice
    says that; ninety of them are the accumulation §12.5 forbids. The audit log
    is where the count lives, which is why it is asserted in the same breath.
    """
    activities = ManagerActivities(kernel)
    for ref in ("apr_1", "apr_2", "apr_3"):
        await as_business(
            company,
            activities.record_dropped_wake,
            {"business_id": company, "reason_kind": "approval", "reason_ref": ref},
        )

    assert len(await _notices(kernel)) == 1, "one unanswered notice per company"
    assert len(await _audited_drops(kernel)) == 3, "the record keeps every one of them"


# ── design 4.4's records, for the round an outage skipped ──────────────────


async def _audited_skips(kernel: PlatformKernel) -> list[AuditLogRow]:
    async with kernel.services() as svc:
        return list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == LATE_WAKE_EVENT)
                )
            ).all()
        )


async def test_a_skipped_round_reaches_the_operator_and_the_record(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Design 4.4: an operator notification and an audit entry, per skipped period.

    Both, because they answer different questions. The audit entry is the
    forensic account — which company, how late, on what schedule — and it is the
    only place a "wakes have been getting later all week" trend can be read
    from. The notification is what reaches the operator without their looking,
    and it is what turns "my company did nothing this morning" from a mystery
    into a sentence.
    """
    await as_business(
        company,
        ManagerActivities(kernel).record_late_wake,
        {"business_id": company, "wake_lateness_seconds": "27240"},
    )

    audited = await _audited_skips(kernel)
    notices = await _notices(kernel)

    assert len(audited) == 1
    assert audited[0].payload["wake_lateness_seconds"] == "27240"
    assert audited[0].payload["schedule_cron"] == "0 9 * * *"
    assert audited[0].payload["schedule_timezone"] == "UTC"
    assert [n.kind for n in notices] == [NotificationKind.MISSED_ROUND.value]
    assert notices[0].title == LATE_WAKE_TITLE.format(name="Summit Trail Gear")
    assert notices[0].body == LATE_WAKE_BODY


async def test_a_long_outage_does_not_fill_the_queue(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§12.5's "no permanent accumulation", against an outage of several days.

    Every skipped round has the same cause and the same (absent) action, so one
    unanswered notice says everything the operator can act on; seven of them are
    the accumulation §12.5 forbids. The count lives in the audit log, which is
    asserted in the same breath so that "deduplicated" cannot quietly become
    "lost".
    """
    activities = ManagerActivities(kernel)
    for lateness in ("3600", "90000", "176400"):
        await as_business(
            company,
            activities.record_late_wake,
            {"business_id": company, "wake_lateness_seconds": lateness},
        )

    assert len(await _notices(kernel)) == 1, "one unanswered notice per company"
    assert len(await _audited_skips(kernel)) == 3, "the record keeps every one of them"


async def test_the_skip_notice_does_not_share_a_kind_with_a_failed_round(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The trap the new kind exists to avoid, made executable.

    One outage produces both conditions in the same minute: rounds that were
    missed while the platform was down (this), and rounds that failed against a
    provider that is still unreachable when it comes back (`UNFINISHED_ROUND`).
    A shared kind would let whichever landed first silence the other under
    `has_unread` — and the operator would be told about one of the two things
    that happened to their company, with no way to know there was a second.
    """
    await as_business(
        company,
        ManagerActivities(kernel).record_cycle_decision,
        {
            "business_id": company,
            "cycle_id": "cyc_outage",
            "summary": "Summit Trail Gear couldn't finish this round of work.",
            "rationale": "Something it needed didn't respond.",
            "outcome": "failed",
            "spend_usd": "0",
            "wake_lateness_seconds": "0",
        },
    )
    await as_business(
        company,
        ManagerActivities(kernel).record_late_wake,
        {"business_id": company, "wake_lateness_seconds": "27240"},
    )

    assert {row.kind for row in await _notices(kernel)} == {
        NotificationKind.UNFINISHED_ROUND.value,
        NotificationKind.MISSED_ROUND.value,
    }


async def test_every_round_files_its_lateness_with_its_decision(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """4.4's trending half, at the row an operator's history is built from.

    Recorded on a healthy round too, which is the whole point: a number that
    only appears when something is wrong has no baseline to be read against. A
    history captured before the field replays its own payload, so the read is
    defensive and the absent case records zero rather than raising inside an
    activity (spec §11).
    """
    payload = {
        "business_id": company,
        "cycle_id": "cyc_ontime",
        "summary": "Summit Trail Gear finished a round of work.",
        "rationale": "It did what it planned.",
        "outcome": "completed",
        "spend_usd": "0.12",
    }
    await as_business(
        company,
        ManagerActivities(kernel).record_cycle_decision,
        payload | {"wake_lateness_seconds": "27240"},
    )
    await as_business(
        company,
        ManagerActivities(kernel).record_cycle_decision,
        payload,  # a caller from before the field, e.g. a replayed history
    )

    entries = await _round_entries(kernel)
    assert [e.inputs_considered["wake_lateness_seconds"] for e in entries] == ["27240", "0"]


async def test_it_does_not_share_a_kind_with_the_notice_that_paused_it(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The trap this kind exists to avoid, made executable.

    The seven-day sweep pauses a company with an unanswered request and raises a
    `PAUSED` notice saying so. The operator answers. The answer is dropped
    because the company is paused — and if this notice shared that kind, the
    still-unread first one would suppress it under the same deduplication. The
    operator would be told to answer, would answer, and would never learn that
    answering did nothing until they start the company again: exactly the loss
    D-035 closes.
    """
    async with kernel.services() as svc:
        await NotificationService(svc.session).notify(
            notification_id="ntf_paused",
            kind=NotificationKind.PAUSED,
            title="Summit Trail Gear is paused",
            body="A request went unanswered for a week.",
            business_id=company,
        )

    await as_business(
        company,
        ManagerActivities(kernel).record_dropped_wake,
        {"business_id": company, "reason_kind": "approval", "reason_ref": "apr_9"},
    )

    async with kernel.services() as svc:
        unread = await NotificationService(svc.session).unread()

    assert {row.kind for row in unread} == {
        NotificationKind.PAUSED.value,
        NotificationKind.WAITING_ON_RESUME.value,
    }
