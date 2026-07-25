"""Service Registry implementation.

The Service Registry is the single source of truth for service registrations,
singleton cache, lifetime management, factories, and descriptors within Jarvis.
It provides thread-safe registration and resolution of services by interface type.

The Registry does NOT perform dependency injection or constructor inspection;
those responsibilities belong exclusively to the DI container.

For simple registrations (factories, instances, or implementations with
no-argument constructors), ``Registry.resolve()`` can be used directly.
For implementations that require constructor injection, use the DI Container.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from kernel.registry.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    ServiceNotFoundError,
)
from kernel.registry.models import Lifetime, ServiceDescriptor

T = TypeVar("T")


class Registry:
    """Thread-safe service registry supporting multiple lifetime policies.

    The Registry maintains service descriptors and a singleton cache.
    All public methods are thread-safe.

    This class is considered **stable** for the Milestone 2 baseline.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._descriptors: dict[type, ServiceDescriptor] = {}
        self._singletons: dict[type, Any] = {}
        self._lock = threading.RLock()

    def register(
        self,
        interface: type,
        implementation: type | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        factory: Callable[..., Any] | None = None,
        instance: Any | None = None,
    ) -> None:
        """Register a service with the registry.

        Exactly one of ``implementation``, ``factory``, or ``instance`` must
        be provided (except when ``instance`` is given, which implies singleton).

        Args:
            interface: The type used as the lookup key.
            implementation: Concrete type to instantiate. Required unless
                factory or instance is provided.
            lifetime: Lifetime policy for this service. Ignored when instance
                is provided (always treated as singleton).
            factory: Callable that creates instances. Overrides implementation.
            instance: Pre-created instance. Overrides factory and implementation
                and forces lifetime to SINGLETON.

        Raises:
            DuplicateRegistrationError: If interface is already registered.
            InvalidRegistrationError: If registration is inconsistent.
        """
        with self._lock:
            if interface in self._descriptors:
                raise DuplicateRegistrationError(
                    f"Service '{interface.__name__}' is already registered. "
                    f"Unregister it first if you want to replace the registration."
                )

            if instance is not None:
                descriptor = ServiceDescriptor(
                    interface=interface,
                    implementation=None,
                    lifetime=Lifetime.SINGLETON,
                    factory=None,
                    instance=instance,
                )
            elif factory is not None:
                descriptor = ServiceDescriptor(
                    interface=interface,
                    implementation=None,
                    lifetime=lifetime,
                    factory=factory,
                    instance=None,
                )
            elif implementation is not None:
                descriptor = ServiceDescriptor(
                    interface=interface,
                    implementation=implementation,
                    lifetime=lifetime,
                    factory=None,
                    instance=None,
                )
            else:
                raise InvalidRegistrationError(
                    f"Registration for '{interface.__name__}' must provide "
                    "implementation, factory, or instance."
                )

            self._descriptors[interface] = descriptor

    def resolve(self, interface: type[T]) -> T:
        """Resolve a service by its interface type.

        .. note::

            This method does **not** perform dependency injection. It calls
            factories as-is and instantiates implementations with no arguments.
            For constructor injection, use the DI Container.

        Handles lifetime management:

        - Singleton: returns the cached instance, creating it on first call.
        - Transient: creates a new instance each time.
        - Scoped: creates a new instance (scope caching is handled by the
          DI container, not the Registry).

        Args:
            interface: The registered interface type.

        Returns:
            An instance of the service.

        Raises:
            ServiceNotFoundError: If interface is not registered.
        """
        with self._lock:
            descriptor = self._descriptors.get(interface)
            if descriptor is None:
                raise ServiceNotFoundError(
                    f"Service '{interface.__name__}' is not registered. "
                    f"Register it before attempting resolution."
                )

            if descriptor.instance is not None:
                return descriptor.instance  # type: ignore[return-value]

            if descriptor.lifetime is Lifetime.SINGLETON:
                if interface not in self._singletons:
                    self._singletons[interface] = self._create_instance(descriptor)
                return self._singletons[interface]  # type: ignore[return-value]

            return self._create_instance(descriptor)  # type: ignore[return-value]

    def create(self, interface: type[T]) -> T:
        """Create a new instance, ignoring the singleton cache.

        This is used by the DI container when it needs a fresh instance
        for transient or scoped resolution while still delegating factory
        and implementation invocation to the Registry.

        Args:
            interface: The registered interface type.

        Returns:
            A new instance of the service.

        Raises:
            ServiceNotFoundError: If interface is not registered.
        """
        with self._lock:
            descriptor = self._descriptors.get(interface)
            if descriptor is None:
                raise ServiceNotFoundError(f"Service '{interface.__name__}' is not registered.")
            return self._create_instance(descriptor)  # type: ignore[return-value]

    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """Create a new instance from a descriptor, ignoring lifetime policy.

        Args:
            descriptor: The service descriptor.

        Returns:
            A new service instance.

        Raises:
            InvalidRegistrationError: If the descriptor has no creation path.
        """
        if descriptor.factory is not None:
            return descriptor.factory()
        if descriptor.implementation is not None:
            return descriptor.implementation()
        raise InvalidRegistrationError(
            f"Descriptor for '{descriptor.interface.__name__}' has no factory or implementation."
        )

    def unregister(self, interface: type) -> None:
        """Remove a registration and clear its singleton cache.

        Args:
            interface: The interface type to unregister.
        """
        with self._lock:
            self._descriptors.pop(interface, None)
            self._singletons.pop(interface, None)

    def contains(self, interface: type) -> bool:
        """Check if an interface is registered.

        Args:
            interface: The type to check.

        Returns:
            True if the interface has been registered.
        """
        with self._lock:
            return interface in self._descriptors

    def get_descriptor(self, interface: type) -> ServiceDescriptor:
        """Get the descriptor for a registered interface.

        Args:
            interface: The registered interface type.

        Returns:
            The immutable service descriptor.

        Raises:
            ServiceNotFoundError: If interface is not registered.
        """
        with self._lock:
            descriptor = self._descriptors.get(interface)
            if descriptor is None:
                raise ServiceNotFoundError(f"Service '{interface.__name__}' is not registered.")
            return descriptor

    def descriptors(self) -> dict[type, ServiceDescriptor]:
        """Return a shallow copy of all registered descriptors.

        Returns:
            Mapping from interface type to descriptor.
        """
        with self._lock:
            return dict(self._descriptors)

    def get_singleton(self, interface: type) -> Any | None:
        """Get a cached singleton instance if one exists.

        Args:
            interface: The registered interface type.

        Returns:
            The cached singleton instance, or None if not yet created.
        """
        with self._lock:
            return self._singletons.get(interface)

    def set_singleton(self, interface: type, instance: Any) -> None:
        """Cache a singleton instance.

        Args:
            interface: The registered interface type.
            instance: The instance to cache.
        """
        with self._lock:
            self._singletons[interface] = instance

    def clear(self) -> None:
        """Clear all registrations and singleton cache."""
        with self._lock:
            self._descriptors.clear()
            self._singletons.clear()
