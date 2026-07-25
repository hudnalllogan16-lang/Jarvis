"""Interactive terminal interface for Jarvis.

The CLI handles only user interaction and delegates all logic to the
Conversation Engine.
"""

from __future__ import annotations

import sys

from services.conversation_engine.engine import ConversationEngine


class CLIApp:
    """Simple read-eval-print loop for Jarvis."""

    def __init__(self, engine: ConversationEngine) -> None:
        """Initialize with a conversation engine.

        Args:
            engine: The engine that processes user input.

        """
        self._engine = engine

    def run(self) -> None:
        """Start the interactive loop."""
        print("Jarvis is ready. Type 'exit' or 'quit' to stop.")
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

            if user_input.lower() in {"exit", "quit"}:
                print("Goodbye.")
                break

            if not user_input:
                continue

            try:
                response = self._engine.process(user_input)
                print(f"Jarvis: {response}")
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
