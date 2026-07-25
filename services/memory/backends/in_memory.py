"""In-memory memory backend for development and testing."""

from __future__ import annotations

import threading

from services.memory.models import Memory


class InMemoryBackend:
    """Simple in-memory backend with relevance scoring.

    Thread-safe for concurrent access. Data is lost when the process exits.
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self._memories: dict[str, Memory] = {}
        self._lock = threading.RLock()

    def store(self, memory: Memory) -> None:
        """Persist memory in memory."""
        with self._lock:
            self._memories[memory.id] = memory

    def retrieve(self, memory_id: str) -> Memory | None:
        """Fetch memory by ID."""
        with self._lock:
            return self._memories.get(memory_id)

    def update(self, memory: Memory) -> None:
        """Replace existing memory."""
        with self._lock:
            if memory.id not in self._memories:
                raise KeyError(f"Memory {memory.id} not found")
            self._memories[memory.id] = memory

    def delete(self, memory_id: str) -> None:
        """Remove memory by ID."""
        with self._lock:
            self._memories.pop(memory_id, None)

    def search(self, query: str, limit: int = 10) -> list[Memory]:
        """Search memories by relevance to query.

        Checks for substring matches in both directions and shared
        significant words (length > 3) to handle natural language queries.
        """
        query_lower = query.lower()
        query_words = {w for w in query_lower.split() if len(w) > 3}
        with self._lock:
            scored: list[tuple[int, Memory]] = []
            for m in self._memories.values():
                content_lower = m.content.lower()
                score = 0
                if query_lower in content_lower or content_lower in query_lower:
                    score += 10
                mem_words = {w for w in content_lower.split() if len(w) > 3}
                shared = query_words & mem_words
                score += len(shared)
                if score > 0:
                    scored.append((score, m))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [m for _, m in scored[:limit]]

    def list_all(self) -> list[Memory]:
        """Return all memories."""
        with self._lock:
            return list(self._memories.values())
