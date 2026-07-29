"""Sweep containment and connectivity observability (design
OPERATIONAL-RUNTIME.md Part 5.2/5.3, M10-F5/M10-F6 residual/M10-F9; packet
P0-E). `run_scheduler`'s own interval (M9-F92, design Part 4.6) is proven at
the bottom, with the scripted-loop harness `test_executive_runner.py` already
uses for `run_executive`.

Two properties `Scheduler.sweep` did not have before this packet, both the
M6-F9 family applied to a timer rather than a workflow activity:

- **Per-step containment (design 5.3).** Before this, `_renotify`,
  `_expire_and_pause` and `_reconcile_reservations` shared one transaction
  and one exception unwound all three plus the two steps that followed
  (`ManagerLifecycle.reconcile`, `dispatch_events`) — a failing re-notify
  silently cancelled Manager reconciliation for the whole tick. Each named
  step (`timers`, `reconcile`, `managers_started`, `events`) now gets its own
  try/except and, where it writes, its own transaction.
- **Transition-deduped connectivity logging (design 5.2).** Before this,
  `ManagerLifecycle.reconcile` and `dispatch_events` each called
  `kernel.temporal_client()` independently and logged nothing themselves
  when it returned `None`. `Scheduler` now remembers reachability across
  sweeps and logs only on transition, plus a periodic heartbeat while an
  outage continues — the "states not alerts" discipline D-046 states for the
  Executive, applied here to the scheduler's own read of Temporal.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

import jarvis.runtime.worker as worker
import jarvis.scheduler.service as scheduler_service
from jarvis.budget.ledger import RESERVED
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.events.bus import Event
from jarvis.events.types import APPROVAL_DECIDED
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import new_event_id
from jarvis.persistence.models import Base, BudgetLedgerRow
from jarvis.scheduler.service import (
    ORPHANED_RESERVATION_AGE,
    TEMPORAL_OUTAGE_HEARTBEAT_SWEEPS,
    Scheduler,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
LOGGER_NAME = "jarvis.scheduler.service"


# ── SchedulerSettings: the interval this timer reads (M9-F92, design 4.6) ───


def test_sweep_interval_defaults_to_300_seconds() -> None:
    from jarvis.kernel.config import SchedulerSettings

    assert SchedulerSettings().sweep_interval_seconds == 300


def test_sweep_interval_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SCHEDULER__SWEEP_INTERVAL_SECONDS", "45")
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.scheduler.sweep_interval_seconds == 45


class _StubProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:  # pragma: no cover - unused
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    """A real Kernel over one shared in-memory connection. Temporal
    reachability is controlled per test by monkeypatching `temporal_client`
    directly, the same pattern `test_manager_start_state.py` and
    `test_reservation_reconcile.py` already use."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(
        Settings(llm=LLMSettings(model="stub-model"), _env_file=None),  # type: ignore[call-arg]
        engine=engine,
        provider=_StubProvider(),  # type: ignore[arg-type]
    )
    yield built
    await built.aclose()


