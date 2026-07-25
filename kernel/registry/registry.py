"""Production Service Registry for the Jarvis kernel.

The Service Registry maps abstract interfaces to concrete implementations
with configurable lifetimes. It supports class registration, instance
registration, and factory registration for both singleton and transient
lifetimes.

Thread Safety:
    All public methods are thread-safe using an internal reentrant lock.
    Singleton instantiation and factory invocation are performed under the
    lock to prevent race conditions during lazy initialization.

Design Notes:
    - Constructor injection and dependency graph resolution are explicitly
      out of scope; they are future milestones.
    - The registry stores descriptors immutably and caches singleton instances
      separately to support explicit replacement without stale instances.
    - Factories are callables invoked with zero arguments. They integrate
      naturally with the existing lifetime model.
    - Transient services must be registered with a class or factory, not an
      instance, since a new instance is created on every resolve.
"""

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from kernel.registry.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    ServiceNotFoundError,
)
from kernel.registry.lifetime import Lifetime
from kernel.registry.service_descriptor import ServiceDescriptor

T = TypeVar("T")


class ServiceRegistry:
    """Thread-safe service registry supporting singleton and transient lifetimes.

    The registry maps abstract interfaces to concrete implementations.
    It does not perform constructor injection or dependency graph resolution.

    Example::

        registry = ServiceRegistry()
        registry.register_singleton(ILogger, ConsoleLogger)
        logger = registry.resolve(ILogger)

    Attributes:
        _lock: Reentrant lock protecting all internal state.
        _descriptors: Mapping from interface type to service descriptor.
        _singletons: Cache of instantiated singleton instances.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._lock = threading.RLock()
        self._descriptors: dict[type[Any], ServiceDescriptor] = {}
        self._singletons: dict[type[Any], Any] = {}

    def _register(
        self,
        interface: type[T],
        implementation: type[T] | T | Callable[[], T],
        lifetime: Lifetime,
    ) -> None:
        """Internal registration logic shared by public register methods.

        Args:
            interface: The abstract interface to register under.
            implementation: The concrete class, instance, or factory.
            lifetime: The service lifetime.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
        """
        if interface in self._descriptors:
            raise DuplicateRegistrationError(
                f"Interface '{interface.__name__}' is already registered. "
                f"Use replace_singleton() or replace_transient() to explicitly "
                f"override, or unregister() first."
            )
        self._descriptors[interface] = ServiceDescriptor(
            interface=interface,
            implementation=implementation,
            lifetime=lifetime,
        )

    def register_singleton(
        self,
        interface: type[T],
        implementation: type[T] | T,
    ) -> None:
        """Register a singleton service from a class or instance.

        If *implementation* is a class, it is lazily instantiated on first
        :meth:`resolve`. If *implementation* is an instance, it is used directly.

        Args:
            interface: The abstract interface to register under.
            implementation: The concrete class or pre-instantiated instance.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
        """
        with self._lock:
            self._register(interface, implementation, Lifetime.SINGLETON)

    def register_singleton_factory(
        self,
        interface: type[T],
        factory: Callable[[], T],
    ) -> None:
        """Register a singleton service from a factory callable.

        The factory is called lazily on first :meth:`resolve` and the result
        is cached for all subsequent resolves.

        Args:
            interface: The abstract interface to register under.
            factory: A callable that returns the service instance.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
        """
        with self._lock:
            self._register(interface, factory, Lifetime.SINGLETON)

    def register_transient(
        self,
        interface: type[T],
        implementation: type[T],
    ) -> None:
        """Register a transient service from a class.

        A new instance is created on every :meth:`resolve`. The *implementation*
        must be a class (not an instance) since it needs to be instantiated
        repeatedly.

        Args:
            interface: The abstract interface to register under.
            implementation: The concrete class to instantiate.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
            InvalidRegistrationError: If *implementation* is not a class.
        """
        with self._lock:
            if not isinstance(implementation, type):  # type: ignore[reportUnnecessaryIsInstance]
                raise InvalidRegistrationError(
                    f"Transient registration for '{interface.__name__}' "
                    f"requires a class, not an instance of type "
                    f"'{type(implementation).__name__}'."
                )
            self._register(interface, implementation, Lifetime.TRANSIENT)

    def register_transient_factory(
        self,
        interface: type[T],
        factory: Callable[[], T],
    ) -> None:
        """Register a transient service from a factory callable.

        The factory is called on every :meth:`resolve`, producing a new
        instance each time.

        Args:
            interface: The abstract interface to register under.
            factory: A callable that returns the service instance.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
            InvalidRegistrationError: If *factory* is not callable.
        """
        with self._lock:
            if not callable(factory):
                raise InvalidRegistrationError(
                    f"Transient factory registration for '{interface.__name__}' "
                    f"requires a callable, not '{type(factory).__name__}'."
                )
            self._register(interface, factory, Lifetime.TRANSIENT)

    def replace_singleton(
        self,
        interface: type[T],
        implementation: type[T] | T,
    ) -> None:
        """Replace an existing singleton registration.

        The old singleton instance (if any) is discarded. The new
        implementation will be instantiated lazily on the next resolve.

        Args:
            interface: The abstract interface to replace.
            implementation: The new concrete class or instance.

        Raises:
            ServiceNotFoundError: If the interface is not currently registered.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"Cannot replace '{interface.__name__}': not registered."
                )
            self._descriptors[interface] = ServiceDescriptor(
                interface=interface,
                implementation=implementation,
                lifetime=Lifetime.SINGLETON,
            )
            self._singletons.pop(interface, None)

    def replace_singleton_factory(
        self,
        interface: type[T],
        factory: Callable[[], T],
    ) -> None:
        """Replace an existing singleton registration with a factory.

        The old singleton instance (if any) is discarded. The factory
        will be called lazily on the next resolve.

        Args:
            interface: The abstract interface to replace.
            factory: A callable that returns the service instance.

        Raises:
            ServiceNotFoundError: If the interface is not currently registered.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"Cannot replace '{interface.__name__}': not registered."
                )
            self._descriptors[interface] = ServiceDescriptor(
                interface=interface,
                implementation=factory,
                lifetime=Lifetime.SINGLETON,
            )
            self._singletons.pop(interface, None)

    def replace_transient(
        self,
        interface: type[T],
        implementation: type[T],
    ) -> None:
        """Replace an existing transient registration.

        Args:
            interface: The abstract interface to replace.
            implementation: The new concrete class.

        Raises:
            ServiceNotFoundError: If the interface is not currently registered.
            InvalidRegistrationError: If *implementation* is not a class.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"Cannot replace '{interface.__name__}': not registered."
                )
            if not isinstance(implementation, type):  # type: ignore[reportUnnecessaryIsInstance]
                raise InvalidRegistrationError(
                    f"Transient registration for '{interface.__name__}' "
                    f"requires a class, not an instance."
                )
            self._descriptors[interface] = ServiceDescriptor(
                interface=interface,
                implementation=implementation,
                lifetime=Lifetime.TRANSIENT,
            )

    def replace_transient_factory(
        self,
        interface: type[T],
        factory: Callable[[], T],
    ) -> None:
        """Replace an existing transient registration with a factory.

        Args:
            interface: The abstract interface to replace.
            factory: A callable that returns the service instance.

        Raises:
            ServiceNotFoundError: If the interface is not currently registered.
            InvalidRegistrationError: If *factory* is not callable.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"Cannot replace '{interface.__name__}': not registered."
                )
            if not callable(factory):
                raise InvalidRegistrationError(
                    f"Transient factory registration for '{interface.__name__}' "
                    f"requires a callable, not '{type(factory).__name__}'."
                )
            self._descriptors[interface] = ServiceDescriptor(
                interface=interface,
                implementation=factory,
                lifetime=Lifetime.TRANSIENT,
            )

    def resolve(self, interface: type[T]) -> T:
        """Resolve the implementation for a registered interface.

        For singletons, returns the same instance on every call.
        For transients, creates and returns a new instance on every call.

        Args:
            interface: The abstract interface to resolve.

        Returns:
            The implementation instance.

        Raises:
            ServiceNotFoundError: If the interface has not been registered.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"No implementation registered for interface '{interface.__name__}'."
                )

            descriptor = self._descriptors[interface]

            if descriptor.lifetime == Lifetime.SINGLETON:
                if interface not in self._singletons:
                    impl = descriptor.implementation
                    if isinstance(impl, type):
                        # Class registration: instantiate lazily.
                        self._singletons[interface] = impl()
                    elif callable(impl):
                        # Factory registration: invoke the factory.
                        self._singletons[interface] = impl()
                    else:
                        # Instance registration: use the pre-built instance.
                        self._singletons[interface] = impl
                return self._singletons[interface]

            # Transient: always invoke the implementation (class or factory).
            return descriptor.implementation()

    def unregister(self, interface: type[T]) -> None:
        """Unregister a service by interface.

        Args:
            interface: The abstract interface to unregister.

        Raises:
            ServiceNotFoundError: If the interface is not registered.
        """
        with self._lock:
            if interface not in self._descriptors:
                raise ServiceNotFoundError(
                    f"Cannot unregister '{interface.__name__}': not registered."
                )
            self._descriptors.pop(interface, None)
            self._singletons.pop(interface, None)

    def contains(self, interface: type[Any]) -> bool:
        """Check whether an interface is registered.

        Args:
            interface: The abstract interface to check.

        Returns:
            True if the interface has a registered implementation,
            False otherwise.
        """
        with self._lock:
            return interface in self._descriptors

    def clear(self) -> None:
        """Remove all registrations and singleton caches.

        Primarily useful for testing and controlled shutdown.
        """
        with self._lock:
            self._descriptors.clear()
            self._singletons.clear()

    def __len__(self) -> int:
        """Return the number of registered interfaces.

        Returns:
            The count of registered service descriptors.
        """
        with self._lock:
            return len(self._descriptors)
