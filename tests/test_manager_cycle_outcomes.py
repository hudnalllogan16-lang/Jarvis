"""Wake-cycle identity and cycle outcomes (D-021, D-003; spec §2.1, §9, §12.5).

Two findings from the first live run meet here.

**M6-F8** — every `ScopedRequest.cycle_id` was NULL, so the budget ledger's
per-cycle branch (`if cycle_id is not None`) never ran: §2.1's cost ceiling was
structurally unenforced and `BUDGET_EXHAUSTED` unreachable. D-021 fixes the start
of a cycle at the start of planning and mints the id in `plan_cycle`. The tests
below follow that id along its whole path — minted in the activity, stamped on
the requests, counted by the ledger, written to the Decision Log.

**M6-F9** — an activity that exhausted its retries failed the entire Manager
workflow, leaving the business with no Manager at all and `CycleOutcome.FAILED`
unreachable. §9 requires a stuck Manager to surface rather than vanish, so a
failed cycle is now a recorded outcome and the workflow lives to its next wake.

The workflow tests drive `BusinessManagerWorkflow` across a scripted activity
boundary. What is under test is the workflow's own branching on activity failure,
which is decided before any server is involved; replay against a real captured
history stays where it belongs, in `test_manager_replay.py`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.exceptions import ActivityError, ApplicationError

from jarvis.approvals.rendering import contains_technical_language
from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates
from jarvis.capabilities.pool import CapabilityPool
from jarvis.capabilities.request import (
    CapabilityResult,
    InvocationStatus,
    ScopedRequest,
)
from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.errors import BudgetExceededError, ProviderError
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId, InvocationId
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager import workflow as workflow_module
from jarvis.manager.activities import ManagerActivities
from jarvis.manager.state import CycleOutcome, ManagerState, TacticalPlan
from jarvis.manager.types import CycleContext, PlanRequest, SynthesisRequest
from jarvis.manager.workflow import BusinessManagerWorkflow
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import BudgetLedgerRow, DecisionLogRow
from jarvis.registry.registry import BusinessRegistry
from tests.conftest import as_business

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")


# ── Part 1: the id is minted in the activity that opens the cycle ──────────


class _StubProvider:
    """Provider returning one canned reply, so no live model is involved.

    It reports token counts because every real transport does, and because a
    reasoning call now settles against them (D-022 point 3): a stub reporting
    zero tokens would make a charged call look free and hide M6-F14 reopening.
    """

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


class _StubKernel:
    """Just enough Kernel for one activity: settings, a services scope, a provider."""

    def __init__(
        self,
        provider: object,
        *,
        session: AsyncSession | None = None,
        **services: object,
    ) -> None:
        self._provider = provider
        self._services = services
        self._session = session
        self.settings = SimpleNamespace(
            budget=SimpleNamespace(reasoning_token_price_per_million_usd=Decimal("50.00"))
        )

    @property
    def llm(self) -> Any:
        return self._provider

    def build_ledger(self, services: object) -> BudgetLedger:
        """Return a real ledger, so a reasoning call is really charged (D-022).

        A stub that returned a no-op ledger would let M6-F14 reopen silently:
        the activity would still call `reserve`, and nothing would check that a
        ceiling can refuse it.
        """
        assert self._session is not None, (
            "an activity that reasons must be given a session; its model call is spend"
        )
        return BudgetLedger(self._session, platform_ceiling_usd=Decimal("500.00"))

    @asynccontextmanager
    async def services(self) -> AsyncIterator[Any]:
        yield SimpleNamespace(**self._services)


async def _installed(registry: BusinessRegistry, contract: BusinessContract) -> BusinessContract:
    """Register and activate ``contract`` so dispatch is authorized."""
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )
    await registry.register_instance(contract)
    await registry.transition(
        contract.business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_start"),
        reason="Started for testing.",
    )
    return contract


async def test_plan_cycle_mints_a_cycle_id_and_stamps_every_request(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-021: the cycle begins when planning begins, and the id travels with it.

    This is the whole of M6-F8's fix at its source. Before it, `plan_cycle`
    returned requests with `cycle_id=None` and the ledger's per-cycle check —
    the only enforcement §2.1's ceiling has — was skipped on every invocation
    the platform has ever dispatched.
    """
    reply = json.dumps(
        {
            "rationale": "Check what's selling.",
            "items": [
                {"ref": "a", "intent": "look at demand", "capability": "research"},
                {"ref": "b", "intent": "look at rivals", "capability": "research"},
            ],
        }
    )
    activities = ManagerActivities(
        _StubKernel(  # type: ignore[arg-type]
            _StubProvider(reply), session=session, registry=_StubRegistry(contract)
        )
    )
    payload = await as_business(
        contract.business_id, activities.plan_cycle, PlanRequest(business_id=contract.business_id)
    )

    cycle_id = payload["cycle_id"]
    assert isinstance(cycle_id, str) and cycle_id.startswith("cyc_")
    requests = [ScopedRequest.model_validate(r) for r in payload["requests"]]  # type: ignore[union-attr]
    assert len(requests) == 2
    assert {r.cycle_id for r in requests} == {cycle_id}, (
        "every request a cycle dispatches must be billed to that cycle (D-003 tier 2)"
    )


