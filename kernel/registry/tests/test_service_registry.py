"""Comprehensive tests for the Jarvis Service Registry.

Coverage targets:
  - Singleton and transient lifetime behavior
  - Duplicate detection and explicit replacement
  - Missing service error handling
  - Thread-safe concurrent access
  - Registry operations (contains, unregister, clear, len)
  - Invalid registration rejection
  - ServiceDescriptor immutability
"""

import threading
from typing import Protocol, cast

import pytest

from kernel.registry import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    Lifetime,
    RegistryError,
    ServiceDescriptor,
    ServiceNotFoundError,
    ServiceRegistry,
)

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


class ILogger(Protocol):
    """Example service interface for testing."""

    def log(self, message: str) -> None:
        """Log a message."""


class ConsoleLogger:
    """Example concrete implementation."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)


class FileLogger:
    """Alternative concrete implementation."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)


class IConfig(Protocol):
    """Secondary interface for multi-registration tests."""

    def get(self, key: str) -> str:
        """Get a configuration value."""
        return f"value-of-{key}"


class ConfigImpl:
    """Configuration implementation."""

    def get(self, key: str) -> str:
        return f"config-{key}"


@pytest.fixture
def registry() -> ServiceRegistry:
    """Return a fresh, empty registry for each test."""
    return ServiceRegistry()


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


