"""Tests for the memory service."""

from services.memory.backends.in_memory import InMemoryBackend
from services.memory.models import Memory, MemoryCategory
from services.memory.service import MemoryService


def test_store_and_retrieve() -> None:
    """Storing a memory should make it retrievable by ID."""
    backend = InMemoryBackend()
    service = MemoryService(backend)
    memory = Memory(content="Test", category=MemoryCategory.FACT)
    service.store(memory)
    retrieved = service.retrieve(memory.id)
    assert retrieved is not None
    assert retrieved.content == "Test"


def test_search_finds_content() -> None:
    """Search should find memories matching the query."""
    backend = InMemoryBackend()
    service = MemoryService(backend)
    service.store(Memory(content="My favorite color is blue", category=MemoryCategory.PREFERENCE))
    results = service.search("favorite color")
    assert len(results) == 1


def test_delete_removes_memory() -> None:
    """Deleting a memory should remove it from storage."""
    backend = InMemoryBackend()
    service = MemoryService(backend)
    memory = Memory(content="To delete", category=MemoryCategory.FACT)
    service.store(memory)
    service.delete(memory.id)
    assert service.retrieve(memory.id) is None
