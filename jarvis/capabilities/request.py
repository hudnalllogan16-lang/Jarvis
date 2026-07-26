"""Scoped requests and terminal results (spec §2.2, §6; D-001).

Spec §2.2 requires every capability invocation to be a scoped request carrying
capability type, prompt reference, tool scope, memory scope, credential scope,
and budget allocation. All six are required fields here rather than optional
ones, because a scope that defaults to something is a scope nobody chose.

`business_id` on the request is deliberately named `declared_business_id`: it is
untrusted input. Authorization uses the runtime-derived identity (D-002).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.domain.contract import CapabilityType
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.llm.base import Usage


class MemoryScope(StrEnum):
    """Memory access granted for one invocation (spec §7).

    There is no value here that grants another business's memory. Business-local
    isolation is expressed by the absence of the option, not by a check that
    could be forgotten.
    """

    NONE = "none"
    READ = "read"
    READ_WRITE = "read_write"


class InvocationStatus(StrEnum):
    """Terminal states of a capability invocation (D-001).

    Every invocation reaches exactly one of these. Spec §2.1 requires a Manager
    to wait for and synthesize *all* results while spec §9 routes exhausted
    invocations to a dead-letter queue; if dead-lettering were a silent sink the
    Manager would wait forever. `DEAD_LETTERED` is a result, not an absence.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


PRIOR_RESULTS_KEY = "prior_results"
"""Reserved `prompt_inputs` key carrying results the Manager granted this
invocation from earlier invocations of the same cycle (D-023 point 3).

A reserved key rather than a new field, deliberately. §2.2 already gives an
invocation exactly one channel for domain content — `prompt_ref` plus
`prompt_inputs` — and D-023 threads *content*, not a new scope: the grant is
same-business, same cycle, and carries no tool, credential, or memory rights.
A new top-level field would read as a seventh scope for the pool to authorise
when nothing new is being authorised.

Its value is a list of `{"ref", "capability", "output"}` objects. The Manager is
the only writer (§2 forbids capabilities calling each other), and the executor
renders it as its own labelled section rather than interpolating it into a
template, so an invocation can never receive prior work disguised as its own
instructions."""


class ScopedRequest(BaseModel):
    """A single scoped capability invocation request (spec §2.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invocation_id: InvocationId
    declared_business_id: BusinessId
    """Untrusted. Cross-checked against the runtime identity (D-002)."""

    capability: CapabilityType
    prompt_ref: str = Field(min_length=1)
    """Reference to a domain-specific prompt template. A capability MUST NOT
    contain business-specific logic in its base prompt (spec §2.2), so the
    domain content arrives by reference from the calling business."""

    prompt_inputs: dict[str, Any] = Field(default_factory=dict)
    tool_scope: frozenset[str] = Field(default_factory=frozenset)
    memory_scope: MemoryScope = MemoryScope.NONE
    credential_refs: frozenset[str] = Field(default_factory=frozenset)
    budget_allocation_usd: Decimal = Field(gt=0)
    cycle_id: str | None = None
    action_type: str | None = None
    """Set when this invocation performs an external-facing action, so the
    idempotency key can be derived (A-001) and approval checked (spec §8)."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    """Bounded retry count (spec §9). Exhaustion dead-letters the invocation."""


class CapabilityResult(BaseModel):
    """The terminal outcome of one invocation (D-001).

    Always returned, including on dead-letter, so an awaiting Business Manager
    can synthesize over failures rather than blocking on a result that will
    never arrive.
    """

    model_config = ConfigDict(frozen=True)

    invocation_id: InvocationId
    business_id: BusinessId
    capability: CapabilityType
    status: InvocationStatus
    output: str = ""
    usage: Usage = Usage()
    attempts: int = 0
    operator_summary: str = ""
    """Plain consequence language (spec §12.5). Never a stack trace or error
    code, because this string can reach the default dashboard view."""

    technical_detail: str = ""
    """Drill-down only (spec §12.5)."""

    @property
    def succeeded(self) -> bool:
        """Return whether the invocation produced usable output."""
        return self.status is InvocationStatus.SUCCEEDED
