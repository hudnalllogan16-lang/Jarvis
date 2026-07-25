"""Unit tests for the Dependency Injection container.

Covers constructor injection, recursive resolution, circular dependency
detection, lifetime integration, scope management, thread safety,
edge cases, and intentionally unsupported scenarios.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, cast

import pytest

from kernel.di.container import Container
from kernel.di.exceptions import (
    CircularDependencyError,
    MissingDependencyError,
    UnresolvableTypeError,
)
from kernel.registry.models import Lifetime
from kernel.registry.registry import Registry

# ---------------------------------------------------------------------------
# Test fixtures and helper types
# ---------------------------------------------------------------------------


class IDatabase(Protocol):
    """Database interface."""

    def query(self) -> str:
        """Execute a query."""
        return ""


class ICache(Protocol):
    """Cache interface."""

    def get(self, key: str) -> str | None:
        """Retrieve a value."""
        return None


class PostgresDatabase:
    """Concrete database implementation."""

    def query(self) -> str:
        """Execute a query."""
        return "postgres"


class RedisCache:
    """Concrete cache implementation."""

    def __init__(self, db: IDatabase) -> None:
        self.db = db

    def get(self, key: str) -> str | None:
        """Retrieve a value."""
        return f"cached:{key}"


class ServiceWithDeps:
    """Service depending on database and cache."""

    def __init__(self, db: IDatabase, cache: ICache) -> None:
        self.db = db
        self.cache = cache


class ServiceWithOptional:
    """Service with optional dependency."""

    def __init__(self, db: IDatabase, name: str = "default") -> None:
        self.db = db
        self.name = name


class ServiceWithPrimitive:
    """Service with primitive parameter that has a default."""

    def __init__(self, db: IDatabase, port: int = 5432) -> None:
        self.db = db
        self.port = port


class UnregisteredConcrete:
    """Concrete type not registered in any registry."""

    def __init__(self, db: IDatabase) -> None:
        self.db = db


class CircularA:
    """Type with circular dependency on B."""

    def __init__(self, b: CircularB) -> None:
        self.b = b


class CircularB:
    """Type with circular dependency on A."""

    def __init__(self, a: CircularA) -> None:
        self.a = a


class CircularViaInterface:
    """Type depending on interface that resolves to self."""

    def __init__(self, dep: ICircular) -> None:
        self.dep = dep


class ICircular(Protocol):
    """Interface for circular test."""

    def work(self) -> str:
        """Do work."""
        return ""


class CircularViaInterfaceImpl:
    """Implementation creating circular dependency."""

    def __init__(self, dep: CircularViaInterface) -> None:
        self.dep = dep

    def work(self) -> str:
        """Do work."""
        return "work"


class DeepA:
    """Top of deep dependency chain."""

    def __init__(self, b: DeepB) -> None:
        self.b = b


class DeepB:
    """Middle of deep dependency chain."""

    def __init__(self, c: DeepC) -> None:
        self.c = c


class DeepC:
    """Leaf of deep dependency chain."""

    def __init__(self, db: IDatabase) -> None:
        self.db = db


class ServiceWithVarArgs:
    """Service with *args and **kwargs."""

    def __init__(self, db: IDatabase, *args: Any, **kwargs: Any) -> None:
        self.db = db
        self.args = args
        self.kwargs = kwargs


class ServiceWithForwardRef:
    """Service using forward reference annotation."""

    def __init__(self, db: IDatabase) -> None:
        self.db = db


class AbstractService(ABC):
    """Abstract base class with abstract method."""

    @abstractmethod
    def work(self) -> str:
        """Do work."""


class ConcreteFromABC(AbstractService):
    """Concrete subclass of ABC."""

    def work(self) -> str:
        """Do work."""
        return "abc-work"


class NoInitClass:
    """Class with no explicit __init__."""

    value: int = 42


@dataclass
class DataClassService:
    """Dataclass service."""

    db: IDatabase


class ServiceWithOptionalRegistered:
    """Optional parameter where the type is registered."""

    def __init__(self, db: IDatabase | None = None) -> None:
        self.db = db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContainerRegistrationDelegation:
    """Test that container properly wraps registry registration."""

    def test_container_uses_provided_registry(self) -> None:
        """Verify container uses the registry passed to it."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(IDatabase)
        assert isinstance(result, PostgresDatabase)

    def test_container_creates_default_registry(self) -> None:
        """Verify container creates a default registry when none is given."""
        container = Container()
        assert container.registry is not None

    def test_registry_property_returns_instance(self) -> None:
        """Verify registry property returns the same instance."""
        registry = Registry()
        container = Container(registry)
        assert container.registry is registry


