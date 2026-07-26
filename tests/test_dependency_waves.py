"""Dependent dispatches within one wake cycle (D-023; spec §2.1, §2.2, §11).

M6-F24: every dispatch in a cycle was independent, so Compliance never saw
Content's draft and the Affiliate type's only declared action —
`affiliate.publish_post` — was legitimately unreachable. D-023 lets a plan
declare that one invocation consumes another's results, and the Manager
dispatches in dependency waves.

Four properties are load-bearing and each is tested here rather than reasoned
about:

1. **Order and parallelism together.** Waves run in sequence; everything inside
   a wave still goes out in one batch. M4-F1 was a silently serialised dispatch
   that passed every functional test, and wave dispatch is exactly the change
   that could reintroduce it — so parallelism is observed (two dispatches in
   flight at once), not inferred from the source.
2. **Nothing changes for a plan without dependencies.** That is what keeps the
   captured history in `test_manager_replay.py` replayable (spec §11): one wave,
   one batch, no extra activity call.
3. **A dependency that did not succeed stops its dependent** and synthesis is
   told why (D-023 point 4). Dispatching a review with a hole where the draft
   should be is worse than not dispatching it.
4. **The graph is validated platform-side** (D-013). Dangling refs, self-
   references, loops, and over-deep chains are recorded and dropped — never
   repaired into whatever the model probably meant.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.ledger import BudgetLedger
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates
from jarvis.capabilities.request import (
    PRIOR_RESULTS_KEY,
    CapabilityResult,
    InvocationStatus,
    ScopedRequest,
)
from jarvis.domain.contract import (
    BudgetPolicy,
    BusinessContract,
    CapabilityPermission,
    CapabilityType,
    WakeConditions,
)
from jarvis.kernel.ids import BusinessId, BusinessTypeName, InvocationId
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager import workflow as workflow_module
from jarvis.manager.activities import (
    DEPENDENCY_BLOCKED,
    DEPENDENCY_CYCLE,
    DEPENDENCY_SELF_REFERENCE,
    DEPENDENCY_TOO_DEEP,
    DEPENDENCY_UNKNOWN_REF,
    MAX_GRANTED_RESULT_CHARS,
    ManagerActivities,
    _dependency_graph,
)
from jarvis.manager.state import CycleOutcome, ManagerState, TacticalPlan
from jarvis.manager.types import (
    CycleContext,
    DependentContextRequest,
    DispatchSequence,
    PlanRequest,
    PriorResultGrant,
)
from jarvis.manager.workflow import DEPENDENCY_SKIP_REASON, BusinessManagerWorkflow
from jarvis.persistence.models import AuditLogRow
from tests.conftest import as_business

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")
OTHER_BIZ = BusinessId("biz_fedcba9876543210fedcba9876543210")
CYCLE_ID = "cyc_waves"


# ── the graph validator, in isolation ──────────────────────────────────────


def test_a_plan_with_no_declarations_is_one_wave() -> None:
    """The pre-D-023 shape, and the one every captured history recorded."""
    graph = _dependency_graph([("a", ()), ("b", ()), ("c", ())])
    assert graph.layers == ((0, 1, 2),)
    assert graph.rejected == {}


def test_a_chain_becomes_one_wave_per_link() -> None:
    """The Affiliate flow D-023 was written for: research -> content -> review."""
    graph = _dependency_graph(
        [("research", ()), ("content", ("research",)), ("review", ("content",))]
    )
    assert graph.layers == ((0,), (1,), (2,))
    assert graph.edges[2] == (1,)


def test_independent_work_still_shares_a_wave_with_a_dependency_present() -> None:
    """A declared dependency must not serialise the items that declared none."""
    graph = _dependency_graph([("research", ()), ("prices", ()), ("content", ("research",))])
    assert graph.layers == ((0, 1), (2,))


def test_declarations_are_matched_in_any_order() -> None:
    """A reviewer listed before the draft it reviews is a valid graph, badly
    ordered. Reading it is not guessing; refusing it would be pedantry."""
    graph = _dependency_graph([("review", ("content",)), ("content", ())])
    assert graph.layers == ((1,), (0,))


def test_a_dangling_reference_drops_the_item_that_declared_it() -> None:
    """D-023's platform-side validation: refs must name real invocations."""
    graph = _dependency_graph([("content", ("research",))])
    assert graph.rejected == {0: DEPENDENCY_UNKNOWN_REF}
    assert graph.layers == ()


