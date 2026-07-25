"""Configuration data models for the Jarvis kernel.

This module defines the configuration schema and validation rules.
Loading logic is handled separately in :mod:`kernel.config.loader`.
"""

from enum import StrEnum
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Runtime environment tiers.

    Using a :class:`StrEnum` instead of :class:`typing.Literal`
    improves IDE discoverability, enables ``is`` comparisons,
    and makes refactoring safer.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Standard Python logging levels.

    A closed enum provides stronger typing than a raw string
    and eliminates the need for a post-hoc validator.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class JarvisSettings(BaseSettings):
    """Single source of truth for Jarvis configuration.

    Values are loaded from environment variables and ``.env`` files.
    Environment variables take precedence over ``.env`` values.

    Attributes:
        APP_NAME: Human-readable application name.
        APP_VERSION: Semantic version of the application.
        ENVIRONMENT: Runtime environment tier.
        LOG_LEVEL: Logging verbosity. Must be a standard Python level.
        DATABASE_URL: Connection string for the primary database.
        LLM_PROVIDER: Identifier for the LLM vendor or routing target.
        LLM_API_KEY: Authentication key for the LLM provider.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
    )

    APP_NAME: str = Field(default="Jarvis", description="Application name.")
    APP_VERSION: str = Field(default="1.0.0", description="Application version.")
    ENVIRONMENT: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Runtime environment: development, staging, or production.",
    )
    LOG_LEVEL: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging verbosity level.",
    )
    DATABASE_URL: str = Field(
        ...,
        description="Primary database connection URL.",
    )
    LLM_PROVIDER: str = Field(
        ...,
        description="LLM provider identifier.",
    )
    LLM_API_KEY: SecretStr = Field(
        ...,
        description="API key for the LLM provider.",
    )

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _coerce_log_level(cls, value: Any) -> Any:
        """Normalise LOG_LEVEL to upper case before enum coercion.

        Args:
            value: The raw LOG_LEVEL string.

        Returns:
            The upper-cased string for enum matching, or the original
            value if it is not a string.
        """
        if isinstance(value, str):
            return value.upper()
        return value
