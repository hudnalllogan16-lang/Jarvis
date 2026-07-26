"""Workflow determinism tests (spec §2, §11; D-004).

D-004 requires all nondeterminism to live in activities. A workflow that reads a
clock, generates a UUID, or calls out to a network passes its unit tests and then
diverges on replay — the failure appears during recovery, which is exactly when
it is least affordable.

These assert on the workflow module's source, because determinism is a property
of what the code *may* do, not of what one execution happened to do.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

WORKFLOW = pathlib.Path("jarvis/manager/workflow.py")
SOURCE = WORKFLOW.read_text()
TREE = ast.parse(SOURCE)

FORBIDDEN_CALLS = [
    "datetime.now",
    "datetime.utcnow",
    "time.time",
    "uuid4",
    "random.",
    "new_invocation_id",
    "new_decision_id",
    "new_approval_id",
    "new_cycle_id",
]


@pytest.mark.parametrize("call", FORBIDDEN_CALLS)
def test_workflow_contains_no_nondeterministic_call(call: str) -> None:
    """D-004: clock, randomness, and identifier minting belong in activities."""
    assert call not in SOURCE


def test_workflow_imports_no_io_modules() -> None:
    """A database handle or HTTP client in workflow code breaks replay."""
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(TREE)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for banned in {"sqlalchemy", "httpx", "redis", "requests"}:
        assert banned not in imported


def test_workflow_does_not_import_services_directly() -> None:
    """Services own I/O. The workflow reaches them only through activities."""
    for banned in ("registry.registry", "observability.audit", "budget.ledger"):
        assert banned not in SOURCE


def test_every_external_call_is_an_activity() -> None:
    """All outward calls go through execute_activity with a bounded timeout."""
    calls = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_activity"
    ]
    assert calls, "the Manager must reach the outside world somehow"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert "start_to_close_timeout" in kwargs, (
            "spec §9: Manager activities take the same timeout discipline as any "
            "other workflow, so a stuck Manager surfaces"
        )


def test_dispatch_is_parallel_not_sequential() -> None:
    """Spec §2.1 permits dispatching multiple requests in parallel.

    Regression guard: the first draft awaited handles in a list comprehension,
    which serialises them and makes a cycle's latency the sum of its parts.
    """
    assert "asyncio.gather" in SOURCE
    assert "[await h for h in handles]" not in SOURCE


def test_continuation_is_bounded() -> None:
    """D-005: history must not grow without bound."""
    assert "continue_as_new" in SOURCE
    assert "CYCLES_BEFORE_CONTINUATION" in SOURCE


def test_approval_ends_the_cycle_rather_than_parking() -> None:
    """D-006: continuation model, not blocking.

    A cycle that waited for an answer would spread one cost ceiling across up to
    seven days (spec §9) and make stuck-Manager detection a week-long timer.
    """
    assert "AWAITING_APPROVAL" in SOURCE
    assert "wait_for_approval" not in SOURCE
    assert "approval_decided" in SOURCE


def test_a_failed_cycle_does_not_fail_the_workflow() -> None:
    """Spec §9, M6-F9: a stuck Manager surfaces rather than vanishing.

    Asserted on the source rather than only on behaviour, because the failure
    mode is a *missing* handler: a future edit that unwraps one of these calls
    would pass every functional test and only show up as a business left without
    a Manager, months later, during an incident.
    """
    handlers = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "ActivityError"
    ]
    assert len(handlers) >= 2, "planning and the cycle body both need a handler"
    assert "CycleOutcome.FAILED" in SOURCE


def test_the_cycle_id_is_read_defensively_from_the_plan_result() -> None:
    """D-021 plus spec §11: a history captured before the id existed must replay.

    Subscripting the payload would raise `KeyError` on any pre-D-021 history and
    turn a recoverable Manager into an unreplayable one.
    """
    assert 'plan_payload["cycle_id"]' not in SOURCE
    assert 'plan_payload.get("cycle_id")' in SOURCE


def test_pool_retry_is_not_duplicated_at_the_workflow_layer() -> None:
    """Spec §9: bounded retry belongs to the pool.

    Retrying dispatch here as well would multiply attempts and spend a business's
    budget several times over for one invocation.
    """
    assert "maximum_attempts=1" in SOURCE
