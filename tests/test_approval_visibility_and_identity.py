"""What the operator authorises, and who the platform thinks is asking (M6-4a).

Spec §8, §10, §12.5; D-002, D-010, D-011, D-024; A-003.

The M6-4 architecture audit left two code findings, and both live at the point
where a mistake authorises the wrong thing.

**The operator could not see what they were approving.** D-024.1 made an
approval's `parameters` the actual bytes an effect publishes — composed from
capability output that read untrusted external content. The approval surface
showed the four §8 facts and rendered `detail`; the bytes were never on the
screen. D-011 exists because attacker-influenced prose must not sit between a
decision and the authorisation, and an unread payload is that same gap with the
text simply absent. So the payload is now on the card, whole, and correctable
before the yes — and a correction resets the graduation ladder (D-010), which is
what stops an action graduating on approvals nobody read.

**The Manager's activities trusted the id in their own payload.** Every other
activity boundary derives identity from the Temporal workflow id (D-002);
`ManagerActivities` did not, and `execute_approved_action` resolved a contract,
a credential, and an effect from an approval row selected by a payload-carried
id. The derived-identity check is asserted here per path, with the negative
control that matters: a mismatched calling identity is refused and audited.
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

from jarvis.api.app import create_app
from jarvis.approvals.models import ApprovalRequest
from jarvis.approvals.rendering import (
    contains_technical_language,
    payload_is_correctable,
    render_payload,
)
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.capabilities import tools as tools_module
from jarvis.capabilities.tools import WebhookPublishTool
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import BusinessId, DecisionId
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager.activities import ManagerActivities
from jarvis.manager.types import PlanRequest
from jarvis.persistence.models import ApprovalRow, AuditLogRow, AutonomyCounterRow, Base
from tests.conftest import as_business

WEBHOOK_SECRET = "s3cr3t-blog-token"  # noqa: S105 — a test value, not a real credential
WEBHOOK_URL = "https://blog.example/publish"

DRAFT = (
    "Best Trail Runners For Overpronators\n\nDisclosure: this post contains affiliate links.\n\n"
) + ("Body paragraph that the company wrote and the compliance step read. " * 40)
"""Long on purpose. §8 asks the operator to see the specific action; a payload
shown as a first line and an ellipsis is a payload they did not read."""

ANOTHER_BUSINESS = BusinessId("biz_" + "b" * 32)
"""A well-formed id belonging to no company here — the shape a mis-assembled
workflow payload would carry."""

DASHBOARD = pathlib.Path("jarvis/api/static/index.html")
ACTIVITIES_SOURCE = pathlib.Path("jarvis/manager/activities.py")


# ── a real Kernel, a real API, one mock endpoint ───────────────────────────


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
    """Settings carrying the credential and its destination.

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


