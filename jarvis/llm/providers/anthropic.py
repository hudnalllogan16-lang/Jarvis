"""Anthropic Messages API transport.

No model identifier is hardcoded: `settings.llm.model` is passed straight
through, so a model rename or deprecation is a configuration change (A-005).
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from jarvis.kernel.config import LLMSettings
from jarvis.kernel.errors import ProviderError
from jarvis.llm.base import CompletionRequest, CompletionResponse, ModelListing, StopReason, Usage
from jarvis.llm.providers._http import get_json, post_json

ANTHROPIC_VERSION = "2023-06-01"

MODEL_PAGE_LIMIT = 1000
"""How many catalog entries one listing request asks for.

The endpoint's documented maximum, so the ordinary case is one page and a
complete list. It is a ceiling rather than a promise: `has_more` decides
whether the list this returns is complete, and the caller refuses to reject a
model on an incomplete one."""


_STOP_REASONS: Final[dict[str, StopReason]] = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.CONTENT_FILTER,
}


class AnthropicProvider:
    """`LLMProvider` implementation for the Anthropic Messages API."""

    def __init__(self, settings: LLMSettings, client: httpx.AsyncClient | None = None) -> None:
        """Args:
        settings: LLM configuration.
        client: Optional injected client, for tests.
        """
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.resolved_base_url(),
            timeout=settings.timeout_seconds,
            headers={
                "x-api-key": settings.require_api_key(),
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        """Return the provider name, for audit records only."""
        return "anthropic"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one completion against the Messages API."""
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
        }
        if request.temperature is not None:
            # Sent only when a caller chose one: current models reject a
            # non-default `temperature` with HTTP 400 (M6-F6).
            payload["temperature"] = request.temperature
        if request.system:
            payload["system"] = request.system
        if request.stop_sequences:
            payload["stop_sequences"] = list(request.stop_sequences)

        body = await post_json(self._client, "/v1/messages", payload, provider=self.name)
        blocks: list[dict[str, Any]] = body.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise ProviderError("anthropic response contained no text block")

        usage: dict[str, Any] = body.get("usage") or {}
        return CompletionResponse(
            text=text,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
            stop_reason=_STOP_REASONS.get(str(body.get("stop_reason")), StopReason.OTHER),
            raw_stop_reason=body.get("stop_reason"),
            model=str(body.get("model", self._settings.model)),
        )

    async def list_models(self) -> ModelListing:
        """Return the models this account may call (`ModelCatalog`).

        Read at worker startup so a configured model that this provider does
        not serve is refused before any company tries to think with it
        (M9-F118). One page, asked for at the endpoint's maximum, and the
        provider's own `has_more` is carried through rather than paged after:
        the caller treats an incomplete list as "cannot tell", so a second
        request would buy a stronger claim than the check is allowed to make
        anyway.
        """
        body = await get_json(
            self._client, "/v1/models", provider=self.name, params={"limit": MODEL_PAGE_LIMIT}
        )
        entries: list[dict[str, Any]] = body.get("data") or []
        return ModelListing(
            ids=tuple(str(entry["id"]) for entry in entries if entry.get("id")),
            complete=not body.get("has_more", False),
        )

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._client.aclose()
