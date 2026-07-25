"""Tests for the conversation engine."""

from kernel.events import EventBus
from services.conversation_engine.engine import ConversationEngine
from services.llm.providers.mock_provider import MockProvider
from services.llm.service import LLMService
from services.memory.backends.in_memory import InMemoryBackend
from services.memory.service import MemoryService
from services.prompt_builder.builder import PromptBuilder


def test_end_to_end_remember_and_recall() -> None:
    """Milestone 3 Definition of Done: remember and recall workflow."""
    event_bus = EventBus()
    memory_service = MemoryService(InMemoryBackend(), event_bus=event_bus)
    llm_service = LLMService(MockProvider(), event_bus=event_bus)
    prompt_builder = PromptBuilder()

    engine = ConversationEngine(
        memory_service=memory_service,
        llm_service=llm_service,
        prompt_builder=prompt_builder,
        event_bus=event_bus,
    )

    # User: Remember that my favorite editor is VS Code.
    response1 = engine.process("Remember that my favorite editor is VS Code.")
    assert response1 == "Stored."

    # User: What is my favorite editor?
    response2 = engine.process("What is my favorite editor?")
    assert "VS Code" in response2
