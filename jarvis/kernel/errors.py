"""Kernel error taxonomy.

Every error carries an operator-facing message (spec §12.5): the default UI must
never surface a stack trace or a technical error code. `technical_detail` is the
drill-down payload and is never shown by default.
"""

from __future__ import annotations


class JarvisError(Exception):
    """Base class for every error raised inside Jarvis.

    Args:
        technical_detail: Engineer-facing description. Written to the audit log,
            surfaced only behind an explicit drill-down (spec §12.5).
        operator_message: Plain-consequence language for the default UI. Must
            describe what it means for the operator, not what failed internally.
    """

    default_operator_message = "Jarvis hit a problem and stopped to stay safe."

    def __init__(
        self,
        technical_detail: str,
        *,
        operator_message: str | None = None,
    ) -> None:
        super().__init__(technical_detail)
        self.technical_detail = technical_detail
        self.operator_message = operator_message or self.default_operator_message


class ConfigurationError(JarvisError):
    """Invalid or missing configuration detected at startup."""

    default_operator_message = "Jarvis isn't set up correctly yet."


class RegistryError(JarvisError):
    """Business Registry operation failed (spec §0.1)."""

    default_operator_message = "Jarvis couldn't find that company."


class BusinessNotFoundError(RegistryError):
    """No business instance exists with the requested identifier."""


class BusinessTypeNotFoundError(RegistryError):
    """No business type is installed under the requested name."""

    default_operator_message = "That company template isn't installed."


class DuplicateBusinessError(RegistryError):
    """A business instance or type already exists under that identity."""

    default_operator_message = "A company with that name already exists."


class InvalidLifecycleTransitionError(RegistryError):
    """Requested lifecycle transition is not permitted (spec §0.1, D-008)."""

    default_operator_message = "That company can't do that right now."


class ScopeViolationError(JarvisError):
    """A request attempted to access a scope it was not granted (spec §10, D-002).

    Raised at the capability-pool boundary when the scopes on an inbound request
    are not a subset of the invoking business's configured permissions. Always
    audited; never narrowed or silently corrected.
    """

    default_operator_message = "Jarvis blocked an action that crossed company boundaries."


class ProviderError(JarvisError):
    """An LLM provider call failed.

    Business logic never catches this by provider type — the whole point of the
    provider interface is that callers cannot tell which vendor is configured.
    """

    default_operator_message = "Jarvis couldn't finish thinking about that — retrying."


class BudgetExceededError(JarvisError):
    """A spend would breach a ceiling in the budget hierarchy (spec §9, D-003).

    Carries the breached scope so callers can distinguish "this invocation asked
    for too much" from "this company is out of money" from "the platform has
    halted", which have very different operator consequences.
    """

    default_operator_message = "This company stopped to stay inside its spending limit."

    def __init__(
        self,
        technical_detail: str,
        *,
        scope: str,
        operator_message: str | None = None,
    ) -> None:
        super().__init__(technical_detail, operator_message=operator_message)
        self.scope = scope


class CircuitBreakerOpenError(BudgetExceededError):
    """Platform-wide dispatch is halted (spec §9)."""

    default_operator_message = "Jarvis paused spending across all companies."


class CapabilityExecutionError(JarvisError):
    """A capability invocation failed during execution.

    Retryable unless `permanent` is set: a malformed request will fail the same
    way on every attempt, so retrying it only burns budget (spec §9).
    """

    default_operator_message = "A task didn't finish — Jarvis is trying again."

    def __init__(
        self,
        technical_detail: str,
        *,
        permanent: bool = False,
        operator_message: str | None = None,
    ) -> None:
        super().__init__(technical_detail, operator_message=operator_message)
        self.permanent = permanent
