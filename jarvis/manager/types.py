"""Payloads crossing the workflow/activity boundary (spec §2.1, D-004).

Every type here is serialised: workflow code cannot hand an activity a live
object, and an activity cannot hand back anything that is not replayable. Keeping
them in one module makes the boundary visible — if a field cannot appear here, it
does not belong in the workflow.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.capabilities.request import CapabilityResult, ScopedRequest
from jarvis.kernel.ids import BusinessId
from jarvis.manager.state import KpiTargetState, SkippedDispatch, TacticalPlan


class CycleContext(BaseModel):
    """Everything a cycle needs to know that lives outside the workflow.

    Loaded once per cycle by an activity. The clock is included as
    `day_ordinal` rather than read in the workflow, because a workflow that
    reads the wall clock diverges on replay (D-004).
    """

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    display_name: str
    dispatchable: bool
    """False when the business is paused, retiring, or retired (D-008 I-4)."""

    schedule_interval_seconds: int | None = None
    max_cycles_per_day: int = 48
    wake_cycle_ceiling_usd: Decimal = Decimal("1.00")
    day_ordinal: int = 0
    """Proleptic day number, supplied by the activity's clock read."""


class PlanRequest(BaseModel):
    """Input to the planning activity."""

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    wake_reasons: tuple[str, ...] = ()
    current_plan: TacticalPlan = TacticalPlan()
    kpi_targets: tuple[KpiTargetState, ...] = ()
    pending_approval_id: str | None = None


class PriorResultGrant(BaseModel):
    """One earlier invocation whose result a dependent invocation may see.

    The `ref` is how the dependent names it — the plan item's own ref, so the
    granted context reads as "the research" rather than as an opaque id.
    """

    model_config = ConfigDict(frozen=True)

    ref: str
    invocation_id: str


class DispatchSequence(BaseModel):
    """The order a cycle's requests are dispatched in (D-023 point 2).

    Computed and validated in `plan_cycle`, not in the workflow: the graph comes
    from model-proposed declarations, so checking it is platform work (D-013),
    and the workflow only walks the result.

    Absent or empty means what it meant before D-023 — one wave containing every
    request. That is the compatibility hinge: a history captured before this
    field existed deserialises to an empty sequence and the workflow issues
    exactly the commands it issued then (spec §11).
    """

    model_config = ConfigDict(frozen=True)

    waves: tuple[tuple[str, ...], ...] = ()
    """Invocation ids, in dispatch order. Everything inside one wave is
    dispatched in parallel (the M4-F1 guard applies per wave)."""

    grants: dict[str, tuple[PriorResultGrant, ...]] = Field(default_factory=dict)
    """Dependent invocation id -> the earlier results it was granted."""

    refs: dict[str, str] = Field(default_factory=dict)
    """Invocation id -> plan item ref, so a skipped dispatch can name itself."""


class DependentContextRequest(BaseModel):
    """Input to the activity that attaches granted prior results (D-023 point 3).

    The results travel through this payload rather than being spliced into the
    requests by the workflow: composing the granted context is platform work
    (which results, how much of each, recorded as a grant), and D-004 keeps the
    workflow to orchestration. It is also bounded by construction — one cycle's
    results, already in hand, never accumulated across cycles (D-005).
    """

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    cycle_id: str | None = None
    requests: tuple[ScopedRequest, ...] = ()
    grants: dict[str, tuple[PriorResultGrant, ...]] = Field(default_factory=dict)
    prior_results: tuple[CapabilityResult, ...] = ()


class SynthesisRequest(BaseModel):
    """Input to the synthesis activity (spec §2.1)."""

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    plan: TacticalPlan
    results: tuple[CapabilityResult, ...]
    cycle_id: str | None = None
    """The owning wake cycle (D-021). Optional so a history captured before
    D-021 still replays: an older `plan_cycle` result carries no cycle id, and a
    required field here would make that history undeserialisable."""

    skipped: tuple[SkippedDispatch, ...] = ()
    """Dispatches a failed dependency stopped (D-023 point 4). Synthesis is
    required to see *why* a planned step is missing from the results, or it
    would summarise a half-finished cycle as a complete one."""


class ProposedAction(BaseModel):
    """An action the Manager wants to take, and whether a human must agree.

    Carries §8's four required facts as structured fields rather than prose, so
    the approval an operator reads is rendered from values (D-011).
    """

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    action_type: str = Field(min_length=1)
    action_summary: str = Field(min_length=1)
    triggering_condition: str = Field(min_length=1)
    downside: str = Field(min_length=1)
    amount_usd: Decimal | None = None
    counterparty: str | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    needs_approval: bool = True
    """Defaults to True. A Manager that forgot to set it asks rather than
    acts, which is the direction spec §8 requires the default to fall."""
