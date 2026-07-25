"""Lightweight event system for the Jarvis kernel.

Provides decoupled, synchronous event publishing and subscription
for cross-cutting concerns.
"""

from kernel.events.bus import Event, EventBus, EventListener

__all__ = [
    "Event",
    "EventBus",
    "EventListener",
]
