"""The approved action executes, once, with the trail to prove it (M6-3).

Spec §6, §10, §11.5; D-011, D-013, D-015; A-001, A-003.

M6-2 proved an operator's answer reaches the Manager. This file is the other
half: what the platform does with a *yes*. Everything below runs the real
Kernel, the real `ToolExecutor`, the real `CredentialManager`, the real
idempotency store and the real operator API — only the HTTP endpoint at the far
end of the webhook is a mock transport, because the assertions are about what
Jarvis sends and records, not about anyone's blog.

Four defects are pinned here, all found by walking the approved-action path:

- **M6-F28**: no entrypoint ever gave the Kernel its secrets, so
  `CredentialManager` was empty in production and no credentialled tool could
  have run at all.
- **M6-F29**: the executing activity took the tool name, the credential handle
  *and* the set of granted handles from its own payload — a caller both chose
  the credential and certified that it had been granted it.
- **M6-F30**: the destination of a publish came from the approval's parameters,
  which an operator may edit and a model proposed.
- **M6-F31**: nothing called the activity. An approved action was recorded,
  the Manager woke, and the effect the human authorised never happened.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.approvals.models import ApprovalRequest
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.capabilities import tools as tools_module
from jarvis.capabilities.request import CapabilityResult, InvocationStatus
from jarvis.capabilities.tools import WebhookPublishTool
from jarvis.domain.contract import CapabilityType
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import BusinessId, DecisionId, InvocationId
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager.activities import ManagerActivities, _effect_parameters, _title_of
from jarvis.persistence.models import ApprovalRow, Base
from tests.conftest import as_business

WEBHOOK_SECRET = "s3cr3t-blog-token"  # noqa: S105 — a test value, not a real credential
WEBHOOK_URL = "https://blog.example/publish"
DRAFT = "Best Trail Runners For Overpronators\n\nDisclosure: affiliate links.\n\nBody text."


class _StubProvider:
    """Provider returning one canned reply. No live model is involved."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        return CompletionResponse(text="{}", usage=Usage(input_tokens=1, output_tokens=1))

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    """Return settings carrying the credential and its destination.

    `_env_file=None`: the repository holds a real `.env`, and a test that read
    it would reach a live provider and a real endpoint.
    """
    return Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        credentials={"affiliate_blog_webhook": WEBHOOK_SECRET},
        tool_endpoints={"affiliate_blog_webhook": WEBHOOK_URL},
        _env_file=None,
    )


@pytest.fixture
def sent() -> list[httpx.Request]:
    """Collect every request that reached the webhook."""
    return []


