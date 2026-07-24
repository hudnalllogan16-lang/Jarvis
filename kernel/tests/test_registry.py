"""Tests for the Jarvis Service Registry."""

import pytest

from kernel.registry import (
    DuplicateRegistrationError,
    Registry,
    ServiceNotFoundError,
)


class AbstractService:
    """Example abstract service interface."""


class ConcreteService:
    """Example concrete service implementation."""


class AnotherConcreteService:
    """Another example concrete service implementation."""


def test_successful_registration():
    """Test that an implementation can be registered under an interface."""
    registry = Registry()
    registry.register(AbstractService, ConcreteService)
    assert registry.contains(AbstractService) is True


def test_duplicate_registration_raises():
    """Test that registering the same interface twice raises an error."""
    registry = Registry()
    registry.register(AbstractService, ConcreteService)
    with pytest.raises(DuplicateRegistrationError) as exc_info:
        registry.register(AbstractService, AnotherConcreteService)
    assert "already registered" in str(exc_info.value)
    assert "AbstractService" in str(exc_info.value)


def test_successful_resolution():
    """Test that a registered implementation can be resolved."""
    registry = Registry()
    registry.register(AbstractService, ConcreteService)
    resolved = registry.resolve(AbstractService)
    assert resolved is ConcreteService


def test_resolve_missing_service_raises():
    """Test that resolving an unregistered interface raises an error."""
    registry = Registry()
    with pytest.raises(ServiceNotFoundError) as exc_info:
        registry.resolve(AbstractService)
    assert "No implementation registered" in str(exc_info.value)
    assert "AbstractService" in str(exc_info.value)


def test_unregister_service():
    """Test that a registered service can be unregistered."""
    registry = Registry()
    registry.register(AbstractService, ConcreteService)
    registry.unregister(AbstractService)
    assert registry.contains(AbstractService) is False


def test_unregister_missing_service_raises():
    """Test that unregistering an unregistered service raises an error."""
    registry = Registry()
    with pytest.raises(ServiceNotFoundError) as exc_info:
        registry.unregister(AbstractService)
    assert "Cannot unregister" in str(exc_info.value)
    assert "AbstractService" in str(exc_info.value)


def test_contains_returns_false_for_unregistered():
    """Test that contains returns False for unregistered interfaces."""
    registry = Registry()
    assert registry.contains(AbstractService) is False


def test_contains_returns_true_for_registered():
    """Test that contains returns True for registered interfaces."""
    registry = Registry()
    registry.register(AbstractService, ConcreteService)
    assert registry.contains(AbstractService) is True