def test_an_ambiguous_reference_names_nothing() -> None:
    """Two items sharing a ref make that name unusable, not arbitrary.

    Picking the first match would be the platform guessing which of two research
    steps a draft was supposed to read.
    """
    graph = _dependency_graph([("research", ()), ("research", ()), ("content", ("research",))])
    assert graph.rejected == {2: DEPENDENCY_UNKNOWN_REF}
    assert graph.layers == ((0, 1),), "the ambiguous items themselves still run"


def test_an_item_cannot_depend_on_itself() -> None:
    graph = _dependency_graph([("content", ("content",))])
    assert graph.rejected == {0: DEPENDENCY_SELF_REFERENCE}


def test_a_loop_is_detected_and_both_items_are_dropped() -> None:
    """Dispatching either would wait on a result the other cannot produce."""
    graph = _dependency_graph([("a", ("b",)), ("b", ("a",))])
    assert graph.rejected == {0: DEPENDENCY_CYCLE, 1: DEPENDENCY_CYCLE}
    assert graph.layers == ()


def test_depending_on_a_dropped_item_is_itself_dropped() -> None:
    """The cascade. Otherwise a review runs with a hole where its input was."""
    graph = _dependency_graph([("content", ("nowhere",)), ("review", ("content",))])
    assert graph.rejected == {0: DEPENDENCY_UNKNOWN_REF, 1: DEPENDENCY_BLOCKED}


def test_a_chain_deeper_than_the_bound_is_refused_not_flattened() -> None:
    """The stated bound is three waves; a fourth link is dropped and recorded."""
    graph = _dependency_graph(
        [("a", ()), ("b", ("a",)), ("c", ("b",)), ("d", ("c",))],
    )
    assert graph.layers == ((0,), (1,), (2,))
    assert graph.rejected == {3: DEPENDENCY_TOO_DEEP}


# ── planning: the model proposes, the platform validates ───────────────────


def _contract() -> BusinessContract:
    """A contract permitting the three capabilities the Affiliate flow chains."""
    return BusinessContract(
        business_id=BIZ,
        business_type=BusinessTypeName("affiliate"),
        display_name="Affiliate Co",
        budget=BudgetPolicy(
            business_cap_usd=Decimal("50.00"), wake_cycle_ceiling_usd=Decimal("5.00")
        ),
        wake_conditions=WakeConditions(schedule_cron="0 9 * * *"),
        capability_permissions=(
            CapabilityPermission(capability=CapabilityType.RESEARCH, memory_read=True),
            CapabilityPermission(capability=CapabilityType.CONTENT, memory_read=True),
            CapabilityPermission(capability=CapabilityType.COMPLIANCE),
        ),
    )


class _StubProvider:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        return CompletionResponse(text=self._reply, usage=Usage(input_tokens=10, output_tokens=10))

    async def aclose(self) -> None:
        return None


class _StubKernel:
    def __init__(self, provider: object, session: AsyncSession, **services: object) -> None:
        self._provider = provider
        self._session = session
        self._services = services
        self.settings = SimpleNamespace(
            budget=SimpleNamespace(reasoning_token_price_per_million_usd=Decimal("50.00"))
        )

    @property
    def llm(self) -> Any:
        return self._provider

    def build_ledger(self, services: object) -> BudgetLedger:
        return BudgetLedger(self._session, platform_ceiling_usd=Decimal("500.00"))

    @asynccontextmanager
    async def services(self) -> AsyncIterator[Any]:
        yield SimpleNamespace(**self._services)


class _StubRegistry:
    def __init__(self, contract: BusinessContract) -> None:
        self._contract = contract

    async def get_contract(self, business_id: BusinessId) -> BusinessContract:
        return self._contract


