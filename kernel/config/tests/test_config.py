"""Unit tests for kernel configuration.

Covers settings validation, defaults, overrides, and enum coercion.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from kernel.config.loader import load_settings
from kernel.config.settings import Environment, JarvisSettings, LogLevel


class TestJarvisSettings:
    """Test the Pydantic settings model."""

    def test_defaults(self) -> None:
        """Verify default values."""
        settings = JarvisSettings()
        assert settings.environment is Environment.DEVELOPMENT
        assert settings.log_level is LogLevel.INFO
        assert settings.llm_provider == "mock"
        assert settings.llm_model == "gpt-4"
        assert settings.llm_api_key is None

    def test_environment_override(self) -> None:
        """Verify environment can be overridden."""
        settings = JarvisSettings(environment=Environment.PRODUCTION)
        assert settings.environment is Environment.PRODUCTION

    def test_log_level_enum(self) -> None:
        """Verify log level enum works."""
        settings = JarvisSettings(log_level=LogLevel.DEBUG)
        assert settings.log_level is LogLevel.DEBUG

    def test_secret_str_not_logged(self) -> None:
        """Verify SecretStr masks the value."""
        settings = JarvisSettings(llm_api_key=SecretStr("secret123"))
        assert "secret123" not in str(settings.llm_api_key)
        assert "secret123" not in repr(settings.llm_api_key)

    def test_extra_forbidden(self) -> None:
        """Verify extra fields are rejected."""
        with pytest.raises(ValueError):
            JarvisSettings(invalid_field="value")  # type: ignore[call-arg]


class TestLoadSettings:
    """Test the settings loader factory."""

    def test_load_settings_returns_fresh_instance(self) -> None:
        """Verify loader returns fresh instances."""
        a = load_settings()
        b = load_settings()
        assert a is not b
        assert a.environment == b.environment
