"""Provider construction from configuration alone.

This is the *only* module in Jarvis that knows which vendors exist. Everything
else depends on the `LLMProvider` protocol, which is what makes the Directive's
"changing providers should require configuration only" true rather than
aspirational.
"""

from __future__ import annotations

from typing import Final

import httpx

from jarvis.kernel.config import LLMProviderName, LLMSettings
from jarvis.kernel.errors import ConfigurationError
from jarvis.llm.base import LLMProvider
from jarvis.llm.providers.anthropic import AnthropicProvider
from jarvis.llm.providers.gemini import GeminiProvider
from jarvis.llm.providers.openai_compatible import OpenAICompatibleProvider

_OPENAI_COMPATIBLE: Final[frozenset[LLMProviderName]] = frozenset(
    {
        LLMProviderName.OPENAI,
        LLMProviderName.OPENROUTER,
        LLMProviderName.LMSTUDIO,
        LLMProviderName.KIMI,
        LLMProviderName.OLLAMA,
    }
)


def build_provider(
    settings: LLMSettings, *, client: httpx.AsyncClient | None = None
) -> LLMProvider:
    """Construct the configured LLM provider.

    Args:
        settings: LLM configuration.
        client: Optional injected HTTP client, for tests.

    Returns:
        A provider implementing the `LLMProvider` protocol.

    Raises:
        ConfigurationError: If the configured provider has no transport. This is
            unreachable while the enum and the mapping agree, and exists so that
            adding an enum member without a transport fails loudly at startup
            rather than silently defaulting to some other vendor.
    """
    if settings.provider is LLMProviderName.ANTHROPIC:
        return AnthropicProvider(settings, client)
    if settings.provider is LLMProviderName.GEMINI:
        return GeminiProvider(settings, client)
    if settings.provider in _OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(settings, client)
    raise ConfigurationError(f"no transport registered for provider {settings.provider}")
