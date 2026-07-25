"""Exceptions raised by the Jarvis Service Registry."""


class RegistryError(Exception):
    """Base exception for all registry operations."""


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register an interface that is already registered."""


class ServiceNotFoundError(RegistryError):
    """Raised when attempting to resolve or unregister an interface that has not been registered."""


class InvalidRegistrationError(RegistryError):
    """Raised when a registration is invalid (e.g., transient with an instance)."""
