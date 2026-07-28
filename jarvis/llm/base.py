"""Provider-agnostic LLM types and protocol.

Nothing in this module names a vendor, and no model identifier appears anywhere:
the model is always supplied by configuration. Business logic depends on this
protocol only, so a provider swap never reaches business code.

Model calls are nondeterministic and therefore always execute inside Temporal
activities, never in workflow code (D-004).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """Message roles common to every supported provider."""

    USER = "user"
    ASSISTANT = "assistant"


class StopReason(StrEnum):
    """Why generation ended, normalised across providers.

    The raw values differ per vendor — ``end_turn`` / ``stop`` / ``STOP`` all
    mean the same thing — so passing them through untranslated would let a
    caller branch on vendor behaviour and quietly reintroduce a provider
    dependency. Providers map into this enum; the raw string is preserved
    separately for the audit log only.
    """

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class Message(BaseModel):
    """A single conversational turn."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class Usage(BaseModel):
    """Token accounting for one completion.

    `cost_usd` feeds the budget hierarchy in D-003: it debits the invocation
    allocation, the wake-cycle ceiling, the business budget, and the platform
    rolling 24h aggregate, in that order.
    """

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @property
    def total_tokens(self) -> int:
        """Return input plus output tokens."""
        return self.input_tokens + self.output_tokens


class CompletionRequest(BaseModel):
    """A provider-agnostic completion request.

    `system` carries instructions only. Secrets MUST NOT appear in prompts
    (spec §10); credentials travel as opaque handles in the scoped request and
    are resolved at the tool-execution boundary, never placed in model context.
    """

    model_config = ConfigDict(frozen=True)

    messages: tuple[Message, ...] = Field(min_length=1)
    system: str | None = None
    max_tokens: int = Field(default=2048, gt=0)

    temperature: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    """Sampling temperature, or None to accept the provider's own default.

    None rather than a number, because a default here is an assertion no caller
    made. Nothing in Jarvis sets this, yet every transport was sending it — and
    some current models reject a non-default `temperature` outright, so a number
    nobody chose turned every model call into HTTP 400 (M6-F6). A
    provider-agnostic request cannot know which sampling knobs a given model
    still accepts; declining to assert one is the only portable answer."""

    stop_sequences: tuple[str, ...] = ()


class CompletionResponse(BaseModel):
    """A provider-agnostic completion response."""

    model_config = ConfigDict(frozen=True)

    text: str
    usage: Usage = Usage()
    stop_reason: StopReason = StopReason.OTHER
    """Normalised. Business logic may branch on this without knowing the vendor."""

    raw_stop_reason: str | None = None
    """The provider's own value. Audit only (spec §11) — never branched on."""

    model: str = ""
    """Echoed back for the audit log (spec §11), never shown to the operator
    (spec §12.5: the model is not an operator-facing concept)."""


class ModelListing(BaseModel):
    """What a provider says it will serve, and whether that is the whole list.

    `complete` is the field that matters and the reason this is not a bare
    tuple. Every catalog endpoint these transports read is paginated, so a
    single page is evidence that a model *is* offered and never evidence that
    one is not — and the caller acting on this (`jarvis/llm/validation.py`) can
    refuse to start a worker. A partial list must therefore be able to say so,
    or the first provider to grow past one page turns a configured, working
    model into a refusal nobody can explain.
    """

    model_config = ConfigDict(frozen=True)

    ids: tuple[str, ...] = ()
    complete: bool = False


@runtime_checkable
class ModelCatalog(Protocol):
    """A provider that can say which models it offers.

    Separate from `LLMProvider` on purpose. That protocol is the surface
    *business logic* depends on, and nothing in business logic may ask which
    models exist — the model is configuration (A-005), and a Manager that could
    enumerate models could choose one. This is a startup and diagnostics
    surface, so it is a second, narrower protocol that the composition root
    checks for with `isinstance` and every other layer ignores.

    A transport that does not implement it is not a defect: the answer is then
    the one an unreachable catalog gives, a warning rather than a refusal.
    """

    async def list_models(self) -> ModelListing:
        """Return the models this provider currently offers.

        Returns:
            The listing, with `complete` False when the provider signalled more
            pages than were read.

        Raises:
            ProviderError: On any transport, auth, or protocol failure.
        """
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """The only LLM surface business logic may depend on.

    Implementations must translate provider-specific errors into
    `ProviderError`, so callers cannot branch on vendor behaviour and thereby
    reintroduce a provider dependency by the back door.
    """

    @property
    def name(self) -> str:
        """Return the configured provider name, for audit records only."""
        ...

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one completion.

        Args:
            request: Provider-agnostic request.

        Returns:
            The completion and its token accounting.

        Raises:
            ProviderError: On any transport, auth, or protocol failure.
        """
        ...

    async def aclose(self) -> None:
        """Release transport resources."""
        ...
