"""Core protocols used across Jarvis layers.

Protocols define structural subtyping contracts. Any class that
implements the required methods satisfies the protocol without
explicit inheritance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Initializable(Protocol):
    """Protocol for components that require explicit initialization."""

    def initialize(self) -> None:
        """Perform any startup logic required by the component."""
        ...


@runtime_checkable
class Disposable(Protocol):
    """Protocol for components that require explicit cleanup."""

    def dispose(self) -> None:
        """Release resources held by the component."""
        ...
