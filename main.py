"""Minimal entry point for Jarvis.

This module serves as the application bootstrap. The DI container is
used to resolve and start all services.
"""

from __future__ import annotations

from apps.cli.app import CLIApp
from kernel.config.loader import load_settings
from kernel.di import Container
from kernel.events import EventBus
from kernel.registry import Lifetime, Registry
from services.conversation_engine.engine import ConversationEngine
from services.llm.provider import LLMProvider
from services.llm.providers.mock_provider import MockProvider
from services.llm.service import LLMService
from services.memory.backend import MemoryBackend
from services.memory.backends.in_memory import InMemoryBackend
from services.memory.service import MemoryService
from services.prompt_builder.builder import PromptBuilder


def create_container() -> Container:
    """Wire up the dependency graph for Milestone 3."""
    registry = Registry()

    # Infrastructure
    registry.register(
        EventBus, instance=EventBus(), lifetime=Lifetime.SINGLETON
    )

    # Memory backend
    registry.register(
        MemoryBackend, implementation=InMemoryBackend, lifetime=Lifetime.SINGLETON
    )

    # LLM provider
    settings = load_settings()
    if settings.llm_provider == "kimi":
        from services.llm.providers.kimi_provider import KimiProvider

        provider = KimiProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        registry.register(
            LLMProvider, instance=provider, lifetime=Lifetime.SINGLETON
        )
    else:
        registry.register(
            LLMProvider, implementation=MockProvider, lifetime=Lifetime.SINGLETON
        )

    # Services
    registry.register(
        MemoryService, implementation=MemoryService, lifetime=Lifetime.SINGLETON
    )
    registry.register(
        LLMService, implementation=LLMService, lifetime=Lifetime.SINGLETON
    )
    registry.register(
        PromptBuilder, implementation=PromptBuilder, lifetime=Lifetime.SINGLETON
    )
    registry.register(
        ConversationEngine,
        implementation=ConversationEngine,
        lifetime=Lifetime.SINGLETON,
    )
    registry.register(
        CLIApp, implementation=CLIApp, lifetime=Lifetime.SINGLETON
    )

    return Container(registry)


def main() -> None:
    """Bootstrap Jarvis."""
    container = create_container()
    app = container.resolve(CLIApp)
    app.run()


if __name__ == "__main__":
    main()
