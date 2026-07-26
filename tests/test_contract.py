"""Standard Business Contract tests (spec §5, §8)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from jarvis.domain.contract import (
    AutonomyPolicy,
    BudgetPolicy,
    BusinessContract,
    CapabilityType,
    WakeConditions,
)


def test_unknown_action_type_requires_approval(contract: BusinessContract) -> None:
    """Spec §8: absence of configuration is never permission."""
    assert contract.requires_approval("affiliate.wire_funds")


def test_configured_action_defaults_to_requiring_approval(contract: BusinessContract) -> None:
    assert contract.requires_approval("affiliate.publish_post")


def test_permission_lookup_is_capability_scoped(contract: BusinessContract) -> None:
    assert contract.permission_for(CapabilityType.RESEARCH) is not None
    assert contract.permission_for(CapabilityType.FINANCE) is None


def test_wake_conditions_must_be_explicit(contract: BusinessContract) -> None:
    """Spec §2.1: wake conditions MUST NOT be left implicit."""
    payload = contract.model_dump()
    payload["wake_conditions"] = WakeConditions(
        schedule_cron=None, event_triggers=frozenset()
    ).model_dump()
    with pytest.raises(ValidationError):
        BusinessContract.model_validate(payload)


def test_graduation_threshold_floor_enforced() -> None:
    """A threshold of 1 would make the autonomy ladder meaningless (spec §8)."""
    with pytest.raises(ValidationError):
        AutonomyPolicy(action_type="affiliate.publish_post", graduation_threshold=1)


def test_action_type_must_be_namespaced() -> None:
    """A-003: identity is namespaced to the business type."""
    with pytest.raises(ValidationError):
        AutonomyPolicy(action_type="publish_post", graduation_threshold=5)


def test_duplicate_action_types_rejected(contract: BusinessContract) -> None:
    policy = AutonomyPolicy(action_type="affiliate.publish_post", graduation_threshold=5)
    payload = contract.model_dump()
    payload["autonomy_policies"] = [policy.model_dump(), policy.model_dump()]
    with pytest.raises(ValidationError):
        BusinessContract.model_validate(payload)


def test_budget_ceilings_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        BudgetPolicy(business_cap_usd=Decimal("0"), wake_cycle_ceiling_usd=Decimal("1"))


def test_contract_is_immutable(contract: BusinessContract) -> None:
    """The Executive Layer reads contracts; only the Registry writes them."""
    with pytest.raises(ValidationError):
        contract.display_name = "Renamed"  # type: ignore[misc]
