"""Memory service implementation.

The MemoryService provides a high-level API for memory operations and
emits lifecycle events through the EventBus.
"""

from __future__ import annotations

from kernel.events import Event, EventBus
from services.memory.backend import MemoryBackend
from services.memory.models import Memory


class MemoryService:
    """Service facade for memory operations.

    Emits ``memory.stored``, ``memory.retrieved``, ``memory.updated``,
    and ``memory.deleted`` events.
    """

    def __init__(
        self,
        backend: MemoryBackend,
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize the memory service.

        Args:
            backend: The persistence backend to use.
            event_bus: Optional event bus for lifecycle events.
        """
        self._backend = backend
        self._event_bus = event_bus

    def store(self, memory: Memory) -> None:
        """Store a new memory.

        Args:
            memory: The memory to persist.
        """
        self._backend.store(memory)
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="memory.stored",
                    payload={
                        "memory_id": memory.id,
                        "category": memory.category.value,
                    },
                )
            )

    def retrieve(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID.

        Args:
            memory_id: The unique identifier.

        Returns:
            The memory if found, otherwise ``None``.
        """
        memory = self._backend.retrieve(memory_id)
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="memory.retrieved",
                    payload={"memory_id": memory_id, "found": memory is not None},
                )
            )
        return memory

    def update(self, memory: Memory) -> None:
        """Update an existing memory.

        Args:
            memory: The memory to replace.
        """
        self._backend.update(memory)
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="memory.updated",
                    payload={"memory_id": memory.id},
                )
            )

    def delete(self, memory_id: str) -> None:
        """Delete a memory by ID.

        Args:
            memory_id: The unique identifier.
        """
        self._backend.delete(memory_id)
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="memory.deleted",
                    payload={"memory_id": memory_id},
                )
            )

    def search(self, query: str, limit: int = 10) -> list[Memory]:
        """Search for memories.

        Args:
            query: The search query.
            limit: Maximum results.

        Returns:
            Matching memories ordered by relevance.
        """
        results = self._backend.search(query, limit)
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="memory.searched",
                    payload={"query": query, "result_count": len(results)},
                )
            )
        return results

    def list_all(self) -> list[Memory]:
        """Return all stored memories.

        Returns:
            All memories in the backend.
        """
        return self._backend.list_all()
