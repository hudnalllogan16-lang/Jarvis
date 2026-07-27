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

import base64
import copy
import json
import pathlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.finance import FINANCE
from jarvis.manager.state import ManagerState
from jarvis.manager.types import CycleContext
from jarvis.manager.workflow import BusinessManagerWorkflow

HISTORY_PATH = pathlib.Path(__file__).parent / "fixtures" / "manager_cycle_history.json"
WORKFLOW_ID = "bm-biz_6f548e12d9b145bfb53ed2e72f764b8b"

RAW_HISTORY = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
EVENTS: list[dict[str, object]] = RAW_HISTORY["events"]

FINANCE_HISTORY_PATH = pathlib.Path(__file__).parent / "fixtures" / "finance_cycle_history.json"
FINANCE_WORKFLOW_ID = "bm-biz_08122842a3034381abe3726d47464f16"
"""The Finance counterpart, captured live in M7-3c from `Portfolio Watch`
(run `11e3a4ab-097d-4f33-aef4-0ef25ed82895`) against a real model.

Added alongside the Affiliate history rather than replacing it, because the two
prove opposite halves of the same D-027 claim and neither is redundant. The
Affiliate history predates `measures_kpis` and shows an unmeasured cycle still
replaying; this one is the first history in the project's life that actually
scheduled `record_cycle_kpis`, and shows a *measured* cycle replaying. Before
it, the only committed evidence for the measured path was
`test_measuring_this_cycle_would_have_diverged` — a history patched in memory,
which proves the gate can fail but not that a real measured cycle survives it.

It spans three cycles of one workflow, including the M7-F20 credential failure
and the first cycle after it, which is why the counts below are per-history
rather than per-cycle. Captured whole and never edited: a history with its
payloads trimmed would be a fixture about our editing, not about what the
Manager did."""

FINANCE_RAW_HISTORY = json.loads(FINANCE_HISTORY_PATH.read_text(encoding="utf-8"))
FINANCE_EVENTS: list[dict[str, object]] = FINANCE_RAW_HISTORY["events"]

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


# ── D-027: a new cycle step, and why this history still replays ────────────


def _recorded_result(activity_name: str) -> dict[str, Any]:
    """Return the payload one activity returned in the captured run."""
    scheduled = {e["eventId"]: _activity_name(e) for e in EVENTS if e["eventType"] == SCHEDULED}
    for event in EVENTS:
        attrs = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        if scheduled.get(attrs["scheduledEventId"]) != activity_name:
            continue
        payload = attrs["result"]["payloads"][0]
        decoded = json.loads(base64.b64decode(payload["data"]).decode())
        assert isinstance(decoded, dict)
        return decoded
    raise AssertionError(f"{activity_name} never completed in this history")


def test_the_captured_cycle_context_predates_kpi_measurement() -> None:
    """Why D-027's new activity does not break this history (spec §11).

    `record_cycle_kpis` is scheduled only when the cycle context says the
    business's type declares KPI mappings. This history was captured before
    that field existed, so the recorded `load_cycle_context` result does not
    carry it and the workflow re-reads the same False it behaved as then —
    the compatibility hinge D-023 used for `DispatchSequence`, asserted here
    rather than asserted by the replay passing, because a replay that passes
    says nothing about *why*.
    """
    recorded = _recorded_result("load_cycle_context")
    assert "measures_kpis" not in recorded
    assert CycleContext.model_validate(recorded).measures_kpis is False


def test_the_business_in_this_history_still_declares_no_kpi_mappings() -> None:
    """The honesty half of the claim above (D-027.3).

    A default that merely absorbs an old payload would be a compatibility
    shim: the workflow would replay the past correctly and behave differently
    if that same company ran today. It would not. This history belongs to an
    Affiliate company, and Affiliate declares no mappings — its mappings are
    D-027.3's recorded follow-up — so False is not a concession to the
    fixture's age, it is what the platform answers for that business now.
    """
    assert AFFILIATE.kpi_mappings == ()


