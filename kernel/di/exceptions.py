"""Exceptions for the Dependency Injection container.

All DI errors inherit from DIError for unified handling.
"""


class DIError(Exception):
    """Base exception for dependency injection operations."""


class CircularDependencyError(DIError):
    """Raised when a circular dependency is detected during resolution."""


class MissingDependencyError(DIError):
    """Raised when a required dependency cannot be resolved."""


class UnresolvableTypeError(DIError):
    """Raised when a type cannot be auto-wired and is not registered."""
