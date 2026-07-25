"""Data models for LLM interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MessageRole(StrEnum):
    """Roles in a conversational message exchange."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    """A single message in a conversation."""

    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Structured request to an LLM provider."""

    messages: list[Message] = field(default_factory=list[Message])
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Structured response from an LLM provider."""

    content: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    raw: Any | None = None
