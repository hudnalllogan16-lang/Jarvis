"""Memory backend protocol.

All memory persistence implementations must satisfy this protocol.
The MemoryService interacts with backends exclusively through this
interface.
"""

from __future__ import annotations

from typing import Protocol

from services.memory.models import Memory


class MemoryBackend(Protocol):
    """Protocol for memory storage backends."""

    def store(self, memory: Memory) -> None:
        """Persist ``memory``.

        Args:
            memory: The memory to store.
        """
        ...

    def retrieve(self, memory_id: str) -> Memory | None:
        """Fetch a memory by its unique identifier.

        Args:
            memory_id: The UUID of the memory.

        Returns:
            The memory if found, otherwise ``None``.
        """
        ...

    def update(self, memory: Memory) -> None:
        """Replace an existing memory.

        Args:
            memory: The memory to update (must have a valid ``id``).
        """
        ...

    def delete(self, memory_id: str) -> None:
        """Remove a memory by its unique identifier.

        Args:
            memory_id: The UUID of the memory to delete.
        """
        ...

    def search(self, query: str, limit: int = 10) -> list[Memory]:
        """Search for memories matching ``query``.

        The search semantics are backend-specific. Simple backends may
        perform substring matching; vector backends may use embeddings.

        Args:
            query: The search query.
            limit: Maximum number of results to return.

        Returns:
            A list of matching memories, ordered by relevance.
        """
        ...

    def list_all(self) -> list[Memory]:
        """Return all stored memories.

        Returns:
            A list of all memories (order is backend-specific).
        """
        ...
