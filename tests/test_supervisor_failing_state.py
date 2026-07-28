"""The crash-loop honesty rule (design OPERATIONAL-RUNTIME.md Part 5.4;
packet P0-E).

Before this, `Supervisor` tracked `consecutive_crashes` but a part that had
been crashing and restarting for hours still reported `RESTARTING` — the same
word a part crashing for the first time uses. Design 5.4's fix is a relabel,
not a mechanism change: at `failing_after_crashes` consecutive crashes (10 by
default, `Settings.heartbeat.part_failing_after_crashes`) the part's state
becomes `FAILING`, and the Supervisor keeps restarting it exactly as before
(Tier 1 never gives up on a part, D-017) — this module records the state; it
never notifies, which is the Executive's `runtime.liveness_verdict` (D-038
layering, packet P0-C) reading these facts back through the heartbeat rows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from jarvis.shell.supervisor import (
    DEFAULT_FAILING_AFTER_CRASHES,
    PartState,
    PartStatus,
    Supervisor,
)

# ── HeartbeatSettings.part_failing_after_crashes: the Settings-driven value ──


def test_part_failing_after_crashes_defaults_to_ten() -> None:
    from jarvis.kernel.config import HeartbeatSettings

    assert HeartbeatSettings().part_failing_after_crashes == DEFAULT_FAILING_AFTER_CRASHES == 10


def test_part_failing_after_crashes_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.kernel.config import LLMSettings, Settings

    monkeypatch.setenv("JARVIS_HEARTBEAT__PART_FAILING_AFTER_CRASHES", "5")
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.heartbeat.part_failing_after_crashes == 5


def _stop_after(n: int) -> Callable[[float], Awaitable[None]]:
    """An injectable `sleep` that lets exactly ``n`` crash/backoff cycles
    happen, then ends the loop the same way `test_executive_runner.py`'s
    scripted `run_executive` tests do — by raising, at the point the part's
    ``n``th crash has already updated its status but before it restarts a
    (``n + 1``)th time."""
    calls = {"i": 0}

    async def _sleep(_seconds: float) -> None:
        calls["i"] += 1
        if calls["i"] >= n:
            raise asyncio.CancelledError

    return _sleep


async def _run_and_stop(supervisor: Supervisor, status: PartStatus, factory: object) -> None:
    with pytest.raises(asyncio.CancelledError):
        await supervisor._run(status, factory)  # type: ignore[arg-type]


def _always_crashes(attempts: dict[str, int]) -> Callable[[], Awaitable[None]]:
    async def _factory() -> None:
        attempts["n"] += 1
        raise RuntimeError("boom")

    return _factory


async def test_a_part_becomes_failing_at_the_default_threshold() -> None:
    supervisor = Supervisor(sleep=_stop_after(DEFAULT_FAILING_AFTER_CRASHES))
    status = PartStatus(name="worker", operator_label="Company runner")

    await _run_and_stop(supervisor, status, _always_crashes({"n": 0}))

    assert status.consecutive_crashes == DEFAULT_FAILING_AFTER_CRASHES
    assert status.state is PartState.FAILING


async def test_a_part_below_the_threshold_stays_restarting() -> None:
    below = DEFAULT_FAILING_AFTER_CRASHES - 1
    supervisor = Supervisor(sleep=_stop_after(below))
    status = PartStatus(name="worker", operator_label="Company runner")

    await _run_and_stop(supervisor, status, _always_crashes({"n": 0}))

    assert status.consecutive_crashes == below
    assert status.state is PartState.RESTARTING


async def test_the_threshold_is_configurable() -> None:
    """`build_supervisor` threads `Settings.heartbeat.part_failing_after_crashes`
    in; this proves the Supervisor actually honours a non-default value."""
    supervisor = Supervisor(sleep=_stop_after(3), failing_after_crashes=3)
    status = PartStatus(name="worker", operator_label="Company runner")

    await _run_and_stop(supervisor, status, _always_crashes({"n": 0}))

    assert status.consecutive_crashes == 3
    assert status.state is PartState.FAILING


async def test_a_failing_part_keeps_being_restarted_tier_1_never_gives_up() -> None:
    """The load-bearing property design 5.4 states explicitly: crossing the
    threshold changes only the label, never whether the part is restarted."""
    total_crashes = DEFAULT_FAILING_AFTER_CRASHES + 3
    supervisor = Supervisor(sleep=_stop_after(total_crashes))
    status = PartStatus(name="worker", operator_label="Company runner")
    attempts = {"n": 0}

    await _run_and_stop(supervisor, status, _always_crashes(attempts))

    assert attempts["n"] == total_crashes  # the factory kept being retried
    assert status.consecutive_crashes == total_crashes
    assert status.state is PartState.FAILING


async def test_a_part_that_never_crashes_is_never_failing() -> None:
    """Negative control: `RUNNING` is set unconditionally at the top of every
    iteration, so a part that simply finishes (returns cleanly) must read
    `STOPPED`, never `FAILING`, however the crash count happens to sit."""
    supervisor = Supervisor()
    status = PartStatus(name="worker", operator_label="Company runner")

    async def _finishes_cleanly() -> None:
        return None

    await supervisor._run(status, _finishes_cleanly)  # type: ignore[arg-type]

    assert status.state is PartState.STOPPED
    assert status.consecutive_crashes == 0
