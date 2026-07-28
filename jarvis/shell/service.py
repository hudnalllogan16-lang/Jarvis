"""The Jarvis runtime: one part table, one bootstrap, one headless entrypoint.

Design OPERATIONAL-RUNTIME.md Parts 1-2, packet P0-A. The audit's central fact
was three composition roots that each wrote their own part list, so the topology
existed three times and nothing asserted the three agreed (M10-F19). The
constraint this module accepts is narrower than "unify the entrypoints":

    The set of supervised parts is written down exactly once. Every entrypoint
    is a choice of which face to put on that one set, never a second opinion
    about what the set is.

So `build_supervisor` below is the only place in `jarvis/` that calls
`Supervisor.add`, and `tests/test_one_part_table.py` is what keeps that a
property rather than a convention.

Three faces on one core:

* `jarvis-run` -> `serve_headless` — the platform. Signals, exit codes, the
  `WAIT` posture, no window and no browser ever. This is what every deployment
  mode in the design's Part 6 actually runs.
* `jarvis` -> `jarvis/shell/launcher.py` — the operator console. The same
  `bootstrap` and the same `build_supervisor`, plus a window, under the
  `REFUSE` posture.
* `python -m jarvis.api.server` — a console-only attach, unchanged here.

**This module holds no logic.** It constructs the object graph and starts it; if
a behaviour matters it lives in the component being started. It is exempt in
`tests/test_layering.py` for that reason and `test_entrypoint_roots_hold_no_logic`
keeps the claim honest — which is also why `Posture` is defined in
`jarvis/shell/preflight.py` rather than here.

**Heartbeat writes (packet P0-B).** The `waiting` and `stopped` rows design
Part 3 asks `bootstrap` and `serve_headless` to write, plus the periodic beat
every running part gets, all land through `_write_heartbeat` below —
best-effort by construction (design 3.2's fact must never become a new way
for the runtime it describes to fail).
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from jarvis.api.app import create_app
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import ConfigurationError
from jarvis.kernel.logging import get_logger
from jarvis.observability.heartbeat import (
    STOPPED_STATE,
    WAITING_STATE,
    HeartbeatStore,
    RuntimeIdentity,
)
from jarvis.persistence.engine import session_scope
from jarvis.shell.preflight import HealthReport, Posture, run_preflight
from jarvis.shell.supervisor import Supervisor

RUNTIME_PART_NAME = "runtime"
"""The synthetic `part_name` for whole-process heartbeat facts no single
supervised part can express on its own (design 3.2): waiting for a
dependency before any part exists, and a clean stop after every part does."""

if TYPE_CHECKING:  # imported for typing only; Alembic is a startup cost, not an import one
    from alembic.config import Config

logger = get_logger(__name__)

EXIT_OK = 0
"""Clean stop, operator-requested. An external supervisor must NOT restart."""

EXIT_DEPENDENCY_UNAVAILABLE = 2
"""A dependency failed past the waiting posture's own patience — the database
disappeared while migrations were running, say. Restart, throttled."""

EXIT_CONFIGURATION = 3
"""Configuration cannot become valid: `Settings()` refused, or the installation
root holds no migrations. Restart throttled, and the throttle *is* the alarm —
an escalating gap between restarts is the visible signal (design 2.3)."""

WAIT_RETRY_SECONDS = 5.0
"""How often the `WAIT` posture re-runs preflight. Indefinitely: the service
never gives up on a dependency that may still be starting."""

WAIT_LOG_INTERVAL_SECONDS = 60.0
"""After the first failure, how often waiting is restated. A log that repeats
itself every five seconds is a log nobody reads."""

DRAIN_SECONDS = 15.0
"""Shutdown budget, matching the launcher's existing `services.join(timeout=15)`
and NSSM's `AppStopMethodConsole` value in the design's Part 6.1."""


def installation_root() -> Path:
    """Return the absolute directory Jarvis is installed in (M10-F10).

    `launcher.py` tested `Path("docker-compose.yml")` and built
    `Config("alembic.ini")`, both relative to the process working directory. A
    Windows service does not start with a useful one, so migrations would
    silently target nothing. Resolved from this file's own location instead,
    overridable by `JARVIS_HOME` for installations that relocate the package
    away from the repository layout.

    Returns:
        The directory holding `alembic.ini` and `migrations/`.
    """
    override = os.environ.get("JARVIS_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def migration_config(root: Path | None = None) -> Config:
    """Build an Alembic config with absolute paths (M10-F10).

    Both path options Alembic resolves against the working directory are set
    explicitly, so `alembic upgrade head` targets this installation's
    migrations whatever directory the process was started in. `alembic.ini`
    itself is required to exist: a service that "migrates" nothing and reports
    success is the failure this whole packet exists to stop.

    Args:
        root: Installation root; defaults to `installation_root()`.

    Returns:
        An `alembic.config.Config` whose script location and sys.path entry are
        both absolute.

    Raises:
        ConfigurationError: If the installation root holds no `alembic.ini`.
    """
    from alembic.config import Config

    base = root if root is not None else installation_root()
    ini = base / "alembic.ini"
    if not ini.is_file():
        raise ConfigurationError(
            f"no alembic.ini under the installation root {base}",
            operator_message="Jarvis can't find its own installation files.",
        )
    config = Config(str(ini))
    config.set_main_option("script_location", str(base / "migrations"))
    config.set_main_option("prepend_sys_path", str(base))
    return config


def apply_migrations(root: Path | None = None) -> None:
    """Apply migrations in-process. Idempotent; safe on every launch.

    Args:
        root: Installation root; defaults to `installation_root()`.

    Raises:
        ConfigurationError: If the installation root holds no `alembic.ini`.
    """
    from alembic import command

    command.upgrade(migration_config(root), "head")


def _log_line(message: str) -> None:
    """Default progress sink: the service's log, since it has no console."""
    logger.info(message)


