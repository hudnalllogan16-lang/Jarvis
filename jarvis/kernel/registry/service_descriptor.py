"""Service descriptor model for the Jarvis Service Registry."""

from dataclasses import dataclass
from typing import Any

from kernel.registry.lifetime import Lifetime


@dataclass(frozen=True, slots=True)
class ServiceDescriptor:
    """Immutable descriptor for a registered service.

    Attributes:
        interface: The abstract interface or protocol the service implements.
        implementation: The concrete implementation. This may be:
            - A class (instantiated on resolve)
            - A pre-instantiated instance (returned as-is for singletons)
            - A callable factory (invoked with no arguments on resolve)
        lifetime: How long the service lives (singleton or transient).
    """

    interface: type[Any]
    implementation: type[Any] | Any
    lifetime: Lifetime
