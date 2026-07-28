"""Kernel configuration (spec §0: Configuration is Kernel-owned).

All secrets arrive from the environment or a secrets manager and are held as
`SecretStr` so they cannot be printed, logged, or interpolated into a prompt by
accident (spec §10).

Provider selection is configuration only — changing LLM vendor never requires a
code change (Implementation Directive, A-005).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, cast

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jarvis.kernel.errors import ConfigurationError


class LLMProviderName(StrEnum):
    """Supported LLM providers. Served by three transports per A-005."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    KIMI = "kimi"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    LMSTUDIO = "lmstudio"


DEFAULT_BASE_URLS: Final[dict[LLMProviderName, str]] = {
    LLMProviderName.ANTHROPIC: "https://api.anthropic.com",
    LLMProviderName.OPENAI: "https://api.openai.com/v1",
    LLMProviderName.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    LLMProviderName.KIMI: "https://api.moonshot.cn/v1",
    LLMProviderName.OLLAMA: "http://localhost:11434/v1",
    LLMProviderName.OPENROUTER: "https://openrouter.ai/api/v1",
    LLMProviderName.LMSTUDIO: "http://localhost:1234/v1",
}

LOCAL_PROVIDERS: Final[frozenset[LLMProviderName]] = frozenset(
    {LLMProviderName.OLLAMA, LLMProviderName.LMSTUDIO}
)
"""Providers that legitimately run without an API key."""


class LLMSettings(BaseModel):
    """LLM provider configuration.

    A plain `BaseModel`, not a `BaseSettings`: only the root `Settings` object
    reads the environment. A nested `BaseSettings` would additionally pick up
    *unprefixed* variables, so an unrelated ``MODEL`` or ``API_KEY`` already
    exported in a developer's shell would silently override the ``JARVIS_LLM__*``
    values — a misconfiguration that shows up as a confusing auth failure rather
    than a config error.

    No model identifier is hardcoded anywhere in Jarvis. `model` is required and
    supplied by configuration, so the platform never silently depends on a model
    that may have been renamed or retired.
    """

    provider: LLMProviderName = LLMProviderName.ANTHROPIC
    model: str = Field(min_length=1)
    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    """Bounded retry count (spec §9). Exceeding it dead-letters the invocation."""

    def resolved_base_url(self) -> str:
        """Return the configured base URL, or this provider's default."""
        return (self.base_url or DEFAULT_BASE_URLS[self.provider]).rstrip("/")

    def require_api_key(self) -> str:
        """Return the API key, raising if one is required but absent.

        Returns:
            The secret value, for use at the HTTP boundary only.

        Raises:
            ConfigurationError: If the provider needs a key and none is set.
        """
        value = self.api_key.get_secret_value()
        if not value and self.provider not in LOCAL_PROVIDERS:
            raise ConfigurationError(f"provider {self.provider.value} requires JARVIS_LLM__API_KEY")
        return value


class BudgetSettings(BaseModel):
    """Platform-level budget ceilings (spec §9, hierarchy per D-003)."""

    platform_rolling_24h_usd: Decimal = Field(default=Decimal("500.00"), gt=0)
    """Global circuit breaker (spec §9, Defaults in Force). Owner-adjustable only."""

    default_wake_cycle_ceiling_usd: Decimal = Field(default=Decimal("1.00"), gt=0)
    """A safety net, not a substitute for per-business configuration: the spec
    requires the ceiling to be explicit per business before launch."""

    reasoning_token_price_per_million_usd: Decimal = Field(default=Decimal("50.00"), gt=0)
    """Upper-bound token price used to turn a reasoning call's token ceiling into
    a budget reservation (D-022 point 2, closing M6-F14).

    An upper bound, deliberately not a market rate. Jarvis has no per-model
    pricing until the Executive Layer's cost tracking lands, and D-022 forbids
    guessing a reservation amount — so the amount is *derived* from the call's
    token ceiling and this bound is the one number configuration supplies. It
    sits above the published per-token price of the frontier models these
    transports talk to, so a reservation over-states a call's cost rather than
    under-stating it; the reservation settles back to the provider's reported
    token counts, so the over-statement gates the check without becoming the
    recorded spend. Owner-adjustable, like every other ceiling here."""


