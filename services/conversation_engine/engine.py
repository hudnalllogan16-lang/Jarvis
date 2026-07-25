"""Conversation engine — orchestrates the intelligence pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.events import Event, EventBus
from services.llm.models import LLMRequest, Message, MessageRole
from services.llm.service import LLMService
from services.memory.models import Memory, MemoryCategory
from services.memory.service import MemoryService
from services.prompt_builder.builder import PromptBuilder, PromptContext


@dataclass
class ConversationState:
    """Mutable state for a single conversation."""

    history: list[Message] = field(default_factory=list[Message])
    max_history: int = 20


class ConversationEngine:
    """Orchestrate the complete request lifecycle.

    User Input → Memory Retrieval → Prompt Construction →
    LLM Provider → Response → Memory Update.
    """

    def __init__(
        self,
        memory_service: MemoryService,
        llm_service: LLMService,
        prompt_builder: PromptBuilder,
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize the engine.

        Args:
            memory_service: Service for long-term memory operations.
            llm_service: Service for LLM completions.
            prompt_builder: Builder for assembling prompts.
            event_bus: Optional event bus for lifecycle events.

        """
        self._memory = memory_service
        self._llm = llm_service
        self._builder = prompt_builder
        self._event_bus = event_bus
        self._state = ConversationState()

    def process(self, user_input: str) -> str:
        """Process a single user turn.

        Args:
            user_input: The raw user message.

        Returns:
            The assistant's response text.

        """
        if self._event_bus is not None:
            self._event_bus.publish(
                Event(name="conversation.started", payload={"input": user_input})
            )

        # 1. Retrieve relevant memories
        memories = self._memory.search(user_input, limit=5)

        # 2. Build prompt
        context = PromptContext(
            conversation_history=list(self._state.history),
            relevant_memories=memories,
            user_message=user_input,
        )
        messages = self._builder.build(context)

        # 3. Call LLM
        request = LLMRequest(messages=messages)
        response = self._llm.complete(request)

        # 4. Update conversation history
        self._state.history.append(
            Message(role=MessageRole.USER, content=user_input)
        )
        self._state.history.append(
            Message(role=MessageRole.ASSISTANT, content=response.content)
        )
        self._trim_history()

        # 5. Persist memory if user asked to remember something
        self._maybe_store_memory(user_input)

        if self._event_bus is not None:
            self._event_bus.publish(
                Event(
                    name="conversation.completed",
                    payload={"response": response.content},
                )
            )

        return response.content

    def _trim_history(self) -> None:
        """Keep history within max limit."""
        if len(self._state.history) > self._state.max_history:
            self._state.history = self._state.history[-self._state.max_history :]

    def _maybe_store_memory(self, user_input: str) -> None:
        """Extract and store memories from remember commands."""
        text_lower = user_input.lower().strip()
        prefixes = (
            "remember that ",
            "remember this ",
            "store that ",
            "save that ",
        )
        for prefix in prefixes:
            if text_lower.startswith(prefix):
                content = user_input[len(prefix) :].strip()
                if content:
                    memory = Memory(content=content, category=MemoryCategory.FACT)
                    self._memory.store(memory)
                break
