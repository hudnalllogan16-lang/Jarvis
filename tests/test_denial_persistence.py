"""A refusal has to outlive itself (M6-4b).

Spec §10, §11; D-002, D-015, D-022.

**M6-F38.** `BusinessRegistry._deny` recorded a `security.scope_violation` entry
and then raised, inside `kernel.services()` — which rolls back on exception. The
raise unwound the record with it. `pool.dispatch` re-raises scope violations
deliberately ("a security event, not a task outcome"), so the exception always
reached the scope boundary and the entry was always discarded: a probe showed
one refused dispatch and zero persisted rows. Every §10 denial the platform had
ever made was invisible afterwards, while the code and its docstring both said
"always audited".

**M6-F37.** `WebhookPublishTool` filled missing title and body with `""` and
POSTed them, so a cycle that produced nothing publishable published nothing —
visibly, to a real endpoint — instead of refusing. `_effect_parameters` had
documented the opposite for the whole of M6-3.

Every test here reads its assertions back **through a fresh transaction**. That
is the point of the file: the tests that covered `_deny` used one bare session
and asserted on flushed-but-uncommitted rows, so they passed for the entire
period the behaviour was broken. Asserting inside the transaction that wrote the
row cannot see a rollback, which is the M5-F5 failure mode wearing a green tick.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.approvals.models import ApprovalRequest
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.capabilities import tools as tools_module
from jarvis.capabilities.request import MemoryScope, ScopedRequest
from jarvis.capabilities.tools import REQUIRED_PARAMS, WebhookPublishTool
from jarvis.domain.contract import CapabilityType
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import CapabilityExecutionError, ScopeViolationError
from jarvis.kernel.ids import BusinessId, DecisionId, InvocationId, new_decision_id
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager.activities import ManagerActivities
from jarvis.persistence.models import AuditLogRow, Base, IdempotencyRow
from jarvis.runtime.activities import KernelActivities
from tests.conftest import as_business

WEBHOOK_SECRET = "s3cr3t-blog-token"  # noqa: S105 — a test value, not a real credential
WEBHOOK_URL = "https://blog.example/publish"

ANOTHER_BUSINESS = BusinessId("biz_" + "d" * 32)

JARVIS = pathlib.Path("jarvis")

STALE_LIVE_PAYLOAD: dict[str, Any] = {"title": "Best trail runners for overpronators"}
"""The shape of `apr_1a161…` in the live evidence trail — an approval raised
before D-024.1 composed a body. It was approved and never executed (M6-F31), so
no empty post ever shipped; had it executed, it would have published a titled
blank. It is the natural negative control for M6-F37."""


class _StubProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        return CompletionResponse(text="{}", usage=Usage(input_tokens=1, output_tokens=1))

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    """`_env_file=None`: the repository holds a real `.env`, and a test that read
    it would reach a live provider and a real endpoint."""
    return Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        credentials={"affiliate_blog_webhook": WEBHOOK_SECRET},
        tool_endpoints={"affiliate_blog_webhook": WEBHOOK_URL},
        _env_file=None,
    )


@pytest.fixture
def sent() -> list[httpx.Request]:
    return []


@pytest_asyncio.fixture
async def kernel(
    sent: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[PlatformKernel]:
    """A real Kernel with real commit semantics.

    `StaticPool` shares one connection, which is what makes an independent
    transaction observable here at all — and is the same substrate D-022's
    reservation transactions already run on.
    """

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
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        return await provisioning.create_company(
            definition=AFFILIATE, display_name="Summit Trail Gear"
        )


async def _violations(kernel: PlatformKernel, event_type: str) -> list[AuditLogRow]:
    """Read audit rows back through a *new* transaction.

    The whole defect was invisible to a reader inside the writing transaction.
    """
    async with kernel.services() as svc:
        return list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == event_type)
                )
            ).all()
        )


def _request(business_id: BusinessId, **over: Any) -> ScopedRequest:
    base: dict[str, Any] = {
        "invocation_id": InvocationId("inv_probe"),
        "declared_business_id": business_id,
        "capability": CapabilityType.RESEARCH,
        "prompt_ref": "affiliate.research",
        "prompt_inputs": {"intent": "look at demand"},
        "tool_scope": frozenset({"web_search"}),
        "memory_scope": MemoryScope.READ,
        "budget_allocation_usd": Decimal("0.10"),
    }
    base.update(over)
    return ScopedRequest(**base)


# ── Part 1: M6-F38 — the denial record survives the denial ─────────────────


async def test_a_refused_dispatch_leaves_a_record_behind(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The probe that found M6-F38, as a standing test.

    End to end through the real activity boundary: a request declaring another
    business is refused (D-002), and the refusal is still on the record after
    the exception has unwound the transaction that wrote it.
    """
    request = _request(BusinessId("biz_" + "c" * 32))

    with pytest.raises(ScopeViolationError):
        await as_business(company, KernelActivities(kernel).dispatch_capability, request)

    rows = await _violations(kernel, "security.scope_violation")
    assert len(rows) == 1, "one refusal, one record — this was 1 and 0 before M6-4b"
    assert rows[0].payload["reason"] == "identity_mismatch"
    assert rows[0].business_id == company


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"declared_business_id": ANOTHER_BUSINESS}, "identity_mismatch"),
        ({"capability": CapabilityType.FINANCE}, "capability_not_permitted"),
        ({"tool_scope": frozenset({"web_search", "wire_transfer"})}, "tool_scope_escalation"),
        ({"credential_refs": frozenset({"someone_elses_key"})}, "credential_scope_escalation"),
    ],
)
async def test_every_denial_reason_persists(
    kernel: PlatformKernel, company: BusinessId, over: dict[str, Any], reason: str
) -> None:
    """`_deny` is the single exit point for all four, so all four are checked.

    Fixing one call site would have left the next check to be written free to
    reintroduce the defect; the property belongs to the exit point.
    """
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
    request = _request(company, **over)

    with pytest.raises(ScopeViolationError):
        async with kernel.services() as svc:
            await svc.registry.authorize_invocation(
                identity=RuntimeIdentity.for_testing(company),
                declared_business_id=request.declared_business_id,
                capability=request.capability,
                requested_tools=request.tool_scope,
                requested_credentials=request.credential_refs,
            )
    assert contract.business_id == company

    rows = await _violations(kernel, "security.scope_violation")
    assert [row.payload["reason"] for row in rows] == [reason]


