"""Business Manager durable state tests (spec §2.1, D-005)."""

from __future__ import annotations

from decimal import Decimal

from jarvis.kernel.ids import BusinessId
from jarvis.manager.state import (
    MAX_PLAN_ITEMS,
    CycleOutcome,
    KpiTargetState,
    ManagerState,
    PlanItem,
    TacticalPlan,
)

BIZ = BusinessId("biz_" + "0123456789abcdef" * 2)


def _state(**over: object) -> ManagerState:
    return ManagerState(business_id=BIZ, **over)  # type: ignore[arg-type]


def test_plan_is_bounded() -> None:
    """D-005: workflow state is a working set, not a growing backlog."""
    plan = TacticalPlan(items=tuple(PlanItem(ref=f"r{i}", intent="do a thing") for i in range(60)))
    assert len(plan.bounded().items) == MAX_PLAN_ITEMS


def test_state_carries_no_decision_history() -> None:
    """D-005 moves history to the Decision Log.

    Asserted on the schema, not on a value: a field would let history accumulate
    even if today's code never filled it, and the failure only appears months in.
    """
    assert "decision_history" not in ManagerState.model_fields
    assert "decisions" not in ManagerState.model_fields


def test_manager_cannot_hold_strategy() -> None:
    """Spec §2.1: a Manager MUST NOT set strategy or allocate capital.

    There is deliberately no field in which any of it could be recorded.
    """
    forbidden = {"strategy", "capital_allocation", "portfolio", "create_business"}
    assert forbidden.isdisjoint(ManagerState.model_fields)
    assert forbidden.isdisjoint(TacticalPlan.model_fields)


def test_supervisor_is_named_not_assumed() -> None:
    """Spec §3.2, §4.1: must not hardcode business as permanently top-level."""
    assert _state().supervisor == "executive"
    assert _state(supervisor="district_north").supervisor == "district_north"


def test_cycle_accounting_rolls_over_at_midnight() -> None:
    state = _state()
    day = 1000
    for _ in range(3):
        state = state.with_cycle_recorded(day_ordinal=day)
    assert state.cycles_today == 3
    assert state.cycles_completed == 3

    state = state.with_cycle_recorded(day_ordinal=day + 1)
    assert state.cycles_today == 1
    assert state.cycles_completed == 4


def test_wake_rate_bound() -> None:
    """Review item 20: §2.1 bounds one cycle's cost, nothing bounds frequency."""
    state = _state()
    day = 1000
    for _ in range(48):
        state = state.with_cycle_recorded(day_ordinal=day)
    assert state.wake_budget_exhausted(48, day_ordinal=day)
    assert not state.wake_budget_exhausted(48, day_ordinal=day + 1)


def test_kpi_targets_are_carried_not_authored() -> None:
    """Spec §3.1: targets are set by the Executive Layer, executed tactically."""
    state = _state(
        kpi_targets=(
            KpiTargetState(
                key="revenue_mtd", target_value=Decimal("1000"), operator_label="Revenue"
            ),
        )
    )
    assert state.kpi_targets[0].key == "revenue_mtd"
    assert not hasattr(state, "set_kpi_target")


def test_awaiting_approval_is_a_terminal_outcome() -> None:
    """D-006: the cycle ends when approval is raised; it does not park."""
    assert CycleOutcome.AWAITING_APPROVAL.value == "awaiting_approval"
    assert _state(pending_approval_id="apr_1").pending_approval_id == "apr_1"


def test_state_survives_serialisation() -> None:
    """Workflow state crosses a serialisation boundary on every continuation."""
    state = _state(plan=TacticalPlan(items=(PlanItem(ref="a", intent="write a post"),)))
    assert ManagerState.model_validate(state.model_dump(mode="json")) == state
