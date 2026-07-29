"""The approval round trip (spec §8; D-006, D-011, D-013).

M6-2's proof obligation: a cycle that needs a human *pauses*, the human sees the
four facts §8 requires, answers, and the Manager starts a new cycle on that
answer. Every layer of that path existed and was unit-tested in isolation before
this file; nothing had ever followed one approval from a Manager's proposal to
the signal that resumes it.

Three defects are pinned here, all of them found by walking that path:

- **M6-F11** (this milestone's assignment): the live model authored a prose
  `action_type`, the platform namespaced it, and it became an approvable action
  in front of an operator. A-003's identity is a stable dotted identifier and
  three mechanisms key on it, so a sentence there is not an action — D-013 makes
  validating that the platform's job, not the model's.
- **M6-F20**: the operator API built its own `ApprovalService` without an event
  bus, so approving published nothing and D-006's loop was open at the one place
  a human closes it. Kept closed structurally in `test_event_loop_closure.py`;
  the wake path itself is exercised here.
- The deny path: a refusal must reset the ladder *and* leave nothing runnable.

The Temporal client is a recording double. What is under test is what the
platform does with an operator's answer, which is decided before any server is
involved; replay against a real captured history stays in `test_manager_replay`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.approvals.models import ApprovalRequest, ApprovalState
from jarvis.approvals.rendering import (
    contains_technical_language,
    render_detail,
    render_request,
)
from jarvis.approvals.service import ApprovalError, ApprovalService
from jarvis.budget.ledger import BudgetLedger
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.capabilities.request import CapabilityResult, InvocationStatus, ScopedRequest
from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.events.types import APPROVAL_DECIDED
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import BusinessId, DecisionId, InvocationId
from jarvis.kernel.runtime import business_workflow_id
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager import workflow as workflow_module
from jarvis.manager.activities import ManagerActivities
from jarvis.manager.state import CycleOutcome, ManagerState, TacticalPlan
from jarvis.manager.types import CycleContext, SynthesisRequest
from jarvis.manager.workflow import BusinessManagerWorkflow
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import AuditLogRow, Base, EventRow
from jarvis.scheduler.service import Scheduler
from tests.conftest import as_business

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")

PROSE_ACTION_TYPE = "Hold publication and re-run compliance review"
"""The exact string the first live run produced (M6-F11). Namespaced by
`_namespaced` it became `affiliate.Hold publication and re-run compliance
review`, which reached the operator's queue as an approvable action."""


# ── doubles ────────────────────────────────────────────────────────────────


class _StubProvider:
    """Provider returning one canned reply. No live model is involved."""

    def __init__(self, reply: str = "{}") -> None:
        self._reply = reply
        self.calls = 0

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        self.calls += 1
        return CompletionResponse(text=self._reply, usage=Usage(input_tokens=80, output_tokens=40))

    async def aclose(self) -> None:
        return None


class _FakeHandle:
    def __init__(self, workflow_id: str, log: list[tuple[str, str, str]]) -> None:
        self._workflow_id = workflow_id
        self._log = log

    async def signal(self, name: str, arg: str, *, rpc_timeout: object = None) -> None:
        # rpc_timeout: M10-F34's bounded deadline on every signal call the
        # sweep makes (Settings.scheduler.sweep_rpc_timeout_seconds). Accepted
        # and ignored here — this double records what was signalled, not how
        # it was bounded.
        self._log.append((self._workflow_id, name, arg))


class _FakeTemporalClient:
    """Records the signals the scheduler sends, in place of a live server."""

    def __init__(self) -> None:
        self.signals: list[tuple[str, str, str]] = []

    def get_workflow_handle(self, workflow_id: str) -> _FakeHandle:
        return _FakeHandle(workflow_id, self.signals)


# ── a real Kernel over an in-memory database ───────────────────────────────


