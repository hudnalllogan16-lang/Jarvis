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

    kpi_targets: tuple[KpiTargetState, ...] | None = None
    """The targets this business is currently working to, from its contract.

    Loaded per cycle rather than carried, closing M8-F7. `ManagerState` is
    seeded with the contract's targets once, when the Manager starts, and then
    carries them across every cycle and every `continue_as_new` — so a target
    changed on the contract reaches every operator-facing number immediately
    (the API reads the contract) while the planner keeps working to the figures
    it was started with, for up to a hundred cycles. There is no contract
    refresh path today (M7-F24), which is why this was invisible rather than
    absent; the fix belongs with the rest of the post-wake snapshot, not with
    whatever ships that path.

    `None`, not `()`, is the pre-M8-3 marker, and the distinction is the whole
    point: a history captured before this field carries no answer at all and the
    workflow keeps using the state it carried, while `()` is a live, current
    answer meaning *this business has no targets set*. Defaulting to `()` would
    make those two indistinguishable and would silently ignore a future refresh
    that removed the last target. Bounded by the contract's own target count, so
    D-005's working set is unaffected — this is a per-cycle payload, not
    accumulated state."""

    measures_kpis: bool = False
    """Whether this business's type declares KPI mappings (D-027.2/.3).

    The workflow needs to know whether a cycle has a measurement step at all,
    and cannot look: reading the type definition is I/O (D-004). So the activity
    that loads the rest of the cycle's context loads this too, and the workflow
    only walks the answer.

    Defaults to False, which is the compatibility hinge D-023 used for
    `DispatchSequence`: a history captured before this field existed
    deserialises to False and the workflow issues exactly the commands it issued
    then (spec §11). That is not a special case for old histories — it is the
    same answer the platform gives today for the type in them, which declares no
    mappings."""


class PlanRequest(BaseModel):
    """Input to the planning activity."""

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    wake_reasons: tuple[str, ...] = ()
    current_plan: TacticalPlan = TacticalPlan()
    kpi_targets: tuple[KpiTargetState, ...] = ()
    pending_approval_id: str | None = None

    cycle_key: str = ""
    """This cycle's budget scope key, derived in the workflow (D-034.2).

    The one field here that travels *in* rather than out, and the reason is
    retries. Temporal re-delivers a failed activity's original input, so a key
    computed in the workflow is identical on every attempt, while the id
    `plan_cycle` used to mint was fresh on each — which let a refusal caused by
    accumulated cycle spend pass on retry (M6-F17) and put three reservations
    for one logical cycle in the live ledger (M7-F25).

    Empty means "no key supplied", not "no cycle": `plan_cycle` mints then,
    exactly as D-021 specified. That keeps every existing caller — and every
    captured history, whose recorded `plan_cycle` result carries a minted id —
    behaving as it did (spec §11)."""


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


class CycleKpiRequest(BaseModel):
    """Input to the activity that measures a finished cycle (D-027.1).

    Carries the cycle's own terminal results because they *are* the platform's
    record of what the cycle did: every one is the recorded output of a
    `dispatch_capability` activity, which is the replay substrate itself
    (D-004). Re-deriving them from the database inside the activity would mean
    matching invocation ids out of JSON payloads across two dialects to
    reconstruct something the workflow is already holding.

    Which observations these facts become is decided in the activity, from the
    type's declared mappings — never here, and never by the workflow, which
    cannot read a type definition without doing I/O.
    """

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    cycle_id: str | None = None
    results: tuple[CapabilityResult, ...] = ()


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