def _log_report(report: HealthReport) -> None:
    """Default settled-preflight sink. One line per component, so an operator
    reading a service log file sees the same ladder the console prints."""
    for component in report.components:
        logger.info(
            "preflight",
            extra={
                "context": {
                    "component": component.name,
                    "status": component.status.value,
                    "summary": component.summary,
                }
            },
        )


async def bootstrap(
    kernel: PlatformKernel,
    *,
    on_unavailable: Posture,
    recover: Callable[[], Awaitable[bool]] | None = None,
    announce: Callable[[str], None] = _log_line,
    on_report: Callable[[HealthReport], None] = _log_report,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    runtime_identity: RuntimeIdentity | None = None,
) -> HealthReport:
    """Preflight, wait or refuse, migrate, install builtin types.

    The one behaviour the console and the service must not share is the
    response to a missing dependency, and it is a parameter here rather than a
    second copy of this function (M10-F15, design 1.4).

    Under `WAIT` this returns only once the platform can serve; under `REFUSE`
    it returns a report the caller must check, without having migrated
    anything — refusing is the caller's to do, because a function that exits
    the process cannot be called by a console that wants to show a window
    first.

    Args:
        kernel: Initialised Platform Kernel.
        on_unavailable: `REFUSE` (console) or `WAIT` (service).
        recover: Console-only attempt to start local dependencies, awaited once
            if the first preflight cannot serve. `docker compose up -d` is a
            user-session concern and a service running as LocalSystem must not
            do it (M10-F11), so the service passes nothing.
        announce: Progress lines, for a caller with a console.
        on_report: Called once with the settled report, before migrations, so
            the ladder is shown while they run rather than after.
        sleep: Injectable delay, so posture tests do not wait real seconds.
        runtime_identity: This process's identity (packet P0-B), for the
            `waiting` heartbeat row `_wait_for_dependencies` writes while
            this posture retries. `None` for a caller with no identity to
            report — the console (`REFUSE` never reaches that branch anyway)
            and every existing test that predates this parameter.

    Returns:
        The settled `HealthReport`. Under `WAIT` it always serves; under
        `REFUSE` the caller must check `can_serve`.

    Raises:
        ConfigurationError: If the installation root holds no migrations.
    """
    report = await run_preflight(kernel)

    if not report.can_serve and recover is not None and await recover():
        for attempt in range(24):  # up to ~2 minutes for first-time image pulls
            await sleep(WAIT_RETRY_SECONDS)
            report = await run_preflight(kernel)
            if report.can_serve:
                break
            if attempt % 3 == 2:  # a visible heartbeat every ~15s, not silence
                announce(f"  Still waiting ({(attempt + 1) * 5}s)...")

    if not report.can_serve and on_unavailable is Posture.WAIT:
        report = await _wait_for_dependencies(
            kernel, report, sleep=sleep, identity=runtime_identity
        )

    on_report(report)
    if not report.can_serve:
        return report

    await asyncio.to_thread(apply_migrations)
    await kernel.ensure_builtin_types()
    return report


