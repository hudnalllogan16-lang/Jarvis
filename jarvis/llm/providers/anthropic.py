"""Anthropic Messages API transport.

No model identifier is hardcoded: `settings.llm.model` is passed straight
through, so a model rename or deprecation is a configuration change (A-005).
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from jarvis.kernel.config import LLMSettings
from jarvis.kernel.errors import ProviderError
from jarvis.llm.base import CompletionRequest, CompletionResponse, StopReason, Usage
from jarvis.llm.providers._http import post_json

ANTHROPIC_VERSION = "2023-06-01"


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

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._client.aclose()
