"""Activity-boundary tests (D-002, D-004; closes Milestone 1 finding M1-R1).

Milestone 1 shipped `RuntimeIdentity` with no production caller, because there
were no activities. These tests cover the derivation contract the activity
boundary now depends on.
"""

from __future__ import annotations

import dataclasses

import pytest
from temporalio.testing import ActivityEnvironment

from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import BusinessId
from jarvis.kernel.runtime import RuntimeIdentity, business_workflow_id

BIZ = BusinessId("biz_" + "0123456789abcdef" * 2)


def _activity_env(workflow_id: str | None) -> ActivityEnvironment:
    """Return an activity context reporting ``workflow_id`` from `activity.info()`."""
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=workflow_id)
    return env


def test_workflow_id_round_trips() -> None:
    assert RuntimeIdentity.from_workflow_id(business_workflow_id(BIZ)).business_id == BIZ


def test_one_manager_per_business_by_construction() -> None:
    """Spec §2.1: each business MUST have exactly one Business Manager.

    A deterministic workflow id makes a second Manager for the same business a
    workflow-id collision rather than a silent duplicate.
    """
    assert business_workflow_id(BIZ) == business_workflow_id(BIZ)


@pytest.mark.parametrize(
    "workflow_id",
    [
        "",
        "bm-",
        "bm-biz_short",
        "bm-biz_" + "z" * 32,
        "biz_" + "a" * 32,
        "executive-cfo",
        "bm-biz_" + "a" * 31,
        "bm-biz_" + "a" * 33,
        "BM-biz_" + "a" * 32,
    ],
)
def test_unidentifiable_callers_are_refused(workflow_id: str) -> None:
    """An unidentifiable caller is refused, never defaulted (spec §10)."""
    with pytest.raises(ScopeViolationError):
        RuntimeIdentity.from_workflow_id(workflow_id)


def test_provenance_is_recorded_for_audit() -> None:
    """Test-provenance identities in a production audit trail are an incident."""
    assert RuntimeIdentity.for_testing(BIZ)._source == "testing"
    assert RuntimeIdentity.from_workflow_id(business_workflow_id(BIZ))._source == "workflow_id"


def test_test_identities_must_match_the_production_format() -> None:
    """Otherwise the derivation path is only ever exercised against easy input."""
    with pytest.raises(ScopeViolationError):
        RuntimeIdentity.for_testing(BusinessId("biz_test0001"))


def test_workflow_less_activity_is_refused() -> None:
    """Finding M6-F4: an activity with no calling workflow has no identity.

    Temporal reports `workflow_id is None` when an activity was not started by a
    workflow. D-002 derives identity *from* the workflow id, so there is nothing
    to derive from and the only safe answer is refusal — not a default, not a
    narrowed scope. Before this guard the None fell through into
    `from_workflow_id`'s regex and surfaced as a bare `TypeError`, which the
    docstring did not promise and which reads as a crash rather than a denial.
    """
    with pytest.raises(ScopeViolationError):
        _activity_env(None).run(RuntimeIdentity.from_activity)


def test_a_business_workflow_still_resolves_inside_an_activity() -> None:
    """Negative control for M6-F4: the guard refuses only the unidentifiable case.

    Without this, a guard that rejected every activity would pass the test above
    while silently disabling the production derivation path.
    """
    identity = _activity_env(business_workflow_id(BIZ)).run(RuntimeIdentity.from_activity)
    assert identity.business_id == BIZ
    assert identity.workflow_id == business_workflow_id(BIZ)
    assert identity.audit_source == "activity"


def test_a_non_business_workflow_id_is_still_refused_inside_an_activity() -> None:
    """The M6-F4 guard is additional to the format check, not a replacement."""
    with pytest.raises(ScopeViolationError):
        _activity_env("executive-cfo").run(RuntimeIdentity.from_activity)


def test_identity_is_immutable() -> None:
    identity = RuntimeIdentity.for_testing(BIZ)
    with pytest.raises(AttributeError):
        identity.business_id = BusinessId("biz_" + "f" * 32)  # type: ignore[misc]
