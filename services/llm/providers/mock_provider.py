"""Mock LLM provider for testing and offline development.

The MockProvider returns deterministic responses based on simple
heuristics. It requires no external API keys and is safe for use
in tests.
"""

from __future__ import annotations

from services.llm.models import LLMRequest, LLMResponse, Message, MessageRole


class MockProvider:
    """Deterministic mock provider for testing.

    Implements the ``LLMProvider`` protocol without external dependencies.
    """

    def __init__(self, model: str = "mock") -> None:
        """Initialize the mock provider.

        Args:
            model: Model name reported in responses.

        """
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a deterministic mock response.

        Args:
            request: The incoming request.

        Returns:
            A mock response based on simple content analysis.

        """
        user_messages = [
            m.content for m in request.messages if m.role == MessageRole.USER
        ]
        last_user = user_messages[-1] if user_messages else ""
        memories = self._extract_memories(request.messages)
        content = self._generate_response(last_user, memories)

        return LLMResponse(
            content=content,
            model=self._model,
            usage={
                "prompt_tokens": len(last_user.split()),
                "completion_tokens": len(content.split()),
            },
        )

    def _extract_memories(self, messages: list[Message]) -> dict[str, str]:
        """Extract key-value memories from system messages."""
        memories: dict[str, str] = {}
        for m in messages:
            if m.role != MessageRole.SYSTEM:
                continue
            if "Relevant memories:" not in m.content:
                continue
            section = m.content.split("Relevant memories:")[-1]
            for line in section.strip().split("\n"):
                line = line.strip()
                if not line.startswith("- [") or "] " not in line:
                    continue
                mem = line.split("] ", 1)[-1]
                if " is " in mem:
                    key = mem.split(" is ")[0].lower()
                    val = mem.split(" is ", 1)[1]
                    memories[key] = val
        return memories

    def _generate_response(self, user_text: str, memories: dict[str, str]) -> str:
        """Generate a deterministic response from user text."""
        text_lower = user_text.lower().strip()

        if any(
            phrase in text_lower
            for phrase in (
                "remember that",
                "remember this",
                "store that",
                "save that",
            )
        ):
            return "Stored."

        if "favorite editor" in text_lower or "favourite editor" in text_lower:
            for key, val in memories.items():
                if "favorite editor" in key:
                    return f"Your favorite editor is {val}."
            return "I don\'t know your favorite editor yet."

        if "what is my name" in text_lower:
            return "I don\'t know your name yet."

        if text_lower.endswith("?"):
            return f"That\'s an interesting question about \'{user_text.rstrip("?")}\'."

        if user_text:
            return f"I understand: {user_text}"

        return "I\'m ready to help."