@pytest_asyncio.fixture
async def api(kernel: PlatformKernel) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client speaking to the real operator API."""
    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _pending(
    kernel: PlatformKernel,
    company: BusinessId,
    *,
    approval_id: str = "apr_publish",
    parameters: dict[str, Any] | None = None,
) -> str:
    """Raise one publish approval through the real service."""
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).request(
            request=ApprovalRequest(
                approval_id=approval_id,
                business_id=company,
                action_type="affiliate.publish_post",
                action_summary="publish the trail-runner review",
                triggering_condition="The draft passed its checks this morning.",
                downside="A weak post could cost a few readers' trust.",
                parameters={"title": "Best Trail Runners", "body": DRAFT}
                if parameters is None
                else parameters,
            ),
            contract=contract,
        )
    return approval_id


async def _counter(kernel: PlatformKernel, company: BusinessId) -> AutonomyCounterRow | None:
    async with kernel.services() as svc:
        return await svc.session.get(AutonomyCounterRow, (company, "affiliate.publish_post"))


# ── Part 1: the operator sees the bytes (§8, D-011, D-024.1) ───────────────


async def test_the_queue_carries_the_payload_the_effect_will_publish(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """The M6-4 audit's first finding, at the route that showed it.

    `parameters` are the published bytes since D-024.1. The queue returned the
    four §8 facts and never them, so the operator authorised content they had
    not been shown.
    """
    await _pending(kernel, company)

    item = (await api.get("/api/approvals")).json()[0]

    payload = {field["key"]: field["value"] for field in item["payload"]}
    assert payload["body"] == DRAFT, "the whole draft, byte for byte"
    assert payload["title"] == "Best Trail Runners"
    assert item["payload_correctable"] is True


async def test_the_payload_is_labelled_in_operator_language(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """§12.5: the labels are language, not field names from a schema dump."""
    await _pending(kernel, company)

    fields = (await api.get("/api/approvals")).json()[0]["payload"]

    assert [field["label"] for field in fields] == ["Title", "What it says"]
    for field in fields:
        assert not contains_technical_language(field["label"])


def test_the_payload_renders_in_a_stable_order() -> None:
    """Two operators reading one approval must be reading the same thing."""
    one = render_payload({"body": "b", "title": "t", "extra_note": "n"})
    two = render_payload({"extra_note": "n", "title": "t", "body": "b"})
    assert [field["key"] for field in one] == ["title", "body", "extra_note"]
    assert one == two


def test_an_unlabelled_field_is_still_shown_in_full() -> None:
    """A field nobody named is a field the operator still has to see."""
    (field,) = render_payload({"summary_line": "the words"})
    assert field == {"key": "summary_line", "label": "Summary line", "value": "the words"}


def test_a_payload_that_cannot_round_trip_is_shown_but_not_edited() -> None:
    """A number edited as text would come back a string, and `approve` would read
    that type change as a correction the operator never made (A-003)."""
    parameters: dict[str, object] = {"title": "t", "copies": 3}
    assert payload_is_correctable(parameters) is False
    assert [field["value"] for field in render_payload(parameters)] == ["t", "3"]
    assert payload_is_correctable({}) is False, "nothing to correct is not correctable"


# ── Part 1b: the correction affordance, end to end (A-003, D-010) ──────────


async def test_an_edit_through_the_api_lands_as_the_decided_parameters(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """The operator's edit is what the platform stores, under A-003's name."""
    approval_id = await _pending(kernel, company)

    response = await api.post(
        f"/api/approvals/{approval_id}/approve",
        json={"modified_parameters": {"title": "A safer title", "body": DRAFT}},
    )

    assert response.status_code == 200
    async with kernel.services() as svc:
        row = await svc.session.get(ApprovalRow, approval_id)
    assert row is not None
    assert row.decided_parameters == {"title": "A safer title", "body": DRAFT}
    assert row.parameters["title"] == "Best Trail Runners", "the original is still on the record"


async def test_a_correction_through_the_api_resets_the_graduation_streak(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """D-010, through the path an operator actually uses.

    `affiliate.publish_post` graduates at five clean approvals. Four clean ones
    followed by an edited one must leave the ladder at the bottom — treating an
    edited approval as an endorsement would graduate the form the operator
    rejected.
    """
    for n in range(4):
        approval_id = await _pending(kernel, company, approval_id=f"apr_clean_{n}")
        assert (await api.post(f"/api/approvals/{approval_id}/approve", json={})).status_code == 200

    counter = await _counter(kernel, company)
    assert counter is not None and counter.consecutive_approvals == 4

    approval_id = await _pending(kernel, company, approval_id="apr_edited")
    await api.post(
        f"/api/approvals/{approval_id}/approve",
        json={"modified_parameters": {"title": "Reworded", "body": DRAFT}},
    )

    counter = await _counter(kernel, company)
    assert counter is not None
    assert counter.consecutive_approvals == 0
    assert counter.graduated is False
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        assert await kernel.build_approvals(svc).requires_approval(
            contract, "affiliate.publish_post"
        )


async def test_an_unchanged_payload_sent_back_is_not_a_correction(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """Negative control. The dashboard posts what the fields hold; if merely
    submitting them counted as an edit, no action could ever graduate and D-010
    would be a ban rather than a rule."""
    approval_id = await _pending(kernel, company)

    await api.post(
        f"/api/approvals/{approval_id}/approve",
        json={"modified_parameters": {"title": "Best Trail Runners", "body": DRAFT}},
    )

    counter = await _counter(kernel, company)
    assert counter is not None and counter.consecutive_approvals == 1
    async with kernel.services() as svc:
        row = await svc.session.get(ApprovalRow, approval_id)
    assert row is not None and row.decided_parameters is None


async def test_the_effect_publishes_the_corrected_bytes(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient, sent: list[httpx.Request]
) -> None:
    """D-024.1 extended: corrected values are still *stored* values.

    The whole chain in one assertion — the operator edits on the card, the edit
    is stored as the decided parameters, and the tool sends those and not the
    draft the model composed.
    """
    approval_id = await _pending(
        kernel, company, parameters={"title": "As drafted", "body": "As drafted, in full."}
    )

    await api.post(
        f"/api/approvals/{approval_id}/approve",
        json={"modified_parameters": {"title": "As corrected", "body": "As corrected, in full."}},
    )
    await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert len(sent) == 1
    assert b"As corrected, in full." in sent[0].content
    assert b"As drafted" not in sent[0].content


async def test_a_correction_may_not_add_a_field_the_operator_never_saw(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """The operator owns the values; the tool owns the set of fields (D-024).

    M6-F30 was this from the model's side — `webhook_url` arriving as an action
    parameter — and D-024.2 answers it at the tool boundary. This closes the
    operator's side of the same surface one step earlier: a field nobody was
    shown is a field nobody approved, so the decision is refused rather than
    partially honoured, and the attempt is recorded.
    """
    approval_id = await _pending(kernel, company)

    response = await api.post(
        f"/api/approvals/{approval_id}/approve",
        json={
            "modified_parameters": {
                "title": "Best Trail Runners",
                "body": DRAFT,
                "webhook_url": "https://attacker.example/collect",
            }
        },
    )

    assert response.status_code == 409
    assert not contains_technical_language(response.json()["detail"])
    async with kernel.services() as svc:
        row = await svc.session.get(ApprovalRow, approval_id)
        rows = list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(
                        AuditLogRow.event_type == "approval.correction_refused"
                    )
                )
            ).all()
        )
    assert row is not None and row.state == "pending", "a refused correction decides nothing"
    assert len(rows) == 1
    assert rows[0].payload["added_fields"] == ["webhook_url"]


# ── Part 1c: the graduation guard (spec §8, D-010) ─────────────────────────


async def test_publish_post_cannot_graduate_on_approvals_the_reset_wiped(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """The guard applied to the live streak this packet found (M6-4a).

    Approvals decided before the payload was visible cannot be allowed to carry
    an action to autonomy: the operator never saw what they were agreeing to, so
    the streak does not mean what §8 needs it to mean. The mechanism is the one
    §12.5 already requires — the operator-facing reset — not a database edit, so
    the wipe is a recorded platform action like any other.
    """
    for n in range(5):
        approval_id = await _pending(kernel, company, approval_id=f"apr_blind_{n}")
        await api.post(f"/api/approvals/{approval_id}/approve", json={})

    graduated = await _counter(kernel, company)
    assert graduated is not None and graduated.graduated is True, (
        "five clean approvals graduate the action — the state the reset has to undo"
    )

    reset = await api.post(f"/api/companies/{company}/revoke/affiliate.publish_post")

    assert reset.status_code == 200
    counter = await _counter(kernel, company)
    assert counter is not None
    assert counter.consecutive_approvals == 0
    assert counter.graduated is False
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        assert await kernel.build_approvals(svc).requires_approval(
            contract, "affiliate.publish_post"
        )


async def test_the_reset_is_audited(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """§11: a streak wiped without a record is a streak nobody can account for."""
    await _pending(kernel, company)
    await api.post("/api/approvals/apr_publish/approve", json={})
    await api.post(f"/api/companies/{company}/revoke/affiliate.publish_post")

    async with kernel.services() as svc:
        rows = list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == "autonomy.reset")
                )
            ).all()
        )

    assert [row.payload["reason"] for row in rows] == ["revoked_by_operator"]
    assert rows[0].payload["action_type"] == "affiliate.publish_post"


# ── Part 1d: the card the operator reads (§12.5) ───────────────────────────


def _script() -> str:
    """Return the dashboard's script text."""
    import re

    source = DASHBOARD.read_text()
    return "".join(re.findall(r"<script.*?>(.*?)</script>", source, flags=re.S))


