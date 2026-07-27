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
import json
import pathlib
from decimal import Decimal
from typing import Any

import pytest
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
from jarvis.manager.state import CycleOutcome, KpiTargetState, ManagerState, TacticalPlan
from jarvis.manager.types import CycleContext, PlanRequest
from jarvis.manager.workflow import PATCH_POST_WAKE_CONTEXT, BusinessManagerWorkflow

BIZ = BusinessId("biz_0123456789abcdef0123456789abcdef")
CYCLE_ID = "cyc_versioning"
TODAY = 739_900

WORKFLOW_SOURCE = pathlib.Path("jarvis/manager/workflow.py").read_text(encoding="utf-8")
WORKFLOW_TREE = ast.parse(WORKFLOW_SOURCE)

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
    }
)
"""Every activity the Manager workflow may schedule, frozen deliberately."""


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

    def __init__(self, contexts: list[CycleContext], *, patched: bool) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.patched_ids: list[str] = []
        self._contexts = list(contexts)
        self._patched = patched

    async def execute_activity(self, name: str, arg: object = None, **kwargs: object) -> Any:
        assert "start_to_close_timeout" in kwargs, "spec §9: every call is bounded"
        self.calls.append((name, arg))
        if name == "load_cycle_context":
            if not self._contexts:
                raise _ParkedError("the script ran out of contexts")
            return self._contexts.pop(0).model_dump(mode="json")
        if name == "plan_cycle":
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

    async def wait_condition(
        self,
        predicate: Any,
        *,
        timeout: Any = None,  # noqa: ASYNC109 — this mirrors the API being stubbed
    ) -> None:
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
    contexts: list[CycleContext], *, patched: bool, state: ManagerState | None = None
) -> tuple[_Boundary, BusinessManagerWorkflow]:
    """Run the wake loop against a script until the script runs out."""
    boundary = _Boundary(contexts, patched=patched)
    manager = BusinessManagerWorkflow()
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
