"""Jarvis Service Registry.

The Service Registry stores and retrieves service registrations by interface type.
It does not instantiate services, manage lifecycles, or perform dependency injection.
"""

from typing import Any, TypeVar

T = TypeVar("T")


class RegistryError(Exception):
    """Base exception for all registry operations."""


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register an interface that is already registered."""


class ServiceNotFoundError(RegistryError):
    """Raised when attempting to resolve or unregister an interface that has not been registered."""


class Registry:
    """Stores and retrieves service registrations by interface type.

    The registry maps abstract interfaces to their concrete implementations.
    It does not instantiate services or manage dependencies.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._registrations: dict[type[Any], Any] = {}

    def register(self, interface: type[T], implementation: Any) -> None:
        """Register an implementation under an interface type.

        Args:
            interface: The abstract interface or type to register under.
            implementation: The concrete implementation to associate with the interface.

        Raises:
            DuplicateRegistrationError: If the interface is already registered.
        """
        if interface in self._registrations:
            raise DuplicateRegistrationError(
                f"Interface '{interface.__name__}' is already registered. "
                f"Unregister it first before re-registering."
            )
        self._registrations[interface] = implementation

    def resolve(self, interface: type[T]) -> Any:
        """Resolve the implementation registered under an interface type.

        Args:
            interface: The abstract interface or type to resolve.

        Returns:
            The implementation registered under the given interface.

        Raises:
            ServiceNotFoundError: If the interface has not been registered.
        """
        if interface not in self._registrations:
            raise ServiceNotFoundError(
                f"No implementation registered for interface '{interface.__name__}'."
            )
        return self._registrations[interface]

    def unregister(self, interface: type[T]) -> None:
        """Unregister an implementation by interface type.

        Args:
            interface: The abstract interface or type to unregister.

        Raises:
            ServiceNotFoundError: If the interface has not been registered.
        """
        if interface not in self._registrations:
            raise ServiceNotFoundError(f"Cannot unregister '{interface.__name__}': not registered.")
        del self._registrations[interface]

    def contains(self, interface: type[Any]) -> bool:
        """Check whether an interface is registered.

        Args:
            interface: The abstract interface or type to check.

        Returns:
            True if the interface has a registered implementation,
            False otherwise.
        """
        return interface in self._registrations
