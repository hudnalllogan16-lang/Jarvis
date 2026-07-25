"""Configuration loading mechanics.

Provides the factory function for creating fresh JarvisSettings instances.
No singleton pattern is used here; lifecycle is managed by the DI container
in Milestone 2.
"""

from __future__ import annotations

from kernel.config.settings import JarvisSettings


def load_settings() -> JarvisSettings:
    """Create and return a fresh JarvisSettings instance.

    Returns:
        A new JarvisSettings loaded from environment variables and .env file.
    """
    return JarvisSettings()