async def test_measuring_this_cycle_would_have_diverged() -> None:
    """Negative control on the gate itself: a guard that cannot fail is not one.

    The same real workflow against the same real history, with one byte of the
    recorded cycle context flipped so the gate opens. The workflow then issues a
    measurement command the history does not contain and the replayer must
    reject it — which is what proves the two tests above are load-bearing and
    that this file would have caught an ungated `record_cycle_kpis`.

    The committed fixture is not touched: the variant is built in memory, and
    it is deliberately *not* offered as evidence of anything a live run did.
    """
    patched = copy.deepcopy(RAW_HISTORY)
    scheduled = {e["eventId"]: _activity_name(e) for e in EVENTS if e["eventType"] == SCHEDULED}
    for event in patched["events"]:
        attrs = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        if scheduled.get(attrs["scheduledEventId"]) != "load_cycle_context":
            continue
        payload = attrs["result"]["payloads"][0]
        context = json.loads(base64.b64decode(payload["data"]).decode())
        context["measures_kpis"] = True
        payload["data"] = base64.b64encode(json.dumps(context).encode()).decode()

    replayer = Replayer(
        workflows=[BusinessManagerWorkflow],
        data_converter=pydantic_data_converter,
    )
    with pytest.raises(Exception) as caught:
        await replayer.replay_workflow(WorkflowHistory.from_json(WORKFLOW_ID, patched))
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


# ── the measured half: a live Finance history that did record KPIs ─────────


def _finance_history() -> WorkflowHistory:
    """Return the captured Finance history in the form the replayer consumes."""
    return WorkflowHistory.from_json(FINANCE_WORKFLOW_ID, FINANCE_RAW_HISTORY)


def _finance_scheduled_names() -> list[str]:
    """Activity names in the order the Finance history scheduled them."""
    return [_activity_name(e) for e in FINANCE_EVENTS if e["eventType"] == SCHEDULED]


def _finance_recorded_result(activity_name: str, *, occurrence: int = 0) -> dict[str, Any]:
    """Return what one activity returned in the captured Finance run.

    `occurrence` selects which completion, because this history holds three
    cycles: `load_cycle_context` ran before D-027 shipped *and* after, and the
    first one is not the one the measured cycle read.
    """
    scheduled = {
        e["eventId"]: _activity_name(e) for e in FINANCE_EVENTS if e["eventType"] == SCHEDULED
    }
    seen = 0
    for event in FINANCE_EVENTS:
        attrs = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        if scheduled.get(attrs["scheduledEventId"]) != activity_name:
            continue
        if seen != occurrence:
            seen += 1
            continue
        decoded = json.loads(base64.b64decode(attrs["result"]["payloads"][0]["data"]).decode())
        assert isinstance(decoded, dict)
        return decoded
    raise AssertionError(f"{activity_name} has no completion #{occurrence} in this history")


async def test_captured_finance_cycle_replays_without_divergence() -> None:
    """A cycle that measured itself replays command for command (spec §11).

    The D-027 gate's first live test. `record_cycle_kpis` is the newest
    command in the cycle body and the only one behind a condition, so it is
    the one most likely to be issued out of step on recovery — and a Manager
    that diverges on recovery is exactly what D-004 exists to prevent.
    """
    replayer = Replayer(
        workflows=[BusinessManagerWorkflow],
        data_converter=pydantic_data_converter,
    )
    await replayer.replay_workflow(_finance_history())


async def test_the_finance_replay_check_actually_fires() -> None:
    """Negative control, per fixture: a guard that cannot fail is not one.

    The Affiliate history has its own control above. This repeats it for the
    Finance history rather than borrowing that result, because a fixture that
    failed to load, or loaded as an empty event list, would let the replay
    above pass while proving nothing.
    """
    replayer = Replayer(
        workflows=[_DivergentManagerWorkflow],
        data_converter=pydantic_data_converter,
    )
    with pytest.raises(Exception) as caught:
        await replayer.replay_workflow(_finance_history())
    assert "nondeterminism" in str(caught.value).lower()


def test_the_finance_history_actually_measured_a_cycle() -> None:
    """The fixture guard: this history's whole point is the measurement step.

    Without this, a regenerated capture from an unmeasured cycle would still
    replay — and would silently stop covering the one command it was added for.
    """
    assert _finance_scheduled_names().count("record_cycle_kpis") == 1


def test_the_measured_cycle_read_a_context_that_enabled_measurement() -> None:
    """Why the command was issued at all (D-027.3), read off the record.

    `measures_kpis` is a recorded activity result, so replay re-reads the
    answer the platform gave *then*. The first `load_cycle_context` completion
    in this history has no such field — it was captured before D-027 shipped,
    and it is the reason the cycle before this one measured nothing.
    """
    before = _finance_recorded_result("load_cycle_context", occurrence=0)
    assert "measures_kpis" not in before
    assert CycleContext.model_validate(before).measures_kpis is False

    enabling = _finance_recorded_result("load_cycle_context", occurrence=2)
    assert CycleContext.model_validate(enabling).measures_kpis is True