class TestContainerSingletonResolution:
    """Test singleton lifetime through the container."""

    def test_singleton_returns_same_instance(self) -> None:
        """Verify singleton returns the cached instance."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.resolve(IDatabase)
        assert a is b

    def test_singleton_auto_wired_implementation(self) -> None:
        """Verify singleton with auto-wired dependencies."""
        registry = Registry()
        registry.register(RedisCache, RedisCache, Lifetime.SINGLETON)
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        cache = container.resolve(RedisCache)
        assert isinstance(cache, RedisCache)
        assert isinstance(cache.db, PostgresDatabase)


class TestContainerTransientResolution:
    """Test transient lifetime through the container."""

    def test_transient_returns_new_instance(self) -> None:
        """Verify transient creates new instances each time."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.TRANSIENT)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.resolve(IDatabase)
        assert a is not b
        assert isinstance(a, PostgresDatabase)
        assert isinstance(b, PostgresDatabase)

    def test_transient_auto_wired_nested(self) -> None:
        """Verify transient with nested auto-wired dependencies."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.TRANSIENT)
        registry.register(ICache, RedisCache, Lifetime.TRANSIENT)
        container = Container(registry)
        cache = container.resolve(ICache)
        assert isinstance(cache, RedisCache)
        assert isinstance(cache.db, PostgresDatabase)


class TestContainerFactoryResolution:
    """Test factory registrations through the container."""

    def test_singleton_factory(self) -> None:
        """Verify singleton factory is called once."""
        registry = Registry()
        call_count = 0

        def factory() -> PostgresDatabase:
            nonlocal call_count
            call_count += 1
            return PostgresDatabase()

        registry.register(IDatabase, factory=factory, lifetime=Lifetime.SINGLETON)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.resolve(IDatabase)
        assert a is b
        assert call_count == 1

    def test_transient_factory(self) -> None:
        """Verify transient factory is called each time."""
        registry = Registry()
        call_count = 0

        def factory() -> PostgresDatabase:
            nonlocal call_count
            call_count += 1
            return PostgresDatabase()

        registry.register(IDatabase, factory=factory, lifetime=Lifetime.TRANSIENT)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.resolve(IDatabase)
        assert a is not b
        assert call_count == 2


class TestContainerInstanceResolution:
    """Test pre-created instance registrations."""

    def test_instance_registration(self) -> None:
        """Verify instance registration returns the same object."""
        registry = Registry()
        instance = PostgresDatabase()
        registry.register(IDatabase, instance=instance)
        container = Container(registry)
        result = container.resolve(IDatabase)
        assert result is instance


class TestContainerAutoWiring:
    """Test automatic constructor injection for unregistered concrete types."""

    def test_resolve_unregistered_concrete(self) -> None:
        """Verify unregistered concrete types are auto-wired."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(UnregisteredConcrete)
        assert isinstance(result, UnregisteredConcrete)
        assert isinstance(result.db, PostgresDatabase)

    def test_build_concrete_explicit(self) -> None:
        """Verify build() forces auto-wiring."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.build(UnregisteredConcrete)
        assert isinstance(result, UnregisteredConcrete)
        assert isinstance(result.db, PostgresDatabase)

    def test_build_rejects_abstract(self) -> None:
        """Verify build() rejects abstract types."""
        container = Container()
        with pytest.raises(TypeError):
            container.build(IDatabase)

    def test_build_on_registered_type_creates_new_instance(self) -> None:
        """Verify build() ignores registration and always auto-wires."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.build(PostgresDatabase)
        assert a is not b

    def test_auto_wire_with_defaults(self) -> None:
        """Verify parameters with defaults are left as defaults."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(ServiceWithOptional)
        assert isinstance(result, ServiceWithOptional)
        assert result.name == "default"

    def test_auto_wire_with_primitive_default(self) -> None:
        """Verify primitive parameters with defaults are left as defaults."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(ServiceWithPrimitive)
        assert isinstance(result, ServiceWithPrimitive)
        assert result.port == 5432

    def test_auto_wire_with_varargs(self) -> None:
        """Verify *args and **kwargs are ignored during injection."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(ServiceWithVarArgs)
        assert isinstance(result, ServiceWithVarArgs)
        assert isinstance(result.db, PostgresDatabase)
        assert result.args == ()
        assert result.kwargs == {}

    def test_auto_wire_forward_reference(self) -> None:
        """Verify forward-reference annotations are resolved."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(ServiceWithForwardRef)
        assert isinstance(result, ServiceWithForwardRef)
        assert isinstance(result.db, PostgresDatabase)

    def test_auto_wire_no_init(self) -> None:
        """Verify class with no explicit __init__ resolves correctly."""
        registry = Registry()
        container = Container(registry)
        result = container.resolve(NoInitClass)
        assert isinstance(result, NoInitClass)
        assert result.value == 42

    def test_auto_wire_dataclass(self) -> None:
        """Verify dataclass with typed fields is auto-wired."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(DataClassService)
        assert isinstance(result, DataClassService)
        assert isinstance(result.db, PostgresDatabase)

    def test_auto_wire_abc_subclass(self) -> None:
        """Verify concrete subclass of ABC is auto-wired."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.build(ConcreteFromABC)
        assert isinstance(result, ConcreteFromABC)
        assert result.work() == "abc-work"

    def test_optional_registered_injects_dependency(self) -> None:
        """Verify Optional[T] where T is registered injects the dependency."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        result = container.resolve(ServiceWithOptionalRegistered)
        assert isinstance(result.db, PostgresDatabase)

    def test_optional_unregistered_uses_default(self) -> None:
        """Verify Optional[T] where T is not registered uses the default."""
        container = Container()
        result = container.resolve(ServiceWithOptionalRegistered)
        assert result.db is None


class TestContainerNestedDependencies:
    """Test recursive resolution of nested dependencies."""

    def test_two_level_nesting(self) -> None:
        """Verify two-level dependency chain resolves correctly."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        registry.register(ICache, RedisCache, Lifetime.SINGLETON)
        container = Container(registry)
        cache = cast(RedisCache, container.resolve(ICache))
        assert isinstance(cache.db, PostgresDatabase)

    def test_three_level_nesting(self) -> None:
        """Verify three-level dependency chain resolves correctly."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        registry.register(ICache, RedisCache, Lifetime.SINGLETON)
        container = Container(registry)
        service = container.resolve(ServiceWithDeps)
        assert isinstance(service.db, PostgresDatabase)
        cache = cast(RedisCache, service.cache)
        assert isinstance(cache.db, PostgresDatabase)

    def test_deep_chain(self) -> None:
        """Verify deep dependency chain resolves correctly."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        a = container.resolve(DeepA)
        assert isinstance(a, DeepA)
        assert isinstance(a.b, DeepB)
        assert isinstance(a.b.c, DeepC)
        assert isinstance(a.b.c.db, PostgresDatabase)


