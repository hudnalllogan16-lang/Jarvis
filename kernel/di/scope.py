"""Scope context for scoped lifetime services.

A scope manages a cache of scoped instances. Within an active scope,
services registered with ``Lifetime.SCOPED`` are created once and reused
for all resolutions within that scope.

Scopes can be nested. When a nested scope is active, it becomes the
innermost scope; upon exit, the outer scope resumes as the active scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.di.container import Container


class Scope:
    """A resolution scope for managing scoped lifetime services.

    Use as a context manager::

        with container.create_scope() as scope:
            service = container.resolve(IService)

    Within the scope, ``Lifetime.SCOPED`` services are cached. Nested
    scopes are supported: entering a new scope pushes it onto the
    thread-local scope stack, and exiting pops it, restoring the outer
    scope.

    This class is considered **stable** for the Milestone 2 baseline.
    """

    def __init__(self, container: Container) -> None:
        """Initialize a new scope.

        Args:
            container: The parent DI container.
        """
        self._container = container
        self._scoped_instances: dict[type, Any] = {}
        self._active = False

    @property
    def is_active(self) -> bool:
        """Return whether the scope is currently active."""
        return self._active

    def __enter__(self) -> Scope:
        """Activate the scope.

        Returns:
            This scope instance.
        """
        self._active = True
        self._container.set_active_scope(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Deactivate the scope and clear scoped instances.

        Exceptions are **not** suppressed; they propagate normally.
        """
        self._scoped_instances.clear()
        self._active = False
        self._container.clear_active_scope(self)

    def resolve_scoped(self, interface: type) -> Any:
        """Resolve a scoped service within this scope.

        Args:
            interface: The registered interface type.

        Returns:
            The cached or newly created instance.

        Raises:
            ServiceNotFoundError: If the interface is not registered.
        """
        if interface in self._scoped_instances:
            return self._scoped_instances[interface]

        instance = self._container.create_from_descriptor(
            self._container.registry.get_descriptor(interface)
        )
        self._scoped_instances[interface] = instance
        return instance
