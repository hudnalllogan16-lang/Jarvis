"""Jarvis Service Registry.

The Service Registry is the foundation of dependency management across Jarvis.
It maps abstract interfaces to concrete implementations with configurable
lifetimes (singleton or transient).

Registration styles::

    # Class-based singleton (lazy instantiation)
    registry.register_singleton(ILogger, ConsoleLogger)

    # Instance-based singleton (pre-built)
    registry.register_singleton(ILogger, ConsoleLogger())

    # Factory-based singleton (lazy factory invocation)
    registry.register_singleton_factory(ILogger, lambda: ConsoleLogger())

    # Class-based transient (new instance per resolve)
    registry.register_transient(ILogger, ConsoleLogger)

    # Factory-based transient (new factory invocation per resolve)
    registry.register_transient_factory(ILogger, lambda: ConsoleLogger())

The registry is thread-safe and designed for production use.
It does not perform constructor injection or dependency graph resolution;
those capabilities are planned for future milestones.
"""

from kernel.registry.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    RegistryError,
    ServiceNotFoundError,
)
from kernel.registry.lifetime import Lifetime
from kernel.registry.registry import ServiceRegistry
from kernel.registry.service_descriptor import ServiceDescriptor

__all__ = [
    "DuplicateRegistrationError",
    "InvalidRegistrationError",
    "Lifetime",
    "RegistryError",
    "ServiceDescriptor",
    "ServiceNotFoundError",
    "ServiceRegistry",
]
