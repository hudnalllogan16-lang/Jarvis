"""Tool execution boundary (spec §6, §10; decision D-015).

This is the boundary D-002's note promised and `CredentialManager` has waited
for since M2: the single place where a credential handle becomes a secret. The
secret exists inside the tool implementation's HTTP call and nowhere else — it
is never in a prompt, never in a log, never in a result (spec §10).

D-015 fixes where tools run in the flow. Capabilities *produce content*; tools
*perform effects*; and effects run only on the approved-action path. A model
call can therefore never cause a side effect directly — the chain is always
Manager proposes → §8 approval (or graduated autonomy) → ToolExecutor. The
alternative, letting capabilities call tools mid-completion, would put an
external effect inside a model's reasoning loop, where neither the approval
gate nor the idempotency key has happened yet.

Every effect is idempotent by construction (spec §6): the executor consults the
IdempotencyStore under the A-001 key before running, and records after. A retry
or replay of an approved action replays the recorded result instead of
publishing twice.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from jarvis.capabilities.idempotency import IdempotencyStore, idempotency_key
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import CapabilityExecutionError, ScopeViolationError
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.kernel.logging import get_logger
from jarvis.observability.audit import AuditLog
from jarvis.security.credentials import CredentialManager

logger = get_logger(__name__)


class Tool(Protocol):
    """One effect-performing tool implementation."""

    async def run(self, params: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """Perform the effect.

        Args:
            params: Action parameters, already operator-approved when approval
                was required (spec §8).
            secret: Resolved credential material, or None for tools needing
                none. Exists only for the duration of this call.

        Returns:
            A JSON-safe result, recorded under the idempotency key.

        Raises:
            CapabilityExecutionError: On failure. ``permanent=True`` when a
                retry cannot help.
        """
        ...


class WebhookPublishTool:
    """Publishes content by POSTing to a per-instance webhook.

    The webhook URL is instance configuration; the bearer secret is a credential
    handle resolved at this boundary. Real enough to exercise the whole path —
    approval, credentials, idempotency, audit — against an actual HTTP endpoint.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Args:
        client: Injectable client, so tests use MockTransport.
        """
        self._client = client or httpx.AsyncClient(timeout=30)

    async def run(self, params: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """POST the post to the configured webhook."""
        url = params.get("webhook_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise CapabilityExecutionError(
                "publish_post requires an https webhook_url parameter",
                permanent=True,
            )
        if not str(params.get("title", "")).strip() or not str(params.get("body", "")).strip():
            # M6-F37. This used to POST `{"title": "", "body": ""}` — the
            # `.get(name, "")` defaults below turned an empty payload into a
            # published empty post. `_effect_parameters` documents the opposite
            # ("fails at the tool boundary rather than silently publishing
            # nothing") and composes `{}` whenever a cycle produced nothing
            # publishable, so the two halves of that contract disagreed and the
            # tool's half was the one that ran. The executor checks this too;
            # keeping it here means a tool called by any other path still
            # refuses rather than publishing a blank.
            raise CapabilityExecutionError(
                "publish_post requires a title and a body; refusing to publish an empty post",
                permanent=True,
                operator_message="Jarvis didn't publish anything — there was nothing to publish.",
            )
        if not secret:
            # A missing secret fails loudly rather than degrading to an
            # unauthenticated POST. The previous form sent no authorization
            # header at all when resolution produced nothing, which turns a
            # credential misconfiguration into a publish to an endpoint that
            # never asked who was calling (spec §10).
            raise CapabilityExecutionError(
                "publish_post requires its credential; refusing to publish unauthenticated",
                permanent=True,
            )
        headers = {"authorization": f"Bearer {secret}"}
        try:
            response = await self._client.post(
                url,
                json={"title": params.get("title", ""), "body": params.get("body", "")},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CapabilityExecutionError(
                f"publish endpoint returned HTTP {exc.response.status_code}",
                permanent=400 <= exc.response.status_code < 500,
            ) from exc
        except httpx.HTTPError as exc:
            raise CapabilityExecutionError(
                f"publish transport failure: {type(exc).__name__}"
            ) from exc
        return {"published": True, "status": response.status_code}


BUILTIN_TOOLS: dict[str, Tool] = {"webhook_publish": WebhookPublishTool()}
"""Implementation key -> tool. Type definitions map tool names onto these keys
(D-014 ``tool_registry``); instances grant names via ``tool_scope``."""

REQUIRED_PARAMS: dict[str, frozenset[str]] = {"webhook_publish": frozenset({"title", "body"})}
"""Implementation key -> parameters without which this tool's effect is empty.

Declared beside the tool, like `DESTINATION_PARAM`, so the executor can refuse a
hollow effect without knowing any tool's semantics. The executor is where the
refusal has to be *audited*: the tool holds no audit log, and a refusal nobody
recorded is indistinguishable afterwards from an effect nobody attempted
(M6-F37, §11)."""

DESTINATION_PARAM: dict[str, str] = {"webhook_publish": "webhook_url"}
"""Implementation key -> the parameter naming where this tool's effect goes.

