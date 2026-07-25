"""LLM provider protocol.

All LLM providers must satisfy this protocol. The Conversation Engine
and other consumers interact with providers exclusively through this
interface, preserving provider independence.
"""

from __future__ import annotations

from typing import Protocol

from services.llm.models import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    """Protocol for LLM provider implementations."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send ``request`` to the provider and return the response.

        Args:
            request: The structured request to send.

        Returns:
            The provider's response.
        """
        ...