@pytest_asyncio.fixture
async def kernel(
    sent: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[PlatformKernel]:
    """Yield a real Kernel whose publish tool talks to a mock endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True, "id": "post_1"})

    monkeypatch.setitem(
        tools_module.BUILTIN_TOOLS,
        "webhook_publish",
        WebhookPublishTool(httpx.AsyncClient(transport=httpx.MockTransport(handler))),
    )
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(_settings(), engine=engine, provider=_StubProvider())  # type: ignore[arg-type]
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def company(kernel: PlatformKernel) -> BusinessId:
    """Create one affiliate company through the real provisioning path (§4)."""
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        return await provisioning.create_company(
            definition=AFFILIATE, display_name="Summit Trail Gear"
        )


async def _approved(
    kernel: PlatformKernel,
    company: BusinessId,
    *,
    approval_id: str = "apr_publish",
    parameters: dict[str, Any] | None = None,
    modified: dict[str, Any] | None = None,
) -> str:
    """Raise and approve one publish request through the real service."""
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        approvals = kernel.build_approvals(svc)
        await approvals.request(
            request=ApprovalRequest(
                approval_id=approval_id,
                business_id=company,
                action_type="affiliate.publish_post",
                action_summary="publish the trail-runner review",
                triggering_condition="The draft passed its checks this morning.",
                downside="A weak post could cost a few readers' trust.",
                parameters=parameters
                if parameters is not None
                else {"title": _title_of(DRAFT), "body": DRAFT},
            ),
            contract=contract,
        )
        await approvals.approve(
            approval_id,
            contract=contract,
            decision_id=DecisionId(f"dec_{approval_id}"),
            modified_parameters=modified,
        )
    return approval_id


# ── the effect itself (D-015, §10) ─────────────────────────────────────────


async def test_an_approved_action_executes_through_the_tool_boundary(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """The whole point: a *yes* becomes a real, credentialled effect."""
    approval_id = await _approved(kernel, company)

    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert outcome["executed"] is True
    assert outcome["replayed"] is False
    assert len(sent) == 1
    assert str(sent[0].url) == WEBHOOK_URL


async def test_the_credential_is_in_the_call_and_nowhere_else(
    kernel: PlatformKernel,
    company: BusinessId,
    sent: list[httpx.Request],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec §10, stated as an assertion rather than a convention.

    The secret exists in the outgoing header. It must not exist in the result,
    in the recorded effect, in the audit log, in the Decision Log, in the
    approval the operator read, or in anything the platform logged.
    """
    caplog.set_level(logging.DEBUG)
    approval_id = await _approved(kernel, company)
    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert sent[0].headers["authorization"] == f"Bearer {WEBHOOK_SECRET}"

    async with kernel.services() as svc:
        audit = [row.payload for row in await svc.audit.for_business(company, limit=100)]
        decisions = [
            (row.summary, row.rationale, row.inputs_considered, row.structured_action)
            for row in await svc.decisions.activity_feed(company, limit=100)
        ]
        row = await svc.session.get(ApprovalRow, approval_id)
        approval = (row.parameters, row.decided_parameters) if row else ()

    haystacks = [
        str(outcome),
        str(audit),
        str(decisions),
        str(approval),
        caplog.text,
        "".join(record.getMessage() for record in caplog.records),
    ]
    for haystack in haystacks:
        assert WEBHOOK_SECRET not in haystack


async def test_a_missing_secret_refuses_rather_than_publishing_unauthenticated(
    company: BusinessId, sent: list[httpx.Request], monkeypatch: pytest.MonkeyPatch, kernel: Any
) -> None:
    """Failure posture: a credential that cannot resolve denies (spec §10)."""
    approval_id = await _approved(kernel, company, approval_id="apr_nosecret")
    monkeypatch.setattr(kernel, "_credentials", type(kernel._credentials)({}))

    with pytest.raises(ScopeViolationError):
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )
    assert sent == [], "nothing may reach the endpoint without a credential"


# ── idempotency (spec §6, A-001) ───────────────────────────────────────────