def test_the_approval_card_shows_the_payload() -> None:
    """Not a teaser and not a drill-down: the bytes are on the card that
    authorises them, open, with a heading an owner understands."""
    script = _script()
    assert "${outgoing(a)}" in script, "the approval card renders the payload"
    assert "What will go out" in script
    assert 'class="outgoing" open' in script, "shown, not folded away behind a click"


def test_the_card_offers_the_correction_and_says_what_it_costs() -> None:
    """§12.5 and D-010 together: the operator can change it, and is told that
    changing it means Jarvis keeps asking."""
    script = _script()
    assert "corrections(id)" in script
    assert "modified_parameters" in script
    assert "Jarvis keeps asking you about this one." in script


@pytest.mark.parametrize(
    "unescaped",
    ["${a.ask}", "${a.id}", "${v}", "${f.value}", "${f.label}", "${f.key}", "${a.company_id}"],
)
def test_the_approval_card_escapes_every_value_it_renders(unescaped: str) -> None:
    """Nothing on this card is trusted text.

    The sentences are model-authored and the payload is content the company read
    off the open internet (§13 Step 5). Interpolated raw into markup, either can
    carry script — and script on the approval card can press the card's own
    Approve button, which turns the §8 gate into a formality. So the values are
    escaped, and that is asserted rather than reviewed.
    """
    assert unescaped not in _script()


