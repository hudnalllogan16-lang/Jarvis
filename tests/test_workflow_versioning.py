"""The workflow-versioning convention, and its first worked example (M6-F33).

M6-3 shipped a change to the Manager's live cycle path — an approved action now
executes at the head of the cycle (M6-F31) — by **terminating and restarting the
Manager**. That worked because the only Manager in existence belonged to a
development database. It is recorded as unacceptable for anything running a
business: a Manager parked on its wake timer is a running history, and a worker
whose cycle body issues one more command than that history recorded fails the
parked business on recovery, which is the single failure mode D-004 exists to
prevent.

**The convention.** Any change to what commands the workflow issues on a path a
running execution can still reach ships behind `workflow.patched`, with the id
declared as a `PATCH_*` constant in `jarvis/manager/workflow.py`. Old executions
carry no marker for the id and take the path they actually ran; executions
started since take the new one. Nothing is emulated and no history is edited.

**What this file proves, and how.** The claim has two halves and needs both, or
it is a gate that cannot fail in one direction:

1. *Old histories replay the old path.* Both committed fixtures replay unedited
   against the real workflow (`test_manager_replay.py`), and they do so through
   the old branch — asserted here by the absence of any patch marker in either
   history, which is the SDK's own precondition for `patched()` answering False.
2. *The new path is real and is what a fresh execution runs.* Forcing the gate
   open makes both real histories diverge, so the branch is load-bearing rather
   than decorative; and driving the wake loop across a scripted activity
   boundary shows what the new path does that the old one did not — which is
   M7-F45's fix, the example this convention is being established on.

**Retroactively**, one shipped change would have required this and did not have
it: M6-3's `execute_approved_action` (D-024, M6-F31), an unconditional new
command at the head of any cycle woken by an answered approval — precisely the
change that forced the restart. D-021's `cycle_id`, D-023's dispatch sequence,
and D-027's `record_cycle_kpis` were payload-shaped or gated on a recorded
result absent from older payloads, so they rode the compatibility hinge instead
and each proved it with a fixture. The two mechanisms are not interchangeable:
recorded-result gating works when the platform's *own answer* for that history
is still the old one, and versioning is what remains when it is not.
"""

from __future__ import annotations

import ast
import base64
import json
import pathlib
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from temporalio.activity import _Definition
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from jarvis.capabilities.request import (
    CapabilityResult,
    InvocationStatus,
    ScopedRequest,
)
from jarvis.domain.contract import CapabilityType
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.llm.base import Usage
from jarvis.manager import workflow as workflow_module
from jarvis.manager.activities import DERIVED_CYCLE_KEY, all_manager_activities
from jarvis.manager.state import CycleOutcome, KpiTargetState, ManagerState, TacticalPlan
from jarvis.manager.types import CycleContext, PlanRequest
from jarvis.manager.workflow import (
    PATCH_NOTHING_TO_DO_KPIS,
    PATCH_PAUSED_WAKE_NOTICE,
    PATCH_POST_WAKE_CONTEXT,
    BusinessManagerWorkflow,
)
from jarvis.runtime.activities import all_activities

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")
CYCLE_ID = "cyc_versioning"
RUN_ID = "11e3a4ab-097d-4f33-aef4-0ef25ed82895"
"""A run id of the shape Temporal assigns, for the scripted `workflow.info()`."""

TODAY = 739_900

WORKFLOW_SOURCE = pathlib.Path("jarvis/manager/workflow.py").read_text(encoding="utf-8")
WORKFLOW_TREE = ast.parse(WORKFLOW_SOURCE)
ACTIVITIES_SOURCE = pathlib.Path("jarvis/manager/activities.py").read_text(encoding="utf-8")
"""The other side of the boundary. Read here because M9-7's change is entirely
on it — which is the whole of the argument that it needs no version gate."""

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HISTORIES = {
    "affiliate": ("bm-biz_6f548e12d9b145bfb53ed2e72f764b8b", "manager_cycle_history.json"),
    "finance": ("bm-biz_08122842a3034381abe3726d47464f16", "finance_cycle_history.json"),
}


def _history(name: str) -> WorkflowHistory:
    workflow_id, filename = HISTORIES[name]
    raw = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    return WorkflowHistory.from_json(workflow_id, raw)


def _events(name: str) -> list[dict[str, Any]]:
    _, filename = HISTORIES[name]
    return list(json.loads((FIXTURES / filename).read_text(encoding="utf-8"))["events"])


# ── the convention, enforced on the source ─────────────────────────────────