def _settings() -> Settings:
    """Return settings that read no environment and reach no provider.

    `_env_file=None` matters: the repository carries a real `.env`, and a test
    that picked it up would talk to a live provider on a stray code path.
    """
    return Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    """Yield a real Kernel backed by one shared in-memory database.

    `StaticPool` because the Kernel opens a session per unit of work and the
    default SQLite pool would hand each one its own empty database.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(_settings(), engine=engine, provider=_StubProvider())
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def company(kernel: PlatformKernel) -> BusinessId:
    """Create one affiliate company through the real provisioning path (§4)."""
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        return await provisioning.create_company(
            definition=AFFILIATE, display_name="Trailside Gear Reviews"
        )


async def _pending_approval(
    kernel: PlatformKernel,
    company: BusinessId,
    *,
    approval_id: str = "apr_round_trip",
    amount_usd: Decimal | None = None,
) -> str:
    """Raise one approval the way `request_approval` does, and return its id."""
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).request(
            request=ApprovalRequest(
                approval_id=approval_id,
                business_id=company,
                action_type="affiliate.publish_post",
                action_summary="publish the trail-shoe review",
                amount_usd=amount_usd,
                triggering_condition="The draft passed its checks this morning.",
                downside="A weak post could cost a few readers' trust.",
                # Title *and* body: since D-024.1 a publish payload carries the
                # bytes, and an effect with only a title is refused at the tool
                # boundary now (M6-F37). Without the body the credential
                # assertion below would pass while testing the empty-payload
                # refusal instead.
                parameters={"title": "Best trail shoes", "body": "The full review text."},
            ),
            contract=contract,
        )
    return approval_id


# ── Part 1: the cycle pauses rather than blocking (D-006) ──────────────────


def _ctx() -> CycleContext:
    return CycleContext(
        business_id=BIZ,
        display_name="Trailside Gear Reviews",
        dispatchable=True,
        max_cycles_per_day=48,
        wake_cycle_ceiling_usd=Decimal("2.00"),
        day_ordinal=1000,
    )


def _scoped_request() -> ScopedRequest:
    return ScopedRequest(
        invocation_id=InvocationId("inv_1"),
        declared_business_id=BIZ,
        capability=CapabilityType.COMPLIANCE,
        prompt_ref="affiliate.compliance",
        prompt_inputs={"intent": "check the draft"},
        budget_allocation_usd=Decimal("0.15"),
        cycle_id="cyc_1",
    )


def _dispatch_payload() -> dict[str, object]:
    return CapabilityResult(
        invocation_id=InvocationId("inv_1"),
        business_id=BIZ,
        capability=CapabilityType.COMPLIANCE,
        status=InvocationStatus.SUCCEEDED,
        output="PASS",
        usage=Usage(cost_usd=Decimal("0.10")),
        attempts=1,
    ).model_dump(mode="json")


class _ScriptedActivities:
    """Stand-in for the activity boundary, recording what the workflow asked for.

    The plan carries one request on purpose: a cycle that dispatches nothing
    short-circuits to `NOTHING_TO_DO` before synthesis, so it can never reach
    the approval branch this file is about.
    """

    def __init__(self, **scripted: object) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._scripted: dict[str, object] = {
            "plan_cycle": {
                "cycle_id": "cyc_1",
                "plan": TacticalPlan(rationale="Its usual round.").model_dump(mode="json"),
                "requests": [_scoped_request().model_dump(mode="json")],
            },
            "dispatch_capability": _dispatch_payload(),
            "synthesize_results": {
                "summary": "Looked at what's selling.",
                "action": {
                    "business_id": BIZ,
                    "action_type": "affiliate.publish_post",
                    "action_summary": "publish the trail-shoe review",
                    "triggering_condition": "The draft passed its checks.",
                    "downside": "A weak post could lose a few readers.",
                    "needs_approval": True,
                },
            },
            "request_approval": "apr_1",
            "record_cycle_decision": "dec_1",
            "execute_approved_action": {"executed": True, "replayed": False, "result": {}},
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
        return next(arg for called, arg in reversed(self.calls) if called == name)

    def called(self, name: str) -> bool:
        return any(called == name for called, _ in self.calls)


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Return a driver that runs one cycle against a scripted activity boundary."""

    async def _run(
        *, reasons: list[str] | None = None, **scripted: object
    ) -> tuple[ManagerState, _ScriptedActivities, Any]:
        activities = _ScriptedActivities(**scripted)
        monkeypatch.setattr(workflow_module, "workflow", activities)
        manager = BusinessManagerWorkflow()
        state = await manager._run_cycle(
            ManagerState(business_id=BIZ), _ctx(), reasons or ["scheduled"]
        )
        return state, activities, manager.last_cycle()

    return _run