async def _wait_for_dependencies(
    kernel: PlatformKernel,
    report: HealthReport,
    *,
    sleep: Callable[[float], Awaitable[None]],
    identity: RuntimeIdentity | None = None,
) -> HealthReport:
    """Re-run preflight every `WAIT_RETRY_SECONDS` until the platform can serve.

    Logs the first failure and then restates it every `WAIT_LOG_INTERVAL_SECONDS`,
    so a long outage reads as ongoing rather than as one line at the start
    followed by silence.

    Writes a `runtime_heartbeat` row in state `waiting` (design 3.2, packet
    P0-B) once at the start of the wait and again on every restatement — a
    reader watching that row sees the same "still waiting" cadence the log
    already gives a console, even with no console attached (Mode 4). Skipped
    entirely when ``identity`` is `None`.

    Args:
        kernel: Initialised Platform Kernel.
        report: The failing report that started the wait.
        sleep: Injectable delay.
        identity: This process's identity, or `None` to skip the heartbeat
            write (see `bootstrap`'s docstring).

    Returns:
        The first report that can serve.
    """
    waited = 0.0
    logger.info("waiting for a dependency", extra={"context": _blockers(report)})
    if identity is not None:
        await _write_heartbeat(kernel, identity, part_name=RUNTIME_PART_NAME, state=WAITING_STATE)
    announced_at = 0.0
    while not report.can_serve:
        await sleep(WAIT_RETRY_SECONDS)
        waited += WAIT_RETRY_SECONDS
        report = await run_preflight(kernel)
        if not report.can_serve and waited - announced_at >= WAIT_LOG_INTERVAL_SECONDS:
            announced_at = waited
            logger.info(
                "still waiting for a dependency",
                extra={"context": {"waited_seconds": waited, **_blockers(report)}},
            )
            if identity is not None:
                await _write_heartbeat(
                    kernel, identity, part_name=RUNTIME_PART_NAME, state=WAITING_STATE
                )
    logger.info("dependencies are available; starting", extra={"context": {"waited": waited}})
    return report


def _blockers(report: HealthReport) -> dict[str, object]:
    """Name the components that are down, for the waiting log's context."""
    return {"down": sorted(c.name for c in report.components if c.status.value == "down")}


async def _write_heartbeat(
    kernel: PlatformKernel,
    identity: RuntimeIdentity,
    *,
    part_name: str,
    state: str,
    consecutive_crashes: int = 0,
    last_error: str = "",
) -> None:
    """Best-effort `runtime_heartbeat` upsert (design 3.2, packet P0-B).

    A heartbeat records that the runtime is healthy; a heartbeat write that
    could itself take the runtime down would make that record less reliable,
    not more, so a failure here is logged and swallowed — the same posture
    `AuditLog.record_independently` takes toward a denial record it cannot
    write. Opens its own short transaction rather than sharing a caller's:
    nothing that calls this holds a session of its own to share (the
    Supervisor's loop and the bootstrap wait are both outside `services()`),
    and a beat has no reason to wait on anyone else's commit.

    Args:
        kernel: Initialised Platform Kernel, for its session factory.
        identity: This process's identity (`RuntimeIdentity`).
        part_name: `'api' | 'worker' | 'scheduler' | 'executive' | 'runtime'`.
        state: The part's current state, as a bare string (see
            `HeartbeatStore.beat`'s docstring for why).
        consecutive_crashes: Mirrors `PartStatus.consecutive_crashes`.
        last_error: Mirrors `PartStatus.last_error`.
    """
    try:
        async with session_scope(kernel.session_factory) as session:
            await HeartbeatStore(session).beat(
                identity,
                part_name=part_name,
                state=state,
                consecutive_crashes=consecutive_crashes,
                last_error=last_error,
            )
    except Exception:
        logger.warning(
            "could not write a runtime heartbeat",
            extra={"context": {"part": part_name, "state": state}},
        )