def _activities(session: AsyncSession, reply: str) -> ManagerActivities:
    from jarvis.observability.audit import AuditLog

    return ManagerActivities(
        _StubKernel(  # type: ignore[arg-type]
            _StubProvider(reply),
            session,
            registry=_StubRegistry(_contract()),
            audit=AuditLog(session),
        )
    )


def _plan_reply(items: list[dict[str, object]]) -> str:
    return json.dumps({"rationale": "Publish today's post.", "items": items})


async def test_plan_cycle_lays_the_affiliate_chain_out_in_waves(session: AsyncSession) -> None:
    """D-023 point 2, at its source: the plan carries the order, not the workflow."""
    activities = _activities(
        session,
        _plan_reply(
            [
                {"ref": "r", "intent": "find topics", "capability": "research"},
                {"ref": "c", "intent": "draft it", "capability": "content", "depends_on": ["r"]},
                {
                    "ref": "k",
                    "intent": "review it",
                    "capability": "compliance",
                    "depends_on": ["c"],
                },
            ]
        ),
    )
    payload = await as_business(BIZ, activities.plan_cycle, PlanRequest(business_id=BIZ))

    sequence = DispatchSequence.model_validate(payload["dispatch"])
    requests = [ScopedRequest.model_validate(r) for r in payload["requests"]]  # type: ignore[union-attr]
    ids = [r.invocation_id for r in requests]

    assert sequence.waves == ((ids[0],), (ids[1],), (ids[2],))
    assert sequence.grants[ids[1]] == (PriorResultGrant(ref="r", invocation_id=ids[0]),)
    assert sequence.refs[ids[2]] == "k"

    plan = TacticalPlan.model_validate(payload["plan"])
    assert [item.depends_on for item in plan.items] == [(), ("r",), ("c",)]


async def test_a_plan_without_declarations_stays_one_wave(session: AsyncSession) -> None:
    """Spec §11: the shape every captured history recorded must be reachable."""
    activities = _activities(
        session,
        _plan_reply(
            [
                {"ref": "a", "intent": "look at demand", "capability": "research"},
                {"ref": "b", "intent": "draft something", "capability": "content"},
            ]
        ),
    )
    payload = await as_business(BIZ, activities.plan_cycle, PlanRequest(business_id=BIZ))
    sequence = DispatchSequence.model_validate(payload["dispatch"])
    assert len(sequence.waves) == 1
    assert sequence.grants == {}


async def test_a_bad_declaration_is_recorded_and_the_item_dropped(session: AsyncSession) -> None:
    """ "Recorded, skipped, never guessed at" — the same degradation an
    unpermitted capability name already produces, with an audit trail."""
    activities = _activities(
        session,
        _plan_reply(
            [
                {"ref": "r", "intent": "find topics", "capability": "research"},
                {
                    "ref": "c",
                    "intent": "draft it",
                    "capability": "content",
                    "depends_on": ["nothing-like-this"],
                },
            ]
        ),
    )
    payload = await as_business(BIZ, activities.plan_cycle, PlanRequest(business_id=BIZ))

    requests = [ScopedRequest.model_validate(r) for r in payload["requests"]]  # type: ignore[union-attr]
    assert [r.capability for r in requests] == [CapabilityType.RESEARCH]

    rows = list((await session.scalars(select(AuditLogRow))).all())
    rejections = [r for r in rows if r.event_type == "plan.dependency_rejected"]
    assert len(rejections) == 1
    assert rejections[0].payload["reason"] == DEPENDENCY_UNKNOWN_REF
    assert rejections[0].payload["ref"] == "c"


async def test_items_without_a_ref_get_distinct_ones(session: AsyncSession) -> None:
    """Two research items previously shared the ref `research`, which would make
    any dependency naming it ambiguous by construction."""
    activities = _activities(
        session,
        _plan_reply(
            [
                {"intent": "demand", "capability": "research"},
                {"intent": "rivals", "capability": "research"},
            ]
        ),
    )
    payload = await as_business(BIZ, activities.plan_cycle, PlanRequest(business_id=BIZ))
    plan = TacticalPlan.model_validate(payload["plan"])
    assert len({item.ref for item in plan.items}) == 2