class TestContainerCircularDependencyDetection:
    """Test circular dependency detection."""

    def test_direct_circular_dependency(self) -> None:
        """Verify direct A->B->A cycle is detected."""
        container = Container()
        with pytest.raises(CircularDependencyError) as exc_info:
            container.resolve(CircularA)
        assert "CircularA" in str(exc_info.value)
        assert "CircularB" in str(exc_info.value)

    def test_indirect_circular_dependency(self) -> None:
        """Verify indirect cycle through interface is detected."""
        registry = Registry()
        registry.register(ICircular, CircularViaInterfaceImpl, Lifetime.TRANSIENT)
        container = Container(registry)
        with pytest.raises(CircularDependencyError) as exc_info:
            container.resolve(CircularViaInterface)
        assert "CircularViaInterface" in str(exc_info.value)

    def test_circular_detection_does_not_cache_partial(self) -> None:
        """Ensure failed resolution does not leave stale state."""
        container = Container()
        with pytest.raises(CircularDependencyError):
            container.resolve(CircularA)
        # Second attempt should also raise, not return a partial object
        with pytest.raises(CircularDependencyError):
            container.resolve(CircularA)


class TestContainerMissingDependencies:
    """Test handling of missing or unresolvable dependencies."""

    def test_unresolvable_abstract_type(self) -> None:
        """Verify unregistered abstract type raises error."""
        container = Container()
        with pytest.raises(UnresolvableTypeError):
            container.resolve(IDatabase)

    def test_missing_dependency_no_default(self) -> None:
        """Verify missing dependency with no default raises error."""

        class NeedsDatabase:
            def __init__(self, db: IDatabase) -> None:
                self.db = db

        container = Container()
        with pytest.raises(MissingDependencyError) as exc_info:
            container.resolve(NeedsDatabase)
        assert "IDatabase" in str(exc_info.value)

    def test_missing_type_hint_no_default(self) -> None:
        """Verify missing type hint with no default raises error."""

        class NoHint:
            def __init__(self, value) -> None:  # type: ignore[no-untyped-def]
                self.value = value

        container = Container()
        with pytest.raises(MissingDependencyError) as exc_info:
            container.resolve(NoHint)
        assert "no type hint" in str(exc_info.value).lower()

    def test_primitive_without_default(self) -> None:
        """Verify primitive parameter without default raises error."""

        class NeedsPort:
            def __init__(self, port: int) -> None:
                self.port = port

        registry = Registry()
        container = Container(registry)
        with pytest.raises(MissingDependencyError) as exc_info:
            container.resolve(NeedsPort)
        assert "primitive" in str(exc_info.value).lower()


