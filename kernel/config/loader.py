"""Configuration loading logic for the Jarvis kernel.

This module is responsible for instantiating :class:`~kernel.config.settings.JarvisSettings`.
It separates the mechanics of loading from the data model itself.

Design note:
    :func:`load_settings` returns a fresh instance on every call.
    There is intentionally no module-level singleton or caching layer here.
    Lifecycle management (singleton vs. factory vs. scoped instances)
    will be handled by the dependency-injection container once it is built.
    Until then, callers that need a single shared instance should
    store the result themselves.
"""

from typing import Any

from kernel.config.settings import JarvisSettings


def load_settings(**overrides: Any) -> JarvisSettings:
    """Create a fresh :class:`JarvisSettings` instance.

    By default the instance reads from ``.env`` and environment variables.
    Keyword arguments override both sources, which is useful in tests.

    Args:
        **overrides: Optional field values that bypass environment loading.

    Returns:
        A validated :class:`JarvisSettings` instance.

    Raises:
        pydantic.ValidationError: If required fields are missing or invalid.
    """
    return JarvisSettings(**overrides)
