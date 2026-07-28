"""The Jarvis launcher: ``python -m jarvis`` (decisions D-016, D-017).

Runs every part under the Supervisor: a crashed worker restarts with backoff
and shows as "restarting" in the app's own health banner — the user never
meets a dead process. With the ``desktop`` extra installed, the dashboard opens
in a native window and closing it quits Jarvis; otherwise the browser opens.

One command, one process, everything running: preflight, service auto-start,
migrations, the operator API and dashboard, the Temporal worker, the
scheduler sweep, and the Executive's own budget/health tick (D-041) — with
clear degradation when a dependency is missing rather than a stack trace.

**Topology, not architecture.** Production keeps the worker and API as separate
processes; the architecture's boundaries are unchanged. This module is a third
composition root (with `kernel/container.py` and `runtime/worker.py`) that wires
the same components into a single developer process. Nothing here holds logic —
if a behaviour matters, it lives in the component and this file merely starts
it. The layering test's exemption list names this file for exactly that reason.

Degradation ladder:
- Database down → try to start Docker services, re-check, and only then refuse
  (there is nothing to show without it).
- Temporal down → API and dashboard run; companies can't act; the dashboard
  banner says so in operator language.
- No LLM key → everything runs; companies can't think; banner says so.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from pathlib import Path

import uvicorn

from jarvis.api.app import create_app
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.logging import get_logger
from jarvis.shell import desktop
from jarvis.shell.preflight import Status, run_preflight
from jarvis.shell.supervisor import StartupOutcome, Supervisor

logger = get_logger(__name__)

BANNER = r"""
   Jarvis — starting up
"""


def _ready_banner(port: int) -> str:
    """Printed only once startup actually reaches the point of serving it — never
    as an upfront claim that may turn out false."""
    return f"\n   Jarvis — your companies, running\n   Dashboard: http://localhost:{port}\n"


async def _try_start_services() -> bool:
    """Attempt ``docker compose up -d`` if Docker and a compose file exist.

    Best-effort by design: the shell starts what it can. Returns whether the
    attempt was made, not whether it succeeded — the re-check afterwards is
    what decides that.

    Runs the subprocess call off the event loop via `asyncio.to_thread`.
    `subprocess.run` blocks its calling thread until the process exits; called
    directly from a coroutine it freezes the *entire* event loop — including
    Ctrl-C handling — for however long ``docker compose`` takes. Every other
    blocking call in this module (`_apply_migrations`) was already offloaded
    this way; this one was missed.
    """
    if shutil.which("docker") is None or not await asyncio.to_thread(
        Path("docker-compose.yml").exists
    ):
        return False
    logger.info("starting services", extra={"context": {"via": "docker compose up -d"}})
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "compose", "up", "-d"],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return True


def _apply_migrations() -> None:
    """Apply migrations in-process. Idempotent; safe on every launch."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


def _supervisor_parts(supervisor: Supervisor) -> list[dict[str, object]]:
    """Render the Supervisor's live part statuses for `/api/health`'s `parts`
    field (M10-F1). A crashed part therefore shows as "restarting" in the
    dashboard's health banner rather than the operator meeting a dead
    terminal — the claim `run_worker`'s docstring makes (`worker.py:47-53`)."""
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
    (M10-F1). This module used to register a *second* route at the same path
    to add Supervisor part statuses — Starlette's first-match routing meant
    `create_app`'s own route always won and this one was permanently dead
    code, so `parts` was `[]` here too even though a real Supervisor exists.
    Fixed by handing `create_app` a `parts_provider` closure instead of
    competing with its route.
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
    """Run the §9 timer sweep and event wakes."""
    from jarvis.runtime.worker import run_scheduler

    await run_scheduler(kernel)


async def _run_executive(kernel: PlatformKernel) -> None:
    """Run the Executive Layer's deterministic tick (D-041)."""
    from jarvis.runtime.worker import run_executive

    await run_executive(kernel)


async def _watch_stop(stop: threading.Event) -> None:
    """End the run when the main thread signals shutdown (D-017).

    In window mode the main thread owns pywebview and sets this event when the
    operator closes the window. `threading.Event` is the coordination point
    between the two threads; an asyncio primitive would not be settable from
    outside the loop. `stop.wait()` blocks its calling thread until the event
    is set, so it runs on a worker thread via `asyncio.to_thread` rather than
    polling `is_set()` on the event loop.
    """
    await asyncio.to_thread(stop.wait)
    raise asyncio.CancelledError