def _reachable(kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Temporal client is available. A bare sentinel is enough: with no
    ACTIVE businesses registered, neither `ManagerLifecycle.reconcile` nor
    `dispatch_events` ever calls a method on it."""

    async def _client() -> object:
        return object()

    monkeypatch.setattr(kernel, "temporal_client", _client)


def _unreachable(kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none() -> None:
        return None

    monkeypatch.setattr(kernel, "temporal_client", _none)


async def _held_reservation(kernel: PlatformKernel) -> None:
    """One orphaned reservation, old enough for the age backstop alone."""
    async with kernel.services() as svc:
        svc.session.add(
            BudgetLedgerRow(
                business_id="biz_x",
                invocation_id=None,
                cycle_id="cyc_x",
                amount_usd=Decimal("0.10"),
                state=RESERVED,
                recorded_at=NOW - ORPHANED_RESERVATION_AGE,
            )
        )


# ── per-step containment (design 5.3) ────────────────────────────────────────


async def test_a_failing_timers_step_does_not_stop_reservation_reconciliation(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Before this fix `_renotify`/`_expire_and_pause` and
    `_reconcile_reservations` shared one transaction, so a failing renotify
    silently rolled the reservation release back too. Proven here by making
    the timers step raise and checking the reconcile step still ran."""
    _reachable(kernel, monkeypatch)
    await _held_reservation(kernel)
    scheduler = Scheduler(kernel)

    async def _boom(_moment: datetime) -> tuple[int, int, tuple[str, ...]]:
        raise RuntimeError("boom — a transient failure, contained")

    monkeypatch.setattr(scheduler, "_timers_step", _boom)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    report = await scheduler.sweep(now=NOW)

    assert report.renotified == 0
    assert report.expired == 0
    assert report.paused == ()
    assert report.reservations_released == 1
    assert any(
        "sweep step failed" in r.message and r.context["step"] == "timers"  # type: ignore[attr-defined]
        for r in caplog.records
    )


async def test_a_failing_reconcile_step_does_not_stop_manager_reconciliation(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The reservation step failing must not cancel `managers_started` or
    `events` — proven by a stub `ManagerLifecycle.reconcile` that would only
    be reached if the sweep kept going past the failure."""
    _reachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    async def _boom(_moment: datetime) -> int:
        raise RuntimeError("boom — a transient failure, contained")

    monkeypatch.setattr(scheduler, "_reconcile_step", _boom)

    class _StubLifecycle:
        def __init__(self, _kernel: object) -> None:
            pass

        async def reconcile(self) -> int:
            return 3

    monkeypatch.setattr(scheduler_service, "ManagerLifecycle", _StubLifecycle)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    report = await scheduler.sweep(now=NOW)

    assert report.reservations_released == 0
    assert report.managers_started == 3
    assert any(
        "sweep step failed" in r.message and r.context["step"] == "reconcile"  # type: ignore[attr-defined]
        for r in caplog.records
    )


async def test_a_failing_managers_started_step_does_not_stop_event_dispatch(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _reachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    async def _boom(_reachable_flag: bool) -> int:
        raise RuntimeError("boom — a transient failure, contained")

    monkeypatch.setattr(scheduler, "_managers_started_step", _boom)

    events_called = {"n": 0}

    async def _events(_reachable_flag: bool) -> int:
        events_called["n"] += 1
        return 0

    monkeypatch.setattr(scheduler, "_events_step", _events)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    report = await scheduler.sweep(now=NOW)

    assert report.managers_started == 0
    assert events_called["n"] == 1
    assert any(
        "sweep step failed" in r.message and r.context["step"] == "managers_started"  # type: ignore[attr-defined]
        for r in caplog.records
    )


async def test_a_failing_events_step_is_contained(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The last step in sweep order: a failure here must not raise out of
    `sweep()` itself, so the caller (`run_scheduler`) still gets a report."""
    _reachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    async def _boom(_reachable_flag: bool) -> int:
        raise RuntimeError("boom — a transient failure, contained")

    monkeypatch.setattr(scheduler, "_events_step", _boom)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    report = await scheduler.sweep(now=NOW)

    assert report.woken == 0
    assert any(
        "sweep step failed" in r.message and r.context["step"] == "events"  # type: ignore[attr-defined]
        for r in caplog.records
    )


# ── connectivity: skip rather than double-fetch when unreachable ────────────


async def test_managers_started_and_events_are_skipped_when_unreachable(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Scheduler` fetches `temporal_client()` once per sweep for its own
    connectivity read; when it is `None`, both steps that need it are
    short-circuited to 0 rather than each paying for (and separately
    logging) their own failed connection attempt."""
    _unreachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    report = await scheduler.sweep(now=NOW)

    assert report.managers_started == 0
    assert report.woken == 0


# ── transition-deduped connectivity logging (design 5.2, D-046 family) ──────


async def test_first_sweep_unreachable_logs_once(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An outage already in progress when the scheduler starts (M10-F12's own
    shape) must not be silent just because it predates this process."""
    _unreachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    await scheduler.sweep(now=NOW)

    unreachable_lines = [r for r in caplog.records if "unreachable" in r.message]
    assert len(unreachable_lines) == 1


async def test_an_ongoing_outage_logs_nothing_between_transitions(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Design 5.2 point 1's whole point: a long outage produces two lines and
    not one per sweep. Run fewer sweeps than the heartbeat cadence and expect
    exactly the one line the first sweep already wrote."""
    _unreachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    for _ in range(TEMPORAL_OUTAGE_HEARTBEAT_SWEEPS - 1):
        await scheduler.sweep(now=NOW)

    unreachable_lines = [r for r in caplog.records if "unreachable" in r.message]
    assert len(unreachable_lines) == 1


async def test_a_long_outage_gets_a_heartbeat_every_nth_sweep(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Design 5.2 point 2: a long outage reads as *ongoing*, not only *begun*."""
    _unreachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    for _ in range(TEMPORAL_OUTAGE_HEARTBEAT_SWEEPS):
        await scheduler.sweep(now=NOW)

    unreachable_lines = [r for r in caplog.records if "unreachable" in r.message]
    # One line for the initial observation, one for the Nth-sweep heartbeat.
    assert len(unreachable_lines) == 2
    assert "still unreachable" in unreachable_lines[-1].message


async def test_recovery_after_an_outage_logs_exactly_one_line(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _unreachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)
    await scheduler.sweep(now=NOW)  # down

    _reachable(kernel, monkeypatch)
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    await scheduler.sweep(now=NOW)  # recovers

    recovery_lines = [r for r in caplog.records if "reachable again" in r.message]
    assert len(recovery_lines) == 1


async def test_a_healthy_platform_logs_nothing_about_connectivity(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative control: Temporal reachable from the first sweep onward
    produces no connectivity log line at all — matching V4's "no crash loop"
    quiet baseline for the case where nothing is wrong."""
    _reachable(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    for _ in range(3):
        await scheduler.sweep(now=NOW)

    assert not [
        r for r in caplog.records if "unreachable" in r.message or "reachable again" in r.message
    ]


# ── bounded RPC deadline on the sweep's Temporal calls (M10-F34) ────────────
#
# The V4 drill (docs/reports/M10-VALIDATION.md §V4) measured a real 10-minute
# Temporal outage that produced zero scheduler log lines: the client object
# stayed cached and non-`None` throughout, so `client is not None` alone (the
# original connectivity read) never flipped, while the SDK retried
# `Unavailable` beneath `start_workflow`/`signal` with no deadline of its own
# and the sweep simply never returned. These tests use a *hanging* fake —
# not the `_unreachable` (`client is None`) fixture above, which is a
# different failure mode — to prove the deadline actually fires, the sweep
# is contained rather than stalled, and the resulting failure is folded into
# the SAME transition-deduped WARNING vocabulary P0-E already built, not a
# new one.


def test_sweep_rpc_timeout_defaults_to_30_seconds() -> None:
    from jarvis.kernel.config import SchedulerSettings

    assert SchedulerSettings().sweep_rpc_timeout_seconds == 30


def test_sweep_rpc_timeout_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SCHEDULER__SWEEP_RPC_TIMEOUT_SECONDS", "5")
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.scheduler.sweep_rpc_timeout_seconds == 5


class _HangingLifecycle:
    """Stands in for `ManagerLifecycle`, simulating V4's own shape: the
    Temporal client is present, but a call beneath it never returns on its
    own because the SDK's retry of `Unavailable` has no deadline. `hang` is
    a class attribute, not instance state, because `_managers_started_step`
    constructs `ManagerLifecycle(self._kernel)` fresh every sweep — a test
    flips it between `sweep()` calls to simulate the outage healing."""

    hang = True

    def __init__(self, _kernel: object) -> None:
        pass

    async def reconcile(self) -> int:
        if type(self).hang:
            await asyncio.sleep(3600)
        return 1


def _hanging(kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch) -> None:
    """A client that is never `None` (so the original `client is not None`
    read stays `True` throughout) with a tiny configured deadline, and
    `ManagerLifecycle` swapped for the hanging fake above."""
    _reachable(kernel, monkeypatch)
    monkeypatch.setattr(kernel.settings.scheduler, "sweep_rpc_timeout_seconds", 0.05)
    monkeypatch.setattr(scheduler_service, "ManagerLifecycle", _HangingLifecycle)
    _HangingLifecycle.hang = True


async def test_managers_started_deadline_is_sourced_from_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value bounding `ManagerLifecycle.reconcile` is read from
    `Settings.scheduler.sweep_rpc_timeout_seconds`, not a hardcoded number —
    proven by capturing what `asyncio.wait_for` was actually called with,
    without waiting out a real timeout."""
    _reachable(kernel, monkeypatch)
    monkeypatch.setattr(kernel.settings.scheduler, "sweep_rpc_timeout_seconds", 17)
    monkeypatch.setattr(scheduler_service, "ManagerLifecycle", _HangingLifecycle)
    _HangingLifecycle.hang = False  # completes instantly; only the timeout kwarg matters

    captured: dict[str, object] = {}
    real_wait_for = asyncio.wait_for

    async def _capturing_wait_for(coro: object, **kwargs: object) -> object:
        captured["timeout"] = kwargs.get("timeout")
        return await real_wait_for(coro, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scheduler_service.asyncio, "wait_for", _capturing_wait_for)

    await Scheduler(kernel).sweep(now=NOW)

    assert captured["timeout"] == 17


async def test_a_hanging_managers_started_call_is_contained_by_the_deadline(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core defect, reproduced and fixed: a Temporal call that never
    returns on its own must not hang the sweep. A real hang against a real
    (tiny) deadline — the outer `wait_for` is this test's own safety net,
    not the mechanism under test, so a regression fails fast instead of
    hanging the suite."""
    _hanging(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    started_at = time.monotonic()
    report = await asyncio.wait_for(scheduler.sweep(now=NOW), timeout=5)
    elapsed = time.monotonic() - started_at

    assert report.managers_started == 0
    assert elapsed < 2, "the sweep waited far longer than its configured deadline"


async def test_deadline_expiry_logs_unreachable_once_across_consecutive_failing_sweeps(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Design 5.2 point 1, applied to the new failure mode: a deadline that
    keeps expiring is a persisting state, announced once — not re-announced
    every sweep just because `client is not None` says "reachable" again at
    the top of each pass before the deadline corrects it."""
    _hanging(kernel, monkeypatch)
    scheduler = Scheduler(kernel)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    for _ in range(3):
        await asyncio.wait_for(scheduler.sweep(now=NOW), timeout=5)

    unreachable_lines = [r for r in caplog.records if "unreachable" in r.message]
    assert len(unreachable_lines) == 1


async def test_recovery_after_a_managers_started_deadline_logs_once_when_the_fake_heals(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _hanging(kernel, monkeypatch)
    scheduler = Scheduler(kernel)
    await asyncio.wait_for(scheduler.sweep(now=NOW), timeout=5)  # down

    _HangingLifecycle.hang = False
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    await asyncio.wait_for(scheduler.sweep(now=NOW), timeout=5)  # recovers

    recovery_lines = [r for r in caplog.records if "reachable again" in r.message]
    assert len(recovery_lines) == 1


class _DeadlineExceededHandle:
    """A workflow handle whose `signal` reports what the real SDK reports
    when `rpc_timeout` (M10-F34) actually fires: `RPCError` at
    `DEADLINE_EXCEEDED`, not a hang. Proves `_events_step`'s own handling of
    that specific, well-defined outcome, in isolation from the wrapper-based
    `managers_started` path above."""

    async def signal(self, name: str, arg: str, *, rpc_timeout: object = None) -> None:
        from temporalio.service import RPCError, RPCStatusCode

        raise RPCError("deadline exceeded", RPCStatusCode.DEADLINE_EXCEEDED, b"")


class _DeadlineExceededClient:
    async def start_workflow(self, name: str, state: object, **kwargs: object) -> None:
        return None

    def get_workflow_handle(self, workflow_id: str) -> _DeadlineExceededHandle:
        return _DeadlineExceededHandle()


class _RecordingHandle:
    """Records the `rpc_timeout` a real signal call would carry."""

    def __init__(self, calls: list[object]) -> None:
        self._calls = calls

    async def signal(self, name: str, arg: str, *, rpc_timeout: object = None) -> None:
        self._calls.append(rpc_timeout)


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def get_workflow_handle(self, workflow_id: str) -> _RecordingHandle:
        return _RecordingHandle(self.calls)


@pytest_asyncio.fixture
async def event_company(kernel: PlatformKernel) -> object:
    """One ACTIVE company subscribed to `APPROVAL_DECIDED` (AFFILIATE's own
    `event_triggers`), with one claimable event already published — the
    minimum `dispatch_events` needs to reach a real `handle.signal` call."""
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        company = await provisioning.create_company(
            definition=AFFILIATE, display_name="Ridgeline Trail Reports"
        )
    async with kernel.services() as svc:
        await kernel.build_bus(svc).publish(
            Event(
                event_id=new_event_id(),
                event_type=APPROVAL_DECIDED,
                business_id=company,
                payload={"approval_id": "apr_1"},
            )
        )
    return company


async def test_dispatch_events_sources_its_rpc_timeout_from_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch, event_company: object
) -> None:
    """`WorkflowHandle.signal`'s own `rpc_timeout` (the SDK's preferred,
    per-call mechanism — reachable directly here, unlike `start_workflow`
    inside `ManagerLifecycle`) carries `Settings.scheduler.
    sweep_rpc_timeout_seconds`, not a hardcoded number."""
    monkeypatch.setattr(kernel.settings.scheduler, "sweep_rpc_timeout_seconds", 12)
    client = _RecordingClient()
    kernel._temporal_client = client  # type: ignore[attr-defined]

    woken = await Scheduler(kernel).dispatch_events()

    assert woken == 1
    assert client.calls == [timedelta(seconds=12)]


async def test_a_deadline_exceeded_signal_is_contained_and_folds_into_connectivity(
    kernel: PlatformKernel, caplog: pytest.LogCaptureFixture, event_company: object
) -> None:
    """The SDK's own well-defined outcome when `rpc_timeout` fires —
    `RPCError(DEADLINE_EXCEEDED)`, not a hang — must be contained by
    `_events_step` itself (no "sweep step failed" line, the generic
    containment path `_run_step` would otherwise log) and folded into the
    same transition-deduped connectivity WARNING a `None` client already
    produces."""
    kernel._temporal_client = _DeadlineExceededClient()  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.woken == 0
    assert not [r for r in caplog.records if "sweep step failed" in r.message]
    unreachable_lines = [r for r in caplog.records if "unreachable" in r.message]
    assert len(unreachable_lines) == 1


# ── run_scheduler: the timer loop, scripted (no real sleep, no live worker) ─


async def test_run_scheduler_reads_the_interval_from_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No override given: the loop sleeps for exactly `Settings.scheduler.
    sweep_interval_seconds`, proven without ever actually waiting 300s
    (M9-F92, design Part 4.6/M10-F5)."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduler(kernel)

    assert sleeps == [kernel.settings.scheduler.sweep_interval_seconds]


async def test_run_scheduler_interval_override_beats_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduler(kernel, interval_seconds=5)

    assert sleeps == [5]


async def test_a_failed_sweep_is_contained_and_the_next_sweep_still_runs(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The outer guard `run_scheduler` already had, still proven end to end
    now that `Scheduler.sweep` itself also contains its own sub-steps."""
    real_sweep = worker.Scheduler.sweep
    calls = {"n": 0}

    async def _flaky_sweep(self: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom — a transient failure, contained")
        return await real_sweep(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(worker.Scheduler, "sweep", _flaky_sweep)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduler(kernel, interval_seconds=0)

    assert calls["n"] == 2  # sweep 1 failed and was contained; sweep 2 still ran


async def test_managers_started_alone_still_triggers_the_log_line(
    kernel: PlatformKernel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M10-F9 point 3: a sweep whose only work was starting a Manager must
    not stay silent."""
    from jarvis.scheduler.service import SweepReport

    async def _fake_sweep(self: object) -> SweepReport:
        return SweepReport(managers_started=1)

    monkeypatch.setattr(worker.Scheduler, "sweep", _fake_sweep)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    caplog.set_level(logging.INFO, logger="jarvis.runtime.worker")
    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduler(kernel, interval_seconds=0)

    assert any("sweep complete" in r.message for r in caplog.records)


async def test_a_quiet_sweep_logs_nothing(
    kernel: PlatformKernel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The negative control on M10-F9 point 3: nothing changed, nothing logged."""
    from jarvis.scheduler.service import SweepReport

    async def _fake_sweep(self: object) -> SweepReport:
        return SweepReport()

    monkeypatch.setattr(worker.Scheduler, "sweep", _fake_sweep)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    caplog.set_level(logging.INFO, logger="jarvis.runtime.worker")
    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduler(kernel, interval_seconds=0)

    assert not [r for r in caplog.records if "sweep complete" in r.message]
