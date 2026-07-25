"""LLM provider implementations.

Each provider translates the generic ``LLMRequest``/``LLMResponse``
contract into provider-specific API calls. New providers are added here
without changing consumer code.
"""

import contextlib

from services.llm.providers.mock_provider import MockProvider

__all__ = ["MockProvider"]

with contextlib.suppress(ImportError):
    from services.llm.providers.kimi_provider import KimiProvider  # noqa: F401
    __all__.append("KimiProvider")