class HeartbeatSettings(BaseModel):
    """Runtime self-report cadence (design OPERATIONAL-RUNTIME.md Part 3.2, D-058).

    Paces the Supervisor's `runtime_heartbeat` writes and the staleness read
    `/api/health`'s `runtime` component (and, later, the Executive's liveness
    verdict, packet P0-C) apply against those writes. Neither value gates a
    permission decision — a slower cadence only delays how quickly a stalled
    part is *noticed*, it changes nothing about what the platform is allowed
    to do — so both are ANNOUNCING parameters (Parameter Register, Part 3.3),
    unlike `platform_rolling_24h_usd`'s ENFORCING ceiling beside them.
    """

    heartbeat_interval_seconds: int = Field(default=15, gt=0)
    """How often the Supervisor upserts one `runtime_heartbeat` row per
    supervised part (design 3.2's own default)."""

    heartbeat_stale_after_seconds: int = Field(default=45, gt=0)
    """A beat older than this reads as stale rather than merely running late.

    Three missed intervals at the default cadence — the same "don't alarm on
    one skipped tick" margin every other periodic check in this platform
    gives itself, so a single delayed write (a slow database round trip, a
    GC pause) does not flip a healthy part to "down" on its own.
    """


class TemporalSettings(BaseModel):
    """Workflow runtime configuration (spec §2: Temporal, non-negotiable)."""

    host: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "jarvis-platform"


class ExecutiveSettings(BaseModel):
    """The Executive Layer's deterministic cadence (spec §3, D-041)."""

    tick_interval_seconds: int = Field(default=60, gt=0)
    """How often rollup -> census -> alerts -> the halt narrative runs as one
    pass (design EXECUTIVE-LAYER.md Part 7).

    Its own setting, not the scheduler's `interval_seconds` (300s, un-configured
    today): Part 7's second argument is that the two cadences are "genuinely
    different" — the sweep is tuned to §9's approval timers (24h re-notify, 7d
    expire), while a company can cross both its 50% and 80% spend bands inside
    a single working session (design 2.3) and is owed a tighter check. 60s is
    chosen for that reason, not derived from any other constant, and is
    owner-adjustable like every other cadence and ceiling here."""


def _lowercase_keys(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``raw`` with lowercased keys.

    Credential handles are lowercase identifiers (`affiliate_blog_webhook`), and
    environment variables are conventionally upper case — on Windows the process
    environment upper-cases them regardless of how they were written. Without
    this, a handle configured as ``JARVIS_CREDENTIALS__AFFILIATE_BLOG_WEBHOOK``
    resolves to nothing and the tool boundary refuses a credential the operator
    believes they configured.
    """
    return {str(key).lower(): value for key, value in raw.items()}


class Settings(BaseSettings):
    """Root configuration object, injected rather than imported as a global."""

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"
    log_level: str = "INFO"
    database_url: SecretStr = SecretStr("postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    api_port: int = Field(default=8000, gt=0, le=65535)
    """Port the operator API and dashboard bind to (`JARVIS_API_PORT`).

    Previously hardcoded in both topologies (`jarvis/api/server.py` and
    `jarvis/shell/launcher.py`), which meant two of them could never run on
    one host at once. Configurable so a lane environment (D-026.2) can give
    each lane its own port the same way it already gets its own database and
    Temporal namespace — `scripts/lane_env.py` prints one alongside those."""

    llm: LLMSettings
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    executive: ExecutiveSettings = Field(default_factory=ExecutiveSettings)
    heartbeat: HeartbeatSettings = Field(default_factory=HeartbeatSettings)

    credentials: dict[str, SecretStr] = Field(default_factory=dict)
    """Credential handle -> secret, from the secrets manager (spec §10).

    This is the environment-backed source `PlatformKernel` has always claimed to
    read and never did (M6-F28): every runtime entrypoint built the Kernel
    without secrets, so `CredentialManager` was empty in production and no tool
    needing a credential could ever have run. Held as `SecretStr` for the same
    reason the LLM key is: an accidental interpolation prints a placeholder.

    Configured as ``JARVIS_CREDENTIALS__<handle>``; handles are matched
    case-insensitively."""

    tool_endpoints: dict[str, str] = Field(default_factory=dict)
    """Credential handle -> the destination that credential authenticates against.

    Deployment configuration, not business data, and deliberately *not* an
    action parameter: the destination of an effect is attached at the tool
    boundary from here (D-015), so neither a model proposing an action nor an
    operator correcting one can redirect a published effect at a host of their
    choosing.

    Configured as ``JARVIS_TOOL_ENDPOINTS__<handle>``."""

    @field_validator("credentials", "tool_endpoints", mode="before")
    @classmethod
    def _normalise_handles(cls, v: Any) -> Any:
        return _lowercase_keys(cast("Mapping[str, Any]", v)) if isinstance(v, Mapping) else v

    @field_validator("log_level")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}"
            raise ValueError(msg)
        return upper
