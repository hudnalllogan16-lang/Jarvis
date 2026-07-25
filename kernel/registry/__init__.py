"""Service Registry package.

Provides the Registry for storing and retrieving service registrations,
along with lifetime management and immutable service descriptors.

This is the single source of truth for service metadata in Jarvis.
"""

from kernel.registry.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationError,
    RegistryError,
    ServiceNotFoundError,
)
from kernel.registry.models import Lifetime, ServiceDescriptor
from kernel.registry.registry import Registry

__all__ = [
    "DuplicateRegistrationError",
    "InvalidRegistrationError",
    "Lifetime",
    "Registry",
    "RegistryError",
    "ServiceDescriptor",
    "ServiceNotFoundError",
]
