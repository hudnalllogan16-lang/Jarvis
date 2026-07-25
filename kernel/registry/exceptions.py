"""Exceptions for the Service Registry.

All registry errors inherit from RegistryError for unified handling.
"""


class RegistryError(Exception):
    """Base exception for all registry operations."""


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register an interface that is already registered."""


class ServiceNotFoundError(RegistryError):
    """Raised when attempting to resolve an interface that has not been registered."""


class InvalidRegistrationError(RegistryError):
    """Raised when a registration is malformed or inconsistent."""