async def _heartbeat_loop(
    kernel: PlatformKernel,
    supervisor: Supervisor,
    identity: RuntimeIdentity,
    *,
    interval: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Upsert one heartbeat row per supervised part, every ``interval`` seconds.

    Runs alongside the Supervisor as its own task, never as one of its parts
    — `tests/test_one_part_table.py` asserts exactly four parts, and a
    heartbeat that could crash-loop would be exactly the silent gap this
    packet exists to close. Beats immediately on entry (a fresh start should
    not read as `down` for a full `interval` before its first write) and then
    on the cadence.

    Args:
        kernel: Initialised Platform Kernel.
        supervisor: The running Supervisor to read part statuses from.
        identity: This process's identity.
        interval: Seconds between beats (`settings.heartbeat.
            heartbeat_interval_seconds`).
        sleep: Injectable delay, so tests do not wait real seconds.
    """
    while True:
        for part in supervisor.statuses():
            await _write_heartbeat(
                kernel,
                identity,
                part_name=part.name,
                state=part.state.value,
                consecutive_crashes=part.consecutive_crashes,
                last_error=part.last_error,
            )
        await sleep(interval)


def _supervisor_parts(supervisor: Supervisor) -> list[dict[str, object]]:
    """Render live part statuses for `/api/health`'s `parts` field (M10-F1).

    A crashed part therefore shows as "restarting" in the dashboard's health
    banner rather than the operator meeting a dead terminal.
    """
    return [
        {
            "name": part.operator_label,
            "state": part.state.value,
            "restarts": part.consecutive_crashes,
        }
        for part in supervisor.statuses()
    ]


async def _serve_api(kernel: PlatformKernel, supervisor: Supervisor, port: int) -> None:
    """Serve the operator API and dashboard on ``port`` (`Settings().api_port`).

    `create_app` owns the single `/api/health` route for every topology
    (M10-F1); the Supervisor's part statuses reach it as a `parts_provider`
    closure rather than as a competing route.
    """
    app = create_app(kernel, parts_provider=lambda: _supervisor_parts(supervisor))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    await server.serve()


async def _run_worker_when_possible(kernel: PlatformKernel) -> None:
    """Run the Temporal worker, retrying until the runtime is reachable."""
    from jarvis.runtime.worker import run_worker

    while True:
        client = await kernel.temporal_client()
        if client is not None:
            logger.info("workflow runtime reachable; worker starting")
            await run_worker(kernel)
            return
        await asyncio.sleep(5)


async def _run_scheduler(kernel: PlatformKernel) -> None:
    """Run the section 9 timer sweep and event wakes."""
    from jarvis.runtime.worker import run_scheduler

    await run_scheduler(kernel)


async def _run_executive(kernel: PlatformKernel) -> None:
    """Run the Executive Layer's deterministic tick (D-041)."""
    from jarvis.runtime.worker import run_executive

    await run_executive(kernel)


def build_supervisor(kernel: PlatformKernel, *, with_api: bool = True) -> Supervisor:
    """Build the supervised runtime: the part table, in one place, once.

    **The only call site of `Supervisor.add` in `jarvis/`.** A fifth entrypoint
    may exist; a second opinion about what runs may not, which is the whole of
    M10-F19 and is enforced by `tests/test_one_part_table.py`.

    Args:
        kernel: Initialised Platform Kernel.
        with_api: Whether this process serves the operator API. False composes
            the runtime for a deployment whose read surface is served
            elsewhere (design Part 6, Mode 4's inverse) — the parts are
            identical either way, which is the point.

    Returns:
        A Supervisor with its parts registered and running. The caller awaits
        `run_until_stopped()`.
    """
    supervisor = Supervisor(
        failing_after_crashes=kernel.settings.heartbeat.part_failing_after_crashes
    )
    if with_api:
        supervisor.add(
            "api", "Dashboard", lambda: _serve_api(kernel, supervisor, kernel.settings.api_port)
        )
    supervisor.add("worker", "Company runner", lambda: _run_worker_when_possible(kernel))
    supervisor.add("scheduler", "Timers and reminders", lambda: _run_scheduler(kernel))
    supervisor.add("executive", "Budget and health checks", lambda: _run_executive(kernel))
    return supervisor


def install_signal_handlers(stop: threading.Event) -> None:
    """Route every stop signal to one event (design 2.4).

    `SIGBREAK` is included because Windows is the deployment host of record and
    NSSM's `AppStopMethodConsole` delivers exactly that; it does not exist on
    other platforms and is looked up rather than imported. `threading.Event` is
    D-017's existing shutdown seam, reused as-is: a signal handler runs on the
    main thread and cannot touch an asyncio primitive belonging to a loop it is
    interrupting.

    Args:
        stop: Set by any of SIGINT, SIGTERM or SIGBREAK.
    """

    def _handler(_number: int, _frame: object) -> None:
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, _handler)
        except (ValueError, OSError):  # not the main thread, or not supported here
            logger.debug("could not install a handler for %s", name)