# ── threading the results: the activity that composes the grant ────────────


def _result(invocation_id: str, output: str, *, business_id: BusinessId = BIZ) -> CapabilityResult:
    return CapabilityResult(
        invocation_id=InvocationId(invocation_id),
        business_id=business_id,
        capability=CapabilityType.RESEARCH,
        status=InvocationStatus.SUCCEEDED,
        output=output,
    )


def _scoped(invocation_id: str, capability: CapabilityType) -> ScopedRequest:
    return ScopedRequest(
        invocation_id=InvocationId(invocation_id),
        declared_business_id=BIZ,
        capability=capability,
        prompt_ref="affiliate.content",
        prompt_inputs={"intent": "draft it"},
        budget_allocation_usd=Decimal("0.40"),
        cycle_id=CYCLE_ID,
    )


async def test_a_dependent_receives_the_named_prior_result(session: AsyncSession) -> None:
    """D-023 point 3: the result arrives in the dependent's scoped context, under
    the name the plan gave it — not fetched by the capability itself (§2)."""
    activities = _activities(session, "{}")
    prepared = await as_business(
        BIZ,
        activities.prepare_dependent_requests,
        DependentContextRequest(
            business_id=BIZ,
            cycle_id=CYCLE_ID,
            requests=(_scoped("inv_c", CapabilityType.CONTENT),),
            grants={"inv_c": (PriorResultGrant(ref="r", invocation_id="inv_r"),)},
            prior_results=(_result("inv_r", "three good topics"),),
        ),
    )
    request = ScopedRequest.model_validate(prepared["requests"][0])  # type: ignore[index]
    assert request.prompt_inputs["intent"] == "draft it", "the original context survives"
    assert request.prompt_inputs[PRIOR_RESULTS_KEY] == [
        {"ref": "r", "capability": "research", "output": "three good topics"}
    ]

    rows = list((await session.scalars(select(AuditLogRow))).all())
    assert [r.event_type for r in rows] == ["capability.context_granted"]


async def test_a_result_from_another_business_is_never_threaded(session: AsyncSession) -> None:
    """Spec §10. The workflow assembled this payload; an activity that trusted
    the assembly would rest isolation on the caller being right."""
    activities = _activities(session, "{}")
    prepared = await as_business(
        BIZ,
        activities.prepare_dependent_requests,
        DependentContextRequest(
            business_id=BIZ,
            cycle_id=CYCLE_ID,
            requests=(_scoped("inv_c", CapabilityType.CONTENT),),
            grants={"inv_c": (PriorResultGrant(ref="r", invocation_id="inv_r"),)},
            prior_results=(_result("inv_r", "someone else's work", business_id=OTHER_BIZ),),
        ),
    )
    request = ScopedRequest.model_validate(prepared["requests"][0])  # type: ignore[index]
    assert PRIOR_RESULTS_KEY not in request.prompt_inputs

    rows = list((await session.scalars(select(AuditLogRow))).all())
    assert [r.event_type for r in rows] == ["capability.context_grant_refused"]


async def test_a_granted_result_is_truncated(session: AsyncSession) -> None:
    """M6-F15: there is no input ceiling, so the thread carries its own bound."""
    activities = _activities(session, "{}")
    prepared = await as_business(
        BIZ,
        activities.prepare_dependent_requests,
        DependentContextRequest(
            business_id=BIZ,
            requests=(_scoped("inv_c", CapabilityType.CONTENT),),
            grants={"inv_c": (PriorResultGrant(ref="r", invocation_id="inv_r"),)},
            prior_results=(_result("inv_r", "x" * (MAX_GRANTED_RESULT_CHARS + 500)),),
        ),
    )
    request = ScopedRequest.model_validate(prepared["requests"][0])  # type: ignore[index]
    assert len(request.prompt_inputs[PRIOR_RESULTS_KEY][0]["output"]) == MAX_GRANTED_RESULT_CHARS


