"""Configuration settings for Jarvis.

Defines the Pydantic-based configuration model with environment variable
and .env file support. Part of the kernel configuration bootstrap.

This module lives in the kernel because configuration is foundational
runtime infrastructure required by all layers.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Runtime environment tiers."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Standard Python logging levels with case-insensitive coercion."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class JarvisSettings(BaseSettings):
    """Root configuration model for Jarvis.

    Loads from environment variables and .env files. Uses ``extra="forbid"``
    to catch configuration typos early.

    Attributes:
        environment: Runtime tier.
        log_level: Minimum log level.
        llm_api_key: API key for the LLM provider, stored as SecretStr.
        llm_provider: Name of the LLM provider.
        llm_model: Model identifier.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    llm_api_key: SecretStr | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4"
