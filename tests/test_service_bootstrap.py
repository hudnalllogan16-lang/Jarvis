"""The service entrypoint: postures, root resolution, exit codes (packet P0-A).

Three properties, each of which the platform got wrong in a way that produced a
live outage or would have produced one under a service manager:

- **Posture (M10-F15).** `launcher.py` exited when the database was unreachable.
  Right for a command a developer typed; for a service it converts a
  dependency-ordering problem into a restart loop and then reports it as one.
- **Root resolution (M10-F10).** Migrations were configured from a path relative
  to the working directory, which a Windows service does not have. The failure
  is silent: `alembic upgrade head` against nothing succeeds.
- **Exit codes (design 2.3).** They are the interface between the Supervisor's
  tier and the operating system's, so a clean stop must never look like a crash
  and invalid configuration must never look like a transient dependency.

Nothing here starts a process, binds a port, or touches a database: preflight is
scripted and the parts are never awaited, which is the same scripted-harness
discipline M8-7 used for the worker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.kernel.errors import ConfigurationError
from jarvis.observability.heartbeat import RuntimeIdentity
from jarvis.shell import service
from jarvis.shell.preflight import ComponentHealth, HealthReport, Posture, Status
from jarvis.shell.supervisor import PartState


def _report(*, serving: bool) -> HealthReport:
    """A settled preflight report, scripted rather than measured."""
    status = Status.OK if serving else Status.DOWN
    return HealthReport(
        components=(
            ComponentHealth("database", status, "scripted", remedy="", detail=""),
            ComponentHealth("workflows", Status.OK, "scripted"),
        )
    )


class _FakeKernel:
    """Only what `bootstrap` touches: builtin-type installation and settings."""

    def __init__(self) -> None:
        self.installed = 0
        self.closed = 0
        self.settings = type("_S", (), {"api_port": 8000})()

    async def ensure_builtin_types(self) -> None:
        self.installed += 1

    async def aclose(self) -> None:
        self.closed += 1


class _Preflight:
    """Returns a scripted sequence of reports, then repeats the last one."""

    def __init__(self, *serving: bool) -> None:
        self.script = list(serving)
        self.calls = 0

    async def __call__(self, _kernel: object) -> HealthReport:
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return _report(serving=self.script[index])


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Scripted preflight and a migration call that records instead of running."""
    applied: list[Path | None] = []
    monkeypatch.setattr(service, "apply_migrations", lambda root=None: applied.append(root))
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    return {"applied": applied, "slept": slept, "sleep": _sleep}


# ── Posture (M10-F15, design 1.4) ────────────────────────────────────────────


