"""Process-internal supervision (decision D-017).

A desktop application's parts are not the user's problem. When the worker
crashes, the user must see "the part that runs companies is restarting" in the
app — never a dead terminal. The launcher therefore runs every long-lived part
under this supervisor: crash → log → backoff → restart, with status queryable
for the health surface.

Deliberately not a workflow and not a service registry — it supervises asyncio
tasks inside one process, nothing more. Backoff doubles per consecutive crash
and resets after a part stays up, so a boot-time race retries fast while a
genuinely broken part settles into slow, visible retries instead of a hot loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
STABLE_AFTER = 30.0
"""Seconds a part must stay up before its crash count resets."""

DEFAULT_FAILING_AFTER_CRASHES = 10
"""Consecutive crashes at which a part's state becomes `failing` rather than
`restarting` (design OPERATIONAL-RUNTIME.md Part 5.4, the crash-loop honesty
rule; packet P0-E). Ten minutes of failure at the capped 60s backoff by
default — module-level default; the live value is
`Settings.heartbeat.part_failing_after_crashes`, threaded in by
`jarvis/shell/service.py::build_supervisor` the same way `sleep` is already
injected below, so this constant is what a caller gets by not overriding it
rather than what the platform actually runs on.

This changes nothing about *what happens*: Tier 1 never gives up on a part
(D-017) and the restart loop below is unconditional either way. Crossing this
threshold only relabels the state `/api/health` and the `runtime_heartbeat`
rows report, so a part that has been "restarting" for six hours stops being
described as if it were still coping. Whether and how that relabeling gets
announced to an operator is the Executive's `runtime.liveness_verdict` (D-038
layering; design 3.3, packet P0-C) reading these facts — this module only
records the state, it never notifies."""


@dataclass
class StartupOutcome:
    """Cross-thread startup result, for launchers that don't own the main thread.

    `done` is set on every exit path, successful or not, so a waiting thread is
    never stranded. `serving` says whether startup actually succeeded.

    Two fields rather than inferring success from `Thread.is_alive()`, because that
    is a race: a launch that raises leaves its thread briefly alive, and a caller
    checking liveness would proceed as though startup had worked — opening a window
    onto a backend that had already died (finding M5-F6).
    """

    done: threading.Event
    serving: bool = False


class PartState(StrEnum):
    """What one supervised part is doing right now."""

    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILING = "failing"
    """`RESTARTING` for `part_failing_after_crashes` consecutive crashes in a
    row with no stable interval between them (design 5.4). The Supervisor
    keeps restarting the part exactly as it would under `RESTARTING` — this
    is a more honest label for the same behaviour, not a different one."""
    STOPPED = "stopped"


@dataclass
class PartStatus:
    """Live status of one part, for the health surface."""

    name: str
    operator_label: str
    """Plain name for the UI (spec §12.5) — "Company runner", never "worker"."""

    state: PartState = PartState.STARTING
    consecutive_crashes: int = 0
    last_error: str = ""
    """Drill-down only; the UI shows the label and state."""


class Supervisor:
    """Runs named coroutines forever, restarting them with backoff."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        failing_after_crashes: int = DEFAULT_FAILING_AFTER_CRASHES,
    ) -> None:
        """Args:
        sleep: Injectable delay so restart tests do not wait real seconds.
        failing_after_crashes: Consecutive-crash threshold for the `failing`
            state (design 5.4). `jarvis/shell/service.py::build_supervisor`
            passes `Settings.heartbeat.part_failing_after_crashes`; the
            module default here is what a caller gets by not overriding it.
        """
        self._parts: dict[str, PartStatus] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._sleep = sleep
        self._stopping = False
        self._failing_after_crashes = failing_after_crashes

    def add(
        self,
        name: str,
        operator_label: str,
        factory: Callable[[], Awaitable[None]],
    ) -> None:
        """Register a part.

        Args:
            name: Internal identifier.
            operator_label: What the UI calls it (§12.5).
            factory: Builds a fresh coroutine per (re)start. A factory rather
                than a coroutine because a crashed coroutine cannot be
                re-awaited — each restart needs a new one.
        """
        status = PartStatus(name=name, operator_label=operator_label)
        self._parts[name] = status
        self._tasks.append(asyncio.ensure_future(self._run(status, factory)))

    async def _run(self, status: PartStatus, factory: Callable[[], Awaitable[None]]) -> None:
        backoff = INITIAL_BACKOFF
        loop = asyncio.get_running_loop()
        while not self._stopping:
            status.state = PartState.RUNNING
            started = loop.time()
            try:
                await factory()
            except asyncio.CancelledError:
                status.state = PartState.STOPPED
                raise
            except Exception as exc:
                if loop.time() - started >= STABLE_AFTER:
                    status.consecutive_crashes = 0
                    backoff = INITIAL_BACKOFF
                status.consecutive_crashes += 1
                status.last_error = f"{type(exc).__name__}: {exc}"[:300]
                status.state = (
                    PartState.FAILING
                    if status.consecutive_crashes >= self._failing_after_crashes
                    else PartState.RESTARTING
                )
                logger.warning(
                    "part crashed; restarting",
                    extra={
                        "context": {
                            "part": status.name,
                            "crashes": status.consecutive_crashes,
                            "backoff_s": backoff,
                            "state": status.state.value,
                        }
                    },
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                # A part that returns cleanly is finished, not crashed.
                status.state = PartState.STOPPED
                return

    def statuses(self) -> list[PartStatus]:
        """Return every part's live status, for /api/health."""
        return list(self._parts.values())

    async def run_until_stopped(self) -> None:
        """Block until every part stops or the supervisor is cancelled."""
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            self._stopping = True
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            raise
