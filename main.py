"""Minimal entry point for Jarvis.

This module serves as the application bootstrap. In production,
the DI container would be used to resolve and start services.
"""

from __future__ import annotations

from kernel.config.loader import load_settings


def main() -> None:
    """Bootstrap Jarvis."""
    settings = load_settings()
    print(f"Jarvis starting in {settings.environment} mode...")


if __name__ == "__main__":
    main()