async def test_refuse_returns_a_failing_report_without_migrating(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    """The console's posture: report the failure, change nothing.

    Migrating a database that could not answer `SELECT 1` is not a thing to
    attempt, and installing builtin types into it even less so.
    """
    monkeypatch.setattr(service, "run_preflight", _Preflight(False))
    kernel = _FakeKernel()

    report = await service.bootstrap(
        kernel,  # type: ignore[arg-type]
        on_unavailable=Posture.REFUSE,
        sleep=harness["sleep"],
    )

    assert not report.can_serve
    assert harness["applied"] == []
    assert kernel.installed == 0


async def test_refuse_migrates_once_the_database_is_there(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    monkeypatch.setattr(service, "run_preflight", _Preflight(True))
    kernel = _FakeKernel()

    report = await service.bootstrap(
        kernel,  # type: ignore[arg-type]
        on_unavailable=Posture.REFUSE,
        sleep=harness["sleep"],
    )

    assert report.can_serve
    assert len(harness["applied"]) == 1
    assert kernel.installed == 1


async def test_wait_retries_indefinitely_instead_of_refusing(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    """The service's posture, and the whole of M10-F15.

    A service that started three seconds before Postgres must wait for it, not
    exit and leave its restarter to express the dependency ordering.
    """
    preflight = _Preflight(False, False, False, True)
    monkeypatch.setattr(service, "run_preflight", preflight)
    kernel = _FakeKernel()

    report = await service.bootstrap(
        kernel,  # type: ignore[arg-type]
        on_unavailable=Posture.WAIT,
        sleep=harness["sleep"],
    )

    assert report.can_serve
    assert preflight.calls == 4
    assert harness["slept"] == [service.WAIT_RETRY_SECONDS] * 3
    assert len(harness["applied"]) == 1


async def test_waiting_is_stated_once_and_then_restated_on_a_cadence(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A thirteen-hour outage should read as ongoing, not as 9,000 lines.

    One line when the wait starts, and a restatement every
    `WAIT_LOG_INTERVAL_SECONDS` — the same argument the design makes about
    sweep logging, applied to the one loop that can run for hours.
    """
    retries = int(service.WAIT_LOG_INTERVAL_SECONDS / service.WAIT_RETRY_SECONDS)
    monkeypatch.setattr(service, "run_preflight", _Preflight(*([False] * (retries + 1)), True))
    caplog.set_level(logging.INFO, logger="jarvis.shell.service")

    await service.bootstrap(
        _FakeKernel(),  # type: ignore[arg-type]
        on_unavailable=Posture.WAIT,
        sleep=harness["sleep"],
    )

    messages = [record.message for record in caplog.records]
    assert messages.count("waiting for a dependency") == 1
    assert messages.count("still waiting for a dependency") == 1


# ── Heartbeat writes (packet P0-B, design 3.2) ───────────────────────────────


async def test_waiting_writes_a_heartbeat_when_given_an_identity(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """One `waiting` row at the start of the wait, one on each restatement —
    the same cadence the log already gives a console, but readable with no
    console attached (design Part 6, Mode 4)."""
    written: list[dict[str, object]] = []

    async def _write_heartbeat(_kernel: object, _identity: object, **fields: object) -> None:
        written.append(fields)

    monkeypatch.setattr(service, "_write_heartbeat", _write_heartbeat)
    retries = int(service.WAIT_LOG_INTERVAL_SECONDS / service.WAIT_RETRY_SECONDS)
    monkeypatch.setattr(service, "run_preflight", _Preflight(*([False] * (retries + 1)), True))
    caplog.set_level(logging.INFO, logger="jarvis.shell.service")
    identity = RuntimeIdentity(runtime_id="r1", hostname="h", pid=1, started_at=datetime.now(UTC))

    await service.bootstrap(
        _FakeKernel(),  # type: ignore[arg-type]
        on_unavailable=Posture.WAIT,
        sleep=harness["sleep"],
        runtime_identity=identity,
    )

    assert len(written) == 2
    assert all(w["part_name"] == service.RUNTIME_PART_NAME for w in written)
    assert all(w["state"] == service.WAITING_STATE for w in written)


async def test_waiting_writes_no_heartbeat_without_an_identity(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    """`runtime_identity=None` (the console's `REFUSE` path never reaches this
    branch, and every pre-P0-B test calls `bootstrap` this way) must not
    attempt a write at all."""
    written: list[dict[str, object]] = []

    async def _write_heartbeat(_kernel: object, _identity: object, **fields: object) -> None:
        written.append(fields)

    monkeypatch.setattr(service, "_write_heartbeat", _write_heartbeat)
    monkeypatch.setattr(service, "run_preflight", _Preflight(False, True))

    await service.bootstrap(
        _FakeKernel(),  # type: ignore[arg-type]
        on_unavailable=Posture.WAIT,
        sleep=harness["sleep"],
    )

    assert written == []


async def test_heartbeat_loop_beats_every_part_once_per_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One `_write_heartbeat` call per supervised part, every `interval`."""
    written: list[dict[str, object]] = []

    async def _write_heartbeat(_kernel: object, _identity: object, **fields: object) -> None:
        written.append(fields)

    monkeypatch.setattr(service, "_write_heartbeat", _write_heartbeat)

    class _Part:
        def __init__(self, name: str) -> None:
            self.name = name
            self.state = PartState.RUNNING
            self.consecutive_crashes = 0
            self.last_error = ""

    class _Supervisor:
        def statuses(self) -> list[_Part]:
            return [_Part("api"), _Part("worker")]

    ticks = 0

    async def _sleep(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks >= 2:
            raise asyncio.CancelledError

    identity = RuntimeIdentity(runtime_id="r1", hostname="h", pid=1, started_at=datetime.now(UTC))
    with pytest.raises(asyncio.CancelledError):
        await service._heartbeat_loop(
            object(),  # type: ignore[arg-type]
            _Supervisor(),  # type: ignore[arg-type]
            identity,
            interval=15.0,
            sleep=_sleep,
        )

    assert [w["part_name"] for w in written] == ["api", "worker", "api", "worker"]
    assert all(w["state"] == "running" for w in written)


async def test_only_the_console_is_offered_a_recovery(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    """`docker compose up -d` is the console's, never the service's (M10-F11).

    Docker Desktop belongs to a user session; a service running as LocalSystem
    starting one is a category error. The mechanism is that the service passes
    no `recover` at all, so there is nothing to accidentally inherit.
    """
    monkeypatch.setattr(service, "run_preflight", _Preflight(False, True))
    attempts = 0

    async def _recover() -> bool:
        nonlocal attempts
        attempts += 1
        return True

    report = await service.bootstrap(
        _FakeKernel(),  # type: ignore[arg-type]
        on_unavailable=Posture.REFUSE,
        recover=_recover,
        sleep=harness["sleep"],
    )

    assert attempts == 1
    assert report.can_serve


# ── Root resolution (M10-F10) ────────────────────────────────────────────────


def test_the_installation_root_does_not_depend_on_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The exact shape of M10-F10: a service inherits no useful cwd."""
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    root = service.installation_root()

    assert root.is_absolute()
    assert (root / "alembic.ini").is_file()
    assert (root / "migrations").is_dir()


def test_jarvis_home_overrides_the_resolved_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installation that relocates the package still says where it lives."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    assert service.installation_root() == tmp_path.resolve()


def test_the_migration_config_carries_absolute_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every path Alembic would otherwise resolve against the cwd is absolute."""
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    config = service.migration_config()

    for option in ("script_location", "prepend_sys_path"):
        value = config.get_main_option(option)
        assert value is not None
        assert Path(value).is_absolute(), f"{option} is relative: {value}"


def test_an_installation_without_migrations_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silence is the failure mode being closed: `upgrade head` against no
    migrations succeeds and leaves the schema wherever it was."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    with pytest.raises(ConfigurationError):
        service.migration_config()


# ── Exit codes (design 2.3) ──────────────────────────────────────────────────


@pytest.fixture
def headless(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`serve_headless` with its process-level effects stubbed out.

    Signal installation is replaced rather than exercised, because
    `signal.signal` mutates the interpreter for the rest of the suite — it is
    tested separately, by recording what it registers.
    """
    fake_heartbeat_settings = type("_H", (), {"heartbeat_interval_seconds": 15})()
    monkeypatch.setattr(
        service,
        "Settings",
        lambda: type("_S", (), {"api_port": 8000, "heartbeat": fake_heartbeat_settings})(),
    )
    monkeypatch.setattr(service, "migration_config", lambda root=None: None)
    kernel = _FakeKernel()
    monkeypatch.setattr(service, "PlatformKernel", lambda _settings: kernel)
    monkeypatch.setattr(service, "install_signal_handlers", lambda _stop: None)
    heartbeats: list[dict[str, object]] = []

    async def _write_heartbeat(_kernel: object, _identity: object, **fields: object) -> None:
        heartbeats.append(fields)

    monkeypatch.setattr(service, "_write_heartbeat", _write_heartbeat)

    class _Supervisor:
        async def run_until_stopped(self) -> None:
            return None

        def statuses(self) -> list[object]:
            return []

    monkeypatch.setattr(service, "build_supervisor", lambda _kernel: _Supervisor())

    async def _bootstrap(_kernel: object, **_: object) -> HealthReport:
        return _report(serving=True)

    monkeypatch.setattr(service, "bootstrap", _bootstrap)
    return {"kernel": kernel, "monkeypatch": monkeypatch, "heartbeats": heartbeats}


def test_a_clean_stop_exits_zero(headless: dict[str, Any]) -> None:
    """Tier 2 must leave an operator-requested stop stopped."""
    assert service.serve_headless() == service.EXIT_OK
    assert headless["kernel"].closed == 1


def test_a_clean_stop_writes_a_final_stopped_heartbeat(headless: dict[str, Any]) -> None:
    """D-060: "stopped cleanly" and "last seen" must stay different recorded
    facts, so a clean stop owes the `runtime_heartbeat` table its own row."""
    assert service.serve_headless() == service.EXIT_OK
    heartbeats: list[dict[str, object]] = headless["heartbeats"]
    stopped = [h for h in heartbeats if h["state"] == service.STOPPED_STATE]
    assert len(stopped) == 1
    assert stopped[0]["part_name"] == service.RUNTIME_PART_NAME


def test_a_stop_while_waiting_for_a_dependency_exits_zero(headless: dict[str, Any]) -> None:
    """A service told to stop while it waits has not failed at anything.

    Also proves the shutdown seam reaches the waiting posture: the wait is
    indefinite, so if the stop event did not interrupt it this test would hang
    rather than fail.
    """
    monkeypatch: pytest.MonkeyPatch = headless["monkeypatch"]

    async def _never(_kernel: object, **_: object) -> HealthReport:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(service, "bootstrap", _never)
    monkeypatch.setattr(service, "install_signal_handlers", lambda stop: stop.set())

    assert service.serve_headless() == service.EXIT_OK


def test_a_dependency_failing_during_startup_exits_two(headless: dict[str, Any]) -> None:
    """Restart, throttled: it may well work on the next attempt."""
    monkeypatch: pytest.MonkeyPatch = headless["monkeypatch"]

    async def _boom(_kernel: object, **_: object) -> HealthReport:
        raise OSError("the database went away mid-migration")

    monkeypatch.setattr(service, "bootstrap", _boom)
    assert service.serve_headless() == service.EXIT_DEPENDENCY_UNAVAILABLE


def test_invalid_configuration_exits_three(headless: dict[str, Any]) -> None:
    """Configuration that cannot become valid, so the throttle is the alarm."""
    monkeypatch: pytest.MonkeyPatch = headless["monkeypatch"]

    def _refuse() -> object:
        raise ValueError("JARVIS_LLM__MODEL is not set")

    monkeypatch.setattr(service, "Settings", _refuse)
    assert service.serve_headless() == service.EXIT_CONFIGURATION


def test_an_installation_that_cannot_migrate_exits_three(headless: dict[str, Any]) -> None:
    """Checked before anything starts: this cannot become valid by waiting."""
    monkeypatch: pytest.MonkeyPatch = headless["monkeypatch"]

    def _refuse(root: Path | None = None) -> object:
        raise ConfigurationError("no alembic.ini")

    monkeypatch.setattr(service, "migration_config", _refuse)
    assert service.serve_headless() == service.EXIT_CONFIGURATION


def test_configuration_failing_during_startup_exits_three(headless: dict[str, Any]) -> None:
    """A configuration refusal raised deeper in bootstrap keeps its code."""
    monkeypatch: pytest.MonkeyPatch = headless["monkeypatch"]

    async def _refuse(_kernel: object, **_: object) -> HealthReport:
        raise ConfigurationError("the installation root moved")

    monkeypatch.setattr(service, "bootstrap", _refuse)
    assert service.serve_headless() == service.EXIT_CONFIGURATION


def test_every_stop_signal_reaches_the_same_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """SIGINT, SIGTERM and — because Windows is the host of record — SIGBREAK.

    NSSM's `AppStopMethodConsole` delivers a console event; a service that
    ignores it is one an operator has to kill, and a killed service cannot
    write the `stopped` fact that distinguishes it from a vanished one.
    """
    import signal as signal_module
    import threading

    registered: dict[int, object] = {}
    monkeypatch.setattr(
        signal_module, "signal", lambda number, handler: registered.setdefault(number, handler)
    )

    stop = threading.Event()
    service.install_signal_handlers(stop)

    expected = {
        getattr(signal_module, name)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK")
        if hasattr(signal_module, name)
    }
    assert set(registered) == expected
    for handler in registered.values():
        stop.clear()
        handler(0, None)  # type: ignore[operator]
        assert stop.is_set()


# ── The part table (design 1.2) ──────────────────────────────────────────────


async def test_the_supervisor_composes_the_four_parts() -> None:
    """The one part table, asserted by name.

    The parts are registered but never awaited: `Supervisor.add` schedules a
    task and this test cancels them before the loop runs one, so nothing here
    binds a port or connects to Temporal.
    """
    supervisor = service.build_supervisor(_FakeKernel())  # type: ignore[arg-type]
    try:
        assert [part.name for part in supervisor.statuses()] == [
            "api",
            "worker",
            "scheduler",
            "executive",
        ]
        assert [part.operator_label for part in supervisor.statuses()] == [
            "Dashboard",
            "Company runner",
            "Timers and reminders",
            "Budget and health checks",
        ]
    finally:
        await _cancel_everything()


async def test_a_runtime_without_the_api_still_runs_every_other_part() -> None:
    """Mode 4's inverse: the read surface served elsewhere, same parts here."""
    supervisor = service.build_supervisor(_FakeKernel(), with_api=False)  # type: ignore[arg-type]
    try:
        assert [part.name for part in supervisor.statuses()] == [
            "worker",
            "scheduler",
            "executive",
        ]
    finally:
        await _cancel_everything()


async def _cancel_everything() -> None:
    """Cancel the part tasks before the event loop ever runs one."""
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is not current:
            task.cancel()
    await asyncio.sleep(0)