def test_the_recorded_observations_match_the_type_s_declared_mappings() -> None:
    """The honesty half (D-027.2): the numbers came from Finance's own data.

    The activity returns what it wrote, so the recorded result is the audit
    trail for a KPI series. Comparing its keys with `FINANCE.kpi_mappings`
    ties the live figures to the type definition that selected them, rather
    than to whatever the platform happened to measure that day.
    """
    recorded = _finance_recorded_result("record_cycle_kpis")
    assert set(recorded) == {mapping.key for mapping in FINANCE.kpi_mappings}
    assert all(Decimal(value) >= 0 for value in recorded.values())


def test_measurement_ran_after_synthesis_and_before_the_decision_record() -> None:
    """D-027.1's placement, observed rather than asserted against the source.

    After synthesis, so a cycle's own results are already terminal when they
    are counted; before the decision record, so the entry an operator reads is
    written by a cycle that has finished measuring itself.
    """
    ordered = _finance_scheduled_names()
    measured = ordered.index("record_cycle_kpis")
    assert ordered.index("synthesize_results") < measured
    assert measured < len(ordered) - 1 - ordered[::-1].index("record_cycle_decision")


# ── M8-3: the stale snapshot, in the record, and why these still replay ────


def _finance_segments() -> list[list[str]]:
    """Activity names between one `load_cycle_context` and the next.

    Each segment is what the workflow did with the context it had just read —
    which, in the shape these histories were captured under, is one loop
    iteration.
    """
    segments: list[list[str]] = []
    for name in _finance_scheduled_names():
        if name == "load_cycle_context":
            segments.append([])
        elif segments:
            segments[-1].append(name)
    return segments


def test_the_finance_history_records_the_stale_snapshot_defect() -> None:
    """M7-F45 as this history holds it — the defect M8-3's Part 1 removes.

    `measures_kpis` turns from absent to True between two consecutive reads of
    the same workflow: the type gained its mappings while the Manager was
    parked. Because the read happened before the wait, the cycle that ran in
    between planned, dispatched, synthesized, and recorded itself without ever
    measuring — the live run's "cycle 1 measured nothing; cycle 2 measured".

    Kept as an assertion on the fixture rather than as prose in DECISIONS.md
    because it is the evidence the fix is answering, and a re-capture that no
    longer showed it would quietly turn this file's guarantee into a smaller one.
    """
    stale = _finance_recorded_result("load_cycle_context", occurrence=1)
    assert "measures_kpis" not in stale
    fresh = _finance_recorded_result("load_cycle_context", occurrence=2)
    assert CycleContext.model_validate(fresh).measures_kpis is True

    segments = _finance_segments()
    assert "record_cycle_kpis" not in segments[1], "the cycle that ran on the stale read"
    assert segments[2].count("record_cycle_kpis") == 1, "and the one after it, measuring"


@pytest.mark.parametrize("events", [EVENTS, FINANCE_EVENTS], ids=["affiliate", "finance"])
def test_no_captured_context_carries_the_planner_s_targets(events: list[dict[str, object]]) -> None:
    """Why M8-F7's change leaves both histories alone (spec §11).

    The targets a cycle plans against now travel in the cycle context. Every
    context in both histories was recorded before that field existed, so each
    deserialises to `None` — not to an empty tuple — and the workflow plans
    against the targets those runs carried in workflow state, which is what they
    did. The same compatibility hinge D-023 and D-027 used, and the same reason
    it is honest: `None` is "this record has no answer", not "no targets".
    """
    scheduled = {e["eventId"]: _activity_name(e) for e in events if e["eventType"] == SCHEDULED}
    contexts = []
    for event in events:
        attrs = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        if scheduled.get(attrs["scheduledEventId"]) != "load_cycle_context":
            continue
        contexts.append(json.loads(base64.b64decode(attrs["result"]["payloads"][0]["data"])))
    assert contexts, "a history with no context reads would make this vacuous"
    for context in contexts:
        assert "kpi_targets" not in context
        assert CycleContext.model_validate(context).kpi_targets is None


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