async def test_a_cycle_that_needs_approval_ends_awaiting_approval(
    drive: Callable[..., Any],
) -> None:
    """D-006: the requesting cycle *ends*; it does not park for seven days.

    Blocking would spread §2.1's one-cycle cost ceiling across a week and turn
    §9's stuck-Manager detection into a week-long timer. The assertion that the
    call returned at all is therefore half the point.
    """
    state, activities, cycle = await drive()

    assert cycle.outcome is CycleOutcome.AWAITING_APPROVAL
    assert activities.called("request_approval")
    assert state.pending_approval_id == "apr_1"
    assert state.cycles_completed == 1, "the cycle happened, so it counts against the day"
    assert activities.payload("record_cycle_decision")["outcome"] == "awaiting_approval"


async def test_the_pausing_cycle_never_runs_the_action(drive: Callable[..., Any]) -> None:
    """§8's gate: nothing executes on the same side of it as the proposal."""
    _, activities, _ = await drive()
    assert not activities.called("execute_approved_action")


async def test_an_approval_decision_is_what_starts_the_next_cycle(
    drive: Callable[..., Any],
) -> None:
    """The Manager's half of D-006: the signal is a wake reason, and the reason
    reaches planning so the new cycle knows what it is resuming."""
    manager = BusinessManagerWorkflow()
    manager.approval_decided("apr_1")
    assert manager._wake_reasons == ["approval:apr_1"]

    _, activities, _ = await drive(reasons=["approval:apr_1"])
    assert activities.payload("plan_cycle").wake_reasons == ("approval:apr_1",)


async def test_the_resumed_cycle_proceeds_past_the_approval(
    drive: Callable[..., Any],
) -> None:
    """The next cycle is a full cycle, not a replay of the request.

    Its plan request carries the pending approval id (so the planner can resume
    the work), and with nothing further to ask it completes.
    """
    state, activities, cycle = await drive(
        reasons=["approval:apr_1"],
        synthesize_results={"summary": "Published the trail-shoe review.", "action": None},
    )
    assert cycle.outcome is CycleOutcome.COMPLETED
    assert not activities.called("request_approval")
    assert state.pending_approval_id is None


# ── Part 2: the operator sees the four facts, from stored values (D-011) ───


