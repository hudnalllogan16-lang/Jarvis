"""Tests for the CLI application."""

from apps.cli.app import CLIApp
from services.conversation_engine.engine import ConversationEngine
from services.llm.providers.mock_provider import MockProvider
from services.llm.service import LLMService
from services.memory.backends.in_memory import InMemoryBackend
from services.memory.service import MemoryService
from services.prompt_builder.builder import PromptBuilder


def test_cli_app_instantiation() -> None:
    """CLIApp should instantiate with a ConversationEngine."""
    memory_service = MemoryService(InMemoryBackend())
    llm_service = LLMService(MockProvider())
    prompt_builder = PromptBuilder()
    engine = ConversationEngine(
        memory_service=memory_service,
        llm_service=llm_service,
        prompt_builder=prompt_builder,
    )
    app = CLIApp(engine)
    assert app._engine is engine  # type: ignore[reportPrivateUsage]
