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


def test_kpi_measurement_is_gated_on_the_cycle_context() -> None:
    """D-027.3 plus spec §11, asserted where the failure would be invisible.

    Two properties in one line of source. A type that declares no mappings must
    record nothing — the workflow cannot know which types those are without
    doing I/O, so it asks the cycle context. And a history captured before that
    field existed deserialises to False, which is what keeps
    `tests/test_manager_replay.py` green with a new activity on the cycle path.

    Ungating this would pass every functional test in the suite and break
    recovery of every history captured to date, which is exactly the class of
    defect D-004 exists to keep out of workflow code.
    """
    guarded = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Attribute)
        and node.test.attr == "measures_kpis"
        and "record_cycle_kpis" in ast.dump(node)
    ]
    assert len(guarded) == 1, "record_cycle_kpis must be scheduled only when the type maps KPIs"
    assert ast.dump(TREE).count("'record_cycle_kpis'") == 1, "no second, ungated call"


def test_the_cycle_loads_its_context_after_the_wake() -> None:
    """M7-F45 plus audit F-B, asserted where the regression would be silent.

    A cycle reasons on a snapshot taken when it begins, not on one taken before
    it waited. Moving the read back above `_await_wake` would pass every
    behavioural test in the suite — the cycle still runs, still plans, still
    records — and would restore a defect whose only symptom is that a change
    made while a Manager was parked takes an extra full wake to apply.

    Two reads, deliberately: the first answers how long to wait and whether to
    wait at all, the second is the cycle's own.
    """
    loop = SOURCE.split("async def run(")[1].split("async def _load_context")[0]
    assert loop.count("self._load_context(") == 2
    assert loop.index("self._await_wake(") < loop.rindex("self._load_context("), (
        "the cycle's context must be read after the wake, not before it"
    )


def test_the_post_wake_reload_is_versioned() -> None:
    """M6-F33: a change to a live workflow path ships behind a patch.

    The reload adds a command to the cycle path, so a Manager parked when it
    shipped would diverge on recovery without a version boundary. Asserted on
    the source because deleting the guard is a one-line edit that leaves every
    test green except the replays — and the replays would then be failing for a
    reason nobody would read as "this needed versioning".

    `tests/test_workflow_versioning.py` holds the rest: the id discipline, the
    proof that both captured histories take the old branch, and the control that
    forces this branch open against those same histories.
    """
    guarded = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and isinstance(node.test.func, ast.Name)
        and node.test.func.id == "_reloads_context_after_wake"
        and "_load_context" in ast.dump(node)
    ]
    assert len(guarded) == 1, "the post-wake read is the patched branch"
    assert "workflow.patched(PATCH_POST_WAKE_CONTEXT)" in SOURCE


def test_the_planner_s_targets_are_read_defensively_from_the_context() -> None:
    """M8-F7 plus spec §11: a history captured before the field must replay.

    `None` means the context predates the field and the carried state is what
    that history planned against; `()` is a live answer meaning no targets are
    set. A truthiness check would collapse them, which would both break those
    histories' honesty and make a future refresh unable to remove the last
    target.
    """
    assert "state.kpi_targets if ctx.kpi_targets is None else ctx.kpi_targets" in SOURCE
    assert "ctx.kpi_targets or state.kpi_targets" not in SOURCE


def test_measurement_precedes_the_decision_record() -> None:
    """D-027.1 fixes the order: after synthesis, before the decision record.

    The cycle's entry is what an owner reads; writing it before the figures it
    describes were measured would let a cycle report a round of work whose
    numbers were never taken.

    Measured from the synthesis call onwards, because the branch above it — a
    cycle that planned nothing — records an entry and measures nothing at all,
    which is the documented shape and not an ordering violation.
    """
    body = SOURCE.split("async def _execute_cycle")[1]
    after_synthesis = body.split('"synthesize_results"')[1]
    assert "record_cycle_kpis" in after_synthesis
    assert after_synthesis.index("record_cycle_kpis") < after_synthesis.index("self._record(")


def test_pool_retry_is_not_duplicated_at_the_workflow_layer() -> None:
    """Spec §9: bounded retry belongs to the pool.

    Retrying dispatch here as well would multiply attempts and spend a business's
    budget several times over for one invocation.
    """
    assert "maximum_attempts=1" in SOURCE