async def test_re_running_an_approved_action_replays_it(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """A retried or replayed approved action publishes once.

    The key is derived from the approval, which is this effect's invocation. A
    fresh id per attempt — what this activity minted before M6-3 — makes every
    attempt a different action under A-001 and publishes as many times as
    Temporal retries.
    """
    approval_id = await _approved(kernel, company)
    activities = ManagerActivities(kernel)

    first = await as_business(
        company, activities.execute_approved_action, {"approval_id": approval_id}
    )
    second = await as_business(
        company, activities.execute_approved_action, {"approval_id": approval_id}
    )

    assert len(sent) == 1, "the second run must replay, not publish again"
    assert second["result"] == first["result"]
    assert first["replayed"] is False
    assert second["replayed"] is True


# ── what the platform decides, and what it refuses to be told (D-013) ──────


async def test_the_destination_comes_from_configuration_not_the_approval(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """M6-F30: an operator's correction cannot redirect a credentialled publish.

    Correcting parameters is the operator's right (A-003). *Where* a
    credentialled effect is sent is not a parameter — it is deployment
    configuration read at the tool boundary, so a value stored on the approval
    is overridden rather than honoured.
    """
    approval_id = await _approved(
        kernel,
        company,
        parameters={"title": "T", "body": DRAFT},
        modified={"title": "T", "body": DRAFT, "webhook_url": "https://attacker.example/collect"},
    )

    await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert str(sent[0].url) == WEBHOOK_URL


async def test_the_payload_cannot_name_its_own_tool_or_credential(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """M6-F29: the binding is derived from the action type and the contract.

    The extra keys below are exactly what the activity used to accept. They are
    ignored now, so a caller can neither reach a different tool nor certify a
    credential grant to itself.
    """
    approval_id = await _approved(kernel, company)

    outcome = await as_business(
        company,
        ManagerActivities(kernel).execute_approved_action,
        {
            "approval_id": approval_id,
            "tool_name": "wire_transfer",
            "credential_handle": "someone_elses_key",
            "granted_credentials": ["someone_elses_key"],
        },
    )

    assert outcome["executed"] is True
    assert sent[0].headers["authorization"] == f"Bearer {WEBHOOK_SECRET}"


async def test_the_operators_decided_parameters_are_what_run(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """A-003 correction semantics, at the point the effect happens."""
    approval_id = await _approved(
        kernel,
        company,
        parameters={"title": "Original", "body": DRAFT},
        modified={"title": "Corrected", "body": DRAFT},
    )

    await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert b"Corrected" in sent[0].content
    assert b"Original" not in sent[0].content


def test_the_payload_is_stored_output_not_regenerated_prose() -> None:
    """D-011's reasoning one step out: the bytes published are the bytes drafted."""
    results = (
        CapabilityResult(
            invocation_id=InvocationId("inv_r"),
            business_id=BusinessId("biz_x"),
            capability=CapabilityType.RESEARCH,
            status=InvocationStatus.SUCCEEDED,
            output="three topic ideas",
            attempts=1,
        ),
        CapabilityResult(
            invocation_id=InvocationId("inv_c"),
            business_id=BusinessId("biz_x"),
            capability=CapabilityType.CONTENT,
            status=InvocationStatus.SUCCEEDED,
            output=DRAFT,
            attempts=1,
        ),
        CapabilityResult(
            invocation_id=InvocationId("inv_k"),
            business_id=BusinessId("biz_x"),
            capability=CapabilityType.COMPLIANCE,
            status=InvocationStatus.SUCCEEDED,
            output="PASS",
            attempts=1,
        ),
    )

    params = _effect_parameters(results)

    assert params["body"] == DRAFT, "the draft, not the compliance verdict or the research"
    assert params["title"] == "Best Trail Runners For Overpronators"


def test_a_cycle_with_nothing_publishable_composes_no_payload() -> None:
    """An empty payload fails at the tool boundary rather than publishing blank."""
    results = (
        CapabilityResult(
            invocation_id=InvocationId("inv_r"),
            business_id=BusinessId("biz_x"),
            capability=CapabilityType.RESEARCH,
            status=InvocationStatus.SUCCEEDED,
            output="three topic ideas",
            attempts=1,
        ),
    )
    assert _effect_parameters(results) == {}


# ── the trail, through the operator's own surface (§11, §11.5, §12.5) ──────


async def test_the_trail_is_retrievable_through_the_operator_api(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Both records exist and both are reachable where §12.5 puts them.

    The narrative belongs in the activity feed the operator sees by default;
    the audit entry belongs behind "Full details". Neither is asserted from the
    database here on purpose — a trail nothing can retrieve is not a trail.
    """
    approval_id = await _approved(kernel, company)
    await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(f"/api/companies/{company}")
        full = await client.get(f"/api/companies/{company}/full-details")

    assert detail.status_code == 200
    feed = [entry["what"] for entry in detail.json()["activity"]]
    assert any("did what you approved" in line for line in feed), feed

    events = [row["event"] for row in full.json()]
    assert "tool.executed" in events


async def test_the_narrative_is_operator_language(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Spec §12.5: the owner's account of a publish names no machinery."""
    from jarvis.approvals.rendering import contains_technical_language

    approval_id = await _approved(kernel, company)
    activities = ManagerActivities(kernel)
    await as_business(company, activities.execute_approved_action, {"approval_id": approval_id})
    await as_business(company, activities.execute_approved_action, {"approval_id": approval_id})

    async with kernel.services() as svc:
        entries = list(await svc.decisions.activity_feed(company, limit=100))

    narratives = [e.summary for e in entries if e.action_type == "affiliate.publish_post"]
    assert any("did what you approved" in n for n in narratives)
    assert any("already done this" in n for n in narratives), "a replay says so, plainly"
    for narrative in narratives:
        assert not contains_technical_language(narrative), narrative


async def test_an_unapproved_action_never_reaches_the_tool(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """§8's gate holds at the executing end too, not only at the proposing end."""
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).request(
            request=ApprovalRequest(
                approval_id="apr_pending",
                business_id=company,
                action_type="affiliate.publish_post",
                action_summary="publish the trail-runner review",
                triggering_condition="The draft passed its checks.",
                downside="A weak post could cost a few readers' trust.",
                parameters={"title": "T", "body": DRAFT},
            ),
            contract=contract,
        )

    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": "apr_pending"}
    )

    assert outcome == {"executed": False, "reason": "not approved"}
    assert sent == []


# ── the wiring that makes any of it happen (D-006 + D-015) ─────────────────


async def test_an_answered_approval_runs_the_action_before_planning(
    drive: Callable[..., Any],
) -> None:
    """M6-F31: the wake that carries the answer is the wake that acts.

    D-006 ends the requesting cycle at the request, so there is no parked frame
    to resume — the effect has to be the first thing the woken cycle does, or
    an approved action is a database row and nothing else.
    """
    _, activities, _ = await drive(reasons=["approval:apr_1", "approval:apr_1"])

    calls = [name for name, _ in activities.calls]
    assert calls.count("execute_approved_action") == 1, "one effect per answer (A-002)"
    assert calls.index("execute_approved_action") < calls.index("plan_cycle")
    assert activities.payload("execute_approved_action") == {"approval_id": "apr_1"}


async def test_a_scheduled_wake_executes_nothing(drive: Callable[..., Any]) -> None:
    """Negative control: only an answer runs an action."""
    _, activities, _ = await drive(reasons=["scheduled"])
    assert not activities.called("execute_approved_action")


async def test_an_exhausted_effect_ends_the_cycle_visibly(drive: Callable[..., Any]) -> None:
    """Spec §9: a Manager that cannot do what was approved says so."""
    from tests.test_manager_cycle_outcomes import _exhausted

    _, activities, cycle = await drive(
        reasons=["approval:apr_1"],
        execute_approved_action=_exhausted(),
    )

    assert cycle.outcome.value == "failed"
    assert not activities.called("plan_cycle"), "no cycle plans past an action it could not take"
    assert activities.called("record_cycle_decision")


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Run one cycle against the recording activity boundary from M6-2."""
    from jarvis.manager import workflow as workflow_module
    from jarvis.manager.state import ManagerState
    from jarvis.manager.workflow import BusinessManagerWorkflow
    from tests.test_approval_roundtrip import BIZ, _ctx, _ScriptedActivities

    async def _run(
        *, reasons: list[str] | None = None, **scripted: object
    ) -> tuple[ManagerState, Any, Any]:
        activities = _ScriptedActivities(**scripted)
        monkeypatch.setattr(workflow_module, "workflow", activities)
        manager = BusinessManagerWorkflow()
        state = await manager._run_cycle(
            ManagerState(business_id=BIZ), _ctx(), reasons or ["scheduled"]
        )
        return state, activities, manager.last_cycle()

    return _run
