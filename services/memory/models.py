"""Data models for the memory service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MemoryCategory(StrEnum):
    """Categories for organizing memories."""

    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    TASK = "task"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class Memory:
    """A single stored memory.

    Memories are immutable once created. Updates create a new memory
    and (typically) delete the old one.
    """

    content: str
    category: MemoryCategory = MemoryCategory.GENERAL
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def with_content(self, new_content: str) -> Memory:
        """Return a new Memory with updated content.

        Args:
            new_content: The replacement content.

        Returns:
            A new ``Memory`` instance preserving metadata.
        """
        return Memory(
            content=new_content,
            category=self.category,
            id=self.id,
            created_at=self.created_at,
            metadata=self.metadata,
        )
