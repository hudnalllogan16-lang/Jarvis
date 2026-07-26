"""Tool execution boundary tests (spec §6, §10; D-015)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.capabilities.idempotency import IdempotencyStore
from jarvis.capabilities.tools import ToolExecutor, WebhookPublishTool
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import CapabilityExecutionError, ScopeViolationError
from jarvis.kernel.ids import InvocationId
from jarvis.observability.audit import AuditLog
from jarvis.security.credentials import CredentialManager


def _executor(
    session: AsyncSession,
    *,
    requests_seen: list[httpx.Request] | None = None,
    secrets: dict[str, str] | None = None,
) -> ToolExecutor:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests_seen is not None:
            requests_seen.append(request)
        return httpx.Response(200, json={"ok": True})

    tool = WebhookPublishTool(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return ToolExecutor(
        credentials=CredentialManager(
            secrets if secrets is not None else {"affiliate_blog_webhook": "blog-secret"}
        ),
        idempotency=IdempotencyStore(session),
        audit=AuditLog(session),
        tools={"webhook_publish": tool},
    )


def _params() -> dict[str, object]:
    return {"webhook_url": "https://blog.example/publish", "title": "T", "body": "B"}


async def _publish(
    executor: ToolExecutor,
    contract: BusinessContract,
    *,
    invocation: str = "inv_1",
    handle: str | None = "serp_key",
) -> dict[str, object]:
    return await executor.execute(
        contract=contract,
        invocation_id=InvocationId(invocation),
        tool_name="web_search",  # fixture contract grants web_search
        implementation_key="webhook_publish",
        action_type="affiliate.publish_post",
        params=_params(),
        credential_handle=handle,
        granted_credentials=frozenset({"serp_key"}),
    )


async def test_unpermitted_tool_is_refused(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §2.2: tool scope is permission, not suggestion."""
    executor = _executor(session)
    with pytest.raises(ScopeViolationError):
        await executor.execute(
            contract=contract,
            invocation_id=InvocationId("inv_1"),
            tool_name="wire_transfer",
            implementation_key="webhook_publish",
            action_type="affiliate.publish_post",
            params=_params(),
        )


async def test_secret_reaches_the_http_call_and_nowhere_else(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §10: the secret materialises in the request header only.

    The fixture contract grants ``serp_key``, so the manager here holds a value
    under that handle. The assertion is on the outgoing request: bearer present
    there, absent from the returned result.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    executor = ToolExecutor(
        credentials=CredentialManager({"serp_key": "real-secret"}),
        idempotency=IdempotencyStore(session),
        audit=AuditLog(session),
        tools={
            "webhook_publish": WebhookPublishTool(
                httpx.AsyncClient(transport=httpx.MockTransport(handler))
            )
        },
    )
    result = await _publish(executor, contract)
    assert result["published"] is True
    assert seen[0].headers["authorization"] == "Bearer real-secret"
    assert "real-secret" not in str(result)


async def test_unresolvable_credential_fails_loudly_not_empty(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A missing secret must never degrade to an unauthenticated call.

    The executor's manager below does not hold ``serp_key``, so resolution must
    raise — sending an empty bearer would turn a config error into a silent
    unauthenticated publish.
    """
    executor = _executor(session)  # manager holds only affiliate_blog_webhook
    with pytest.raises(ScopeViolationError):
        await _publish(executor, contract)


async def test_effect_is_idempotent_across_retries(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §6 + A-001: a retried approved action publishes once."""
    seen: list[httpx.Request] = []
    executor = _executor(session, requests_seen=seen, secrets={"serp_key": "real-secret"})
    first = await _publish(executor, contract)
    second = await _publish(executor, contract)
    assert first == second
    assert len(seen) == 1, "the second call must replay, not re-publish"


async def test_distinct_invocations_publish_separately(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Distinct invocations are distinct intents (A-001)."""
    seen: list[httpx.Request] = []
    executor = _executor(session, requests_seen=seen, secrets={"serp_key": "real-secret"})
    await _publish(executor, contract, invocation="inv_1")
    await _publish(executor, contract, invocation="inv_2")
    assert len(seen) == 2


async def test_http_url_is_refused(session: AsyncSession, contract: BusinessContract) -> None:
    """A bearer secret over plaintext http is a credential leak (spec §10).

    The params carry a title and a body deliberately. Without them the empty-
    payload refusal (M6-F37) fires first and this test would keep passing while
    testing something else entirely — the M5-F5 failure mode in miniature.
    """
    executor = _executor(session)
    with pytest.raises(CapabilityExecutionError) as exc:
        await executor.execute(
            contract=contract,
            invocation_id=InvocationId("inv_1"),
            tool_name="web_search",
            implementation_key="webhook_publish",
            action_type="affiliate.publish_post",
            params={**_params(), "webhook_url": "http://blog.example/publish"},
        )
    assert exc.value.permanent
    assert "webhook_url" in exc.value.technical_detail


async def test_unknown_implementation_fails_permanently(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Retrying a missing implementation only burns budget (spec §9)."""
    executor = _executor(session)
    with pytest.raises(CapabilityExecutionError) as exc:
        await executor.execute(
            contract=contract,
            invocation_id=InvocationId("inv_1"),
            tool_name="web_search",
            implementation_key="nonexistent",
            action_type="affiliate.publish_post",
            params=_params(),
        )
    assert exc.value.permanent


async def test_client_errors_do_not_retry_server_errors_do(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A 4xx will fail identically forever; a 5xx might not."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422)

    tool = WebhookPublishTool(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(CapabilityExecutionError) as exc:
        await tool.run(_params(), "real-secret")
    assert exc.value.permanent

    def handler5(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    tool5 = WebhookPublishTool(httpx.AsyncClient(transport=httpx.MockTransport(handler5)))
    with pytest.raises(CapabilityExecutionError) as exc5:
        await tool5.run(_params(), "real-secret")
    assert not exc5.value.permanent
