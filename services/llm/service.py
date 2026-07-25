"""LLM service implementation.

The ``LLMService`` wraps a concrete ``LLMProvider`` and adds lifecycle
events and optional request/response logging. It is the canonical entry
point for all LLM interactions within Jarvis.
"""

from __future__ import annotations

from kernel.events import Event, EventBus
from services.llm.models import LLMRequest, LLMResponse
from services.llm.provider import LLMProvider


class LLMService:
    """Service facade for LLM operations.

    Emits ``llm.requested`` and ``llm.responded`` events through the
    configured ``EventBus``.
    """

    def __init__(
        self,
        provider: LLMProvider,
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            provider: The concrete LLM provider to use.
            event_bus: Optional event bus for publishing lifecycle events.
        """
        self._provider = provider
        self._event_bus = event_bus

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a completion request.

        Args:
            request: The structured request.

        Returns:
            The provider's response.
        """
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="llm.requested",
                    payload={
                        "model": request.model,
                        "message_count": len(request.messages),
                    },
                )
            )

        response = self._provider.complete(request)

        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="llm.responded",
                    payload={
                        "model": response.model,
                        "content_length": len(response.content),
                    },
                )
            )

        return response