def test_the_escaper_covers_every_character_that_can_open_a_tag() -> None:
    """A guard that misses a quote is a guard that stops nothing."""
    script = _script()
    assert "const esc =" in script
    for char in ("'&':", "'<':", "'>':", "'\"':", '"\'":'):
        assert char in script


# ── Part 2: identity is derived, never declared (D-002, §10) ───────────────


def _activity_methods() -> list[ast.AsyncFunctionDef]:
    """Return every `@activity.defn` method on `ManagerActivities`."""
    tree = ast.parse(ACTIVITIES_SOURCE.read_text())
    klass = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ManagerActivities"
    )
    return [
        node
        for node in klass.body
        if isinstance(node, ast.AsyncFunctionDef)
        and any("activity.defn" in ast.unparse(d) for d in node.decorator_list)
    ]


def test_there_are_activities_to_check() -> None:
    """A structural assertion over an empty set passes for the wrong reason."""
    assert len(_activity_methods()) >= 7


@pytest.mark.parametrize("method", _activity_methods(), ids=lambda m: m.name)
def test_every_manager_activity_derives_and_checks_its_identity(
    method: ast.AsyncFunctionDef,
) -> None:
    """The M6-4 audit's second finding, generalised and kept closed.

    The audit found `execute_approved_action` trusting a payload-carried id.
    Fixing only that one would leave the next activity to be written free to
    repeat it, so the property is asserted over the class: every activity
    derives identity from the runtime and compares it to whatever its payload
    claims. Source-level because the alternative — a live call per path — proves
    it for the paths someone remembered to add.
    """
    body = ast.unparse(method)
    assert "RuntimeIdentity.from_activity()" in body, f"{method.name} never derives an identity"
    assert "self._assert_identity(" in body, f"{method.name} never checks the id it was given"


