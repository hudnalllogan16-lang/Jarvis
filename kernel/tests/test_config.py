"""Tests for the Jarvis kernel configuration subsystem."""

import pytest
from pydantic import ValidationError

from kernel.config import Environment, LogLevel, load_settings


def _base_overrides(**extra: str) -> dict[str, str]:
    """Return a dict with all required fields populated."""
    return {
        "DATABASE_URL": "postgresql://localhost/jarvis",
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": "sk-test",
        **extra,
    }


class TestSuccessfulLoading:
    """Happy-path scenarios where configuration loads correctly."""

    def test_loads_with_all_required_fields(self) -> None:
        """Settings instantiate when all required fields are provided."""
        settings = load_settings(**_base_overrides())
        assert settings.DATABASE_URL == "postgresql://localhost/jarvis"
        assert settings.LLM_PROVIDER == "openai"
        assert settings.LLM_API_KEY.get_secret_value() == "sk-test"


class TestDefaultValues:
    """Fields that should carry sensible defaults when omitted."""

    def test_app_name_defaults_to_jarvis(self) -> None:
        """APP_NAME falls back to "Jarvis"."""
        settings = load_settings(**_base_overrides())
        assert settings.APP_NAME == "Jarvis"

    def test_app_version_defaults_to_1_0_0(self) -> None:
        """APP_VERSION falls back to "1.0.0"."""
        settings = load_settings(**_base_overrides())
        assert settings.APP_VERSION == "1.0.0"

    def test_environment_defaults_to_development(self) -> None:
        """ENVIRONMENT falls back to :attr:`Environment.DEVELOPMENT`."""
        settings = load_settings(**_base_overrides())
        assert settings.ENVIRONMENT is Environment.DEVELOPMENT

    def test_log_level_defaults_to_info(self) -> None:
        """LOG_LEVEL falls back to :attr:`LogLevel.INFO`."""
        settings = load_settings(**_base_overrides())
        assert settings.LOG_LEVEL is LogLevel.INFO


class TestEnvironmentOverrides:
    """Environment variables should take precedence over defaults."""

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An environment variable overrides the built-in default."""
        monkeypatch.setenv("APP_NAME", "Jarvis-Test")
        monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "sk-override")
        settings = load_settings()
        assert settings.APP_NAME == "Jarvis-Test"
        assert settings.DATABASE_URL == "postgresql://test/db"
        assert settings.LLM_PROVIDER == "anthropic"
        assert settings.LLM_API_KEY.get_secret_value() == "sk-override"

    def test_kwarg_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keyword arguments override environment variables."""
        monkeypatch.setenv("APP_NAME", "FromEnv")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/db")
        monkeypatch.setenv("LLM_PROVIDER", "env-provider")
        monkeypatch.setenv("LLM_API_KEY", "env-key")
        settings = load_settings(
            APP_NAME="FromKwarg",
            DATABASE_URL="postgresql://kwarg/db",
            LLM_PROVIDER="kwarg-provider",
            LLM_API_KEY="kwarg-key",
        )
        assert settings.APP_NAME == "FromKwarg"
        assert settings.DATABASE_URL == "postgresql://kwarg/db"
        assert settings.LLM_PROVIDER == "kwarg-provider"
        assert settings.LLM_API_KEY.get_secret_value() == "kwarg-key"


class TestMissingRequiredSettings:
    """Required fields must be present or loading fails fast."""

    def test_missing_database_url_raises(self) -> None:
        """DATABASE_URL is required."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                LLM_PROVIDER="openai",
                LLM_API_KEY="sk-test",
            )
        assert "DATABASE_URL" in str(exc_info.value)

    def test_missing_llm_provider_raises(self) -> None:
        """LLM_PROVIDER is required."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                DATABASE_URL="postgresql://localhost/db",
                LLM_API_KEY="sk-test",
            )
        assert "LLM_PROVIDER" in str(exc_info.value)

    def test_missing_llm_api_key_raises(self) -> None:
        """LLM_API_KEY is required."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                DATABASE_URL="postgresql://localhost/db",
                LLM_PROVIDER="openai",
            )
        assert "LLM_API_KEY" in str(exc_info.value)


class TestInvalidEnumValues:
    """Enum-like fields reject values outside their domain."""

    def test_invalid_environment_rejected(self) -> None:
        """ENVIRONMENT must be one of the allowed enum values."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                ENVIRONMENT="invalid_env",
                **_base_overrides(),
            )
        assert "ENVIRONMENT" in str(exc_info.value)

    def test_invalid_log_level_rejected(self) -> None:
        """LOG_LEVEL must be a recognised :class:`LogLevel` member."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                LOG_LEVEL="VERBOSE",
                **_base_overrides(),
            )
        assert "LOG_LEVEL" in str(exc_info.value)
        assert "VERBOSE" in str(exc_info.value)

    def test_log_level_case_insensitive(self) -> None:
        """LOG_LEVEL normalises to upper case via enum coercion."""
        settings = load_settings(LOG_LEVEL="debug", **_base_overrides())
        assert settings.LOG_LEVEL is LogLevel.DEBUG

    def test_environment_case_sensitive(self) -> None:
        """ENVIRONMENT enum values are case-sensitive."""
        with pytest.raises(ValidationError) as exc_info:
            load_settings(
                ENVIRONMENT="Development",
                **_base_overrides(),
            )
        assert "ENVIRONMENT" in str(exc_info.value)
