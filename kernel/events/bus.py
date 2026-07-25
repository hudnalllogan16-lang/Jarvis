"""Lightweight event system for the Jarvis kernel.

Provides decoupled, synchronous event publishing and subscription
for cross-cutting concerns such as logging, telemetry, and plugin hooks.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    """Base event dataclass.

    Subclass this to define domain-specific events.

    Attributes:
        name: The event type identifier.
        payload: Arbitrary structured data associated with the event.
    """

    name: str
    payload: dict[str, Any] = field(default_factory=dict[str, Any])


EventListener = Callable[[Event], None]


class EventBus:
    """In-memory event bus with synchronous delivery.

    Thread-safe for concurrent subscription and publication.
    Listeners are invoked synchronously in the order they were
    registered. A failing listener does not break the chain.
    """

    def __init__(self) -> None:
        """Initialize an empty event bus."""
        self._listeners: dict[str, list[EventListener]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_name: str, listener: EventListener) -> None:
        """Register ``listener`` for ``event_name``.

        Args:
            event_name: The event type to listen for.
            listener: Callable invoked when the event is published.

        """
        with self._lock:
            self._listeners.setdefault(event_name, []).append(listener)

    def unsubscribe(self, event_name: str, listener: EventListener) -> None:
        """Remove ``listener`` from ``event_name``.

        Args:
            event_name: The event type to unsubscribe from.
            listener: The callable to remove.

        """
        with self._lock:
            if event_name in self._listeners:
                self._listeners[event_name] = [
                    ln for ln in self._listeners[event_name] if ln is not listener
                ]

    def publish(self, event: Event) -> None:
        """Publish ``event`` to all registered listeners.

        Args:
            event: The event to publish.

        """
        with self._lock:
            listeners = list(self._listeners.get(event.name, []))

        for listener in listeners:
            with contextlib.suppress(Exception):
                listener(event)
