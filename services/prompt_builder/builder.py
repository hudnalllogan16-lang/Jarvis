"""Prompt builder implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

from services.llm.models import Message, MessageRole
from services.memory.models import Memory


@dataclass(frozen=True, slots=True)
class PromptContext:
    """Inputs required to assemble a prompt."""

    system_instructions: str = (
        "You are Jarvis, a helpful personal AI assistant. "
        "Answer concisely and accurately. "
        "Use the provided memories to personalize your responses."
    )
    conversation_history: list[Message] = field(default_factory=list[Message])
    relevant_memories: list[Memory] = field(default_factory=list[Memory])
    user_message: str = ""


class PromptBuilder:
    """Assembles structured prompts from context components."""

    def build(self, context: PromptContext) -> list[Message]:
        """Build a message list from the provided context.

        Args:
            context: The prompt construction inputs.

        Returns:
            Ordered messages: system, memories (if any), history, user.

        """
        messages: list[Message] = []

        # System instructions
        system_content = context.system_instructions
        if context.relevant_memories:
            memory_section = self._format_memories(context.relevant_memories)
            system_content += "\n\nRelevant memories:\n" + memory_section
        messages.append(Message(role=MessageRole.SYSTEM, content=system_content))

        # Conversation history
        messages.extend(context.conversation_history)

        # Current user message
        if context.user_message:
            messages.append(
                Message(role=MessageRole.USER, content=context.user_message)
            )

        return messages

    def _format_memories(self, memories: list[Memory]) -> str:
        """Format memories for injection into the system prompt."""
        lines: list[str] = []
        for m in memories:
            lines.append(f"- [{m.category.value}] {m.content}")
        return "\n".join(lines)