async def test_a_paused_company_denial_persists_too(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The fifth reason, which needs a lifecycle change rather than a bad request."""
    async with kernel.services() as svc:
        await svc.registry.transition(
            company, LifecycleState.PAUSED, decision_id=new_decision_id(), reason="Paused."
        )

    with pytest.raises(ScopeViolationError):
        async with kernel.services() as svc:
            await svc.registry.authorize_invocation(
                identity=RuntimeIdentity.for_testing(company),
                declared_business_id=company,
                capability=CapabilityType.RESEARCH,
                requested_tools=frozenset({"web_search"}),
                requested_credentials=frozenset(),
            )

    rows = await _violations(kernel, "security.scope_violation")
    assert [row.payload["reason"] for row in rows] == ["not_dispatchable"]


async def test_an_authorised_invocation_records_no_violation(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Negative control. A `_deny` that fired on everything would satisfy every
    test above and stop the platform dead."""
    async with kernel.services() as svc:
        await svc.registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(company),
            declared_business_id=company,
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset({"web_search"}),
            requested_credentials=frozenset(),
        )

    assert await _violations(kernel, "security.scope_violation") == []


async def test_a_denial_alongside_other_work_still_persists(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The denial survives even when the aborted scope had already written.

    The other half of "independent" — that the caller's in-flight work still
    rolls back — is **not asserted here, because this substrate cannot show
    it**. `StaticPool` hands every session the same connection, so the
    independent commit sweeps up whatever the caller had pending; a file-backed
    SQLite goes the other way and blocks the independent write behind SQLite's
    single-writer lock, losing the denial instead. Both are substitution
    artefacts (see `conftest`), and a test asserting either would be asserting
    SQLite.

    Verified instead against the production engine, on a throwaway Postgres
    database: denial rows 1, caller-work rows 0. Recorded as M6-F40, because a
    mechanism whose correctness the suite cannot observe is a fact about the
    suite that should be written down rather than discovered later.
    """
    with pytest.raises(ScopeViolationError):
        async with kernel.services() as svc:
            await svc.audit.record(
                event_type="probe.work_in_progress",
                actor="platform",
                business_id=company,
                payload={},
            )
            await svc.registry.authorize_invocation(
                identity=RuntimeIdentity.for_testing(company),
                declared_business_id=ANOTHER_BUSINESS,
                capability=CapabilityType.RESEARCH,
                requested_tools=frozenset(),
                requested_credentials=frozenset(),
            )

    assert len(await _violations(kernel, "security.scope_violation")) == 1


async def test_the_kernel_wires_denial_transactions(kernel: PlatformKernel) -> None:
    """Structural, like `test_kernel_wires_reservation_transactions` (D-022).

    The factory is optional so a single-session test can drive the log directly;
    that fallback is safe only while production is known to be wired, so the
    wiring is asserted rather than assumed.
    """
    async with kernel.services() as svc:
        assert svc.audit._denial_sessions is not None
        assert svc.registry._audit._denial_sessions is not None


def _own_raises(fn: ast.AST) -> list[int]:
    """Return `raise` lines belonging to ``fn`` itself, not to a nested def."""
    lines: list[int] = []
    for node in ast.iter_child_nodes(fn):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            continue
        if isinstance(node, ast.Raise):
            lines.append(node.lineno)
        lines.extend(_own_raises(node))
    return lines


def _own_plain_records(fn: ast.AST) -> list[int]:
    """Return lines where ``fn`` itself calls the transaction-bound `record`."""
    lines: list[int] = []
    for node in ast.iter_child_nodes(fn):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            continue
        if isinstance(node, ast.Call):
            call = ast.unparse(node)
            if "audit.record(" in call.replace("record_independently(", "ri("):
                lines.append(node.lineno)
        lines.extend(_own_plain_records(node))
    return lines


ALLOWED_RECORD_THEN_RAISE = {
    ("jarvis/api/app.py", "_decide"),
    ("jarvis/manager/activities.py", "_assert_identity"),
}
"""Functions that record with `record` and raise later, legitimately.

Both write inside a scope they then let close **cleanly**, and raise afterwards
— so the record is committed before the refusal exists, reaching the same place
`record_independently` reaches by a different route. It is visible in both
because each has a single exit; that is the whole justification, and it does not
extend to a function whose raise is inside the scope that wrote the entry.

The list is meant to stay this short. A purely local check cannot decide the
general case — `_deny` and `_refuse` are rolled back by a scope they never see,
opened by a caller two layers up — so the rule is that a transaction-bound
record followed by a raise must be argued for here, one line each, or use
`record_independently`.
"""


def test_no_audited_refusal_is_rolled_back_by_its_own_refusal() -> None:
    """The sweep the packet asked for, kept executable.

    A one-time grep finds today's instances; this finds tomorrow's. Any function
    that writes a transaction-bound audit entry and then raises is discarding
    that entry, unless it is on the short allowlist above.
    """
    offenders: list[str] = []
    for path in sorted(JARVIS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            records = _own_plain_records(fn)
            raises = _own_raises(fn)
            if not records or not raises:
                continue
            if not any(r > min(records) for r in raises):
                continue
            if (path.as_posix(), fn.name) in ALLOWED_RECORD_THEN_RAISE:
                continue
            offenders.append(f"{path.as_posix()}:{fn.lineno} {fn.name}")

    assert not offenders, (
        "these record an audit entry and then raise inside the same transaction, "
        f"which rolls the entry back (M6-F38): {offenders}"
    )


def test_the_sweep_can_actually_fail() -> None:
    """A structural guard that cannot fire reads as coverage and is worse than none."""
    tree = ast.parse(
        "async def f():\n"
        "    await self._audit.record(event_type='x', actor='y')\n"
        "    raise ScopeViolationError('no')\n"
    )
    fn = tree.body[0]
    assert _own_plain_records(fn) and _own_raises(fn)

    clean = ast.parse(
        "async def f():\n"
        "    await self._audit.record_independently(event_type='x', actor='y')\n"
        "    raise ScopeViolationError('no')\n"
    )
    assert not _own_plain_records(clean.body[0])


# ── Part 2: M6-F37 — an effect with nothing in it is refused ───────────────


async def _approved(
    kernel: PlatformKernel,
    company: BusinessId,
    *,
    approval_id: str = "apr_publish",
    parameters: dict[str, Any],
) -> str:
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
                parameters=parameters,
            ),
            contract=contract,
        )
        await approvals.approve(
            approval_id, contract=contract, decision_id=DecisionId(f"dec_{approval_id}")
        )
    return approval_id


async def test_the_stale_live_shape_publishes_nothing(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """M6-F37 on the exact payload shape the live trail carries.

    `apr_1a161…` holds a title and no body. Approved and executed, the tool used
    to POST that title with an empty body — a real, published, empty post, from
    an approval whose §8 display never showed the operator a body because there
    was not one.
    """
    approval_id = await _approved(kernel, company, parameters=STALE_LIVE_PAYLOAD)

    with pytest.raises(CapabilityExecutionError) as caught:
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )

    assert caught.value.permanent, "an empty payload fails the same way on every attempt"
    assert sent == [], "nothing reaches the endpoint"


async def test_the_refusal_is_audited_and_survives(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§11 plus M6-F38's lesson: the refusal record outlives the refusal."""
    approval_id = await _approved(kernel, company, parameters=STALE_LIVE_PAYLOAD)

    with pytest.raises(CapabilityExecutionError):
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )

    rows = await _violations(kernel, "tool.refused")
    assert len(rows) == 1
    assert rows[0].payload["reason"] == "empty_payload"
    assert rows[0].payload["missing"] == ["body"]
    assert rows[0].payload["tool"] == "publish_post"