async def test_the_pending_queue_shows_the_four_facts_in_plain_language(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Spec §8 via the same assembly `/api/approvals` performs.

    The amount is the assertion that matters: it is read back off the stored
    column and formatted, never regenerated. Capabilities read untrusted
    external content, so prose between the decision and the human authorising
    money is an attack path, not an inconvenience (D-011).
    """
    await _pending_approval(kernel, company, amount_usd=Decimal("42.5"))

    async with kernel.services() as svc:
        row = (await kernel.build_approvals(svc).pending())[0]
        contract = await svc.registry.get_contract(BusinessId(row.business_id))
        request = ApprovalRequest(
            approval_id=row.approval_id,
            business_id=BusinessId(row.business_id),
            action_type=row.action_type,
            action_summary=row.action_summary,
            amount_usd=Decimal(str(row.amount_usd)),
            triggering_condition=row.triggering_condition,
            downside=row.downside,
        )
        detail = render_detail(request, contract.display_name)

    assert set(detail) == {"What happens", "Why now", "What could go wrong", "How much"}
    assert detail["How much"] == "$42.50"
    assert "$42.50" in render_request(request, contract.display_name)
    for text in detail.values():
        assert not contains_technical_language(text)


async def test_approving_publishes_the_event_that_wakes_the_manager(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-006's edge, through the Kernel-built service the API now uses (M6-F20)."""
    approval_id = await _pending_approval(kernel, company)

    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_ok")
        )

    async with kernel.services() as svc:
        published = list(
            (
                await svc.session.scalars(
                    select(EventRow).where(EventRow.event_type == APPROVAL_DECIDED)
                )
            ).all()
        )
    assert [e.payload["approval_id"] for e in published] == [approval_id]


async def test_the_scheduler_signals_the_manager_that_asked(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The rest of the path: publish -> `dispatch_events` -> Manager signal.

    The whole chain in one assertion, because each link was individually sound
    and the chain was not. `approval.decided` maps to the `approval_decided`
    signal carrying the approval id — a bare `wake` would start a cycle that
    cannot tell which request was answered.
    """
    approval_id = await _pending_approval(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_ok")
        )

    client = _FakeTemporalClient()
    kernel._temporal_client = client  # a live server is not what this proves
    woken = await Scheduler(kernel).dispatch_events()

    assert woken == 1
    assert client.signals == [(business_workflow_id(company), "approval_decided", approval_id)]


async def test_a_redelivered_decision_cannot_wake_the_manager_twice(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """A-002: claiming is the deduplication point, so a second sweep is quiet.

    Without this a Manager would pay for a second cycle for every sweep that
    ran after an approval, which is spend the operator never authorised.
    """
    approval_id = await _pending_approval(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_ok")
        )

    client = _FakeTemporalClient()
    kernel._temporal_client = client
    scheduler = Scheduler(kernel)
    assert await scheduler.dispatch_events() == 1
    assert await scheduler.dispatch_events() == 0
    assert len(client.signals) == 1


async def test_one_companys_decision_never_wakes_another(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M6-F21, at the layer that showed it. Spec §10.

    Every affiliate company subscribes to the same event types, and the bus
    filtered claims by type alone — so `dispatch_events` handed the second
    company the first company's `approval.decided` and signalled its Manager
    with an approval id belonging to someone else. Exactly one Manager is
    signalled here, and the assertion names which.
    """
    async with kernel.services() as svc:
        neighbour = await kernel.build_provisioning(svc).create_company(
            definition=AFFILIATE, display_name="Ridgeline Outfitters"
        )

    approval_id = await _pending_approval(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_ok")
        )

    client = _FakeTemporalClient()
    kernel._temporal_client = client
    assert await Scheduler(kernel).dispatch_events() == 1
    assert client.signals == [(business_workflow_id(company), "approval_decided", approval_id)]
    assert business_workflow_id(neighbour) not in {wid for wid, _, _ in client.signals}


# ── Part 3: a denial resets the ladder and leaves nothing runnable ─────────


async def test_a_denial_resets_the_graduation_streak(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-010: a correction or a refusal returns the ladder to the bottom."""
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        approvals = kernel.build_approvals(svc)
        for n in range(1, 5):
            await approvals.request(
                request=ApprovalRequest(
                    approval_id=f"apr_ok_{n}",
                    business_id=company,
                    action_type="affiliate.publish_post",
                    action_summary="publish today's post",
                    triggering_condition="The draft passed its checks.",
                    downside="A weak post could lose a few readers.",
                ),
                contract=contract,
            )
            await approvals.approve(
                f"apr_ok_{n}", contract=contract, decision_id=DecisionId(f"dec_{n}")
            )

    approval_id = await _pending_approval(kernel, company, approval_id="apr_no")
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        approvals = kernel.build_approvals(svc)
        await approvals.deny(approval_id, contract=contract, decision_id=DecisionId("dec_no"))
        assert await approvals.requires_approval(contract, "affiliate.publish_post"), (
            "four clean approvals and a refusal must not leave the action one step "
            "from graduating (D-010)"
        )


async def test_a_denied_action_does_not_execute(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The refusal has to bind the effect, not only the counter (D-015)."""
    approval_id = await _pending_approval(kernel, company, approval_id="apr_denied")
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).deny(
            approval_id, contract=contract, decision_id=DecisionId("dec_no")
        )

    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )
    assert outcome == {"executed": False, "reason": "not approved"}