def _patch_calls() -> list[ast.Call]:
    return [
        node
        for node in ast.walk(WORKFLOW_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "patched"
    ]


def _patch_constants() -> dict[str, str]:
    """Module-level `PATCH_* = "..."` declarations in the workflow module."""
    found: dict[str, str] = {}
    for node in WORKFLOW_TREE.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("PATCH_"):
                assert isinstance(node.value.value, str), f"{target.id} must be a string id"
                found[target.id] = node.value.value
    return found


def test_every_patch_id_is_a_declared_constant() -> None:
    """A patch id typed twice is two cohorts of histories, silently.

    `workflow.patched("post-wake-context")` and
    `workflow.patched("post_wake_context")` are different patches to Temporal
    and the same intent to a reader. Requiring the id to come from a named
    constant makes a typo a NameError at import rather than a divergence on
    somebody's parked Manager months later.
    """
    calls = _patch_calls()
    assert calls, "the convention needs at least its own example to stay honest"
    constants = _patch_constants()
    for call in calls:
        assert len(call.args) == 1, "patched() takes exactly the id"
        arg = call.args[0]
        assert isinstance(arg, ast.Name), "pass the PATCH_* constant, not a literal"
        assert arg.id in constants, f"{arg.id} is not a declared PATCH_* constant"


def test_each_declared_patch_is_used_exactly_once() -> None:
    """One id, one branch. Two branches on one id cannot be versioned apart.

    Also catches the opposite slip: a `PATCH_*` constant left behind after its
    branch was deleted reads as an active version boundary and is not one.
    """
    constants = _patch_constants()
    used = [call.args[0].id for call in _patch_calls() if isinstance(call.args[0], ast.Name)]
    assert sorted(used) == sorted(constants), "every declared patch is used, and used once"
    assert len(set(constants.values())) == len(constants), "two constants share one id"


MANAGER_ACTIVITIES = frozenset(
    {
        "load_cycle_context",
        "execute_approved_action",
        "plan_cycle",
        "prepare_dependent_requests",
        "dispatch_capability",
        "synthesize_results",
        "record_cycle_kpis",
        "request_approval",
        "record_cycle_decision",
        "record_manager_park",
        "record_dropped_wake",
    }
)
"""Every activity the Manager workflow may schedule, frozen deliberately.

`record_manager_park` was added in M8-7 (D-034.1), and the question this
inventory exists to force was asked and answered rather than skipped: it is a
new command, but only on a path *no captured history contains and no live
execution could have survived* — before D-034.1 a context load past its retries
failed the whole workflow, so a history holding one is a terminated execution
that will never be replayed. It therefore rides no version gate, and
`test_no_captured_history_records_a_failed_context_load` is that claim checked
against both fixtures rather than asserted in prose.

`record_dropped_wake` was added in M8-10 (D-035) and the same question got the
opposite answer, which is why the two sit here together. Its branch is also in
no captured history — neither fixture ever read a non-dispatchable context — but
"no fixture" is not "no live execution": a Manager parked on the pause branch is
a perfectly healthy running history, and a paused company is the ordinary state
of one an operator has stopped. So it ships behind `PATCH_PAUSED_WAKE_NOTICE`,
and the evidence for the gate is the scripted pair below rather than a forced
divergence, because a fixture that never reaches the branch cannot diverge on
it."""


def test_the_manager_schedules_only_the_activities_in_this_inventory() -> None:
    """The convention's tripwire: adding a command is a versioned change.

    This test failing is not a defect — it is the question being asked at the
    only moment anyone can answer it. A command added to, removed from, or moved
    on the cycle path changes what a *running* Manager will do on recovery, so
    it ships behind a `PATCH_*` constant (or, when the platform's own answer for
    an old history is still the old one, behind a recorded result the way D-023
    and D-027 did) and is recorded in DECISIONS.md. Update this set in the same
    change, so the next person sees a deliberate edit rather than a green suite.
    """
    scheduled = {
        node.args[0].value
        for node in ast.walk(WORKFLOW_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_activity"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert scheduled == set(MANAGER_ACTIVITIES)


def test_the_worker_registers_every_activity_the_manager_schedules() -> None:
    """The other end of the inventory, which nothing was checking.

    A command the workflow issues and the worker does not implement is not a
    test failure anywhere — it is an activity task that no worker will ever poll
    for, so the Manager waits out its `start_to_close_timeout`, retries, and ends
    the cycle FAILED. Found while adding `record_manager_park` (D-034.1): the
    inventory above would have stayed green with the registration list untouched,
    and the failure would have landed on the one path whose entire purpose is
    keeping a Manager alive when something else has already gone wrong.

    Both registries, because the Manager schedules `dispatch_capability`, which
    `KernelActivities` owns — a per-module check would have declared that one
    missing.
    """
    kernel = cast(Any, object())  # only stored, never used, by either constructor
    registered = {
        _Definition.from_callable(fn).name  # type: ignore[union-attr]
        for fn in [*all_manager_activities(kernel), *all_activities(kernel)]
    }
    assert registered >= MANAGER_ACTIVITIES, sorted(MANAGER_ACTIVITIES - registered)


# ── half one: the captured histories take the old path ─────────────────────


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_no_captured_history_records_a_patch_marker(name: str) -> None:
    """Why both fixtures replay the pre-wake load (spec §11), read off the record.

    `patched()` answers False during replay exactly when the history holds no
    marker for that id. Both were captured before any patch existed, so both
    hold none — the same shape as `measures_kpis` being absent from a pre-D-027
    context, asserted rather than inferred from a green replay, because a replay
    that passes says nothing about which branch it passed through.
    """
    marker_events = [e for e in _events(name) if e["eventType"] == "EVENT_TYPE_MARKER_RECORDED"]
    assert marker_events == []


@pytest.mark.parametrize("name", sorted(HISTORIES))
async def test_forcing_the_post_wake_reload_diverges_the_captured_history(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the version gate is load-bearing, per fixture.

    The same real workflow against the same real history, with only the version
    decision pinned open. The workflow then reads its context a second time
    where the history scheduled `plan_cycle`, and the replayer must reject it.

    Without this, "both fixtures still replay" would be equally true of a patch
    that guards nothing — and a gate that never opens looks exactly like a gate
    that never closes from a green suite. The committed fixtures are not
    touched: the branch is forced in this process, which is also why the replay
    runs unsandboxed here (the sandbox re-imports the module and would not see
    it). The sandboxed, unforced replay is `test_manager_replay.py`'s.
    """
    monkeypatch.setattr(workflow_module, "_reloads_context_after_wake", lambda: True)
    replayer = Replayer(
        workflows=[BusinessManagerWorkflow],
        data_converter=pydantic_data_converter,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    with pytest.raises(Exception) as caught:
        await replayer.replay_workflow(_history(name))
    message = str(caught.value).lower()
    assert "nondeterminism" in message
    assert "load_cycle_context" in message, "diverged somewhere other than the reload"


# ── M8-7: two live-path changes, and why neither is a version boundary ─────
#
# D-033 is not "patch everything"; it says versioning is what remains when
# recorded-result gating is not available, because "the platform's own answer
# for an old history is still the old one" is the cheaper and more honest
# mechanism where it holds. D-034 points 1 and 2 both change the live cycle
# path, and neither one takes a `PATCH_*` id. The two arguments are different
# and both are checked against the real fixtures here rather than asserted in a
# commit message — a patch that guards nothing is the failure this file exists
# to prevent, and so is a change that skipped one it needed.


def _completions(name: str, activity: str) -> list[dict[str, Any]]:
    """Return every payload ``activity`` returned in one captured history."""
    events = _events(name)
    scheduled = {
        e["eventId"]: _activity_name(e)
        for e in events
        if e["eventType"] == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    }
    out: list[dict[str, Any]] = []
    for event in events:
        attrs = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attrs, dict) or scheduled.get(attrs["scheduledEventId"]) != activity:
            continue
        decoded = json.loads(base64.b64decode(attrs["result"]["payloads"][0]["data"]).decode())
        assert isinstance(decoded, dict)
        out.append(decoded)
    return out


def _inputs(name: str, activity: str) -> list[dict[str, Any]]:
    """Return every payload ``activity`` was *given* in one captured history.

    The mirror of `_completions` above, and the side that matters for a change
    which reads an existing field rather than adding a command: what a fresh
    worker would send has to be compared against what these histories recorded
    being sent.
    """
    out: list[dict[str, Any]] = []
    for event in _events(name):
        if _activity_name(event) != activity:
            continue
        attrs = event["activityTaskScheduledEventAttributes"]
        decoded = json.loads(base64.b64decode(attrs["input"]["payloads"][0]["data"]).decode())
        assert isinstance(decoded, dict)
        out.append(decoded)
    return out


def _activity_name(event: dict[str, Any]) -> str:
    attrs = event.get("activityTaskScheduledEventAttributes")
    if not isinstance(attrs, dict):
        return ""
    return str(attrs.get("activityType", {}).get("name", ""))


def _lost_activities(name: str) -> list[str]:
    """Return the activities that ran out of retries in one captured history."""
    events = _events(name)
    scheduled = {
        e["eventId"]: _activity_name(e)
        for e in events
        if e["eventType"] == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    }
    lost: list[str] = []
    for event in events:
        for key in (
            "activityTaskFailedEventAttributes",
            "activityTaskTimedOutEventAttributes",
            "activityTaskCanceledEventAttributes",
        ):
            attrs = event.get(key)
            if isinstance(attrs, dict):
                lost.append(scheduled.get(attrs["scheduledEventId"], "?"))
    return lost


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_no_captured_history_records_a_failed_context_load(name: str) -> None:
    """Why D-034.1's park needs no version gate, read off the record.

    The park adds commands — a `record_manager_park` and a timer — on the branch
    a failed `load_cycle_context` takes. That branch is new, and it is also
    unreachable in every history there is: before D-034.1 a context load past its
    retries failed the whole workflow, so a history containing one belongs to a
    terminated execution that will never be replayed, and neither fixture
    contains one at all.

    Asserted here rather than argued, because "it cannot happen" is exactly the
    kind of claim that stops being true quietly. If a future fixture is captured
    from a Manager that parked, this fails — and the right answer then is a patch
    id, decided with that history in hand.
    """
    assert "load_cycle_context" not in _lost_activities(name)


def test_the_history_that_did_lose_an_activity_lost_planning_instead() -> None:
    """The fixture guard for the claim above: it is not vacuous.

    The Finance history holds a real exhausted activity — `plan_cycle`, the
    M7-F20 credential failure — so "no failed context load" is a statement about
    *which* activity failed and not about a suite that has never seen one. That
    failure is inside the cycle body, which M6-F9 already covered, which is why
    this history replays across it today.
    """
    assert _lost_activities("finance") == ["plan_cycle"]
    assert _lost_activities("affiliate") == []


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_no_captured_plan_result_carries_a_derived_cycle_key(name: str) -> None:
    """Why D-034.2's cycle key needs no version gate either (spec §11).

    The workflow now sends a derived key *into* `plan_cycle`, and still reads the
    id it threads downstream back *out* of the recorded result — the D-023 /
    D-027 compatibility hinge. So a replayed history files synthesis,
    measurement, and its decision entry under the id its own ledger rows and
    audit entries already carry, whatever this worker would have chosen. Changing
    an activity's input payload is not a divergence; substituting a different id
    downstream would have been a silent rewriting of what those runs did.

    Both fixtures are on the old side of the change and in two different ways,
    which is why this is parametrized rather than asserted once: the Affiliate
    history predates D-021 and records no cycle id at all (`.get` is what keeps
    it replayable), and the Finance history records ids the activity minted. A
    derived key ends in `_<ordinal>` and a minted id does not, so the shape is
    the tell.
    """
    recorded = [payload.get("cycle_id") for payload in _completions(name, "plan_cycle")]
    assert recorded, "a history with no planning result would make this vacuous"
    for cycle_id in recorded:
        assert cycle_id is None or not DERIVED_CYCLE_KEY.fullmatch(cycle_id)
    assert 'plan_payload.get("cycle_id")' in WORKFLOW_SOURCE, (
        "the recorded answer is the one that travels downstream, not the derived key"
    )


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_no_captured_history_ever_read_a_paused_context(name: str) -> None:
    """Why D-035's gate gets no fixture control, stated as a fact about them.

    `record_dropped_wake` is issued on the branch a non-dispatchable context
    takes. Every context either history recorded was dispatchable — both belong
    to companies that were running — so forcing that gate open changes nothing
    about either replay, and "both fixtures still replay" would be true of a
    patch guarding nothing.

    That is an argument for the scripted control below, not against the patch.
    The park's version of this question (`record_manager_park`) could be
    answered by the fixtures because a history holding a failed context load
    belongs to an execution that was killed by it; a history holding a *paused*
    context belongs to an execution that is alive, parked, and waiting to be
    resumed. It is simply not one of the two we captured.
    """
    contexts = _completions(name, "load_cycle_context")
    assert contexts, "a history with no context reads would make this vacuous"
    assert all(context.get("dispatchable") is True for context in contexts)


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_no_captured_history_ever_continued_as_new(name: str) -> None:
    """Why M8-F87's reset needs no version gate, read off the record.

    The reset changes what `continue_as_new` is *given*, not whether it is
    issued or when — the condition on `CYCLES_BEFORE_CONTINUATION` is untouched
    — so the command sequence a history can be checked against is the same
    before and after. That is the recorded-result side of D-033's own rule
    rather than the versioning side, and it is checked here rather than argued
    in a commit message: neither fixture reaches a continuation at all, so
    nothing in either replay is on the changed line.

    The live consumers of the ordinal are two and both survive it. The cycle key
    (D-034.2) namespaces by run id, which `continue_as_new` reassigns, so a reset
    ordinal cannot collide across generations — asserted in
    `tests/test_manager_resilience.py`. The daily allowance is a different pair
    of fields and is carried over untouched. If a fixture is ever captured from a
    Manager that continued, this fails, and the right answer then is to look
    again with that history in hand.
    """
    assert not [event for event in _events(name) if "ContinuedAsNew" in str(event["eventType"])]
    assert "workflow.continue_as_new(state.continued())" in WORKFLOW_SOURCE, (
        "the ordinal resets where the generation does"
    )


# ── M9-7: the failed round now notifies, and why that is not a boundary ────


def test_a_captured_history_does_hold_a_failed_cycle() -> None:
    """Read off the record, because the packet's premise said otherwise.

    M9-7 was dispatched believing neither fixture held a `FAILED` cycle and
    asked for that to be verified. It is false: the Finance history's first
    recorded round is `outcome: failed` — the M7-F20 credential failure, whose
    exhausted `plan_cycle` is already pinned above — so `_end_in_failure` is
    not a branch that only fresh executions reach. It is a branch a captured,
    replayed history takes.

    That makes the "no new command" claim below load-bearing rather than
    convenient: if M9-7 had put one more `execute_activity` on this path, this
    fixture is what would have caught it.
    """
    outcomes = [payload["outcome"] for payload in _inputs("finance", "record_cycle_decision")]
    assert "failed" in outcomes
    assert "failed" not in [
        payload["outcome"] for payload in _inputs("affiliate", "record_cycle_decision")
    ], "one history on each side of the branch, so neither claim is about a single shape"


@pytest.mark.parametrize("name", sorted(HISTORIES))
def test_the_unfinished_round_notice_reads_a_field_these_histories_already_sent(
    name: str,
) -> None:
    """Why M9-F118's notice needs no version gate (D-033's own rule).

    The notice is raised *inside* `record_cycle_decision`, off the `outcome`
    the payload has carried since the activity existed — asserted here per
    fixture rather than assumed. So the workflow issues exactly the commands it
    issued before: same activity, same call site, same arguments. There is no
    changed command for a `PATCH_*` id to gate, and a patch that guards nothing
    is the failure this file exists to prevent.

    The recorded-result side holds too, and in the direction that matters. A
    replayed history does not re-run its activities, so no captured round
    raises a notice on replay — an operator is not told today about a round
    that failed in June. A *running* Manager, though, gains the notice on its
    next real failure rather than at its next continuation, which is the point:
    the three live Managers that were silent on the morning of M9-F118 are the
    ones this has to reach.
    """
    payloads = _inputs(name, "record_cycle_decision")
    assert payloads, "a history with no decision entries would make this vacuous"
    for payload in payloads:
        assert "outcome" in payload
    assert 'payload["outcome"]' in ACTIVITIES_SOURCE, (
        "the notice is chosen from the recorded outcome, not from a new field"
    )


def test_the_decision_record_s_result_is_not_read() -> None:
    """Why the activity may now return a pair instead of an id (spec §11).

    `record_cycle_decision` returns what the park's does — the decision id and
    whether an operator was told — where it used to return a bare string. Every
    captured history holds the old shape, and a replay hands the recorded
    result straight back to the workflow. That is safe for exactly one reason,
    pinned here: the call site discards it. A workflow that parsed this result
    would be reading a string where it now expects a mapping, on the histories
    of the three Managers this change exists for.
    """
    record = next(
        node
        for node in ast.walk(WORKFLOW_TREE)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_record"
    )
    scheduled = [
        node
        for node in ast.walk(record)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_activity"
    ]
    assert len(scheduled) == 1, "one command, the one this helper exists to issue"
    assert not [node for node in ast.walk(record) if isinstance(node, ast.Assign | ast.Return)], (
        "the recorded result is discarded, which is what makes its shape free to change"
    )


def test_the_failed_round_path_issues_no_command_of_its_own() -> None:
    """The structural half of the claim above, on the source rather than a history.

    `_end_in_failure` records through `_record`, the same helper every healthy
    outcome uses, and takes no `workflow.patched` decision of its own. Pinned
    because the tempting version of this change — a second activity beside the
    entry, or a version gate around it — is exactly what would have split one
    cohort of histories in two, and the Finance fixture above proves there is a
    cohort here to split.
    """
    failure_path = next(
        node
        for node in ast.walk(WORKFLOW_TREE)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_end_in_failure"
    )
    calls = [
        node.func.attr
        for node in ast.walk(failure_path)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "execute_activity" not in calls
    assert "patched" not in calls
    assert "_record" in calls


def test_the_two_fixtures_straddle_d_021_s_own_hinge() -> None:
    """The guard on the test above: neither case is imaginary.

    One history from before the id existed, one from after — so "no derived key
    in either" is a statement about two real shapes rather than about a single
    fixture that happens to be old.
    """
    assert [p.get("cycle_id") for p in _completions("affiliate", "plan_cycle")] == [None]
    finance = [p.get("cycle_id") for p in _completions("finance", "plan_cycle")]
    assert finance and all(isinstance(c, str) and c.startswith("cyc_") for c in finance)


# ── half two: what a fresh execution does instead ──────────────────────────


def _ctx(**overrides: Any) -> CycleContext:
    """One business's snapshot, with only what a test is about spelled out."""
    fields: dict[str, Any] = {
        "business_id": BIZ,
        "display_name": "Portfolio Watch",
        "dispatchable": True,
        "schedule_interval_seconds": 3600,
        "max_cycles_per_day": 48,
        "wake_cycle_ceiling_usd": Decimal("2.00"),
        "day_ordinal": TODAY,
        "measures_kpis": False,
    }
    return CycleContext(**(fields | overrides))


class _ParkedError(Exception):
    """The scripted Manager reached a wait nothing in the script will end."""


class _Boundary:
    """Scripted activity boundary for the wake loop itself.

    The loop is the part `_run_cycle`-level tests cannot reach: everything the
    other Manager tests script starts *after* the wake, and the whole of M7-F45
    is about which side of the wake a read happens on. Replay covers the shape
    against real histories; this covers the branch a fresh execution takes,
    which no captured history contains yet.

    `contexts` is consumed one per `load_cycle_context`, so a test says what the
    platform answers at each read and the workflow decides which reads happen.
    Running out ends the run: the script has nothing left to say.
    """

    def __init__(
        self, contexts: list[CycleContext], *, patched: bool, dispatch: bool = True
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.patched_ids: list[str] = []
        self._contexts = list(contexts)
        self._patched = patched
        self._dispatch = dispatch
        """Whether the scripted plan proposes anything (M7-F32). False takes the
        NOTHING_TO_DO branch instead of the ordinary dispatch one — the only way
        to drive that branch, since no captured history ever takes it either."""

    async def execute_activity(self, name: str, arg: object = None, **kwargs: object) -> Any:
        assert "start_to_close_timeout" in kwargs, "spec §9: every call is bounded"
        self.calls.append((name, arg))
        if name == "load_cycle_context":
            if not self._contexts:
                raise _ParkedError("the script ran out of contexts")
            return self._contexts.pop(0).model_dump(mode="json")
        if name == "plan_cycle":
            if not self._dispatch:
                return {
                    "cycle_id": CYCLE_ID,
                    "plan": TacticalPlan(rationale="Nothing needed doing.").model_dump(mode="json"),
                    "requests": [],
                }
            request = ScopedRequest(
                invocation_id=InvocationId("inv_versioning"),
                declared_business_id=BIZ,
                capability=CapabilityType.RESEARCH,
                prompt_ref="finance.daily",
                budget_allocation_usd=Decimal("0.50"),
                cycle_id=CYCLE_ID,
            )
            return {
                "cycle_id": CYCLE_ID,
                "plan": TacticalPlan(rationale="Check the portfolio.").model_dump(mode="json"),
                "requests": [request.model_dump(mode="json")],
            }
        if name == "dispatch_capability":
            assert isinstance(arg, ScopedRequest)
            return CapabilityResult(
                invocation_id=arg.invocation_id,
                business_id=BIZ,
                capability=arg.capability,
                status=InvocationStatus.SUCCEEDED,
                output="a report",
                usage=Usage(cost_usd=Decimal("0.10")),
            ).model_dump(mode="json")
        if name == "synthesize_results":
            return {"summary": "Looked at the portfolio.", "action": None}
        if name == "record_cycle_kpis":
            return {"reports_delivered": "1"}
        return "dec_versioning"

    def patched(self, patch_id: str) -> bool:
        self.patched_ids.append(patch_id)
        return self._patched

    def info(self) -> Any:
        """Return the run facts the loop derives its cycle key from (D-034.2).

        A fixed run id, because the point of the key is that it is a *function*
        of the run and the cycle ordinal — a script handing back a fresh one per
        call would hide exactly the property being scripted.
        """
        return SimpleNamespace(run_id=RUN_ID)

    async def wait_condition(
        self,
        predicate: Any,
        *,
        timeout: Any = None,  # noqa: ASYNC109 — this mirrors the API being stubbed
    ) -> None:
        if predicate():
            # The real one returns at once when its condition already holds,
            # which is how a reason signalled before the wait began reaches the
            # branch that drops it (D-035).
            return
        if timeout is None:
            # Parked on a signal with no scheduled wake — the end of the script.
            raise _ParkedError("parked on a signal")
        raise TimeoutError  # the schedule fired, which is what `_await_wake` reads

    def scheduled(self) -> list[str]:
        return [name for name, _ in self.calls]

    def first_cycle(self) -> list[str]:
        """Activity names up to and including the first cycle's own record."""
        names = self.scheduled()
        return names[: names.index("record_cycle_decision") + 1]


async def _drive(
    contexts: list[CycleContext],
    *,
    patched: bool,
    state: ManagerState | None = None,
    signals: list[str] | None = None,
    dispatch: bool = True,
) -> tuple[_Boundary, BusinessManagerWorkflow]:
    """Run the wake loop against a script until the script runs out.

    `signals` are delivered before the run begins, which is what a reason that
    arrived while the Manager was between waits looks like from inside — and the
    only way a paused company's Manager gets one at all, since the scheduler
    signals ACTIVE companies (`dispatch_events`) and a pause can land after the
    claim.

    `dispatch=False` scripts a plan that proposes nothing, driving the
    NOTHING_TO_DO branch (M7-F32) instead of the ordinary one.
    """
    boundary = _Boundary(contexts, patched=patched, dispatch=dispatch)
    manager = BusinessManagerWorkflow()
    for reason in signals or []:
        manager.wake(reason)
    original = workflow_module.workflow
    workflow_module.workflow = boundary  # type: ignore[assignment]
    try:
        with pytest.raises(_ParkedError):
            await manager.run(state or ManagerState(business_id=BIZ))
    finally:
        workflow_module.workflow = original  # type: ignore[assignment]
    return boundary, manager


async def test_a_type_upgrade_applies_on_the_first_cycle_after_it() -> None:
    """M7-F45's fix, stated as the behaviour it was reported as.

    The script is the live sequence the finance history recorded: a context read
    while the type declared no mappings, an upgrade landing during the wait, and
    then a cycle. The cycle measures itself, because the snapshot it reasons on
    is the one taken when it began (D-021) and not the one taken before it
    waited.
    """
    boundary, _ = await _drive([_ctx(measures_kpis=False), _ctx(measures_kpis=True)], patched=True)
    assert boundary.patched_ids == [PATCH_POST_WAKE_CONTEXT]
    assert boundary.first_cycle().count("load_cycle_context") == 2
    assert "record_cycle_kpis" in boundary.first_cycle()


async def test_on_the_old_path_the_upgrade_costs_a_whole_extra_cycle() -> None:
    """The defect itself, pinned: M7-F45 as the live run observed it.

    Same script, version gate closed — which is what every history captured
    before M8-3 replays. The first cycle after the upgrade measures nothing and
    the second one measures, which is exactly what the M7-3c live run reported
    ("cycle 1 measured nothing; cycle 2 measured").

    Kept as a test rather than deleted with the defect, because it is the only
    thing that distinguishes a version gate that preserves old behaviour from
    one that quietly does nothing.
    """
    boundary, _ = await _drive([_ctx(measures_kpis=False), _ctx(measures_kpis=True)], patched=False)
    assert boundary.first_cycle().count("load_cycle_context") == 1
    assert "record_cycle_kpis" not in boundary.first_cycle()
    assert "record_cycle_kpis" in boundary.scheduled(), "measured, but one cycle late"


async def test_the_cycle_is_counted_against_the_day_it_actually_ran() -> None:
    """Audit F-B's second half: `day_ordinal` is the wake accounting's whole
    idea of today.

    A Manager that reads the date, waits an hour, and then records the cycle
    against the date it read can cross midnight without the daily allowance
    noticing — the count resets a wake period early. The recorded day is now the
    one taken when the cycle began.
    """
    boundary, manager = await _drive(
        [_ctx(day_ordinal=TODAY), _ctx(day_ordinal=TODAY + 1)], patched=True
    )
    state = manager.current_state()
    assert state is not None
    assert state.day_ordinal == TODAY + 1
    assert boundary.first_cycle().count("plan_cycle") == 1


async def test_the_daily_allowance_is_read_after_the_wake_too() -> None:
    """The other half of the same snapshot: an allowance lowered during the wait.

    D-021's daily wake allowance is `max_cycles_per_day` compared against the
    Manager's own count for that day. Read before the wait, a lowering an
    operator made while the Manager was parked would not bind until the round
    after next.
    """
    already_busy = ManagerState(business_id=BIZ, cycles_today=3, day_ordinal=TODAY)
    boundary, manager = await _drive(
        [_ctx(max_cycles_per_day=48), _ctx(max_cycles_per_day=3)],
        patched=True,
        state=already_busy,
    )
    cycle = manager.last_cycle()
    assert cycle is not None
    assert cycle.outcome is CycleOutcome.NOTHING_TO_DO
    assert "plan_cycle" not in boundary.scheduled()


def _target(value: str) -> KpiTargetState:
    return KpiTargetState(key="reports_delivered", target_value=Decimal(value), operator_label="R")


async def test_a_changed_target_reaches_the_very_next_cycle_s_planning() -> None:
    """M8-F7: the planner works to the contract's targets, not to a keepsake.

    `ManagerState` is seeded with the contract's targets when the Manager
    starts and then carries them across every cycle and every `continue_as_new`
    — up to a hundred cycles. No contract-refresh path exists yet (M7-F24), so
    the drift has never been visible; the moment one ships, every operator-facing
    number would move and the planner would keep working to the old figures.

    Loading them with the rest of the post-wake snapshot means the first cycle
    after a change plans against it, which is the same property this packet's
    Part 1 establishes for the rest of the context.
    """
    started_with = ManagerState(business_id=BIZ, kpi_targets=(_target("2"),))
    boundary, _ = await _drive(
        [_ctx(kpi_targets=(_target("2"),)), _ctx(kpi_targets=(_target("9"),))],
        patched=True,
        state=started_with,
    )
    planned = boundary.calls[boundary.scheduled().index("plan_cycle")][1]
    assert isinstance(planned, PlanRequest)
    assert [t.target_value for t in planned.kpi_targets] == [Decimal("9")]


async def test_a_context_that_carries_no_targets_leaves_the_carried_ones_alone() -> None:
    """The replay hinge for M8-F7, and why `None` is not `()` (spec §11).

    A history captured before this field carries no answer, so the workflow must
    keep planning against the targets it was started with — which is what those
    histories recorded. An empty tuple is a different statement: a live context
    saying this business has no targets set. Collapsing the two would make a
    future refresh unable to express the removal of the last target, and would
    make this the compatibility shim that D-027's default deliberately is not.
    """
    started_with = ManagerState(business_id=BIZ, kpi_targets=(_target("2"),))
    carried, _ = await _drive([_ctx(), _ctx()], patched=True, state=started_with)
    planned = carried.calls[carried.scheduled().index("plan_cycle")][1]
    assert isinstance(planned, PlanRequest)
    assert [t.target_value for t in planned.kpi_targets] == [Decimal("2")]

    cleared, _ = await _drive(
        [_ctx(kpi_targets=()), _ctx(kpi_targets=())], patched=True, state=started_with
    )
    emptied = cleared.calls[cleared.scheduled().index("plan_cycle")][1]
    assert isinstance(emptied, PlanRequest)
    assert emptied.kpi_targets == ()


# ── M8-10: D-035's gate, proved where a fixture cannot reach ──────────────


def _dropped(boundary: _Boundary) -> list[Any]:
    """Every payload the loop sent to `record_dropped_wake`."""
    return [arg for name, arg in boundary.calls if name == "record_dropped_wake"]


async def test_a_pause_reports_the_answered_approval_it_dropped() -> None:
    """D-035, stated as the behaviour M8-F45 was reported as.

    An operator answers a request, the company is paused before the answer
    reaches its Manager, and the Manager drops the reason because "Paused by
    you" means nothing happens. The answer itself is not lost — the approval row
    is untouched, and resume plus the next wake still acts on it (D-006) — but
    until now nothing told the operator that their answer was sitting there. Now
    the drop is reported, with the kind it was, before the queue is cleared.
    """
    boundary, _ = await _drive([_ctx(dispatchable=False)], patched=True, signals=["approval:apr_9"])

    assert _dropped(boundary) == [
        {"business_id": BIZ, "reason_kind": "approval", "reason_ref": "apr_9"}
    ]
    assert boundary.patched_ids == [PATCH_PAUSED_WAKE_NOTICE]


async def test_on_the_old_path_the_dropped_answer_is_silent() -> None:
    """The defect itself, pinned: the silent drop D-035 calls today's behaviour.

    Same script, version gate closed — which is what a Manager parked on a pause
    when this shipped replays. Kept rather than deleted with the defect, because
    it is the only thing that distinguishes a version gate that preserves old
    behaviour from one that quietly does nothing, and no captured history can
    make that distinction for this branch.
    """
    boundary, _ = await _drive(
        [_ctx(dispatchable=False)], patched=False, signals=["approval:apr_9"]
    )

    assert _dropped(boundary) == []
    assert boundary.scheduled() == ["load_cycle_context", "load_cycle_context"], (
        "the old path reads, waits, drops, and reads again"
    )


async def test_every_actionable_reason_is_reported_not_only_approvals() -> None:
    """The owner's breadth: an approval "or other actionable wake reason".

    A Manager's signals are an answered approval or a bus event this company
    subscribed to, and each of the latter means work it would have responded to
    arrived while it was stopped. The kind travels so the notice can say which —
    "you answered a request" and "a piece of work finished" lead an operator to
    different decisions, and one sentence covering both would be the vague copy
    §12.5 exists to prevent.
    """
    boundary, _ = await _drive(
        [_ctx(dispatchable=False)],
        patched=True,
        signals=["capability.result_returned", "approval:apr_9"],
    )

    assert [payload["reason_kind"] for payload in _dropped(boundary)] == [
        "capability.result_returned",
        "approval",
    ]
    assert [payload["reason_ref"] for payload in _dropped(boundary)] == ["", "apr_9"]


async def test_one_delivery_slip_does_not_become_two_notices() -> None:
    """A-002 is at-least-once per consumer, so a repeat is expected, not a bug.

    Deduplicated in the workflow rather than left to the activity, because the
    cheap fix is the one that never issues the second command — and a command
    issued is a command a replay has to reissue forever.
    """
    boundary, _ = await _drive(
        [_ctx(dispatchable=False)],
        patched=True,
        signals=["approval:apr_9", "approval:apr_9"],
    )

    assert len(_dropped(boundary)) == 1


async def test_a_pause_that_lands_mid_wait_reports_what_it_drops_too() -> None:
    """The second drop site, which reads like the first and was just as silent.

    M8-F41 taught the loop to re-check `dispatchable` after the wake, so a pause
    landing while a Manager waited no longer buys a paid planning round. The
    reasons that woke it are already out of the queue by then, so that branch
    drops them exactly as the branch above does — and D-035 is about the drop,
    not about which line of the loop performed it.
    """
    boundary, _ = await _drive(
        [_ctx(), _ctx(dispatchable=False)], patched=True, signals=["approval:apr_9"]
    )

    assert [payload["reason_kind"] for payload in _dropped(boundary)] == ["approval"]
    assert "plan_cycle" not in boundary.scheduled(), "and still no round is planned"


async def test_a_running_company_reports_nothing() -> None:
    """Negative control. A report that fired on every wake would pass every test
    above and put a notice in the operator's queue for every ordinary round of
    work a healthy company does."""
    boundary, _ = await _drive([_ctx(), _ctx()], patched=True, signals=["approval:apr_9"])

    assert _dropped(boundary) == []
    assert "plan_cycle" in boundary.scheduled(), "it ran the cycle instead"


async def test_a_business_paused_during_the_wait_does_not_plan_a_round() -> None:
    """The dispatchable half, now checked on the side of the wake that decides.

    Pausing a company while its Manager is parked used to leave one already-
    granted round: the loop had read `dispatchable` before the wait and did not
    look again. The activities re-check lifecycle themselves, so this was never
    an authorization hole (audit F-B) — it was a planning call, and the model
    spend behind it, for a company an operator had stopped.
    """
    boundary, _ = await _drive([_ctx(), _ctx(dispatchable=False)], patched=True)
    assert boundary.scheduled().count("load_cycle_context") == 3, (
        "the wake read, the reload that saw the pause, and the loop parking"
    )
    assert "plan_cycle" not in boundary.scheduled()


# ── M8-5: D-027 amendment pass, M7-F32's gate ───────────────────────────────


async def test_a_nothing_to_do_cycle_measures_itself_when_the_type_declares_mappings() -> None:
    """M7-F32's fix, stated as the behaviour it was reported as.

    A plan that proposes nothing still runs `record_cycle_kpis` for a type
    that measures itself, between the decision the cycle just made and the
    entry it writes to explain it — the same command a dispatching cycle
    issues, on the one branch that used to skip it.

    Two contexts, not one: `patched=True` also opens `PATCH_POST_WAKE_CONTEXT`
    (both patches ship together on every execution started since M8-3), so the
    loop reads context once before the wait and again after it before it
    plans — the same shape `test_a_type_upgrade_applies_on_the_first_cycle_
    after_it` scripts. Only the second (post-wake) read is what planning
    reasons from.
    """
    boundary, _ = await _drive([_ctx(), _ctx(measures_kpis=True)], patched=True, dispatch=False)
    assert PATCH_NOTHING_TO_DO_KPIS in boundary.patched_ids
    first_cycle = boundary.first_cycle()
    assert "record_cycle_kpis" in first_cycle
    assert first_cycle.index("plan_cycle") < first_cycle.index("record_cycle_kpis")
    assert first_cycle.index("record_cycle_kpis") < first_cycle.index("record_cycle_decision")


async def test_on_the_old_path_a_nothing_to_do_cycle_measures_nothing() -> None:
    """The defect itself, pinned: what every history captured before this ships
    replays. Kept rather than deleted with the defect, for the same reason the
    other patches' negative branches are: it is the only thing that
    distinguishes a version gate that preserves old behaviour from one that
    quietly does nothing, and no captured history reaches this branch to make
    that distinction for itself.
    """
    boundary, _ = await _drive([_ctx(measures_kpis=True)], patched=False, dispatch=False)
    assert "record_cycle_kpis" not in boundary.first_cycle()


async def test_a_nothing_to_do_cycle_for_an_unmapped_type_still_measures_nothing() -> None:
    """Negative control: the gate opening is not the same question as D-027.3's.

    `measures_kpis=False` is what a type declaring no `kpi_mappings` looks
    like from the workflow's side (`CycleContext`, D-027.3). Opening
    `PATCH_NOTHING_TO_DO_KPIS` must not measure a type that was never asking
    to be measured at all — the two gates answer different questions and a
    fix to one must not quietly answer the other.
    """
    boundary, _ = await _drive([_ctx(), _ctx(measures_kpis=False)], patched=True, dispatch=False)
    assert "record_cycle_kpis" not in boundary.first_cycle()
