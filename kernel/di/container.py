"""Dependency Injection container for Jarvis.

The DI container is responsible for constructor inspection, automatic object
creation, recursive dependency resolution, and circular dependency detection.
It consumes the Service Registry for registration metadata, lifetime management,
singleton cache, factories, and descriptors. It does NOT duplicate those concerns.

Thread-safe for concurrent resolution operations.

Lifecycle
---------

1. ``resolve(T)`` is called.
2. If ``T`` is registered in the Registry, the lifetime policy is consulted:

   - **Singleton:** The Container checks the Registry singleton cache. If
     absent, it creates the instance via auto-wiring and caches it.
   - **Scoped:** If an active scope exists, the scope cache is used.
     Otherwise, the instance is created as transient.
   - **Transient:** A new instance is created on every call.

3. If ``T`` is not registered but is a concrete class, constructor injection
   (auto-wiring) is performed.
4. If ``T`` is neither registered nor concrete, ``UnresolvableTypeError`` is
   raised.

Constructor injection inspects ``__init__`` type hints and resolves each
parameter recursively. Parameters without type hints or with primitive types
and no default value cause ``MissingDependencyError``. Circular dependencies
are detected via a per-thread resolution stack.
"""

from __future__ import annotations

import inspect
import threading
from typing import Any, Protocol, TypeVar, get_args, get_origin, get_type_hints

from kernel.di.exceptions import (
    CircularDependencyError,
    DIError,
    MissingDependencyError,
    UnresolvableTypeError,
)
from kernel.di.scope import Scope
from kernel.registry.exceptions import InvalidRegistrationError, ServiceNotFoundError
from kernel.registry.models import Lifetime, ServiceDescriptor
from kernel.registry.registry import Registry

T = TypeVar("T")

# Primitive types that should never be auto-wired
_PRIMITIVE_TYPES: set[type] = {
    int,
    float,
    str,
    bool,
    bytes,
    list,
    dict,
    set,
    tuple,
    type(None),
}


