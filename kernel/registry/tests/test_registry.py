"""Unit tests for the Service Registry.

Covers registration, resolution, lifetime management, factories, instances,
thread safety, and error conditions.
"""

from __future__ import annotations

import threading
from typing import Protocol

import pytest

from kernel.registry.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    ServiceNotFoundError,
)
from kernel.registry.models import Lifetime
from kernel.registry.registry import Registry


class IService(Protocol):
    """Test interface."""

    def do_work(self) -> str:
        """Return work result."""
        return ""


class ServiceImpl:
    """Test implementation."""

    def do_work(self) -> str:
        """Return work result."""
        return "done"


class AnotherImpl:
    """Another test implementation."""

    def do_work(self) -> str:
        """Return work result."""
        return "another"


class TestRegistryBasics:
    """Test basic registration and resolution."""

    def test_register_and_resolve(self) -> None:
        """Verify basic registration and resolution."""
        registry = Registry()
        registry.register(IService, ServiceImpl)
        result = registry.resolve(IService)
        assert isinstance(result, ServiceImpl)

    def test_register_concrete_type(self) -> None:
        """Verify concrete type registration."""
        registry = Registry()
        registry.register(ServiceImpl, ServiceImpl, Lifetime.SINGLETON)
        result = registry.resolve(ServiceImpl)
        assert isinstance(result, ServiceImpl)

    def test_contains(self) -> None:
        """Verify contains checks registration status."""
        registry = Registry()
        assert not registry.contains(IService)
        registry.register(IService, ServiceImpl)
        assert registry.contains(IService)

    def test_unregister(self) -> None:
        """Verify unregister removes registration."""
        registry = Registry()
        registry.register(IService, ServiceImpl)
        registry.unregister(IService)
        assert not registry.contains(IService)
        with pytest.raises(ServiceNotFoundError):
            registry.resolve(IService)

    def test_clear(self) -> None:
        """Verify clear removes all registrations."""
        registry = Registry()
        registry.register(IService, ServiceImpl)
        registry.clear()
        assert not registry.contains(IService)

    def test_descriptors(self) -> None:
        """Verify descriptors returns all registrations."""
        registry = Registry()
        registry.register(IService, ServiceImpl, Lifetime.SINGLETON)
        descs = registry.descriptors()
        assert IService in descs
        assert descs[IService].lifetime is Lifetime.SINGLETON

    def test_get_descriptor(self) -> None:
        """Verify get_descriptor returns correct metadata."""
        registry = Registry()
        registry.register(IService, ServiceImpl, Lifetime.TRANSIENT)
        desc = registry.get_descriptor(IService)
        assert desc.interface is IService
        assert desc.implementation is ServiceImpl
        assert desc.lifetime is Lifetime.TRANSIENT

    def test_get_descriptor_not_found(self) -> None:
        """Verify get_descriptor raises for missing interface."""
        registry = Registry()
        with pytest.raises(ServiceNotFoundError):
            registry.get_descriptor(IService)


class TestRegistryLifetimes:
    """Test singleton, transient, and scoped lifetimes."""

    def test_singleton_returns_same_instance(self) -> None:
        """Verify singleton returns cached instance."""
        registry = Registry()
        registry.register(IService, ServiceImpl, Lifetime.SINGLETON)
        a = registry.resolve(IService)
        b = registry.resolve(IService)
        assert a is b

    def test_transient_returns_new_instance(self) -> None:
        """Verify transient returns new instance each time."""
        registry = Registry()
        registry.register(IService, ServiceImpl, Lifetime.TRANSIENT)
        a = registry.resolve(IService)
        b = registry.resolve(IService)
        assert a is not b
        assert isinstance(a, ServiceImpl)
        assert isinstance(b, ServiceImpl)

    def test_scoped_creates_new_instance(self) -> None:
        """Registry itself does not cache scoped; DI container handles that."""
        registry = Registry()
        registry.register(IService, ServiceImpl, Lifetime.SCOPED)
        a = registry.resolve(IService)
        b = registry.resolve(IService)
        assert a is not b

    def test_singleton_caches_on_first_resolve(self) -> None:
        """Verify singleton is created exactly once."""
        registry = Registry()
        call_count = 0

        class CountingImpl:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

        registry.register(IService, CountingImpl, Lifetime.SINGLETON)
        registry.resolve(IService)
        registry.resolve(IService)
        assert call_count == 1

    def test_transient_creates_each_time(self) -> None:
        """Verify transient creates instance each time."""
        registry = Registry()
        call_count = 0

        class CountingImpl:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

        registry.register(IService, CountingImpl, Lifetime.TRANSIENT)
        registry.resolve(IService)
        registry.resolve(IService)
        assert call_count == 2