async def test_the_capability_sees_the_grant_as_its_own_labelled_section() -> None:
    """§2.2: a capability sees what the request granted it, visibly. Spliced into
    the template it could not tell the draft from its instructions."""
    captured: list[Any] = []

    class _Recorder:
        @property
        def name(self) -> str:
            return "stub"

        async def complete(self, request: object) -> CompletionResponse:
            captured.append(request)
            return CompletionResponse(text="ok", usage=Usage())

        async def aclose(self) -> None:
            return None

    executor = CapabilityExecutor(
        _Recorder(),  # type: ignore[arg-type]
        InMemoryTemplates({"affiliate.content": "Draft a post. Intent: {intent}"}),
    )
    request = _scoped("inv_c", CapabilityType.CONTENT)
    request = request.model_copy(
        update={
            "prompt_inputs": {
                **request.prompt_inputs,
                PRIOR_RESULTS_KEY: [
                    {"ref": "r", "capability": "research", "output": "three good topics"}
                ],
            }
        }
    )
    await executor.execute(request=request, contract=_contract())

    content = captured[0].messages[0].content
    assert "Draft a post. Intent: draft it" in content
    assert "three good topics" in content
    assert content.index("Draft a post") < content.index("three good topics")


# ── the workflow: waves in order, parallel within a wave ───────────────────


def _ctx() -> CycleContext:
    return CycleContext(
        business_id=BIZ,
        display_name="Affiliate Co",
        dispatchable=True,
        max_cycles_per_day=48,
        wake_cycle_ceiling_usd=Decimal("5.00"),
        day_ordinal=1000,
    )


def _dispatch_result(invocation_id: str, status: InvocationStatus) -> dict[str, object]:
    return CapabilityResult(
        invocation_id=InvocationId(invocation_id),
        business_id=BIZ,
        capability=CapabilityType.RESEARCH,
        status=status,
        output=f"{invocation_id} output",
        usage=Usage(cost_usd=Decimal("0.10")),
        operator_summary="It couldn't finish that step.",
    ).model_dump(mode="json")


class _Boundary:
    """Scripted activity boundary that also observes concurrency.

    `max_in_flight` is what makes the M4-F1 guard hold *per wave*: dispatches
    awaited one at a time never reach two.
    """

    def __init__(self, plan_payload: dict[str, object], statuses: dict[str, InvocationStatus]):
        self.calls: list[tuple[str, Any]] = []
        self.max_in_flight = 0
        self._in_flight = 0
        self._plan = plan_payload
        self._statuses = statuses

    async def execute_activity(self, name: str, arg: object = None, **kwargs: object) -> Any:
        assert "start_to_close_timeout" in kwargs, "spec §9: every call is bounded"
        self.calls.append((name, arg))
        if name == "load_cycle_context":
            return _ctx().model_dump(mode="json")
        if name == "plan_cycle":
            return self._plan
        if name == "prepare_dependent_requests":
            assert isinstance(arg, DependentContextRequest)
            return {"requests": [r.model_dump(mode="json") for r in arg.requests]}
        if name == "dispatch_capability":
            assert isinstance(arg, ScopedRequest)
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self._in_flight -= 1
            return _dispatch_result(arg.invocation_id, self._statuses[arg.invocation_id])
        if name == "synthesize_results":
            return {"summary": "Looked at what's selling.", "action": None}
        return "dec_1"

    def names(self, name: str) -> list[Any]:
        return [arg for called, arg in self.calls if called == name]

    def order(self) -> list[str]:
        return [called for called, _ in self.calls]


def _plan_payload(sequence: DispatchSequence, requests: list[ScopedRequest]) -> dict[str, object]:
    return {
        "cycle_id": CYCLE_ID,
        "plan": TacticalPlan(rationale="Publish today's post.").model_dump(mode="json"),
        "requests": [r.model_dump(mode="json") for r in requests],
        "dispatch": sequence.model_dump(mode="json"),
    }