class Container:
    """Dependency injection container with automatic constructor wiring.

    The Container delegates registration and lifetime metadata to the
    Service Registry. It adds constructor injection, recursive resolution,
    circular dependency detection, and scope management on top.

    Typical usage::

        registry = Registry()
        registry.register(IDatabase, PostgresDatabase, Lifetime.SINGLETON)
        container = Container(registry)
        db = container.resolve(IDatabase)

    This class is considered **stable** for the Milestone 2 baseline.
    """

    def __init__(self, registry: Registry | None = None) -> None:
        """Initialize the container with an optional registry.

        Args:
            registry: The service registry to use. If None, a new Registry
                is created.
        """
        self._registry = registry if registry is not None else Registry()
        self._lock = threading.RLock()
        self._local = threading.local()

    @property
    def registry(self) -> Registry:
        """Access the underlying service registry.

        Returns:
            The Registry instance used by this container.
        """
        return self._registry

    def create_scope(self) -> Scope:
        """Create a new resolution scope.

        Returns:
            A new Scope instance. Use as a context manager.
        """
        return Scope(self)

    def resolve(self, interface: type[T]) -> T:
        """Resolve a service by type, using registration or auto-wiring.

        Resolution order:

        1. If the type is registered in the Registry:

           - Singleton: checks the Registry singleton cache; creates via
             auto-wiring and caches if absent.
           - Scoped: checks the active scope cache; creates if absent.
             If no scope is active, treats as transient.
           - Transient: creates a new instance with auto-wiring.

        2. If not registered but is a concrete class: auto-wires via
           constructor injection.

        3. Otherwise: raises ``UnresolvableTypeError``.

        Args:
            interface: The type to resolve.

        Returns:
            An instance of the requested type.

        Raises:
            CircularDependencyError: If a circular dependency is detected.
            MissingDependencyError: If a dependency cannot be resolved.
            UnresolvableTypeError: If the type is neither registered nor concrete.
        """
        with self._lock:
            resolution_stack: list[type] = getattr(self._local, "resolution_stack", [])
            self._local.resolution_stack = resolution_stack

            stack: list[type] = resolution_stack

            if interface in stack:
                chain = " -> ".join(t.__name__ for t in stack + [interface])
                raise CircularDependencyError(
                    f"Circular dependency detected: {chain}. "
                    f"Break the cycle by registering a factory or using an interface."
                )

            stack.append(interface)
            try:
                if self._registry.contains(interface):
                    descriptor = self._registry.get_descriptor(interface)
                    if descriptor.lifetime is Lifetime.SINGLETON:
                        cached = self._registry.get_singleton(interface)
                        if cached is not None:
                            return cached
                        instance = self.create_from_descriptor(descriptor)
                        self._registry.set_singleton(interface, instance)
                        return instance
                    if descriptor.lifetime is Lifetime.SCOPED:
                        active_scope = self._active_scope()
                        if active_scope is not None and active_scope.is_active:
                            return active_scope.resolve_scoped(interface)
                        # No active scope: treat as transient
                        return self.create_from_descriptor(descriptor)
                    return self.create_from_descriptor(descriptor)

                if self._is_concrete_type(interface):
                    return self._build_concrete(interface)

                raise UnresolvableTypeError(
                    f"Cannot resolve type '{interface.__name__}'. "
                    f"It is not registered and cannot be auto-wired "
                    f"(it may be abstract or a primitive type)."
                )
            finally:
                stack.pop()
                if len(stack) == 0:
                    delattr(self._local, "resolution_stack")

    def build(self, cls: type[T]) -> T:
        """Build a concrete type using constructor injection.

        Unlike ``resolve()``, this method always performs auto-wiring and
        does not check the registry first. Useful for building unregistered
        concrete types whose dependencies are registered.

        Args:
            cls: The concrete class to instantiate.

        Returns:
            An instance of the class with dependencies injected.

        Raises:
            CircularDependencyError: If a circular dependency is detected.
            MissingDependencyError: If a required dependency cannot be resolved.
            TypeError: If the class is not concrete.
        """
        if not self._is_concrete_type(cls):
            raise TypeError(
                f"Cannot build abstract type '{cls.__name__}'. "
                f"Use resolve() for registered services."
            )
        return self._build_concrete(cls)

    def _build_concrete(self, cls: type[T]) -> T:
        """Build a concrete type by inspecting ``__init__`` and resolving parameters.

        ``*args`` and ``**kwargs`` parameters are ignored. Parameters with
        primitive types (``int``, ``str``, etc.) and no default value raise
        ``MissingDependencyError``. Parameters annotated as ``Optional[T]``
        or ``T | None`` are unwrapped to ``T``; if ``T`` is resolvable, it
        is injected even when a default of ``None`` is present.

        Args:
            cls: The concrete class to instantiate.

        Returns:
            An instance with injected dependencies.

        Raises:
            MissingDependencyError: If a parameter lacks a type hint or default
                and cannot be resolved.
        """
        try:
            sig = inspect.signature(cls.__init__)
            type_hints = get_type_hints(cls.__init__)
        except (TypeError, NameError) as exc:
            raise MissingDependencyError(
                f"Failed to inspect constructor for '{cls.__name__}': {exc}"
            ) from exc

        kwargs: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "args", "kwargs"):
                continue

            param_type = type_hints.get(param_name)
            if param_type is None:
                if param.default is inspect.Parameter.empty:
                    raise MissingDependencyError(
                        f"Parameter '{param_name}' in '{cls.__name__}.__init__' "
                        f"has no type hint and no default value."
                    )
                continue

            unwrapped = self._unwrap_optional(param_type)
            if unwrapped is type(None):
                if param.default is inspect.Parameter.empty:
                    raise MissingDependencyError(
                        f"Parameter '{param_name}' in '{cls.__name__}.__init__' "
                        f"is None-only and has no default value."
                    )
                continue

            param_type = unwrapped

            if not self._is_resolvable_type(param_type):
                if param.default is inspect.Parameter.empty:
                    raise MissingDependencyError(
                        f"Parameter '{param_name}: {param_type.__name__}' in "
                        f"'{cls.__name__}.__init__' is a primitive type with "
                        f"no default value."
                    )
                continue

            try:
                kwargs[param_name] = self.resolve(param_type)
            except CircularDependencyError:
                raise
            except (DIError, ServiceNotFoundError) as exc:
                if param.default is inspect.Parameter.empty:
                    raise MissingDependencyError(
                        f"Failed to resolve dependency '{param_name}: "
                        f"{param_type.__name__}' for '{cls.__name__}': {exc}"
                    ) from exc
                # Use default value if resolution fails

        try:
            return cls(**kwargs)
        except Exception as exc:
            raise MissingDependencyError(f"Failed to instantiate '{cls.__name__}': {exc}") from exc

    def create_from_descriptor(self, descriptor: ServiceDescriptor) -> Any:
        """Create an instance from a registry descriptor with auto-wiring.

        This is the canonical creation path for registered services. It
        handles factories, pre-created instances, and implementation types
        that require constructor injection.

        Args:
            descriptor: The service descriptor.

        Returns:
            A new service instance.

        Raises:
            InvalidRegistrationError: If the descriptor has no creation path.
        """
        if descriptor.instance is not None:
            return descriptor.instance
        if descriptor.factory is not None:
            return descriptor.factory()
        if descriptor.implementation is not None:
            return self._build_concrete(descriptor.implementation)  # type: ignore[reportUnknownVariableType]
        raise InvalidRegistrationError(
            f"Descriptor for '{descriptor.interface.__name__}' has no factory or implementation."
        )

    def _is_concrete_type(self, cls: type) -> bool:
        """Check if a type is concrete and can be instantiated.

        Protocols and abstract classes are rejected.

        Args:
            cls: The type to check.

        Returns:
            True if the type is a non-abstract, non-primitive, non-Protocol
            class.
        """
        if cls in _PRIMITIVE_TYPES:
            return False
        try:
            return (
                inspect.isclass(cls)
                and not inspect.isabstract(cls)
                and not issubclass(cls, Protocol)
            )
        except TypeError:
            return False

    def _is_resolvable_type(self, cls: type) -> bool:
        """Check if a type is eligible for resolution.

        Args:
            cls: The type to check.

        Returns:
            True if the type can be resolved (registered or concrete).
        """
        if cls in _PRIMITIVE_TYPES:
            return False
        try:
            return self._registry.contains(cls) or (
                inspect.isclass(cls)
                and not inspect.isabstract(cls)
                and not issubclass(cls, Protocol)
            )
        except TypeError:
            return False

    @staticmethod
    def _unwrap_optional(param_type: type) -> type:
        """Extract the inner type from ``Optional[X]`` or ``X | None``.

        Args:
            param_type: The parameter type hint.

        Returns:
            The unwrapped type, or the original if not an optional.
        """
        origin = get_origin(param_type)
        if origin is None:
            return param_type

        args = get_args(param_type)
        if origin is type or origin is type[Any]:
            return param_type

        # Handle UnionType (X | None) and typing.Union
        try:
            from types import UnionType

            if origin is UnionType or (
                hasattr(origin, "__origin__") and origin.__origin__ is type | None
            ):
                non_none = [a for a in args if a is not type(None)]
                if len(non_none) == 1:
                    return non_none[0]
        except ImportError:
            pass

        return param_type

    # ------------------------------------------------------------------
    # Scope coordination (package-internal API)
    # ------------------------------------------------------------------

    def _active_scope(self) -> Scope | None:
        """Return the currently active scope for this thread.

        If multiple scopes are nested, returns the innermost (most recent)
        active scope.

        Returns:
            The active Scope, or None if no scope is active.
        """
        scope_stack: list[Scope] = getattr(self._local, "scope_stack", [])
        if scope_stack:
            return scope_stack[-1]
        return None

    def set_active_scope(self, scope: Scope) -> None:
        """Push a scope onto the active-scope stack for the current thread.

        Called by ``Scope.__enter__``. This method is part of the
        package-internal coordination API between Container and Scope.

        Args:
            scope: The scope to activate.
        """
        scope_stack: list[Scope] = getattr(self._local, "scope_stack", [])
        scope_stack.append(scope)
        self._local.scope_stack = scope_stack

    def clear_active_scope(self, scope: Scope) -> None:
        """Pop the given scope from the active-scope stack.

        Called by ``Scope.__exit__``. If the scope is not the top of the
        stack, the stack is cleared defensively.

        Args:
            scope: The scope being cleared.
        """
        scope_stack: list[Scope] = getattr(self._local, "scope_stack", [])
        if scope_stack and scope_stack[-1] is scope:
            scope_stack.pop()
        else:
            # Defensive: stack is in an unexpected state
            scope_stack.clear()
        self._local.scope_stack = scope_stack
