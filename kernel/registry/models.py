"""Data models for the Service Registry.

This module defines the core data structures used by the Service Registry
to describe service registrations, including lifetime policies and
immutable service descriptors.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Lifetime(StrEnum):
    """Defines the lifetime policy for a registered service.

    Attributes:
        SINGLETON: One instance shared across the entire application.
        TRANSIENT: A new instance created on every resolution.
        SCOPED: One instance per active scope (managed by DI container).
    """

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


@dataclass(frozen=True)
class ServiceDescriptor:
    """Immutable description of a registered service.

    Attributes:
        interface: The type used as the lookup key for this service.
        implementation: The concrete type to instantiate. None if factory
            or instance is used.
        lifetime: The lifetime policy for this service.
        factory: A callable that creates the service instance. None if
            implementation or instance is used.
        instance: A pre-created instance. None if implementation or factory
            is used.
    """

    interface: type
    implementation: type | None
    lifetime: Lifetime
    factory: Callable[..., Any] | None
    instance: Any | None