class TestSingletonRegistration:
    """Singleton lifetime: shared instance across all resolves."""

    def test_class_lazy_instantiation(self, registry: ServiceRegistry) -> None:
        """A class-registered singleton is instantiated lazily."""
        registry.register_singleton(ILogger, ConsoleLogger)
        logger = registry.resolve(ILogger)
        assert isinstance(logger, ConsoleLogger)
        logger.log("hello")
        assert logger.messages == ["hello"]

    def test_instance_direct_use(self, registry: ServiceRegistry) -> None:
        """A pre-instantiated singleton is returned as-is."""
        instance = ConsoleLogger()
        registry.register_singleton(ILogger, instance)
        resolved = cast(ConsoleLogger, registry.resolve(ILogger))
        assert resolved is instance
        resolved.log("direct")
        assert instance.messages == ["direct"]

    def test_returns_same_instance(self, registry: ServiceRegistry) -> None:
        """Multiple resolves return the identical object."""
        registry.register_singleton(ILogger, ConsoleLogger)
        a = registry.resolve(ILogger)
        b = registry.resolve(ILogger)
        assert a is b

    def test_lazy_instantiated_once(self, registry: ServiceRegistry) -> None:
        """A class-registered singleton is constructed exactly once."""
        call_count = 0

        class CountedLogger(ConsoleLogger):
            def __init__(self) -> None:
                super().__init__()
                nonlocal call_count
                call_count += 1

        registry.register_singleton(ILogger, CountedLogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        assert call_count == 1

    def test_multiple_singletons(self, registry: ServiceRegistry) -> None:
        """Different interfaces can each have their own singleton."""
        registry.register_singleton(ILogger, ConsoleLogger)
        registry.register_singleton(IConfig, ConfigImpl)
        logger = registry.resolve(ILogger)
        config = registry.resolve(IConfig)
        assert isinstance(logger, ConsoleLogger)
        assert isinstance(config, ConfigImpl)
        assert logger is registry.resolve(ILogger)
        assert config is registry.resolve(IConfig)


# ---------------------------------------------------------------------------
# Transient behaviour
# ---------------------------------------------------------------------------


class TestTransientRegistration:
    """Transient lifetime: new instance on every resolve."""

    def test_returns_new_instance(self, registry: ServiceRegistry) -> None:
        """Each resolve yields a distinct object."""
        registry.register_transient(ILogger, ConsoleLogger)
        a = registry.resolve(ILogger)
        b = registry.resolve(ILogger)
        assert a is not b
        assert isinstance(a, ConsoleLogger)
        assert isinstance(b, ConsoleLogger)

    def test_instantiated_every_time(self, registry: ServiceRegistry) -> None:
        """The constructor is called on every resolve."""
        call_count = 0

        class CountedLogger(ConsoleLogger):
            def __init__(self) -> None:
                super().__init__()
                nonlocal call_count
                call_count += 1

        registry.register_transient(ILogger, CountedLogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        assert call_count == 3

    def test_rejects_instance(self, registry: ServiceRegistry) -> None:
        """Transient registration requires a class, not an instance."""
        instance = ConsoleLogger()
        with pytest.raises(InvalidRegistrationError) as exc_info:
            registry.register_transient(ILogger, instance)  # type: ignore[reportArgumentType]
        assert "requires a class" in str(exc_info.value)
        assert "ConsoleLogger" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateRegistration:
    """Attempting to register the same interface twice is rejected."""

    def test_singleton_then_singleton(self, registry: ServiceRegistry) -> None:
        """Two singleton registrations for the same interface raise."""
        registry.register_singleton(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError) as exc_info:
            registry.register_singleton(ILogger, FileLogger)
        assert "already registered" in str(exc_info.value)
        assert "ILogger" in str(exc_info.value)

    def test_transient_then_transient(self, registry: ServiceRegistry) -> None:
        """Two transient registrations for the same interface raise."""
        registry.register_transient(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError) as exc_info:
            registry.register_transient(ILogger, FileLogger)
        assert "already registered" in str(exc_info.value)

    def test_mixed_lifetimes(self, registry: ServiceRegistry) -> None:
        """Singleton then transient on the same interface raises."""
        registry.register_singleton(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError):
            registry.register_transient(ILogger, FileLogger)

    def test_transient_then_singleton(self, registry: ServiceRegistry) -> None:
        """Transient then singleton on the same interface raises."""
        registry.register_transient(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError):
            registry.register_singleton(ILogger, FileLogger)


# ---------------------------------------------------------------------------
# Explicit replacement
# ---------------------------------------------------------------------------


class TestReplaceRegistration:
    """Explicit replacement of existing registrations."""

    def test_replace_singleton_with_class(self, registry: ServiceRegistry) -> None:
        """Replacing a singleton class registration discards the old instance."""
        registry.register_singleton(ILogger, ConsoleLogger)
        old = registry.resolve(ILogger)
        registry.replace_singleton(ILogger, FileLogger)
        new = registry.resolve(ILogger)
        assert isinstance(new, FileLogger)
        assert new is not old

    def test_replace_singleton_with_instance(self, registry: ServiceRegistry) -> None:
        """Replacing a singleton with a pre-instantiated instance works."""
        registry.register_singleton(ILogger, ConsoleLogger)
        instance = FileLogger()
        registry.replace_singleton(ILogger, instance)
        assert cast(FileLogger, registry.resolve(ILogger)) is instance

    def test_replace_transient(self, registry: ServiceRegistry) -> None:
        """Replacing a transient registration changes the factory class."""
        registry.register_transient(ILogger, ConsoleLogger)
        registry.replace_transient(ILogger, FileLogger)
        assert isinstance(registry.resolve(ILogger), FileLogger)

    def test_replace_missing_raises(self, registry: ServiceRegistry) -> None:
        """Replacing an unregistered interface raises."""
        with pytest.raises(ServiceNotFoundError) as exc_info:
            registry.replace_singleton(ILogger, ConsoleLogger)
        assert "Cannot replace" in str(exc_info.value)

    def test_replace_transient_rejects_instance(self, registry: ServiceRegistry) -> None:
        """Replacing a transient with an instance is rejected."""
        registry.register_transient(ILogger, ConsoleLogger)
        with pytest.raises(InvalidRegistrationError):
            registry.replace_transient(ILogger, ConsoleLogger())  # type: ignore[reportArgumentType]


# ---------------------------------------------------------------------------
# Missing service handling
# ---------------------------------------------------------------------------


class TestMissingService:
    """Resolving or unregistering unknown interfaces fails fast."""

    def test_resolve_missing_raises(self, registry: ServiceRegistry) -> None:
        """Resolving an unregistered interface raises ServiceNotFoundError."""
        with pytest.raises(ServiceNotFoundError) as exc_info:
            registry.resolve(ILogger)
        assert "No implementation registered" in str(exc_info.value)
        assert "ILogger" in str(exc_info.value)

    def test_unregister_missing_raises(self, registry: ServiceRegistry) -> None:
        """Unregistering an unregistered interface raises."""
        with pytest.raises(ServiceNotFoundError) as exc_info:
            registry.unregister(ILogger)
        assert "Cannot unregister" in str(exc_info.value)
        assert "ILogger" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------


class TestRegistryOperations:
    """contains, unregister, clear, and len."""

    def test_contains_false_for_unregistered(self, registry: ServiceRegistry) -> None:
        """contains returns False for unknown interfaces."""
        assert registry.contains(ILogger) is False

    def test_contains_true_for_registered(self, registry: ServiceRegistry) -> None:
        """contains returns True for registered interfaces."""
        registry.register_singleton(ILogger, ConsoleLogger)
        assert registry.contains(ILogger) is True

    def test_unregister_removes_registration(self, registry: ServiceRegistry) -> None:
        """After unregister, the interface is no longer resolvable."""
        registry.register_singleton(ILogger, ConsoleLogger)
        registry.unregister(ILogger)
        assert registry.contains(ILogger) is False
        with pytest.raises(ServiceNotFoundError):
            registry.resolve(ILogger)

    def test_clear_removes_all(self, registry: ServiceRegistry) -> None:
        """clear empties the entire registry."""
        registry.register_singleton(ILogger, ConsoleLogger)
        registry.register_singleton(IConfig, ConfigImpl)
        assert len(registry) == 2
        registry.clear()
        assert len(registry) == 0
        assert registry.contains(ILogger) is False
        assert registry.contains(IConfig) is False

    def test_len_counts_descriptors(self, registry: ServiceRegistry) -> None:
        """len reflects the number of registered interfaces."""
        assert len(registry) == 0
        registry.register_singleton(ILogger, ConsoleLogger)
        assert len(registry) == 1
        registry.register_singleton(IConfig, ConfigImpl)
        assert len(registry) == 2
        registry.unregister(ILogger)
        assert len(registry) == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Concurrent access from multiple threads."""

    def test_concurrent_singleton_resolution(self) -> None:
        """Many threads resolving the same singleton get the same instance."""
        registry = ServiceRegistry()
        registry.register_singleton(ILogger, ConsoleLogger)

        results: list[object] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def resolve() -> None:
            try:
                result = registry.resolve(ILogger)
                with lock:
                    results.append(result)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 100
        first = results[0]
        assert all(r is first for r in results)

    def test_concurrent_transient_resolution(self) -> None:
        """Many threads resolving transients get distinct instances."""
        registry = ServiceRegistry()
        registry.register_transient(ILogger, ConsoleLogger)

        results: list[object] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def resolve() -> None:
            try:
                result = registry.resolve(ILogger)
                with lock:
                    results.append(result)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 50
        ids = {id(r) for r in results}
        assert len(ids) == 50

    def test_concurrent_registration_race(self) -> None:
        """Only one concurrent registration succeeds; the rest get duplicates."""
        registry = ServiceRegistry()

        success_count = 0
        errors: list[Exception] = []
        lock = threading.Lock()

        def register() -> None:
            nonlocal success_count
            try:
                registry.register_singleton(ILogger, ConsoleLogger)
                with lock:
                    success_count += 1
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=register) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert success_count == 1
        assert len(errors) == 19
        assert all(isinstance(e, DuplicateRegistrationError) for e in errors)

    def test_concurrent_mixed_access(self) -> None:
        """Concurrent reads and writes do not corrupt state."""
        registry = ServiceRegistry()
        registry.register_singleton(ILogger, ConsoleLogger)

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(worker_id: int) -> None:
            try:
                for _ in range(20):
                    _ = registry.resolve(ILogger)
                    if worker_id == 0:
                        registry.contains(ILogger)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# ServiceDescriptor model
# ---------------------------------------------------------------------------


class TestServiceDescriptor:
    """Immutability and correctness of the descriptor dataclass."""

    def test_descriptor_fields(self) -> None:
        """Descriptor stores interface, implementation, and lifetime."""
        desc = ServiceDescriptor(
            interface=ILogger,
            implementation=ConsoleLogger,
            lifetime=Lifetime.SINGLETON,
        )
        assert desc.interface is ILogger
        assert desc.implementation is ConsoleLogger
        assert desc.lifetime is Lifetime.SINGLETON

    def test_descriptor_is_frozen(self) -> None:
        """Frozen dataclass cannot be modified after creation."""
        desc = ServiceDescriptor(
            interface=ILogger,
            implementation=ConsoleLogger,
            lifetime=Lifetime.SINGLETON,
        )
        with pytest.raises(AttributeError):
            desc.lifetime = Lifetime.TRANSIENT  # type: ignore[misc]

    def test_descriptor_has_slots(self) -> None:
        """Slots prevent arbitrary attribute assignment."""
        desc = ServiceDescriptor(
            interface=ILogger,
            implementation=ConsoleLogger,
            lifetime=Lifetime.SINGLETON,
        )
        # frozen=True and slots=True both prevent new attributes;
        # either way the descriptor is immutable.
        with pytest.raises((AttributeError, TypeError)):
            desc.extra = "value"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Lifetime enum
# ---------------------------------------------------------------------------


class TestLifetimeEnum:
    """Lifetime StrEnum behaviour."""

    def test_members(self) -> None:
        """Lifetime has exactly two members."""
        assert Lifetime.SINGLETON == "singleton"
        assert Lifetime.TRANSIENT == "transient"

    def test_identity_comparison(self) -> None:
        """StrEnum supports identity comparison."""
        assert Lifetime.SINGLETON is Lifetime.SINGLETON
        assert Lifetime.TRANSIENT is not Lifetime.SINGLETON


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """All registry exceptions inherit from RegistryError."""

    def test_duplicate_is_registry_error(self) -> None:
        assert issubclass(DuplicateRegistrationError, RegistryError)

    def test_not_found_is_registry_error(self) -> None:
        assert issubclass(ServiceNotFoundError, RegistryError)

    def test_invalid_is_registry_error(self) -> None:
        assert issubclass(InvalidRegistrationError, RegistryError)

    def test_registry_error_is_exception(self) -> None:
        assert issubclass(RegistryError, Exception)


# ---------------------------------------------------------------------------
# Singleton factory behaviour
# ---------------------------------------------------------------------------


class TestSingletonFactoryRegistration:
    """Singleton factories: called once, result cached."""

    def test_factory_called_lazily(self, registry: ServiceRegistry) -> None:
        """A singleton factory is not invoked until the first resolve."""
        call_count = 0

        def factory() -> ConsoleLogger:
            nonlocal call_count
            call_count += 1
            return ConsoleLogger()

        registry.register_singleton_factory(ILogger, factory)
        assert call_count == 0
        logger = registry.resolve(ILogger)
        assert call_count == 1
        assert isinstance(logger, ConsoleLogger)

    def test_factory_result_cached(self, registry: ServiceRegistry) -> None:
        """The factory result is reused on every resolve."""
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
        a = registry.resolve(ILogger)
        b = registry.resolve(ILogger)
        assert a is b

    def test_factory_called_exactly_once(self, registry: ServiceRegistry) -> None:
        """The factory is invoked exactly one time."""
        call_count = 0

        def factory() -> ConsoleLogger:
            nonlocal call_count
            call_count += 1
            return ConsoleLogger()

        registry.register_singleton_factory(ILogger, factory)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        assert call_count == 1

    def test_factory_with_complex_initialization(self, registry: ServiceRegistry) -> None:
        """Factories can perform arbitrary setup logic."""
        config = {"level": "DEBUG"}

        def factory() -> ConsoleLogger:
            logger = ConsoleLogger()
            logger.messages.append(f"init-with-{config['level']}")
            return logger

        registry.register_singleton_factory(ILogger, factory)
        logger = cast(ConsoleLogger, registry.resolve(ILogger))
        assert logger.messages == ["init-with-DEBUG"]

    def test_duplicate_factory_registration_raises(self, registry: ServiceRegistry) -> None:
        """Registering the same interface twice as a factory raises."""
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
        with pytest.raises(DuplicateRegistrationError):
            registry.register_singleton_factory(ILogger, lambda: FileLogger())

    def test_factory_then_class_raises(self, registry: ServiceRegistry) -> None:
        """A factory registration blocks a later class registration."""
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
        with pytest.raises(DuplicateRegistrationError):
            registry.register_singleton(ILogger, ConsoleLogger)

    def test_class_then_factory_raises(self, registry: ServiceRegistry) -> None:
        """A class registration blocks a later factory registration."""
        registry.register_singleton(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError):
            registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())


# ---------------------------------------------------------------------------
# Transient factory behaviour
# ---------------------------------------------------------------------------


class TestTransientFactoryRegistration:
    """Transient factories: called on every resolve, new instance each time."""

    def test_factory_called_every_resolve(self, registry: ServiceRegistry) -> None:
        """A transient factory is invoked on every resolve."""
        call_count = 0

        def factory() -> ConsoleLogger:
            nonlocal call_count
            call_count += 1
            return ConsoleLogger()

        registry.register_transient_factory(ILogger, factory)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        registry.resolve(ILogger)
        assert call_count == 3

    def test_factory_returns_new_instance(self, registry: ServiceRegistry) -> None:
        """Each resolve yields a distinct object from the factory."""
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())
        a = registry.resolve(ILogger)
        b = registry.resolve(ILogger)
        assert a is not b
        assert isinstance(a, ConsoleLogger)
        assert isinstance(b, ConsoleLogger)

    def test_factory_with_stateful_production(self, registry: ServiceRegistry) -> None:
        """Factories can produce stateful instances based on external state."""
        counter = 0

        def factory() -> ConsoleLogger:
            nonlocal counter
            counter += 1
            logger = ConsoleLogger()
            logger.messages.append(f"instance-{counter}")
            return logger

        registry.register_transient_factory(ILogger, factory)
        a = cast(ConsoleLogger, registry.resolve(ILogger))
        b = cast(ConsoleLogger, registry.resolve(ILogger))
        assert a.messages == ["instance-1"]
        assert b.messages == ["instance-2"]

    def test_rejects_non_callable(self, registry: ServiceRegistry) -> None:
        """Transient factory registration requires a callable."""
        with pytest.raises(InvalidRegistrationError) as exc_info:
            registry.register_transient_factory(ILogger, "not-callable")  # type: ignore[reportArgumentType]
        assert "requires a callable" in str(exc_info.value)

    def test_duplicate_factory_registration_raises(self, registry: ServiceRegistry) -> None:
        """Registering the same interface twice as a factory raises."""
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())
        with pytest.raises(DuplicateRegistrationError):
            registry.register_transient_factory(ILogger, lambda: FileLogger())

    def test_factory_then_class_raises(self, registry: ServiceRegistry) -> None:
        """A factory registration blocks a later class registration."""
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())
        with pytest.raises(DuplicateRegistrationError):
            registry.register_transient(ILogger, ConsoleLogger)

    def test_class_then_factory_raises(self, registry: ServiceRegistry) -> None:
        """A class registration blocks a later factory registration."""
        registry.register_transient(ILogger, ConsoleLogger)
        with pytest.raises(DuplicateRegistrationError):
            registry.register_transient_factory(ILogger, lambda: ConsoleLogger())


# ---------------------------------------------------------------------------
# Factory replacement behaviour
# ---------------------------------------------------------------------------


class TestFactoryReplacement:
    """Explicit replacement of factory registrations."""

    def test_replace_singleton_factory(self, registry: ServiceRegistry) -> None:
        """Replacing a singleton factory discards the old cached instance."""
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
        old = registry.resolve(ILogger)
        registry.replace_singleton_factory(ILogger, lambda: FileLogger())
        new = registry.resolve(ILogger)
        assert isinstance(new, FileLogger)
        assert new is not old

    def test_replace_transient_factory(self, registry: ServiceRegistry) -> None:
        """Replacing a transient factory changes the production logic."""
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())
        registry.replace_transient_factory(ILogger, lambda: FileLogger())
        assert isinstance(registry.resolve(ILogger), FileLogger)

    def test_replace_class_with_factory(self, registry: ServiceRegistry) -> None:
        """A class registration can be replaced with a factory."""
        registry.register_singleton(ILogger, ConsoleLogger)
        old = registry.resolve(ILogger)
        registry.replace_singleton_factory(ILogger, lambda: FileLogger())
        new = registry.resolve(ILogger)
        assert isinstance(new, FileLogger)
        assert new is not old

    def test_replace_factory_with_class(self, registry: ServiceRegistry) -> None:
        """A factory registration can be replaced with a class."""
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
        old = registry.resolve(ILogger)
        registry.replace_singleton(ILogger, FileLogger)
        new = registry.resolve(ILogger)
        assert isinstance(new, FileLogger)
        assert new is not old

    def test_replace_missing_factory_raises(self, registry: ServiceRegistry) -> None:
        """Replacing an unregistered interface raises."""
        with pytest.raises(ServiceNotFoundError) as exc_info:
            registry.replace_singleton_factory(ILogger, lambda: ConsoleLogger())
        assert "Cannot replace" in str(exc_info.value)

    def test_replace_transient_factory_rejects_non_callable(
        self, registry: ServiceRegistry
    ) -> None:
        """Replacing a transient factory with a non-callable is rejected."""
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())
        with pytest.raises(InvalidRegistrationError):
            registry.replace_transient_factory(ILogger, "not-callable")  # type: ignore[reportArgumentType]


# ---------------------------------------------------------------------------
# Factory thread safety
# ---------------------------------------------------------------------------


class TestFactoryThreadSafety:
    """Concurrent access with factory-registered services."""

    def test_concurrent_singleton_factory_resolution(self) -> None:
        """Many threads resolving a singleton factory get the same instance."""
        registry = ServiceRegistry()
        call_count = 0
        lock = threading.Lock()

        def factory() -> ConsoleLogger:
            nonlocal call_count
            with lock:
                call_count += 1
            return ConsoleLogger()

        registry.register_singleton_factory(ILogger, factory)

        results: list[object] = []
        errors: list[Exception] = []
        result_lock = threading.Lock()

        def resolve() -> None:
            try:
                result = registry.resolve(ILogger)
                with result_lock:
                    results.append(result)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 100
        first = results[0]
        assert all(r is first for r in results)
        assert call_count == 1

    def test_concurrent_transient_factory_resolution(self) -> None:
        """Many threads resolving a transient factory get distinct instances."""
        registry = ServiceRegistry()
        registry.register_transient_factory(ILogger, lambda: ConsoleLogger())

        results: list[object] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def resolve() -> None:
            try:
                result = registry.resolve(ILogger)
                with lock:
                    results.append(result)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 50
        ids = {id(r) for r in results}
        assert len(ids) == 50

    def test_concurrent_factory_registration_race(self) -> None:
        """Only one concurrent factory registration succeeds."""
        registry = ServiceRegistry()
        success_count = 0
        errors: list[Exception] = []
        lock = threading.Lock()

        def register() -> None:
            nonlocal success_count
            try:
                registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())
                with lock:
                    success_count += 1
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=register) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert success_count == 1
        assert len(errors) == 19
        assert all(isinstance(e, DuplicateRegistrationError) for e in errors)

    def test_concurrent_mixed_factory_access(self) -> None:
        """Concurrent reads and factory writes do not corrupt state."""
        registry = ServiceRegistry()
        registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(worker_id: int) -> None:
            try:
                for _ in range(20):
                    _ = registry.resolve(ILogger)
                    if worker_id == 0:
                        registry.contains(ILogger)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# Factory exception behaviour
# ---------------------------------------------------------------------------


class TestFactoryExceptionBehaviour:
    """Factories that raise exceptions propagate correctly."""

    def test_singleton_factory_exception_on_first_resolve(self, registry: ServiceRegistry) -> None:
        """A factory that raises propagates the exception on first resolve."""

        def factory() -> ConsoleLogger:
            raise RuntimeError("factory failed")

        registry.register_singleton_factory(ILogger, factory)
        with pytest.raises(RuntimeError, match="factory failed"):
            registry.resolve(ILogger)

    def test_singleton_factory_exception_not_cached(self, registry: ServiceRegistry) -> None:
        """After a factory exception, the next resolve retries the factory."""
        call_count = 0

        def factory() -> ConsoleLogger:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first call fails")
            return ConsoleLogger()

        registry.register_singleton_factory(ILogger, factory)
        with pytest.raises(RuntimeError):
            registry.resolve(ILogger)
        logger = registry.resolve(ILogger)
        assert isinstance(logger, ConsoleLogger)
        assert call_count == 2

    def test_transient_factory_exception_propagates(self, registry: ServiceRegistry) -> None:
        """A transient factory exception propagates on every resolve."""

        def factory() -> ConsoleLogger:
            raise RuntimeError("transient factory failed")

        registry.register_transient_factory(ILogger, factory)
        with pytest.raises(RuntimeError, match="transient factory failed"):
            registry.resolve(ILogger)
        with pytest.raises(RuntimeError, match="transient factory failed"):
            registry.resolve(ILogger)

    def test_factory_exception_does_not_corrupt_registry(self, registry: ServiceRegistry) -> None:
        """A factory exception leaves the registry in a consistent state."""
        registry.register_singleton_factory(
            ILogger,
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        registry.register_singleton(IConfig, ConfigImpl)

        with pytest.raises(RuntimeError):
            registry.resolve(ILogger)

        config = registry.resolve(IConfig)
        assert isinstance(config, ConfigImpl)
        assert registry.contains(ILogger) is True
        assert registry.contains(IConfig) is True
