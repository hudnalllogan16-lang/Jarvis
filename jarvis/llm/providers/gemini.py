"""Google Gemini generateContent transport."""

from __future__ import annotations

from typing import Any, Final

import httpx

from jarvis.kernel.config import LLMSettings
from jarvis.kernel.errors import ProviderError
from jarvis.llm.base import (
    CompletionRequest,
    CompletionResponse,
    ModelListing,
    Role,
    StopReason,
    Usage,
)
from jarvis.llm.providers._http import get_json, post_json

MODEL_PAGE_SIZE = 1000
"""How many catalog entries one listing request asks for.

Deliberately above this API's documented maximum page size: it clamps rather
than refuses, so asking for more than can be returned is how one request gets
the whole list wherever that ceiling happens to sit. `nextPageToken` is what
decides whether it did."""

MODEL_NAME_PREFIX = "models/"
"""How this API namespaces a model in its catalog.

The configured id is the bare name — it is what `generateContent` is addressed
with below — so the prefix is stripped here rather than accommodated by the
caller, which would put one vendor's naming convention into provider-agnostic
code."""

_STOP_REASONS: Final[dict[str, StopReason]] = {
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.CONTENT_FILTER,
    "RECITATION": StopReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": StopReason.CONTENT_FILTER,
}


class GeminiProvider:
    """`LLMProvider` implementation for the Gemini API."""

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
                "content-type": "application/json",
                "x-goog-api-key": settings.require_api_key(),
            },
        )

    @property
    def name(self) -> str:
        """Return the provider name, for audit records only."""
        return "gemini"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one generateContent call."""
        payload: dict[str, Any] = {
            "contents": [
                {"role": _role(m.role), "parts": [{"text": m.content}]} for m in request.messages
            ],
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
            },
        }
        if request.temperature is not None:
            payload["generationConfig"]["temperature"] = request.temperature
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}
        if request.stop_sequences:
            payload["generationConfig"]["stopSequences"] = list(request.stop_sequences)

        url = f"/models/{self._settings.model}:generateContent"
        body = await post_json(self._client, url, payload, provider=self.name)

        candidates: list[dict[str, Any]] = body.get("candidates") or []
        if not candidates:
            raise ProviderError("gemini response contained no candidates")
        content: dict[str, Any] = candidates[0].get("content") or {}
        parts: list[dict[str, Any]] = content.get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise ProviderError("gemini response contained no text parts")

        usage: dict[str, Any] = body.get("usageMetadata") or {}
        return CompletionResponse(
            text=text,
            usage=Usage(
                input_tokens=int(usage.get("promptTokenCount", 0)),
                output_tokens=int(usage.get("candidatesTokenCount", 0)),
            ),
            stop_reason=_STOP_REASONS.get(str(candidates[0].get("finishReason")), StopReason.OTHER),
            raw_stop_reason=candidates[0].get("finishReason"),
            model=self._settings.model,
        )

    async def list_models(self) -> ModelListing:
        """Return the models this key may call (`ModelCatalog`).

        Entries are namespaced (`models/<id>`) and the configured id is not, so
        the prefix is stripped to whatever the caller would have to compare
        against. A `nextPageToken` means the list is partial, which the caller
        reads as "cannot tell" rather than as grounds to refuse a model.
        """
        body = await get_json(
            self._client, "/models", provider=self.name, params={"pageSize": MODEL_PAGE_SIZE}
        )
        entries: list[dict[str, Any]] = body.get("models") or []
        return ModelListing(
            ids=tuple(
                str(entry["name"]).removeprefix(MODEL_NAME_PREFIX)
                for entry in entries
                if entry.get("name")
            ),
            complete=not body.get("nextPageToken"),
        )

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._client.aclose()


def _role(role: Role) -> str:
    return "model" if role is Role.ASSISTANT else "user"