async def _stopped(stop: threading.Event) -> None:
    """Return once `stop` is set. Waits on a worker thread, because
    `Event.wait()` blocks its caller and would otherwise freeze the loop."""
    await asyncio.to_thread(stop.wait)


async def _serve(settings: Settings, stop: threading.Event) -> int:
    """Bootstrap in the waiting posture, run every part, drain on stop.

    Args:
        settings: Validated settings.
        stop: Set by `install_signal_handlers`.

    Returns:
        A process exit code (design 2.3).
    """
    kernel = PlatformKernel(settings)
    identity = RuntimeIdentity(
        runtime_id=str(uuid.uuid4()),
        hostname=socket.gethostname(),
        pid=os.getpid(),
        started_at=datetime.now(UTC),
    )
    stopping = asyncio.ensure_future(_stopped(stop))
    try:
        booting = asyncio.ensure_future(
            bootstrap(kernel, on_unavailable=Posture.WAIT, runtime_identity=identity)
        )
        done, _ = await asyncio.wait({booting, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if booting not in done:
            # Stopped while waiting for a dependency. Never a failure: the
            # operator asked, and an external restarter must leave it stopped.
            booting.cancel()
            return EXIT_OK
        booting.result()  # re-raises whatever bootstrap failed on

        supervisor = build_supervisor(kernel)
        running = asyncio.ensure_future(supervisor.run_until_stopped())
        heartbeat = asyncio.ensure_future(
            _heartbeat_loop(
                kernel,
                supervisor,
                identity,
                interval=settings.heartbeat.heartbeat_interval_seconds,
            )
        )
        logger.info("runtime serving", extra={"context": {"port": settings.api_port}})
        await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
        running.cancel()
        heartbeat.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(running, heartbeat, return_exceptions=True), timeout=DRAIN_SECONDS
            )
        except TimeoutError:
            logger.warning("parts did not stop within the drain budget")
        # "Stopped cleanly at 04:12" and "last seen at 04:12" are different
        # operational facts (D-060); this row is what keeps them different.
        await _write_heartbeat(kernel, identity, part_name=RUNTIME_PART_NAME, state=STOPPED_STATE)
        return EXIT_OK
    except ConfigurationError:
        logger.exception("the runtime cannot start with this configuration")
        return EXIT_CONFIGURATION
    except Exception:
        logger.exception("the runtime stopped: a dependency failed during startup")
        return EXIT_DEPENDENCY_UNAVAILABLE
    finally:
        # Set before cancelling: `_stopped` blocks a pooled thread on
        # `Event.wait()`, and `asyncio.run` waits for that pool at loop close.
        # Cancelling the task alone would leave the thread parked forever and
        # the process would hang on exit instead of stopping.
        stop.set()
        stopping.cancel()
        await kernel.aclose()


def serve_headless() -> int:
    """Console entrypoint: ``jarvis-run``. The platform, with no window.

    Never opens a window and never opens a browser — this module does not
    import `jarvis.shell.desktop` and `tests/test_one_part_table.py` asserts it
    stays that way. There is no window whose close event can end the runtime,
    which is the difference between this and the console (design 1.2).

    Returns:
        A process exit code, which the generated console script passes to
        `sys.exit`. 0 clean, 2 dependency-unavailable, 3 configuration-refused
        (design 2.3) — the interface between the Supervisor's tier and the
        operating system's.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:
        logger.exception("configuration is invalid; not starting")
        return EXIT_CONFIGURATION
    try:
        migration_config()  # fail fast on an installation that cannot migrate
    except ConfigurationError:
        logger.exception("the installation root holds no migrations; not starting")
        return EXIT_CONFIGURATION

    stop = threading.Event()
    install_signal_handlers(stop)
    try:
        return asyncio.run(_serve(settings, stop))
    except KeyboardInterrupt:  # Ctrl-C between signal delivery and the handler
        return EXIT_OK