async def test_a_mismatched_calling_identity_cannot_run_an_approved_action(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """The negative control the packet asks for.

    The approval id selects the row, and everything else — contract, credential
    handle, destination — follows from it. A Manager running for another company
    that presents this id would otherwise perform this company's approved action
    with a credential resolved from this company's contract. §10 says that must
    not happen "under any circumstance, including bugs".
    """
    approval_id = await _pending(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_yes")
        )

    with pytest.raises(ScopeViolationError):
        await as_business(
            ANOTHER_BUSINESS,
            ManagerActivities(kernel).execute_approved_action,
            {"approval_id": approval_id},
        )

    assert sent == [], "nothing reaches the endpoint on a refused identity"


async def test_the_refusal_is_audited_and_survives_the_refusal(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """A denial nobody can see is the signal an operator most needs (§11).

    Worth its own test because the obvious implementation loses it: the audit
    entry is written inside a transaction that the raised refusal would roll
    back, so the record is taken in its own scope before the refusal travels.
    """
    approval_id = await _pending(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_yes")
        )

    with pytest.raises(ScopeViolationError):
        await as_business(
            ANOTHER_BUSINESS,
            ManagerActivities(kernel).execute_approved_action,
            {"approval_id": approval_id},
        )

    async with kernel.services() as svc:
        rows = list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == "security.scope_violation")
                )
            ).all()
        )

    assert len(rows) == 1
    assert rows[0].business_id == ANOTHER_BUSINESS, "recorded against whoever asked"
    assert rows[0].payload["reason"] == "identity_mismatch"
    assert rows[0].payload["declared"] == company
    assert rows[0].payload["reached"] == "credential and effect"
    assert rows[0].payload["identity_source"] == "activity"


async def test_a_mismatched_identity_cannot_reach_a_contract_either(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The check is not specific to the effect path.

    `plan_cycle` reads the tool scope, credential refs, memory scope, and budget
    it attaches to every request straight off the contract it loads — so which
    contract it loads is the whole of §2.2's scoping.
    """
    with pytest.raises(ScopeViolationError):
        await as_business(
            ANOTHER_BUSINESS,
            ManagerActivities(kernel).plan_cycle,
            PlanRequest(business_id=company),
        )


async def test_a_matching_identity_still_runs(
    kernel: PlatformKernel, company: BusinessId, sent: list[httpx.Request]
) -> None:
    """Negative control for the controls: a check that refused everything would
    pass every test above and close the platform."""
    approval_id = await _pending(kernel, company)
    async with kernel.services() as svc:
        contract = await svc.registry.get_contract(company)
        await kernel.build_approvals(svc).approve(
            approval_id, contract=contract, decision_id=DecisionId("dec_yes")
        )

    outcome = await as_business(
        company, ManagerActivities(kernel).execute_approved_action, {"approval_id": approval_id}
    )

    assert outcome["executed"] is True
    assert len(sent) == 1


async def test_an_activity_with_no_calling_workflow_has_no_identity(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M6-F4's posture, now binding on the Manager's activities too: an
    unidentifiable caller is refused, never defaulted."""
    approval_id = await _pending(kernel, company)

    with pytest.raises(ScopeViolationError):
        await ManagerActivities(kernel).execute_approved_action({"approval_id": approval_id})


def test_the_declared_id_is_still_bounded_when_it_is_recorded() -> None:
    """The rejected id is attacker-shaped input and reaches the audit log; it is
    truncated there, like every other untrusted string this platform records."""
    source = ACTIVITIES_SOURCE.read_text()
    assert "str(declared_business_id)[:200]" in source


async def test_the_amount_and_the_payload_are_both_stored_values(
    kernel: PlatformKernel, company: BusinessId, api: httpx.AsyncClient
) -> None:
    """D-011 restated across both halves of the surface.

    The amount was already rendered from a stored column. The payload now is
    too, and by the same mechanism — deterministic assembly, no second model
    call between the decision and the authorisation.
    """
    await _pending(kernel, company, parameters={"title": "T", "body": "B"})
    async with kernel.services() as svc:
        row = await svc.session.get(ApprovalRow, "apr_publish")
        assert row is not None
        row.amount_usd = Decimal("42.50")
        await svc.session.flush()

    item = (await api.get("/api/approvals")).json()[0]

    assert item["detail"]["How much"] == "$42.50"
    assert [field["value"] for field in item["payload"]] == ["T", "B"]
