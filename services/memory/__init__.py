"""Memory service for long-term context storage and retrieval.

The memory service abstracts persistence behind the ``MemoryBackend``
protocol so that storage backends can be swapped without changing
consumer code.
"""

from services.memory.backend import MemoryBackend
from services.memory.models import Memory, MemoryCategory
from services.memory.service import MemoryService

__all__ = [
    "Memory",
    "MemoryBackend",
    "MemoryCategory",
    "MemoryService",
]
