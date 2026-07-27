"""Business Manager durable state (spec §2.1, bounded per D-005).

§2.1 says the Manager owns, as durable workflow state, the current tactical plan,
active KPI targets, and decision history. D-005 keeps the first two here and
moves decision history to the Decision Log, because an accumulating history
inside a long-lived workflow hits Temporal's history limits — a failure that
surfaces in production after months, not in test.

Everything in this module must survive JSON serialisation and must never carry a
clock, a random value, or a database handle: it is workflow state, and workflow
code is deterministic (D-004).

The `supervisor` field exists for §3.2 and §4.1. Districts are not built and MUST
NOT be built speculatively, but a Manager that hardcoded "my parent is the
Executive Layer" would need redesigning to admit one. Naming the supervisor
rather than assuming it costs one string and removes that redesign.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from jarvis.capabilities.request import CapabilityResult, ScopedRequest
from jarvis.kernel.ids import BusinessId

MAX_PLAN_ITEMS = 20
"""Hard cap on plan size. A plan is a working set, not a backlog; without a cap
a Manager that appends every cycle grows its own state without bound."""


class CycleOutcome(StrEnum):
    """How a wake cycle ended.

    `AWAITING_APPROVAL` is a terminal outcome, not a pause. Under D-006 the
    Manager emits its approval request and the cycle *ends*; the operator's
    answer arrives later as an event that starts a new cycle. A cycle that
    blocked for up to seven days (spec §9) would make §2.1's per-cycle cost
    ceiling undefined.
    """

    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NOTHING_TO_DO = "nothing_to_do"
    FAILED = "failed"


class PlanItem(BaseModel):
    """One thing the Manager intends to do this cycle or next."""

    model_config = ConfigDict(frozen=True)

    ref: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    """Plain language, because it reaches the Decision Log and then the
    operator's activity feed (spec §11.5, §12.5)."""

    kpi_key: str | None = None
    """Which target this serves, if any. Ties tactical work to the direction the
    Executive Layer set (spec §3.1)."""

    depends_on: tuple[str, ...] = ()
    """`ref`s of other items in the same plan whose results this one consumes
    (D-023 point 1). Empty is the norm and behaves exactly as before: items with
    no declared dependency are dispatched together.

    Model-proposed, platform-validated (D-013). By the time a plan reaches here
    every name has been checked against the plan's own refs and the graph has
    been checked for cycles and depth; an item whose declaration failed either
    check is not in the plan at all."""


class TacticalPlan(BaseModel):
    """The Manager's current plan (spec §2.1).

    Tactical only. A Manager MUST NOT set long-term strategy, allocate capital
    across businesses, or decide to create or retire a business (spec §2.1) —
    there is deliberately no field here in which any of those could be recorded.
    """

    model_config = ConfigDict(frozen=True)

    items: tuple[PlanItem, ...] = ()
    rationale: str = ""

    def bounded(self) -> TacticalPlan:
        """Return a plan truncated to `MAX_PLAN_ITEMS`."""
        return (
            self
            if len(self.items) <= MAX_PLAN_ITEMS
            else TacticalPlan(items=self.items[:MAX_PLAN_ITEMS], rationale=self.rationale)
        )


