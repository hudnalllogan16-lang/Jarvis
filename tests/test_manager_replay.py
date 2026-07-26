"""Replay of a real Business Manager cycle (spec §11; D-004, M4-F1).

`test_manager_determinism.py` asserts against the workflow module's AST — what
the code *may* do. This file asserts against a history the code actually
produced: `tests/fixtures/manager_cycle_history.json` is the Temporal event
history of one live wake cycle of `bm-biz_6f548e12d9b145bfb53ed2e72f764b8b`
(run `1656651d-16c1-4ca6-91e6-9ee3411042ae`), captured from a real Temporal
server during M6-1 against a real model. The two are complementary: the AST gate
catches a nondeterministic construct before it ever runs, and this catches a
change in the *sequence of commands* the workflow issues, which is the thing that
actually breaks recovery.

Why a captured history rather than a synthetic one: a hand-written history proves
the replayer works, not that this workflow replays. The failure mode D-004 exists
to prevent — a Manager that resumes after a worker restart and diverges — is only
reachable through a history a real run produced.

The history also records *when* each activity was scheduled and started, which is
the only place parallel dispatch is observable. M4-F1 (dispatch silently
serialised by a list comprehension) passed every functional test; it could not
have passed `test_dispatch_capability_runs_in_parallel` below.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from jarvis.manager.state import ManagerState
from jarvis.manager.workflow import BusinessManagerWorkflow

HISTORY_PATH = pathlib.Path(__file__).parent / "fixtures" / "manager_cycle_history.json"
WORKFLOW_ID = "bm-biz_6f548e12d9b145bfb53ed2e72f764b8b"

RAW_HISTORY = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
EVENTS: list[dict[str, object]] = RAW_HISTORY["events"]

SCHEDULED = "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
STARTED = "EVENT_TYPE_ACTIVITY_TASK_STARTED"
COMPLETED = "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"


def _history() -> WorkflowHistory:
    """Return the captured history in the form the replayer consumes."""
    return WorkflowHistory.from_json(WORKFLOW_ID, RAW_HISTORY)


def _activity_name(event: dict[str, object]) -> str:
    attrs = event.get("activityTaskScheduledEventAttributes")
    if not isinstance(attrs, dict):
        return ""
    activity_type = attrs.get("activityType")
    if not isinstance(activity_type, dict):
        return ""
    return str(activity_type.get("name", ""))


def _scheduled_names() -> dict[str, str]:
    """Map scheduled-event id -> activity name."""
    return {str(e["eventId"]): _activity_name(e) for e in EVENTS if e["eventType"] == SCHEDULED}


def _moment(event: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(event["eventTime"]).replace("Z", "+00:00"))


# ── the replay itself ──────────────────────────────────────────────────────


async def test_captured_cycle_replays_without_divergence() -> None:
    """The shipped workflow replays a real cycle's history command for command.

    This is the property §11 asks for and the one D-004 protects. It fails the
    moment someone reorders an activity call, adds one, or makes a branch depend
    on something the history does not contain.
    """
    replayer = Replayer(
        workflows=[BusinessManagerWorkflow],
        data_converter=pydantic_data_converter,
    )
    await replayer.replay_workflow(_history())


@workflow.defn(name="BusinessManager")
class _DivergentManagerWorkflow:
    """A Manager that issues a different first command. Negative control only."""

    @workflow.run
    async def run(self, state: ManagerState) -> ManagerState:
        await workflow.execute_activity(
            "record_cycle_decision",
            {
                "business_id": state.business_id,
                "summary": "x",
                "rationale": "x",
                "outcome": "completed",
                "spend_usd": "0",
            },
            start_to_close_timeout=timedelta(minutes=5),
        )
        return state


async def test_the_replay_check_actually_fires() -> None:
    """Negative control: a guard that cannot fail reads as coverage and is not.

    Replaying the same captured history against a workflow whose first command
    differs must be rejected. Without this, a replayer misconfiguration would
    make the test above pass for every possible workflow.
    """
    replayer = Replayer(
        workflows=[_DivergentManagerWorkflow],
        data_converter=pydantic_data_converter,
    )
    with pytest.raises(Exception) as caught:
        await replayer.replay_workflow(_history())
    assert "nondeterminism" in str(caught.value).lower()


# ── what the history shows the cycle did ───────────────────────────────────


def test_history_is_a_complete_manager_cycle() -> None:
    """Guard on the fixture: replaying a truncated history proves little.

    If this fixture is ever regenerated from a cycle that did less work, the
    replay above would still pass while covering less of the workflow. This
    pins what the fixture must contain.
    """
    started = EVENTS[0]
    attrs = started["workflowExecutionStartedEventAttributes"]
    assert isinstance(attrs, dict)
    assert attrs["workflowType"]["name"] == "BusinessManager"

    names = list(_scheduled_names().values())
    assert names.count("load_cycle_context") >= 1
    assert names.count("plan_cycle") == 1
    assert names.count("dispatch_capability") >= 2, "a one-request cycle cannot show parallelism"
    assert names.count("synthesize_results") == 1
    assert names.count("record_cycle_decision") == 1


def test_dispatch_capability_runs_in_parallel() -> None:
    """Regression guard on M4-F1, observed rather than inferred.

    Two independent facts, both unavailable to a source-level test:

    1. Every dispatch was *scheduled* before any of them was scheduled second —
       i.e. they arrive in one workflow task, which is what `asyncio.gather`
       produces and what awaiting handles one at a time cannot.
    2. Every dispatch had *started* before the first one finished. Under serial
       dispatch the second activity cannot start until the first completes, so
       this is impossible for more than one request.
    """
    names = _scheduled_names()
    dispatch_ids = [eid for eid, name in names.items() if name == "dispatch_capability"]
    assert len(dispatch_ids) >= 2

    order = [str(e["eventId"]) for e in EVENTS]
    positions = sorted(order.index(eid) for eid in dispatch_ids)
    assert positions == list(range(positions[0], positions[0] + len(positions))), (
        "dispatches were not scheduled together in one workflow task"
    )

    starts = [
        _moment(e)
        for e in EVENTS
        if e["eventType"] == STARTED
        and str(e["activityTaskStartedEventAttributes"]["scheduledEventId"]) in dispatch_ids
    ]
    completions = [
        _moment(e)
        for e in EVENTS
        if e["eventType"] == COMPLETED
        and str(e["activityTaskCompletedEventAttributes"]["scheduledEventId"]) in dispatch_ids
    ]
    assert len(starts) == len(dispatch_ids)
    assert len(completions) == len(dispatch_ids)
    assert max(starts) < min(completions), (
        "a dispatch started only after another finished — dispatch is serial"
    )


def test_cycle_wrote_a_decision_log_entry_last() -> None:
    """Spec §2.1/§11.5: the cycle ends by explaining itself.

    The Decision Log entry is what the operator's activity feed reads, and D-006
    requires an approval to be reconstructable from it alone — so the write has
    to be part of the cycle, not a best-effort afterthought.
    """
    names = _scheduled_names()
    ordered = [names[str(e["eventId"])] for e in EVENTS if e["eventType"] == SCHEDULED]
    assert ordered.index("record_cycle_decision") > ordered.index("synthesize_results")
    assert ordered.index("record_cycle_decision") > ordered.index("request_approval")