class TestContainerScopeManagement:
    """Test scoped lifetime management."""

    def test_scope_caches_scoped_service(self) -> None:
        """Verify scoped service is cached within a scope."""
        registry = Registry()
        call_count = 0

        class CountingDB:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

            def query(self) -> str:
                """Execute a query."""
                return "counting"

        registry.register(IDatabase, CountingDB, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope():
            a = container.resolve(IDatabase)
            b = container.resolve(IDatabase)
            assert a is b
            assert call_count == 1

    def test_scope_disposes_on_exit(self) -> None:
        """Verify scope clears cache on exit."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope() as scope:
            a = container.resolve(IDatabase)
            assert scope.is_active

        # After exit, new resolution should create a new instance
        with container.create_scope():
            b = container.resolve(IDatabase)
            assert a is not b

    def test_scoped_outside_scope_is_transient(self) -> None:
        """Verify scoped outside active scope behaves as transient."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        container = Container(registry)
        a = container.resolve(IDatabase)
        b = container.resolve(IDatabase)
        assert a is not b

    def test_nested_scoped_dependencies(self) -> None:
        """Verify nested scoped dependencies share the same scope."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        registry.register(ICache, RedisCache, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope():
            cache = cast(RedisCache, container.resolve(ICache))
            db = container.resolve(IDatabase)
            assert cache.db is db  # Same scoped instance

    def test_scope_isolation(self) -> None:
        """Verify separate scopes create separate instances."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope():
            a = container.resolve(IDatabase)

        with container.create_scope():
            b = container.resolve(IDatabase)

        assert a is not b

    def test_nested_scopes_restore_outer(self) -> None:
        """Verify nested scopes restore the outer scope on exit."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        container = Container(registry)

        with container.create_scope() as outer:
            outer_db = container.resolve(IDatabase)

            with container.create_scope():
                inner_db = container.resolve(IDatabase)
                assert inner_db is not outer_db

            # After inner exits, outer should still be active
            assert outer.is_active
            later_db = container.resolve(IDatabase)
            assert later_db is outer_db


class TestContainerThreadSafety:
    """Test thread-safe resolution."""

    def test_concurrent_singleton_resolution(self) -> None:
        """Verify singleton is created exactly once under concurrency."""
        registry = Registry()
        call_count = 0

        class CountingDB:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

            def query(self) -> str:
                """Execute a query."""
                return "counting"

        registry.register(IDatabase, CountingDB, Lifetime.SINGLETON)
        container = Container(registry)
        results: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            instance = container.resolve(IDatabase)
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count == 1
        assert all(r is results[0] for r in results)

    def test_concurrent_transient_resolution(self) -> None:
        """Verify transient creates separate instances under concurrency."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.TRANSIENT)
        container = Container(registry)
        results: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            instance = container.resolve(IDatabase)
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert len({id(r) for r in results}) == 10

    def test_concurrent_scope_resolution(self) -> None:
        """Verify each thread gets its own scoped instance."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SCOPED)
        container = Container(registry)
        results: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            with container.create_scope():
                instance = container.resolve(IDatabase)
                with lock:
                    results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread got its own scoped instance
        assert len({id(r) for r in results}) == 5

    def test_concurrent_auto_wire(self) -> None:
        """Verify auto-wiring is thread-safe."""
        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        registry.register(ICache, RedisCache, Lifetime.SINGLETON)
        container = Container(registry)
        results: list[ServiceWithDeps] = []
        lock = threading.Lock()

        def worker() -> None:
            instance = container.resolve(ServiceWithDeps)
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        # All databases should be the same singleton
        assert all(r.db is results[0].db for r in results)