@pytest.fixture
def run_cycle(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Run one cycle against a scripted boundary and return what it did."""

    async def _run(
        payload: dict[str, object], statuses: dict[str, InvocationStatus]
    ) -> tuple[_Boundary, Any]:
        boundary = _Boundary(payload, statuses)
        monkeypatch.setattr(workflow_module, "workflow", boundary)
        manager = BusinessManagerWorkflow()
        await manager._run_cycle(ManagerState(business_id=BIZ), _ctx(), ["scheduled"])
        return boundary, manager.last_cycle()

    return _run


def _two_then_one() -> tuple[dict[str, object], list[ScopedRequest]]:
    """Two independent steps, then one that consumes both."""
    requests = [
        _scoped("inv_r1", CapabilityType.RESEARCH),
        _scoped("inv_r2", CapabilityType.RESEARCH),
        _scoped("inv_c", CapabilityType.CONTENT),
    ]
    sequence = DispatchSequence(
        waves=(("inv_r1", "inv_r2"), ("inv_c",)),
        grants={
            "inv_c": (
                PriorResultGrant(ref="r1", invocation_id="inv_r1"),
                PriorResultGrant(ref="r2", invocation_id="inv_r2"),
            )
        },
        refs={"inv_r1": "r1", "inv_r2": "r2", "inv_c": "c"},
    )
    return _plan_payload(sequence, requests), requests


async def test_waves_run_in_order_and_in_parallel_within_a_wave(
    run_cycle: Callable[..., Any],
) -> None:
    """D-023 point 2 and the M4-F1 guard, in one assertion each.

    The first wave's two dispatches are in flight together; the dependent goes
    out only afterwards. Serial dispatch would satisfy the ordering claim and
    fail the parallelism one, which is why both are here.
    """
    payload, _ = _two_then_one()
    boundary, cycle = await run_cycle(
        payload, dict.fromkeys(("inv_r1", "inv_r2", "inv_c"), InvocationStatus.SUCCEEDED)
    )

    dispatched = [r.invocation_id for r in boundary.names("dispatch_capability")]
    assert dispatched == ["inv_r1", "inv_r2", "inv_c"]
    assert boundary.max_in_flight == 2, "the first wave was serialised (M4-F1 shape)"
    assert cycle.outcome is CycleOutcome.COMPLETED
    assert len(cycle.results) == 3


async def test_the_dependent_is_dispatched_with_its_grants_attached(
    run_cycle: Callable[..., Any],
) -> None:
    """The grant is composed by an activity, between the waves that need it."""
    payload, _ = _two_then_one()
    boundary, _ = await run_cycle(
        payload, dict.fromkeys(("inv_r1", "inv_r2", "inv_c"), InvocationStatus.SUCCEEDED)
    )

    order = boundary.order()
    assert order.index("prepare_dependent_requests") > order.index("dispatch_capability")
    assert order.index("prepare_dependent_requests") < order.index("synthesize_results")

    prepared = boundary.names("prepare_dependent_requests")[0]
    assert [r.invocation_id for r in prepared.requests] == ["inv_c"]
    assert {r.invocation_id for r in prepared.prior_results} == {"inv_r1", "inv_r2"}
    assert prepared.cycle_id == CYCLE_ID


@pytest.mark.parametrize("status", [InvocationStatus.FAILED, InvocationStatus.DEAD_LETTERED])
async def test_a_dependency_that_did_not_succeed_stops_its_dependent(
    run_cycle: Callable[..., Any], status: InvocationStatus
) -> None:
    """D-023 point 4. Not an absence — a decision, recorded, with its reason.

    Both non-SUCCEEDED terminal states count (D-001): a dead-lettered invocation
    returns a result, and that result is still not a draft.
    """
    payload, _ = _two_then_one()
    boundary, cycle = await run_cycle(
        payload,
        {"inv_r1": status, "inv_r2": InvocationStatus.SUCCEEDED, "inv_c": status},
    )

    dispatched = [r.invocation_id for r in boundary.names("dispatch_capability")]
    assert "inv_c" not in dispatched
    assert not boundary.names("prepare_dependent_requests")

    assert [s.invocation_id for s in cycle.skipped] == ["inv_c"]
    assert cycle.skipped[0].blocked_by == ("r1",)
    assert cycle.skipped[0].ref == "c"


async def test_synthesis_is_told_what_was_not_started(run_cycle: Callable[..., Any]) -> None:
    """ "Synthesis sees why" (D-023 point 4). Otherwise the owner's account of the
    day describes a cycle that quietly did less than it planned."""
    payload, _ = _two_then_one()
    boundary, _ = await run_cycle(
        payload,
        {
            "inv_r1": InvocationStatus.FAILED,
            "inv_r2": InvocationStatus.SUCCEEDED,
            "inv_c": InvocationStatus.SUCCEEDED,
        },
    )
    synthesis = boundary.names("synthesize_results")[0]
    assert [s.ref for s in synthesis.skipped] == ["c"]
    assert synthesis.skipped[0].reason == DEPENDENCY_SKIP_REASON


async def test_a_skip_cascades_down_the_chain(run_cycle: Callable[..., Any]) -> None:
    """Nothing downstream of a step that never ran can run either."""
    requests = [
        _scoped("inv_r", CapabilityType.RESEARCH),
        _scoped("inv_c", CapabilityType.CONTENT),
        _scoped("inv_k", CapabilityType.COMPLIANCE),
    ]
    sequence = DispatchSequence(
        waves=(("inv_r",), ("inv_c",), ("inv_k",)),
        grants={
            "inv_c": (PriorResultGrant(ref="r", invocation_id="inv_r"),),
            "inv_k": (PriorResultGrant(ref="c", invocation_id="inv_c"),),
        },
        refs={"inv_r": "r", "inv_c": "c", "inv_k": "k"},
    )
    boundary, cycle = await run_cycle(
        _plan_payload(sequence, requests),
        {
            "inv_r": InvocationStatus.FAILED,
            "inv_c": InvocationStatus.SUCCEEDED,
            "inv_k": InvocationStatus.SUCCEEDED,
        },
    )
    assert [r.invocation_id for r in boundary.names("dispatch_capability")] == ["inv_r"]
    assert [s.ref for s in cycle.skipped] == ["c", "k"]


# ── the compatibility hinge ────────────────────────────────────────────────


async def test_a_cycle_with_no_dependencies_issues_the_commands_it_always_did(
    run_cycle: Callable[..., Any],
) -> None:
    """Spec §11, and the reason the committed replay fixture stays valid.

    One batch of dispatches, no context-threading call, and the same activity
    sequence a pre-D-023 history recorded.
    """
    requests = [
        _scoped("inv_a", CapabilityType.RESEARCH),
        _scoped("inv_b", CapabilityType.CONTENT),
    ]
    sequence = DispatchSequence(waves=(("inv_a", "inv_b"),), refs={"inv_a": "a", "inv_b": "b"})
    boundary, cycle = await run_cycle(
        _plan_payload(sequence, requests),
        dict.fromkeys(("inv_a", "inv_b"), InvocationStatus.SUCCEEDED),
    )

    assert boundary.order() == [
        "plan_cycle",
        "dispatch_capability",
        "dispatch_capability",
        "synthesize_results",
        "record_cycle_decision",
    ]
    assert boundary.max_in_flight == 2
    assert cycle.skipped == ()


async def test_a_plan_result_from_before_d023_still_runs(run_cycle: Callable[..., Any]) -> None:
    """A history captured before the dispatch sequence existed carries no such
    key, and replaying it must behave exactly as it did then (spec §11)."""
    requests = [
        _scoped("inv_a", CapabilityType.RESEARCH),
        _scoped("inv_b", CapabilityType.CONTENT),
    ]
    legacy = _plan_payload(DispatchSequence(), requests)
    del legacy["dispatch"]

    boundary, cycle = await run_cycle(
        legacy, dict.fromkeys(("inv_a", "inv_b"), InvocationStatus.SUCCEEDED)
    )
    assert cycle.outcome is CycleOutcome.COMPLETED
    assert [r.invocation_id for r in boundary.names("dispatch_capability")] == ["inv_a", "inv_b"]
    assert not boundary.names("prepare_dependent_requests")
