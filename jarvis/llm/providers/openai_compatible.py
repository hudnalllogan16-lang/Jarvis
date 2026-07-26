"""OpenAI-compatible chat-completions transport.

Covers OpenAI, OpenRouter, LM Studio, Kimi, and Ollama — five of the seven named
providers — because all five expose the same `/chat/completions` contract and
differ only by base URL and auth (A-005). One transport, five vendors, zero
business-logic impact.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from jarvis.kernel.config import LOCAL_PROVIDERS, LLMSettings
from jarvis.kernel.errors import ProviderError
from jarvis.llm.base import CompletionRequest, CompletionResponse, Role, StopReason, Usage
from jarvis.llm.providers._http import post_json

_STOP_REASONS: Final[dict[str, StopReason]] = {
    "stop": StopReason.END_TURN,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.CONTENT_FILTER,
    "tool_calls": StopReason.OTHER,
}


class OpenAICompatibleProvider:
    """`LLMProvider` implementation for any OpenAI-compatible endpoint."""

    def __init__(self, settings: LLMSettings, client: httpx.AsyncClient | None = None) -> None:
        """Args:
        settings: LLM configuration, including which vendor is selected.
        client: Optional injected client, for tests.
        """
        self._settings = settings
        headers = {"content-type": "application/json"}
        if settings.provider not in LOCAL_PROVIDERS:
            headers["authorization"] = f"Bearer {settings.require_api_key()}"
        self._client = client or httpx.AsyncClient(
            base_url=settings.resolved_base_url(),
            timeout=settings.timeout_seconds,
            headers=headers,
        )

    @property
    def name(self) -> str:
        """Return the configured vendor name, for audit records only."""
        return self._settings.provider.value

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one chat completion."""
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend({"role": _role(m.role), "content": m.content} for m in request.messages)

        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.stop_sequences:
            payload["stop"] = list(request.stop_sequences)

        body = await post_json(self._client, "/chat/completions", payload, provider=self.name)
        choices: list[dict[str, Any]] = body.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name} response contained no choices")

        first: dict[str, Any] = choices[0]
        message: dict[str, Any] = first.get("message") or {}
        text: str = message.get("content") or ""
        if not text:
            raise ProviderError(f"{self.name} response contained no message content")

        usage: dict[str, Any] = body.get("usage") or {}
        return CompletionResponse(
            text=text,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
            stop_reason=_STOP_REASONS.get(str(first.get("finish_reason")), StopReason.OTHER),
            raw_stop_reason=first.get("finish_reason"),
            model=str(body.get("model", self._settings.model)),
        )

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._client.aclose()


def _role(role: Role) -> str:
    return "assistant" if role is Role.ASSISTANT else "user"
