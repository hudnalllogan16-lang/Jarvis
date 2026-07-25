"""Dependency Injection package.

Provides the Container for automatic constructor injection and
recursive dependency resolution, and Scope for managing scoped
lifetimes.
"""

from kernel.di.container import Container
from kernel.di.exceptions import (
    CircularDependencyError,
    DIError,
    MissingDependencyError,
    UnresolvableTypeError,
)
from kernel.di.scope import Scope

__all__ = [
    "Container",
    "Scope",
    "CircularDependencyError",
    "DIError",
    "MissingDependencyError",
    "UnresolvableTypeError",
]
