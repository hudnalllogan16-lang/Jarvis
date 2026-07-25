"""Jarvis kernel configuration.

Public API for loading and accessing application configuration.

Example::

    from kernel.config import load_settings

    settings = load_settings()
    print(settings.APP_NAME)
    print(settings.DATABASE_URL)

In tests, pass overrides to bypass environment loading::

    settings = load_settings(
        DATABASE_URL="postgresql://test",
        LLM_PROVIDER="openai",
        LLM_API_KEY="test-key",
    )
"""

from kernel.config.loader import load_settings
from kernel.config.settings import Environment, JarvisSettings, LogLevel

__all__ = [
    "Environment",
    "JarvisSettings",
    "LogLevel",
    "load_settings",
]