async def test_each_cycle_gets_its_own_id(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A shared id across cycles would make the ceiling a lifetime cap."""
    reply = json.dumps({"rationale": "x", "items": []})
    activities = ManagerActivities(
        _StubKernel(  # type: ignore[arg-type]
            _StubProvider(reply), session=session, registry=_StubRegistry(contract)
        )
    )
    first = await as_business(
        contract.business_id, activities.plan_cycle, PlanRequest(business_id=contract.business_id)
    )
    second = await as_business(
        contract.business_id, activities.plan_cycle, PlanRequest(business_id=contract.business_id)
    )
    assert first["cycle_id"] != second["cycle_id"]


class _StubRegistry:
    """Registry stand-in returning one contract."""

    def __init__(self, contract: BusinessContract) -> None:
        self._contract = contract

    async def get_contract(self, business_id: BusinessId) -> BusinessContract:
        return self._contract


# ── Part 1b: the Manager's own reasoning is spend too (M6-F14, D-022) ──────


class _FailingProvider:
    """Provider that never answers, so a hold has nothing to settle against."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        raise ProviderError("the model did not answer")

    async def aclose(self) -> None:
        return None


def _tiny_ceiling(contract: BusinessContract) -> BusinessContract:
    """Return ``contract`` with a wake-cycle ceiling one reasoning call exceeds."""
    return contract.model_copy(
        update={
            "budget": contract.budget.model_copy(
                update={"wake_cycle_ceiling_usd": Decimal("0.000001")}
            )
        }
    )


def _planner(
    session: AsyncSession, contract: BusinessContract, provider: object
) -> ManagerActivities:
    return ManagerActivities(
        _StubKernel(provider, session=session, registry=_StubRegistry(contract))  # type: ignore[arg-type]
    )


async def test_the_plan_call_is_charged_to_the_cycle_it_opens(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """M6-F14: `plan_cycle` and `synthesize_results` are most of a cycle's cost
    and were charged to no ceiling at all, so §2.1's ceiling bounded only what a
    cycle *dispatched*. D-003 covers "every unit of spend"."""
    activities = _planner(session, contract, _StubProvider(json.dumps({"items": []})))
    payload = await as_business(
        contract.business_id, activities.plan_cycle, PlanRequest(business_id=contract.business_id)
    )

    row = (await session.scalars(select(BudgetLedgerRow))).one()
    assert row.cycle_id == payload["cycle_id"]
    assert row.state == "SETTLED"
    assert row.amount_usd > Decimal("0"), "a reasoning call that costs nothing is M6-F14 reopened"


async def test_a_plan_call_alone_can_exhaust_a_tiny_ceiling(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-003 rule 1: the reservation is refused *before* the call is made.

    The provider is asserted untouched — a check that ran after the tokens were
    bought would be the post-hoc alarm D-003 rejects.
    """
    provider = _StubProvider(json.dumps({"items": []}))
    activities = _planner(session, _tiny_ceiling(contract), provider)

    with pytest.raises(BudgetExceededError) as caught:
        await as_business(
            contract.business_id,
            activities.plan_cycle,
            PlanRequest(business_id=contract.business_id),
        )

    assert caught.value.scope == "wake_cycle"
    assert provider.calls == 0, "the ceiling refused it after spending it"
    assert not contains_technical_language(caught.value.operator_message)


async def test_a_refused_reasoning_call_ends_the_cycle_budget_exhausted(
    drive: Callable[..., Any],
) -> None:
    """The other end of the same path: a `plan_cycle` refused by a ceiling
    reaches the workflow as a budget refusal, and D-003 rule 5 ends the cycle
    `BUDGET_EXHAUSTED` with an entry saying so — not `FAILED`."""
    _, activities, cycle = await drive(plan_cycle=_exhausted("BudgetExceededError"))
    assert cycle.outcome is CycleOutcome.BUDGET_EXHAUSTED
    assert activities.payload("record_cycle_decision")["outcome"] == "budget_exhausted"
    assert not activities.called("dispatch_capability")


async def test_a_reasoning_call_that_fails_releases_its_hold(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-022 point 3: terminality resolves the hold, and failure is terminal.

    Without the release, every failed cycle would leave its worst case charged
    against the company forever and a Manager would strangle itself by degrees
    on spend that never happened.
    """
    activities = _planner(session, contract, _FailingProvider())

    with pytest.raises(ProviderError):
        await as_business(
            contract.business_id,
            activities.plan_cycle,
            PlanRequest(business_id=contract.business_id),
        )

    row = (await session.scalars(select(BudgetLedgerRow))).one()
    assert row.state == "RELEASED"
    assert await BudgetLedger(session, platform_ceiling_usd=Decimal("500.00")).business_spend(
        contract.business_id
    ) == Decimal("0")


async def test_synthesis_is_charged_to_the_cycle_that_asked_for_it(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Both reasoning calls debit the same cycle ceiling as its dispatches."""
    activities = _planner(
        session, contract, _StubProvider(json.dumps({"summary": "Did a round.", "action": None}))
    )
    await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_synth",
        ),
    )
    row = (await session.scalars(select(BudgetLedgerRow))).one()
    assert row.cycle_id == "cyc_synth"
    assert row.amount_usd > Decimal("0")


async def test_decision_entry_is_filed_under_its_cycle(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-021: the decision record carries the cycle id, so a cycle's entry,
    ledger rows, and results can be read together."""
    activities = ManagerActivities(
        _StubKernel(_StubProvider(""), decisions=DecisionLog(session))  # type: ignore[arg-type]
    )
    await as_business(
        contract.business_id,
        activities.record_cycle_decision,
        {
            "business_id": contract.business_id,
            "cycle_id": "cyc_abc",
            "summary": "Looked at what's selling.",
            "rationale": "Its usual round.",
            "outcome": "completed",
            "spend_usd": "0.20",
        },
    )
    row = (await session.scalars(select(DecisionLogRow))).one()
    assert row.cycle_id == "cyc_abc"


async def test_decision_entry_tolerates_a_payload_from_before_d021(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Replay of a pre-D-021 history must write an entry, not raise a KeyError."""
    activities = ManagerActivities(
        _StubKernel(_StubProvider(""), decisions=DecisionLog(session))  # type: ignore[arg-type]
    )
    await as_business(
        contract.business_id,
        activities.record_cycle_decision,
        {
            "business_id": contract.business_id,
            "summary": "Looked at what's selling.",
            "rationale": "Its usual round.",
            "outcome": "completed",
            "spend_usd": "0.20",
        },
    )
    assert (await session.scalars(select(DecisionLogRow))).one().cycle_id is None


# ── Part 1: the ledger now has something to count ──────────────────────────


async def _pool(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> CapabilityPool:
    """Build a pool over the real ledger, so ceilings are actually enforced."""
    await _installed(registry, contract)
    ledger = BudgetLedger(session, platform_ceiling_usd=Decimal("500.00"))
    return CapabilityPool(
        session=session,
        registry=registry,
        ledger=ledger,
        breaker=CircuitBreaker(ledger, DecisionLog(session), ceiling_usd=Decimal("500.00")),
        executor=CapabilityExecutor(
            _StubProvider("done"),  # type: ignore[arg-type]
            InMemoryTemplates({"affiliate.research": "Research {topic}"}),
        ),
        audit=registry._audit,
    )


def _request(n: int, cycle_id: str | None) -> ScopedRequest:
    return ScopedRequest(
        invocation_id=InvocationId(f"inv_{n}"),
        declared_business_id=BIZ,
        capability=CapabilityType.RESEARCH,
        prompt_ref="affiliate.research",
        prompt_inputs={"topic": "x"},
        tool_scope=frozenset({"web_search"}),
        credential_refs=frozenset({"serp_key"}),
        budget_allocation_usd=Decimal("0.50"),
        cycle_id=cycle_id,
    )


async def test_ledger_rows_carry_the_cycle_that_spent_them(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The link M6-F8 broke: the pool passes the request's cycle id through."""
    pool = await _pool(session, registry, contract)
    await pool.dispatch(
        identity=RuntimeIdentity.for_testing(contract.business_id),
        request=_request(1, "cyc_one"),
    )
    rows = list((await session.scalars(select(BudgetLedgerRow))).all())
    assert [r.cycle_id for r in rows] == ["cyc_one"]


async def test_a_cycle_that_reaches_its_ceiling_is_refused(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §2.1 via D-003 tier 2, end to end through the pool.

    The contract allows $0.50 an invocation against a $1.00 cycle ceiling, so the
    third invocation of one cycle is refused before it spends anything — the
    pre-flight refusal D-003 requires, not a post-hoc alarm.
    """
    pool = await _pool(session, registry, contract)
    identity = RuntimeIdentity.for_testing(contract.business_id)
    for n in (1, 2):
        await pool.dispatch(identity=identity, request=_request(n, "cyc_one"))

    with pytest.raises(BudgetExceededError) as caught:
        await pool.dispatch(identity=identity, request=_request(3, "cyc_one"))
    assert caught.value.scope == "wake_cycle"
    assert not contains_technical_language(caught.value.operator_message)


async def test_the_ceiling_is_per_cycle_not_per_business(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Negative control: the next cycle starts with full headroom.

    Without this the test above would also pass for a ceiling implemented as a
    lifetime cap, which would quietly retire every business at $1.00.
    """
    pool = await _pool(session, registry, contract)
    identity = RuntimeIdentity.for_testing(contract.business_id)
    for n in (1, 2):
        await pool.dispatch(identity=identity, request=_request(n, "cyc_one"))
    result = await pool.dispatch(identity=identity, request=_request(3, "cyc_two"))
    assert result.status is InvocationStatus.SUCCEEDED


# ── Part 2: a cycle that fails is recorded, not fatal ──────────────────────

CYCLE_ID = "cyc_test"


def _ctx(**over: object) -> CycleContext:
    base: dict[str, object] = {
        "business_id": BIZ,
        "display_name": "Affiliate Co",
        "dispatchable": True,
        "max_cycles_per_day": 48,
        "wake_cycle_ceiling_usd": Decimal("1.00"),
        "day_ordinal": 1000,
    }
    base.update(over)
    return CycleContext(**base)  # type: ignore[arg-type]


def _plan_payload() -> dict[str, object]:
    return {
        "cycle_id": CYCLE_ID,
        "plan": TacticalPlan(rationale="Its usual round.").model_dump(mode="json"),
        "requests": [_request(1, CYCLE_ID).model_dump(mode="json")],
    }


def _dispatch_payload() -> dict[str, object]:
    return CapabilityResult(
        invocation_id=InvocationId("inv_1"),
        business_id=BIZ,
        capability=CapabilityType.RESEARCH,
        status=InvocationStatus.SUCCEEDED,
        output="done",
        usage=Usage(cost_usd=Decimal("0.20")),
        attempts=1,
    ).model_dump(mode="json")


def _exhausted(error_type: str = "CapabilityExecutionError") -> ActivityError:
    """Build the failure a workflow sees once an activity's retries are spent.

    Shaped the way Temporal delivers it — an `ActivityError` whose cause is a
    serialised `ApplicationError` carrying only the original class *name*. The
    workflow never receives the exception object itself, which is precisely why
    `_refused_by_a_ceiling` matches on the name.
    """
    failure = ActivityError(
        "activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="dispatch_capability",
        activity_id="1",
        retry_state=None,
    )
    failure.__cause__ = ApplicationError("the detail an operator never sees", type=error_type)
    return failure


class _ScriptedActivities:
    """Stand-in for the activity boundary, recording what the workflow asked for."""

    def __init__(self, **scripted: object) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._scripted: dict[str, object] = {
            "plan_cycle": _plan_payload(),
            "dispatch_capability": _dispatch_payload(),
            "synthesize_results": {"summary": "Looked at what's selling.", "action": None},
            "request_approval": "apr_1",
            "record_cycle_decision": "dec_1",
        }
        self._scripted.update(scripted)

    async def execute_activity(self, name: str, arg: object = None, **kwargs: object) -> Any:
        assert "start_to_close_timeout" in kwargs, "spec §9: every call is bounded"
        self.calls.append((name, arg))
        outcome = self._scripted[name]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def payload(self, name: str) -> Any:
        """Return the argument of the last call to ``name``."""
        return next(arg for called, arg in reversed(self.calls) if called == name)

    def called(self, name: str) -> bool:
        return any(called == name for called, _ in self.calls)


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Return a driver that runs one cycle against a scripted activity boundary."""

    async def _run(**scripted: object) -> tuple[ManagerState, _ScriptedActivities, Any]:
        activities = _ScriptedActivities(**scripted)
        monkeypatch.setattr(workflow_module, "workflow", activities)
        manager = BusinessManagerWorkflow()
        state = await manager._run_cycle(ManagerState(business_id=BIZ), _ctx(), ["scheduled"])
        return state, activities, manager.last_cycle()

    return _run


async def test_a_healthy_cycle_still_completes(drive: Callable[..., Any]) -> None:
    """Negative control. A failure path that also catches success is not a fix."""
    state, activities, cycle = await drive()
    assert cycle.outcome is CycleOutcome.COMPLETED
    assert state.cycles_completed == 1
    assert activities.payload("record_cycle_decision")["outcome"] == "completed"


async def test_exhausted_activity_ends_the_cycle_instead_of_the_manager(
    drive: Callable[..., Any],
) -> None:
    """M6-F9. Observed live as `WORKFLOW_EXECUTION_FAILED`: one activity gave up
    and the business was left with no Manager at all, which is exactly the
    indefinite pending state §9 says must surface instead."""
    state, activities, cycle = await drive(dispatch_capability=_exhausted())
    assert cycle.outcome is CycleOutcome.FAILED
    assert activities.payload("record_cycle_decision")["outcome"] == "failed"
    assert state.cycles_completed == 1, "a failed cycle is still a cycle that happened"


async def test_a_failed_cycle_explains_itself_in_the_operators_language(
    drive: Callable[..., Any],
) -> None:
    """Spec §12.5: the entry reaches the activity feed, so it says what it means
    for the company — never that a workflow, worker, or retry gave up."""
    _, activities, cycle = await drive(dispatch_capability=_exhausted())
    entry = activities.payload("record_cycle_decision")
    assert not contains_technical_language(entry["summary"])
    assert not contains_technical_language(entry["rationale"])
    assert "Affiliate Co" in cycle.summary


async def test_a_failed_cycle_is_filed_under_its_cycle_id(
    drive: Callable[..., Any],
) -> None:
    """The failure belongs to the cycle whose ledger rows and results it shares."""
    _, activities, _ = await drive(dispatch_capability=_exhausted())
    assert activities.payload("record_cycle_decision")["cycle_id"] == CYCLE_ID


async def test_a_ceiling_refusal_reads_as_budget_not_breakage(
    drive: Callable[..., Any],
) -> None:
    """D-003 rule 5: a refused reservation stopped the cycle before it spent.

    "This company stopped to stay inside its limit" and "this company broke" are
    different facts, and only one of them should send an operator looking for a
    fault.
    """
    _, activities, cycle = await drive(
        dispatch_capability=_exhausted("BudgetExceededError"),
    )
    assert cycle.outcome is CycleOutcome.BUDGET_EXHAUSTED
    entry = activities.payload("record_cycle_decision")
    assert entry["outcome"] == "budget_exhausted"
    assert not contains_technical_language(entry["summary"])
    assert "spending limit" in entry["summary"]


async def test_a_platform_halt_also_reads_as_budget(drive: Callable[..., Any]) -> None:
    """`CircuitBreakerOpenError` subclasses `BudgetExceededError` in the kernel
    taxonomy; the cycle stopped on money either way (spec §9)."""
    _, _, cycle = await drive(dispatch_capability=_exhausted("CircuitBreakerOpenError"))
    assert cycle.outcome is CycleOutcome.BUDGET_EXHAUSTED


async def test_a_failure_before_planning_returns_still_records(
    drive: Callable[..., Any],
) -> None:
    """D-021 puts the start of a cycle at the start of planning, so a cycle can
    fail before it has an id. It must still leave the operator an explanation."""
    state, activities, cycle = await drive(plan_cycle=_exhausted())
    assert cycle.outcome is CycleOutcome.FAILED
    assert activities.payload("record_cycle_decision")["cycle_id"] == ""
    assert not activities.called("dispatch_capability")
    assert state.cycles_completed == 1


async def test_synthesis_failure_does_not_take_the_manager_down(
    drive: Callable[..., Any],
) -> None:
    """Every activity in the cycle is covered, not only dispatch."""
    _, _, cycle = await drive(synthesize_results=_exhausted())
    assert cycle.outcome is CycleOutcome.FAILED


async def test_the_manager_survives_even_a_failed_log_write(
    drive: Callable[..., Any],
) -> None:
    """Worst case: the cycle failed *and* the entry explaining it cannot be
    written. The Manager still returns to its wake loop — a business with a
    living Manager and a missing log line can recover; one whose Manager died
    cannot tell anybody anything."""
    state, _, cycle = await drive(
        dispatch_capability=_exhausted(), record_cycle_decision=_exhausted()
    )
    assert cycle.outcome is CycleOutcome.FAILED
    assert state.cycles_completed == 1


async def test_the_cycle_id_reaches_synthesis(drive: Callable[..., Any]) -> None:
    """D-021: dispatch, synthesis, and the decision record all carry it."""
    _, activities, _ = await drive()
    assert activities.payload("synthesize_results").cycle_id == CYCLE_ID
    assert activities.payload("dispatch_capability").cycle_id == CYCLE_ID
    assert activities.payload("record_cycle_decision")["cycle_id"] == CYCLE_ID


async def test_a_history_without_a_cycle_id_still_runs(drive: Callable[..., Any]) -> None:
    """Replay compatibility (spec §11): a `plan_cycle` result captured before
    D-021 has no cycle id, and the cycle must complete rather than raise."""
    legacy = _plan_payload()
    del legacy["cycle_id"]
    _, activities, cycle = await drive(plan_cycle=legacy)
    assert cycle.outcome is CycleOutcome.COMPLETED
    assert activities.payload("synthesize_results").cycle_id is None
