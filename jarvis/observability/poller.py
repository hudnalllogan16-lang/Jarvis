"""The second liveness signal's fact type (design OPERATIONAL-RUNTIME.md Part
3.2 Signal 2, D-058, packet P0-C) — Temporal's own poller count, read
independently of anything the runtime says about itself.

Lives beside `heartbeat.py` rather than inside it: `heartbeat.py` (packet
P0-B) already recorded that it "deliberately does not build the design's full
two-signal `assess_runtime_liveness`" because that needs the Temporal probe,
which lands in the Executive as an L1 rule (`jarvis/executive/liveness.py`).
This module is the narrow slice that *is* a fact rather than a verdict — a
plain, dependency-free reading of "how many pollers, how recently" — and it
earns its own home for a layering reason the verdict does not: both
`jarvis/api/app.py` (M3, `/api/health`'s `workers` component) and
`jarvis/executive/liveness.py` (M9, the verdict) need this *type*, and
`jarvis/observability` (M1) is the only package earlier than both.

**Never imports `temporalio`.** The actual `DescribeTaskQueue` call belongs to
whichever composition root or M3 route needs a live reading —
`jarvis/runtime/worker.py::probe_task_queue_pollers` is the one built so far —
so that a Temporal client, and the ability to fail talking to one, never
enters a package other code depends on being pure and offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final


@dataclass(frozen=True, slots=True)
class PollerReading:
    """One `DescribeTaskQueue` reading, injected as a value (design 3.3).

    Never constructed by anything in `jarvis/executive/` or `jarvis/api/` —
    both receive an already-read instance, exactly as `platform_ceiling_usd`
    is already handed to the Executive tick as a value rather than a
    collaborator it could read for itself (`jarvis/runtime/worker.py`).

    `reachable=False` is Part 3.2's fourth failure row made a type-level
    fact: Temporal being unreachable and Temporal reporting zero pollers are
    different sentences, and this shape makes conflating them a type error
    rather than a missed comparison — the poller counts below are simply not
    populated (and must not be read) when `reachable` is False.
    """

    reachable: bool
    workflow_pollers: int = 0
    activity_pollers: int = 0
    newest_last_access_at: datetime | None = None
    """The newest `last_access_time` across every reported poller of either
    queue type (design 3.2's Signal 2), or None if there were none to read.
    Only meaningful when `reachable` is True."""


UNREACHABLE_POLLER_READING: Final[PollerReading] = PollerReading(reachable=False)
"""The one legitimate way to represent "we cannot tell" — never a `PollerReading`
with `reachable=True` and zero counts, which would say "nothing is listening"
about a question that was never actually asked (design 3.2's warning against
manufacturing the false alarm that trains operators to ignore the real one)."""


def summarise_worker_health(
    poller: PollerReading,
    *,
    now: datetime,
    poller_stale_after_seconds: float,
) -> tuple[str, str]:
    """Reduce one poller reading to `/api/health`'s `workers` component (design 3.4).

    Deliberately not the same function as `heartbeat.summarise_runtime_health`:
    that one folds several parts' self-reports into one `runtime` reading, and
    this one describes a single external fact. The two components are reported
    side by side, never merged (design 3.4's table) — a reader who wants the
    combined two-signal verdict is the Executive's `runtime.liveness_verdict`
    L1 rule, not this route.

    Args:
        poller: One reading, from `jarvis.runtime.worker.probe_task_queue_pollers`
            or an equivalent probe.
        now: The instant to assess staleness against (no uninjected clock).
        poller_stale_after_seconds: `settings.heartbeat.poller_stale_after_seconds`.

    Returns:
        ``(status, summary)`` — ``status`` is one of ``ok``/``degraded``/
        ``down``/``unknown`` (design 3.4's own four); ``summary`` is one plain
        sentence, safe for the operator surface (spec §12.5: no queue name, no
        poller identity, no mechanism).
    """
    if not poller.reachable:
        return (
            "unknown",
            "Jarvis can't tell whether anything is picking up work right now.",
        )

    if poller.workflow_pollers <= 0 or poller.activity_pollers <= 0:
        return "down", "Nothing is picking up work for your companies right now."

    if poller.newest_last_access_at is None:
        return "down", "Nothing is picking up work for your companies right now."

    age_seconds = (now - _aware(poller.newest_last_access_at)).total_seconds()
    if age_seconds <= poller_stale_after_seconds:
        return "ok", "Jarvis is picking up work as expected."

    return "degraded", "Jarvis is connected but isn't picking up work as quickly as usual."


def _aware(value: datetime) -> datetime:
    """Coerce a possibly-naive timestamp to UTC-aware.

    Protobuf's `Timestamp.ToDatetime` hands back an aware value when given a
    `tzinfo`, which `jarvis.runtime.worker.probe_task_queue_pollers` already
    does — this guard exists for the same dialect-safety reason
    `heartbeat._aware` and `alerts._halt_already_explained` keep their own
    copies rather than trusting every caller to pass an aware value.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "UNREACHABLE_POLLER_READING",
    "PollerReading",
    "summarise_worker_health",
]