async def test_an_approved_action_passes_the_gate_it_stops_at(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Negative control for the test above.

    A guard that refused everything would pass it too. An *approved* action gets
    past the approval check and travels on to the tool boundary — where this
    Kernel, holding no secrets, refuses out loud rather than publishing without
    a credential (spec §10). M6-3 picks the path up from there; the executing
    half lives in `test_approved_action_execution.py`.
    """
    approval_id = await _pending_approval(kernel, company, approval_id="apr_yes")
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_yes")
        )

    with pytest.raises(ScopeViolationError):
        await as_business(
            company,
            ManagerActivities(kernel).execute_approved_action,
            {"approval_id": approval_id},
        )


# ── Part 4: M6-F11 — the model proposes, the platform validates (D-013) ────


def _synthesis_activities(
    session: AsyncSession, contract: BusinessContract, reply: str
) -> ManagerActivities:
    """Return activities whose synthesis call returns ``reply``."""

    class _Kernel:
        def __init__(self) -> None:
            self.settings = SimpleNamespace(
                budget=SimpleNamespace(reasoning_token_price_per_million_usd=Decimal("50.00"))
            )
            self.llm = _StubProvider(reply)

        def build_ledger(self, services: object) -> BudgetLedger:
            return BudgetLedger(session, platform_ceiling_usd=Decimal("500.00"))

        def build_approvals(self, services: object) -> ApprovalService:
            return ApprovalService(session, AuditLog(session), DecisionLog(session))

        async def type_definition(self, services: object, name: str) -> Any:
            return AFFILIATE if name == AFFILIATE.name else None

        @asynccontextmanager
        async def services(self) -> AsyncIterator[Any]:
            yield SimpleNamespace(
                session=session,
                audit=AuditLog(session),
                decisions=DecisionLog(session),
                registry=SimpleNamespace(get_contract=_get_contract),
            )

    async def _get_contract(business_id: BusinessId) -> BusinessContract:
        return contract

    return ManagerActivities(_Kernel())  # type: ignore[arg-type]


def _synthesis_reply(action_type: str) -> str:
    return json.dumps(
        {
            "summary": "Checked the draft against the rules.",
            "action": {
                "action_type": action_type,
                "action_summary": "hold the post until it is checked",
                "triggering_condition": "The compliance check has not run.",
                "downside": "Publishing unchecked could breach the disclosure rules.",
            },
        }
    )


async def test_a_prose_action_type_never_becomes_an_action(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """M6-F11, on the exact string the live run produced.

    A-003 requires a stable dotted identifier and the graduation counters key on
    it. A sentence there names no action: no tool implements it, no policy can
    graduate it, and an operator approving it would authorise nothing.
    """
    activities = _synthesis_activities(session, contract, _synthesis_reply(PROSE_ACTION_TYPE))
    result = await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_prose",
        ),
    )
    assert result["action"] is None
    assert result["summary"] == "Checked the draft against the rules."


async def test_a_rejected_proposal_is_recorded_rather_than_lost(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Degrading silently would make a Manager that proposes nothing valid look
    like a Manager with nothing to propose (spec §11)."""
    activities = _synthesis_activities(session, contract, _synthesis_reply(PROSE_ACTION_TYPE))
    await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_prose",
        ),
    )
    rows = list(
        (
            await session.scalars(
                select(AuditLogRow).where(AuditLogRow.event_type == "action.proposal_rejected")
            )
        ).all()
    )
    assert len(rows) == 1
    assert PROSE_ACTION_TYPE in str(rows[0].payload["proposed_action_type"])
    assert rows[0].payload["declared_action_types"] == ["affiliate.publish_post"]