async def launch(
    *,
    startup: StartupOutcome | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Bring everything up, degrade where necessary, and say so plainly.

    Args:
        startup: Cross-thread startup outcome. `serving` is set True only once the
            dashboard port is actually bound; `done` is set on every exit path so a
            waiting thread is never stranded.
        stop: Watched for shutdown requests from another thread.
    """
    print(BANNER)
    settings = Settings()  # type: ignore[call-arg]
    kernel = PlatformKernel(settings)

    report = await run_preflight(kernel)
    if not report.can_serve and await _try_start_services():
        print("  Waiting for services to come up...")
        for attempt in range(24):  # up to ~2 minutes for first-time image pulls
            await asyncio.sleep(5)
            report = await run_preflight(kernel)
            if report.can_serve:
                break
            if attempt % 3 == 2:  # a visible heartbeat every ~15s, not silence
                print(f"  Still waiting ({(attempt + 1) * 5}s)...")

    for component in report.components:
        marker = {"ok": "  ✓", "degraded": "  ~", "down": "  ✗"}[component.status.value]
        line = f"{marker} {component.summary}"
        if component.remedy and component.status is not Status.OK:
            line += f"  →  {component.remedy}"
        print(line)

    if not report.can_serve:
        print("\n  Jarvis can't start without its database. Fix the above and rerun.")
        if startup is not None:
            startup.done.set()  # serving stays False; the caller will not open a window
        await kernel.aclose()
        return

    await asyncio.to_thread(_apply_migrations)
    await kernel.ensure_builtin_types()

    print(_ready_banner(settings.api_port))
    supervisor = Supervisor()
    supervisor.add("api", "Dashboard", lambda: _serve_api(kernel, supervisor, settings.api_port))
    supervisor.add("worker", "Company runner", lambda: _run_worker_when_possible(kernel))
    supervisor.add("scheduler", "Timers and reminders", lambda: _run_scheduler(kernel))
    supervisor.add("executive", "Budget and health checks", lambda: _run_executive(kernel))

    # Signal readiness only once the port is actually bound. Opening a window or a
    # browser tab before then shows a connection error as the operator's first
    # impression of the application.
    bound = await asyncio.to_thread(desktop.wait_for_dashboard, port=settings.api_port)
    if not bound:
        logger.warning("dashboard did not bind within the timeout")
    if startup is not None:
        startup.serving = bound
        startup.done.set()
    elif bound:
        desktop.open_browser(port=settings.api_port)

    print("\n  Ready. Close the window or press Ctrl-C to stop.\n")
    watchers = [supervisor.run_until_stopped()]
    if stop is not None:
        watchers.append(_watch_stop(stop))
    try:
        await asyncio.gather(*watchers)
    except asyncio.CancelledError:
        pass
    finally:
        await kernel.aclose()


def _launch_in_thread(startup: StartupOutcome, stop: threading.Event) -> threading.Thread:
    """Run the asyncio launch on a background thread.

    Needed because pywebview requires the main thread (finding M5-F6), so the
    event loop cannot have it. Daemon, so an unexpected hang in shutdown cannot
    keep the process alive after the window closes.
    """

    def _run() -> None:
        try:
            asyncio.run(launch(startup=startup, stop=stop))
        except Exception:
            logger.exception("Jarvis stopped with an error")
            startup.serving = False
        finally:
            startup.done.set()  # never leave the main thread waiting on a dead loop

    thread = threading.Thread(target=_run, name="jarvis-services", daemon=True)
    thread.start()
    return thread


def main() -> None:
    """Console entrypoint: ``jarvis`` or ``python -m jarvis``.

    Two topologies, chosen by whether a native window is available:

    * **Window mode** — the main thread runs pywebview and the services run on a
      background thread. This ownership is forced by the platform: native GUI
      toolkits require the main thread, and pywebview raises if started anywhere
      else (finding M5-F6).
    * **Browser mode** — the services own the main thread as usual and the default
      browser is opened once the port is bound.
    """
    if not desktop.window_available():
        try:
            asyncio.run(launch())
        except KeyboardInterrupt:
            print("\n  Stopped.")
        return

    startup, stop = StartupOutcome(done=threading.Event()), threading.Event()
    services = _launch_in_thread(startup, stop)

    # Wait for the services to bind, or to fail. Bounded so a startup that never
    # completes doesn't hang the process without explanation.
    if not startup.done.wait(timeout=180):
        print("\n  Jarvis didn't finish starting up. See the messages above.")
        stop.set()
        return
    if not startup.serving:
        # Checked explicitly rather than via Thread.is_alive(), which races: a
        # failed launch stays briefly alive and the window would open onto a
        # backend that had already died.
        print("\n  Jarvis stopped during startup. See the messages above.")
        stop.set()
        return

    # `launch()` already built its own `Settings()` on the services thread; this
    # one is for the main thread, which never sees that instance. Settings reads
    # only the environment and `.env`, so building it twice costs nothing and
    # keeps this thread's view of the port consistent with the one that bound it.
    port = Settings().api_port  # type: ignore[call-arg]
    try:
        desktop.run_window_blocking(port=port)
    except KeyboardInterrupt:
        pass
    except Exception:
        # A window that cannot open must not take the application down: fall back
        # to the browser and keep serving.
        logger.exception("couldn't open the app window; falling back to the browser")
        desktop.open_browser(port=port)
        try:
            while services.is_alive():
                services.join(timeout=0.5)
        except KeyboardInterrupt:
            pass
    finally:
        stop.set()
        services.join(timeout=15)
    print("\n  Stopped.")


if __name__ == "__main__":
    main()