async def test_the_refusal_reads_as_a_consequence(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§12.5: the operator is told what it means, not what failed internally."""
    from jarvis.approvals.rendering import contains_technical_language

    approval_id = await _approved(kernel, company, parameters=STALE_LIVE_PAYLOAD)

    with pytest.raises(CapabilityExecutionError) as caught:
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )

    assert not contains_technical_language(caught.value.operator_message)
    assert caught.value.operator_message.endswith(".")


async def test_a_refused_effect_records_no_idempotency_key(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """A refusal is not a performance, so it must not be replayable as one.

    If the empty payload took a key, the corrected retry — same approval, so the
    same A-001 key — would replay the refusal instead of publishing, and a
    correction could never rescue the action.
    """
    approval_id = await _approved(kernel, company, parameters=STALE_LIVE_PAYLOAD)

    with pytest.raises(CapabilityExecutionError):
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )

    async with kernel.services() as svc:
        keys = list((await svc.session.scalars(select(IdempotencyRow))).all())
    assert keys == []


@pytest.mark.parametrize(
    "parameters",
    [
        {"title": "T"},
        {"body": "B"},
        {"title": "T", "body": ""},
        {"title": "   ", "body": "B"},
        {"title": "T", "body": "   \n  "},
        {},
    ],
    ids=["no-body", "no-title", "blank-body", "blank-title", "whitespace-body", "neither"],
)
async def test_a_hollow_payload_is_refused_however_it_is_hollow(
    kernel: PlatformKernel,
    company: BusinessId,
    sent: list[httpx.Request],
    parameters: dict[str, Any],
) -> None:
    """Blank is the same as absent. A body of spaces publishes an empty post just
    as surely as no body at all, and is likelier — it is what a truncated or
    stripped draft leaves behind."""
    approval_id = await _approved(kernel, company, parameters=parameters)

    with pytest.raises(CapabilityExecutionError):
        await as_business(
            company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
        )
    assert sent == []


async def test_a_complete_payload_still_publishes(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """Negative control: the refusal is about emptiness, not about publishing."""
    approval_id = await _approved(
        kernel, company, parameters={"title": "Best Trail Runners", "body": "The full review."}
    )

    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert outcome["executed"] is True
    assert len(sent) == 1
    assert await _violations(kernel, "tool.refused") == []


async def test_the_tool_refuses_on_its_own_account() -> None:
    """Defence in depth: the executor checks, and so does the tool.

    The executor's check is the audited one, but a tool reached by any other
    path must not publish a blank because the caller forgot to look.
    """
    tool = WebhookPublishTool(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    )
    with pytest.raises(CapabilityExecutionError) as caught:
        await tool.run({"webhook_url": WEBHOOK_URL, "title": "T"}, "secret")
    assert caught.value.permanent


def test_the_required_parameters_are_declared_beside_the_tool() -> None:
    """D-024's shape: per-tool facts live with the tool, not in the executor."""
    assert REQUIRED_PARAMS["webhook_publish"] == frozenset({"title", "body"})


async def test_an_unpermitted_tool_denial_is_recorded(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M6-F39, found by the sweep: this §10 denial was raised in total silence.

    Not rolled back — never written. An operator asking why a company did
    nothing saw a cycle that quietly did less, with no record that a boundary
    had refused anything.
    """
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        executor = kernel.build_tools(svc)
        with pytest.raises(ScopeViolationError):
            await executor.execute(
                contract=contract,
                invocation_id=InvocationId("inv_x"),
                tool_name="wire_transfer",
                implementation_key="webhook_publish",
                action_type="affiliate.publish_post",
                params={"title": "T", "body": "B"},
            )

    rows = await _violations(kernel, "tool.refused")
    assert [row.payload["reason"] for row in rows] == ["tool_not_permitted"]
    assert rows[0].payload["tool"] == "wire_transfer"
