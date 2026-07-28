"""The Jarvis operator console: ``jarvis`` / ``python -m jarvis`` (D-016, D-017).

Runs every part under the Supervisor: a crashed worker restarts with backoff
and shows as "restarting" in the app's own health banner — the user never
meets a dead process. With the ``desktop`` extra installed, the dashboard opens
in a native window and closing it quits Jarvis; otherwise the browser opens.

**A console, not the platform (design OPERATIONAL-RUNTIME.md 1.2, packet
P0-A).** The part table and the bootstrap sequence now live in
`jarvis/shell/service.py` and this module adds exactly one thing to them: a
window. It can no longer be a *different* runtime from the service, because
there is only one part table and neither entrypoint writes its own.

Two things stay this module's alone, and both are consequences of a human being
present:

- **The `REFUSE` posture.** A developer who typed a command is there to read
  the ladder and fix it; a service that exits because Postgres was three
  seconds late is a service that has outsourced dependency ordering to its
  restarter (M10-F15).
- **`docker compose up -d`.** Docker Desktop belongs to a user session, so a
  service running as LocalSystem must never start it (M10-F11).

When a runtime is already serving on the dashboard port — `jarvis-run` under a
service manager, or a container — the console **attaches** to it and starts no
parts (design 6.3). Closing the window then does nothing to the platform, which
is the owner's criterion stated as a measurement.

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

from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.logging import get_logger
from jarvis.shell import desktop, service
from jarvis.shell.preflight import HealthReport, Posture, Status
from jarvis.shell.supervisor import StartupOutcome

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
    Ctrl-C handling — for however long ``docker compose`` takes.

    The compose file is looked up under the installation root rather than the
    working directory (M10-F10): the same probe returned False whenever the
    console was started from anywhere but the repository.
    """
    compose = service.installation_root() / "docker-compose.yml"
    if shutil.which("docker") is None or not await asyncio.to_thread(compose.is_file):
        return False
    logger.info("starting services", extra={"context": {"via": "docker compose up -d"}})
    print("  Waiting for services to come up...")
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "compose", "up", "-d"],
            check=False,
            capture_output=True,
            timeout=120,
            cwd=service.installation_root(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return True


def _print_ladder(report: HealthReport) -> None:
    """Print the preflight ladder the way the console always has.

    The console's, not the service's: `bootstrap` writes the same facts to the
    log for a process with nobody watching it, and hands them here for one with
    somebody watching.
    """
    for component in report.components:
        marker = {"ok": "  ✓", "degraded": "  ~", "down": "  ✗"}[component.status.value]
        line = f"{marker} {component.summary}"
        if component.remedy and component.status is not Status.OK:
            line += f"  →  {component.remedy}"
        print(line)


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

    report = await service.bootstrap(
        kernel,
        on_unavailable=Posture.REFUSE,
        recover=_try_start_services,
        announce=print,
        on_report=_print_ladder,
    )
    if not report.can_serve:
        print("\n  Jarvis can't start without its database. Fix the above and rerun.")
        if startup is not None:
            startup.done.set()  # serving stays False; the caller will not open a window
        await kernel.aclose()
        return

    print(_ready_banner(settings.api_port))
    supervisor = service.build_supervisor(kernel)

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


def _attach(port: int) -> None:
    """Open the console onto a runtime that is already serving (design 6.3).

    Starts no parts, so closing the window is a no-op for the platform — the
    owner's headline criterion, and what makes this an operator console rather
    than the platform itself.

    Args:
        port: The dashboard port that already answered.
    """
    print(f"\n   Jarvis is already running. Opening the console on port {port}.\n")
    if desktop.window_available():
        desktop.run_window_blocking(port=port)
    else:
        desktop.open_browser(port=port)


def main() -> None:
    """Console entrypoint: ``jarvis`` or ``python -m jarvis``.

    Three paths. The first is the one that makes this a console:

    * **Attach** — something already answers on the dashboard port, so a
      runtime is hosted elsewhere (`jarvis-run` under a service manager, or a
      container). Show it; start nothing. Competing for the port would give the
      operator a crash-looping API part and a *second* set of companies being
      run (design 6.3).
    * **Window mode** — the main thread runs pywebview and the services run on a
      background thread. This ownership is forced by the platform: native GUI
      toolkits require the main thread, and pywebview raises if started anywhere
      else (finding M5-F6).
    * **Browser mode** — the services own the main thread as usual and the default
      browser is opened once the port is bound.
    """
    # `launch()` builds its own `Settings()` on the services thread; this one is
    # for the main thread, which never sees that instance. Settings reads only
    # the environment and `.env`, so building it twice costs nothing and keeps
    # this thread's view of the port consistent with the one that bound it.
    port = Settings().api_port  # type: ignore[call-arg]

    if desktop.dashboard_is_serving(port=port):
        _attach(port)
        return

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