class KpiTargetState(BaseModel):
    """A KPI target as the Manager holds it (spec §2.1, §3.1).

    Copied from the contract, never authored here: targets are set by the
    Executive Layer and executed against tactically. The Manager has no method
    to change one.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    target_value: Decimal
    operator_label: str


class ManagerState(BaseModel):
    """Durable workflow state for one Business Manager (§2.1, bounded per D-005)."""

    model_config = ConfigDict(frozen=True)

    business_id: BusinessId
    supervisor: str = "executive"
    """Who this Manager rolls up to. `executive` today; a district id later,
    without a Manager redesign (spec §3.2, §4.1)."""

    plan: TacticalPlan = TacticalPlan()
    kpi_targets: tuple[KpiTargetState, ...] = ()
    cycles_completed: int = 0
    """Cycles completed *in this run*, which is what drives `continue_as_new`
    (D-005) and what keeps Temporal history bounded.

    Per run, not per Manager: `continued` resets it, so the count means "how
    much history this execution has accumulated" rather than "how long this
    company has existed". A lifetime count would answer a different question,
    and answering it here is what made M8-F87 possible."""

    cycles_today: int = 0
    day_ordinal: int = 0
    """Wake-rate accounting. §2.1's cost ceiling bounds a single cycle; nothing
    in v1.4 bounds how *often* cycles start, so a Manager woken by its own
    capability results could oscillate indefinitely within budget."""

    pending_approval_id: str | None = None
    """Set when the previous cycle ended awaiting an answer (D-006). Its presence
    is how a resumed Manager knows it is continuing rather than starting fresh."""

    def with_cycle_recorded(self, *, day_ordinal: int) -> ManagerState:
        """Return state advanced by one completed cycle.

        Args:
            day_ordinal: Proleptic day number, passed in rather than read from a
                clock — workflow code cannot read the wall clock (D-004).
        """
        same_day = day_ordinal == self.day_ordinal
        return self.model_copy(
            update={
                "cycles_completed": self.cycles_completed + 1,
                "cycles_today": self.cycles_today + 1 if same_day else 1,
                "day_ordinal": day_ordinal,
            }
        )

    def continued(self) -> ManagerState:
        """Return the state the next generation of this Manager starts from (M8-F87).

        `continue_as_new` starts a fresh execution with a fresh history, so the
        count of what the *previous* history accumulated has to go back to zero
        with it. It did not: the same state was handed over intact, so the very
        first cycle of generation two took the count to 101, met the threshold
        again, and continued as new immediately — and every cycle after that
        did the same. `CYCLES_BEFORE_CONTINUATION` bound the first hundred
        cycles of a Manager's life and nothing afterwards.

        Only the ordinal resets. Everything else is durable state that a
        continuation is not supposed to disturb (D-005):

        - `cycles_today` and `day_ordinal` are the daily wake allowance, which
          bounds how often a *company* reasons and has nothing to do with how
          much history one execution holds. Resetting them here would hand a
          business a fresh day's allowance every hundred cycles, which is the
          rate limit quietly removing itself.
        - `pending_approval_id` is how a resumed Manager knows it is waiting on
          an answer (D-006); dropping it at a continuation would lose an
          approval roundtrip that spans one.
        - `plan` and `kpi_targets` are the working set §2.1 says the Manager
          owns.

        Safe against the cycle key (D-034.2) because that key namespaces by run
        id, and `continue_as_new` assigns a new one: generation two's cycle 0
        and generation one's cycle 0 derive different keys, so a reset ordinal
        cannot make two cycles share a budget scope.
        """
        return self.model_copy(update={"cycles_completed": 0})

    def wake_budget_exhausted(self, max_per_day: int, *, day_ordinal: int) -> bool:
        """Return whether this business has woken too often today."""
        if day_ordinal != self.day_ordinal:
            return False
        return self.cycles_today >= max_per_day


class SkippedDispatch(BaseModel):
    """A dispatch the cycle declined to make because a dependency did not land.

    D-023 point 4: a dependency on a FAILED or DEAD_LETTERED result makes the
    dependent's dispatch a *decision*, not an absence. Recording it is what lets
    synthesis say why a step it expected never ran, instead of summarising a
    cycle as if the step had never been planned.

    No `status`: nothing was invoked, so there is no invocation outcome to
    report. Conflating "not started" with `FAILED` would put an invocation that
    never existed into D-001's terminal-state accounting.
    """

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    capability: str
    ref: str = ""
    """The plan item this would have been."""

    blocked_by: tuple[str, ...] = ()
    """Refs of the earlier items whose results did not arrive."""

    reason: str = ""
    """Plain language, because it reaches synthesis and then the operator's
    activity feed (spec §12.5)."""


class CycleResult(BaseModel):
    """What one wake cycle produced.

    Returned from the workflow so tests and the dashboard can assert on a cycle
    without reconstructing it from logs.
    """

    model_config = ConfigDict(frozen=True)

    outcome: CycleOutcome
    dispatched: tuple[ScopedRequest, ...] = ()
    results: tuple[CapabilityResult, ...] = ()
    skipped: tuple[SkippedDispatch, ...] = ()
    """Planned dispatches a failed dependency stopped (D-023 point 4)."""

    spend_usd: Decimal = Decimal("0")
    summary: str = ""
    """Plain language; becomes the Decision Log entry for this cycle."""
