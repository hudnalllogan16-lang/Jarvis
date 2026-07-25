"""Integration tests for kernel subsystems.

Validates that the Service Registry and DI container work together
correctly across realistic scenarios.
"""

from __future__ import annotations

from typing import Protocol, cast

from kernel.di.container import Container
from kernel.registry.models import Lifetime
from kernel.registry.registry import Registry


class ILogger(Protocol):
    """Logger interface."""

    def log(self, message: str) -> None:
        """Log a message."""


class IRepository(Protocol):
    """Repository interface."""

    def fetch(self) -> str:
        """Fetch data."""
        return ""


class ConsoleLogger:
    """Simple logger implementation."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        """Log a message."""
        self.messages.append(message)


class InMemoryRepository:
    """Repository that depends on a logger."""

    def __init__(self, logger: ILogger) -> None:
        self.logger = logger

    def fetch(self) -> str:
        """Fetch data."""
        self.logger.log("fetching")
        return "data"


class ApplicationService:
    """Top-level service with multiple dependencies."""

    def __init__(self, logger: ILogger, repo: IRepository) -> None:
        self.logger = logger
        self.repo = repo

    def run(self) -> str:
        """Run the service."""
        self.logger.log("run")
        return self.repo.fetch()


class TestRegistryAndDIIntegration:
    """Integration tests for Registry + Container."""

    def test_full_stack_resolution(self) -> None:
        """Verify full stack resolves and shares singletons."""
        registry = Registry()
        registry.register(ILogger, ConsoleLogger, Lifetime.SINGLETON)
        registry.register(IRepository, InMemoryRepository, Lifetime.SINGLETON)
        container = Container(registry)

        app = container.resolve(ApplicationService)
        result = app.run()

        assert result == "data"
        assert app.logger is container.resolve(ILogger)
        assert app.repo is container.resolve(IRepository)
        repo = cast(InMemoryRepository, app.repo)
        assert repo.logger is app.logger

    def test_mixed_lifetimes(self) -> None:
        """Verify mixed lifetimes work correctly."""
        registry = Registry()
        registry.register(ILogger, ConsoleLogger, Lifetime.SINGLETON)
        registry.register(IRepository, InMemoryRepository, Lifetime.TRANSIENT)
        container = Container(registry)

        repo_a = container.resolve(IRepository)
        repo_b = container.resolve(IRepository)

        assert repo_a is not repo_b
        repo_a_cast = cast(InMemoryRepository, repo_a)
        repo_b_cast = cast(InMemoryRepository, repo_b)
        assert repo_a_cast.logger is repo_b_cast.logger

    def test_unregistered_top_level_with_registered_deps(self) -> None:
        """Verify unregistered top-level with registered deps auto-wires."""
        registry = Registry()
        registry.register(ILogger, ConsoleLogger, Lifetime.SINGLETON)
        registry.register(IRepository, InMemoryRepository, Lifetime.SINGLETON)
        container = Container(registry)

        # ApplicationService is not registered, but its deps are
        app = container.resolve(ApplicationService)
        assert isinstance(app, ApplicationService)
        assert isinstance(app.logger, ConsoleLogger)
        repo = cast(InMemoryRepository, app.repo)
        assert isinstance(repo, InMemoryRepository)

    def test_scope_with_mixed_lifetimes(self) -> None:
        """Verify scope caches scoped services correctly."""
        registry = Registry()
        registry.register(ILogger, ConsoleLogger, Lifetime.SCOPED)
        registry.register(IRepository, InMemoryRepository, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope():
            app = container.resolve(ApplicationService)
            logger = container.resolve(ILogger)
            repo = container.resolve(IRepository)
            repo_cast = cast(InMemoryRepository, repo)

            assert app.logger is logger
            assert app.repo is repo
            assert repo_cast.logger is logger

        with container.create_scope():
            app2 = container.resolve(ApplicationService)
            logger2 = container.resolve(ILogger)

            assert app2.logger is logger2
            assert logger is not logger2
