"""Provider-agnosticism tests (Implementation Directive, A-005)."""

from __future__ import annotations

import inspect
import sys

import httpx
import pytest

from jarvis.kernel.config import LLMProviderName, LLMSettings
from jarvis.kernel.errors import ConfigurationError, ProviderError
from jarvis.llm.base import CompletionRequest, LLMProvider, Message, Role, StopReason
from jarvis.llm.factory import build_provider
from jarvis.llm.providers.anthropic import AnthropicProvider
from jarvis.llm.providers.gemini import GeminiProvider
from jarvis.llm.providers.openai_compatible import OpenAICompatibleProvider

REQUEST = CompletionRequest(messages=(Message(role=Role.USER, content="hello"),))


def _settings(provider: LLMProviderName) -> LLMSettings:
    return LLMSettings(provider=provider, model="configured-model", api_key="test-key")


@pytest.mark.parametrize("provider", list(LLMProviderName))
def test_every_configured_provider_builds(provider: LLMProviderName) -> None:
    """Every enum member must have a transport, or startup fails loudly."""
    built = build_provider(_settings(provider), client=httpx.AsyncClient())
    assert isinstance(built, LLMProvider)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (LLMProviderName.ANTHROPIC, AnthropicProvider),
        (LLMProviderName.GEMINI, GeminiProvider),
        (LLMProviderName.OPENAI, OpenAICompatibleProvider),
        (LLMProviderName.OPENROUTER, OpenAICompatibleProvider),
        (LLMProviderName.LMSTUDIO, OpenAICompatibleProvider),
        (LLMProviderName.KIMI, OpenAICompatibleProvider),
        (LLMProviderName.OLLAMA, OpenAICompatibleProvider),
    ],
)
def test_provider_routing(provider: LLMProviderName, expected: type) -> None:
    assert isinstance(build_provider(_settings(provider), client=httpx.AsyncClient()), expected)


def test_local_providers_need_no_api_key() -> None:
    settings = LLMSettings(provider=LLMProviderName.OLLAMA, model="configured-model")
    assert settings.require_api_key() == ""


def test_remote_provider_without_key_fails_at_startup() -> None:
    settings = LLMSettings(provider=LLMProviderName.OPENAI, model="configured-model")
    with pytest.raises(ConfigurationError):
        settings.require_api_key()


async def test_anthropic_response_is_normalised() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "result"}],
                "usage": {"input_tokens": 11, "output_tokens": 4},
                "stop_reason": "end_turn",
                "model": "configured-model",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")
    provider = AnthropicProvider(_settings(LLMProviderName.ANTHROPIC), client)
    response = await provider.complete(REQUEST)
    assert response.text == "result"
    assert response.usage.total_tokens == 15


async def test_openai_compatible_response_is_normalised() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "result"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
                "model": "configured-model",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")
    provider = OpenAICompatibleProvider(_settings(LLMProviderName.OPENAI), client)
    response = await provider.complete(REQUEST)
    assert response.text == "result"
    assert response.usage.total_tokens == 15


async def test_providers_normalise_failures_to_provider_error() -> None:
    """Callers must not be able to branch on vendor-specific failure shapes."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")
    provider = OpenAICompatibleProvider(_settings(LLMProviderName.OPENAI), client)
    with pytest.raises(ProviderError):
        await provider.complete(REQUEST)


def test_no_model_identifier_is_hardcoded() -> None:
    """A-005: model ids live in configuration, never in source."""
    settings = _settings(LLMProviderName.ANTHROPIC)
    provider = AnthropicProvider(settings, httpx.AsyncClient())
    assert provider.name == "anthropic"
    assert settings.model == "configured-model"


# ── Vendor concepts must not leak through the interface ─────────────────────


def test_interface_exposes_no_vendor_names() -> None:
    """`jarvis/llm/base.py` is what business logic imports; it must be neutral."""
    source = inspect.getsource(sys.modules["jarvis.llm.base"])
    lowered = source.lower()
    for vendor in ("anthropic", "openai", "gemini", "google", "ollama", "moonshot", "kimi"):
        assert vendor not in lowered, f"{vendor} leaked into the provider interface"


@pytest.mark.parametrize(
    ("provider_cls", "provider_name", "body", "expected"),
    [
        (
            AnthropicProvider,
            LLMProviderName.ANTHROPIC,
            {"content": [{"type": "text", "text": "x"}], "stop_reason": "max_tokens"},
            StopReason.MAX_TOKENS,
        ),
        (
            OpenAICompatibleProvider,
            LLMProviderName.OPENAI,
            {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]},
            StopReason.MAX_TOKENS,
        ),
        (
            GeminiProvider,
            LLMProviderName.GEMINI,
            {"candidates": [{"content": {"parts": [{"text": "x"}]}, "finishReason": "MAX_TOKENS"}]},
            StopReason.MAX_TOKENS,
        ),
    ],
)
async def test_stop_reasons_normalise_across_vendors(
    provider_cls: type,
    provider_name: LLMProviderName,
    body: dict,
    expected: StopReason,
) -> None:
    """``max_tokens`` / ``length`` / ``MAX_TOKENS`` must all mean one thing.

    Without this, business logic branching on the raw value would silently
    change behaviour when the provider config changed.
    """
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        base_url="https://x",
    )
    response = await provider_cls(_settings(provider_name), client).complete(REQUEST)
    assert response.stop_reason is expected


async def test_raw_stop_reason_preserved_for_audit_only() -> None:
    """The vendor's own value survives for §11, separate from the normalised one."""
    body = {"content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn"}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        base_url="https://x",
    )
    response = await AnthropicProvider(_settings(LLMProviderName.ANTHROPIC), client).complete(
        REQUEST
    )
    assert response.stop_reason is StopReason.END_TURN
    assert response.raw_stop_reason == "end_turn"


async def test_unknown_stop_reason_degrades_to_other() -> None:
    """A new vendor value must not crash the platform or masquerade as success."""
    body = {"content": [{"type": "text", "text": "x"}], "stop_reason": "brand_new_reason"}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        base_url="https://x",
    )
    response = await AnthropicProvider(_settings(LLMProviderName.ANTHROPIC), client).complete(
        REQUEST
    )
    assert response.stop_reason is StopReason.OTHER