class TestRegistryFactories:
    """Test factory registrations."""

    def test_singleton_factory(self) -> None:
        """Verify singleton factory is called once."""
        registry = Registry()
        call_count = 0

        def factory() -> ServiceImpl:
            nonlocal call_count
            call_count += 1
            return ServiceImpl()

        registry.register(IService, factory=factory, lifetime=Lifetime.SINGLETON)
        a = registry.resolve(IService)
        b = registry.resolve(IService)
        assert a is b
        assert call_count == 1

    def test_transient_factory(self) -> None:
        """Verify transient factory is called each time."""
        registry = Registry()
        call_count = 0

        def factory() -> ServiceImpl:
            nonlocal call_count
            call_count += 1
            return ServiceImpl()

        registry.register(IService, factory=factory, lifetime=Lifetime.TRANSIENT)
        a = registry.resolve(IService)
        b = registry.resolve(IService)
        assert a is not b
        assert call_count == 2

    def test_factory_overrides_implementation(self) -> None:
        """Verify factory takes precedence over implementation."""
        registry = Registry()
        registry.register(IService, implementation=ServiceImpl, factory=lambda: AnotherImpl())
        result = registry.resolve(IService)
        assert isinstance(result, AnotherImpl)


class TestRegistryInstances:
    """Test pre-created instance registrations."""

    def test_instance_registration(self) -> None:
        """Verify instance registration returns the same object."""
        registry = Registry()
        instance = ServiceImpl()
        registry.register(IService, instance=instance)
        result = registry.resolve(IService)
        assert result is instance

    def test_instance_forces_singleton(self) -> None:
        """Verify instance registration forces singleton lifetime."""
        registry = Registry()
        instance = ServiceImpl()
        registry.register(IService, instance=instance)
        desc = registry.get_descriptor(IService)
        assert desc.lifetime is Lifetime.SINGLETON


class TestRegistryErrors:
    """Test error conditions."""

    def test_resolve_not_found(self) -> None:
        """Verify resolve raises for unregistered interface."""
        registry = Registry()
        with pytest.raises(ServiceNotFoundError):
            registry.resolve(IService)

    def test_duplicate_registration(self) -> None:
        """Verify duplicate registration raises error."""
        registry = Registry()
        registry.register(IService, ServiceImpl)
        with pytest.raises(DuplicateRegistrationError):
            registry.register(IService, ServiceImpl)

    def test_invalid_registration_no_source(self) -> None:
        """Verify registration without source raises error."""
        registry = Registry()
        with pytest.raises(InvalidRegistrationError):
            registry.register(IService)

    def test_create_bypasses_singleton_cache(self) -> None:
        """Verify create bypasses singleton cache."""
        registry = Registry()
        call_count = 0

        class CountingImpl:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

        registry.register(IService, CountingImpl, Lifetime.SINGLETON)
        a = registry.resolve(IService)
        b = registry.create(IService)
        assert a is not b
        assert call_count == 2


class TestRegistryThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_singleton_resolution(self) -> None:
        """Verify singleton is created exactly once under concurrency."""
        registry = Registry()
        call_count = 0

        class CountingImpl:
            def __init__(self) -> None:
                nonlocal call_count
                call_count += 1

        registry.register(IService, CountingImpl, Lifetime.SINGLETON)
        results: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            instance = registry.resolve(IService)
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count == 1
        assert all(r is results[0] for r in results)

    def test_concurrent_registration_and_resolution(self) -> None:
        """Verify concurrent registration is safe."""
        registry = Registry()
        errors: list[Exception] = []
        lock = threading.Lock()

        def register_worker() -> None:
            try:
                registry.register(IService, ServiceImpl)
            except DuplicateRegistrationError:
                pass
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=register_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert registry.contains(IService)