Declared here, beside the tool that reads it, so the approved-action path can
attach a destination from Kernel configuration without knowing any tool's
parameter vocabulary. The destination is deliberately *not* carried in the
approved parameters: a value an operator can edit, or a model can propose, is a
value that can point a credentialled publish at an arbitrary host."""


class ToolExecutor:
    """Runs one approved effect with scoped credentials and idempotency."""

    def __init__(
        self,
        *,
        credentials: CredentialManager,
        idempotency: IdempotencyStore,
        audit: AuditLog,
        tools: dict[str, Tool] | None = None,
    ) -> None:
        """Args:
        credentials: Resolves handles at this boundary and nowhere else (§10).
        idempotency: A-001 effect guard (§6).
        audit: Every effect is audited, replayed or fresh (§11).
        tools: Implementation registry; defaults to the builtins.
        """
        self._credentials = credentials
        self._idempotency = idempotency
        self._audit = audit
        self._tools = tools if tools is not None else BUILTIN_TOOLS

    async def execute(
        self,
        *,
        contract: BusinessContract,
        invocation_id: InvocationId,
        tool_name: str,
        implementation_key: str,
        action_type: str,
        params: dict[str, Any],
        credential_handle: str | None = None,
        granted_credentials: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Run one effect, or replay it if it already ran.

        Args:
            contract: The acting business's contract.
            invocation_id: Owning invocation — the retry-stable key component.
            tool_name: The tool as the instance's ``tool_scope`` names it.
            implementation_key: From the type's ``tool_registry`` (D-014).
            action_type: Namespaced action (A-003), for the idempotency key.
            params: Effect parameters — the operator-approved values when
                approval was required.
            credential_handle: Handle to resolve, if the tool needs one.
            granted_credentials: Handles this invocation was granted (§2.2).

        Returns:
            The effect's result — recorded on first run, replayed thereafter.

        Raises:
            ScopeViolationError: If the tool is outside every permission's
                tool_scope, or the credential fails resolution (§10).
            CapabilityExecutionError: If the implementation is unknown or the
                effect fails.
        """
        permitted = {name for p in contract.capability_permissions for name in p.tool_scope}
        if tool_name not in permitted:
            # Audited from here on. This denial was previously raised in
            # silence: §10's boundary refused the call and left nothing behind
            # saying it had, so an operator asking what happened saw a cycle
            # that simply did less (M6-F39).
            await self._refuse(
                contract,
                tool_name=tool_name,
                action_type=action_type,
                reason="tool_not_permitted",
            )
            raise ScopeViolationError(
                f"business {contract.business_id} has no permission for tool "
                f"{tool_name!r} (spec §2.2)"
            )

        tool = self._tools.get(implementation_key)
        if tool is None:
            raise CapabilityExecutionError(
                f"no implementation registered under {implementation_key!r}",
                permanent=True,
            )

        missing = sorted(
            name
            for name in REQUIRED_PARAMS.get(implementation_key, frozenset())
            if not str(params.get(name, "")).strip()
        )
        if missing:
            # Checked before the idempotency key is taken: a refused effect must
            # not record a key, or the retry that arrives with a real payload
            # would replay the refusal as though it had already happened.
            await self._refuse(
                contract,
                tool_name=tool_name,
                action_type=action_type,
                reason="empty_payload",
                extra={"missing": missing},
            )
            raise CapabilityExecutionError(
                f"{tool_name} was given no {' or '.join(missing)}; refusing to perform an "
                "effect with nothing in it (M6-F37)",
                permanent=True,
                operator_message="Jarvis didn't send anything out — there was nothing to send.",
            )

        key = idempotency_key(
            business_id=BusinessId(contract.business_id),
            invocation_id=invocation_id,
            action_type=action_type,
            payload=params,
        )
        existing = await self._idempotency.existing(key)
        if existing is not None:
            await self._audit.record(
                event_type="tool.replayed",
                actor=contract.business_id,
                business_id=BusinessId(contract.business_id),
                payload={"tool": tool_name, "action_type": action_type},
            )
            return existing

        secret = (
            self._credentials.resolve(
                contract=contract,
                handle=credential_handle,
                granted_handles=granted_credentials,
            ).get_secret_value()
            if credential_handle
            else None
        )

        result = await tool.run(params, secret)

        await self._idempotency.record(
            key=key,
            business_id=BusinessId(contract.business_id),
            action_type=action_type,
            result=result,
        )
        await self._audit.record(
            event_type="tool.executed",
            actor=contract.business_id,
            business_id=BusinessId(contract.business_id),
            payload={"tool": tool_name, "action_type": action_type},
        )
        return result

    async def _refuse(
        self,
        contract: BusinessContract,
        *,
        tool_name: str,
        action_type: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record that an effect was refused, before the refusal is raised.

        Written independently of the caller's transaction (M6-F38): the raise
        that follows unwinds the scope this runs in, and an entry rolled back
        with it would leave the platform silently doing less than it was asked
        to. Recording only, never raising — the call site raises, so the
        refusal and its reason stay next to each other.
        """
        await self._audit.record_independently(
            event_type="tool.refused",
            actor=contract.business_id,
            business_id=BusinessId(contract.business_id),
            payload={
                "tool": tool_name,
                "action_type": action_type,
                "reason": reason,
                **(extra or {}),
            },
        )
        logger.warning(
            "refused an effect",
            extra={"context": {"reason": reason, "business_id": contract.business_id}},
        )