async def test_an_undeclared_but_well_formed_action_type_is_also_refused(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The live queue also held `affiliate.connect_content_system_access`, which
    matches A-003's pattern and is still not an action this type has.

    Shape is not the check. §8's "unknown actions require approval" governs
    actions the platform knows about and has not configured; it is not a licence
    for a model to name new company powers into existence (D-013, D-014).
    """
    activities = _synthesis_activities(
        session, contract, _synthesis_reply("affiliate.connect_content_system_access")
    )
    result = await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_undeclared",
        ),
    )
    assert result["action"] is None


async def test_a_declared_action_still_reaches_the_operator(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Negative control. A validator that rejected everything would close the
    approval path entirely and pass every test above."""
    activities = _synthesis_activities(
        session, contract, _synthesis_reply("affiliate.publish_post")
    )
    result = await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_ok",
        ),
    )
    action = result["action"]
    assert isinstance(action, dict)
    assert action["action_type"] == "affiliate.publish_post"
    assert action["needs_approval"] is True


async def test_a_bare_action_name_is_still_namespaced(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A-003 namespacing survives the check: the model may name `publish_post`."""
    activities = _synthesis_activities(session, contract, _synthesis_reply("publish_post"))
    result = await as_business(
        contract.business_id,
        activities.synthesize_results,
        SynthesisRequest(
            business_id=contract.business_id,
            plan=TacticalPlan(rationale="Its usual round."),
            results=(),
            cycle_id="cyc_bare",
        ),
    )
    action = result["action"]
    assert isinstance(action, dict)
    assert action["action_type"] == "affiliate.publish_post"


async def test_the_approval_store_refuses_an_undeclared_action_outright(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The backstop. An approval row is the only thing between model prose and
    an operator's authorisation, so the write itself refuses rather than
    trusting every caller to have validated first."""
    service = ApprovalService(session, AuditLog(session), DecisionLog(session))
    with pytest.raises(ApprovalError) as caught:
        await service.request(
            request=ApprovalRequest(
                approval_id="apr_prose",
                business_id=contract.business_id,
                action_type=f"affiliate.{PROSE_ACTION_TYPE}",
                action_summary="hold the post",
                triggering_condition="The compliance check has not run.",
                downside="Publishing unchecked could breach the rules.",
            ),
            contract=contract,
        )
    assert not contains_technical_language(caught.value.operator_message)
    assert await service.pending() == []


async def test_the_declared_set_comes_from_the_type_definition(
    contract: BusinessContract,
) -> None:
    """D-014: the set is data on the type, snapshotted into the contract.

    If a type ever ships with no declared actions, every proposal it makes is
    refused and the company can only ever report. That is the correct failure —
    silent and safe — but it is a data question worth seeing, so it is asserted
    rather than assumed."""
    assert AFFILIATE.autonomy_policies, "a type with no declared actions can propose nothing"
    assert contract.declared_action_types == {"affiliate.publish_post"}
    assert contract.declares_action("affiliate.publish_post")
    assert not contract.declares_action("affiliate.publish_post ")


def test_the_approval_state_machine_has_no_silent_yes() -> None:
    """Spec §9, restated where the round trip can see it: every terminal state
    other than APPROVED means the action did not happen."""
    assert ApprovalState.EXPIRED_PAUSED != ApprovalState.APPROVED
    assert {s.value for s in ApprovalState} == {
        "pending",
        "approved",
        "denied",
        "expired_paused",
    }
