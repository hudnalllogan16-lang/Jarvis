"""The two-signal liveness verdict (design OPERATIONAL-RUNTIME.md Part 3.2/3.3/
5.4/7.1, D-058, D-061, packet P0-C) — the founding mandate's own exhibit
(M10-F12: zero pollers, thirteen and a half hours, `/api/health` reporting the
workflow runtime reachable because it was).

**Facts in, verdict out.** Everything this module reads is already a fact
recorded elsewhere — `HeartbeatStore` rows (`jarvis.observability.heartbeat`,
packet P0-B) and a `PollerReading` (`jarvis.observability.poller`, packet
P0-C). Nothing here computes either signal; :func:`assess_runtime_liveness`
only compares the two the way design 3.2's table does, and
:func:`raise_runtime_liveness_alerts` is the one place that turns a changed
comparison into an audit record and a notice — "the component that enforces
the rule is the component that announces it" (design 1.6), and the reason
`runtime.liveness_verdict` has exactly one emit site.

**The probe is a value, never a dependency (D-038).** This package may import
`registry`, `budget`, `kpi`, `observability`, `notifications`, `kernel`,
`domain` and itself (`tests/test_executive_import_boundary.py`) — `runtime`
and `temporalio` are not on that list, on purpose, so nothing here can reach
for a Temporal client even by accident. `jarvis.runtime.worker` (a composition
root) builds the `PollerReading` this module consumes and hands it over
already read, exactly as `platform_ceiling_usd` is already handed to the
Executive tick as a value rather than a collaborator (`jarvis.executive.
runner.run_executive_tick`).

**Two conditions, two different notify shapes, both real per design.**

- **The outage verdict** (design 3.5's own illustration: "Nothing has been
  running your companies for 13 hours") is a *state*, not a recurring alert
  (D-046: "a persisting condition is a state, announced once; a recurring
  condition is an alert"). It is announced once with its start and once with
  its recovery — never once per tick it stays true — which the usual
  `NotificationService.has_unread` dedup cannot express on its own: an
  operator who has already read "it's down" would, under that dedup, be told
  again the moment they read it while the platform was still down. Instead
  this reads the *last recorded verdict* (`AuditLog.latest_platform_entry`)
  and only writes when today's verdict disagrees with it — D-046's "current
  state is re-derived on read, never stored" made literal: there is no
  separate "are we currently down" column to drift out of sync with the
  audit trail that is already the record of every time this was asked.
- **A crash-looping part** (design 5.4) recurs by nature — a part can crash
  loop, get noticed, keep crash-looping — and design 5.4 says so explicitly:
  "deduped exactly like D-053's `UNFINISHED_ROUND`", i.e. `has_unread` per
  condition, the ordinary shape every other L1 notice in this platform uses.

Both ride the single `runtime.liveness_verdict` registry row (design 7.1):
design's own governance table adds exactly one new action for this packet,
not two, so a part crash-looping is a second *fact* this rule announces, not
a second *rule*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from jarvis.kernel.ids import new_notification_id
from jarvis.kernel.logging import get_logger
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.heartbeat import HeartbeatStore
from jarvis.observability.poller import PollerReading

logger = get_logger(__name__)

RUNTIME_LIVENESS_EVENT: Final[str] = "runtime.liveness_transition"
"""The audit entry beside the notice (design 7.1's AUDIT obligation, §11).

Written only on a transition, mirroring D-046 rather than one row per tick —
a runtime that stayed down for a week would otherwise write 672 identical
rows at the default cadence, which is exactly the "log that repeats itself is
a log nobody reads" defect design 5.2 fixes for the sweep. The audit log's
own trail of transitions is also what :func:`raise_runtime_liveness_alerts`
reads back to tell a new outage from a continuing one — see the module
docstring."""


# ── the verdict: pure, no I/O (design 3.2) ──────────────────────────────────


@dataclass(frozen=True, slots=True)
class RuntimeLiveness:
    """One two-signal reading. Produced by :func:`assess_runtime_liveness`.

    `reason` is internal only — a phrase for logs and audit payloads, never
    rendered to an operator (spec §12.5); :func:`raise_runtime_liveness_alerts`
    renders its own fixed copy from `outage` alone, the same discipline
    `jarvis.executive.alerts._spend_body` holds for `SpendAlert.band`.
    """

    outage: bool
    reason: str


def _aware(value: datetime) -> datetime:
    """Coerce a possibly-naive timestamp to UTC-aware.

    The same dialect gap `jarvis.observability.heartbeat._aware`,
    `jarvis.observability.poller._aware` and `jarvis.executive.alerts.
    _halt_already_explained` each keep their own copy of: SQLite hands back
    naive what Postgres stores with an offset, and every row here is written
    from `datetime.now(UTC)` either way.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _freshest(beats: Any, part_name: str) -> Any | None:
    """Return `part_name`'s most recently beaten row among `beats`, or None.

    A restart mints a fresh `runtime_id` (design 3.2), so more than one row
    can share a `part_name` — the newest one is what is true now, the same
    reduction `jarvis.observability.heartbeat.summarise_runtime_health`
    already applies across every part at once. This does it for one.
    """
    freshest: Any | None = None
    for beat in beats:
        if beat.part_name != part_name:
            continue
        if freshest is None or _aware(beat.last_beat_at) > _aware(freshest.last_beat_at):
            freshest = beat
    return freshest


def assess_runtime_liveness(
    beats: Any,
    poller: PollerReading,
    *,
    now: datetime,
    heartbeat_stale_after_seconds: float,
    poller_stale_after_seconds: float,
) -> RuntimeLiveness:
    """Compare the two signals design 3.2's table names and return one verdict.

    Centred on the ``worker`` part deliberately: that is the part that
    actually serves a company's round (design 3.5's "Nothing has been
    running your companies"), so its self-report — not `scheduler`'s or
    `executive`'s — is the heartbeat half of this comparison. A dead
    scheduler with a healthy worker is a real problem, but it is not *this*
    outage, and folding it in here would make this verdict wrong about the
    one thing it exists to be right about (row 3 of design 3.2's table:
    "scheduler or executive part dead, worker fine" reads `outage=False`).

    Table 3.2's four rows, verified by this function's own tests:

    - **process killed** — heartbeat stale, pollers reachable and zero ->
      `outage=True`.
    - **worker wedged inside a poll that never returns** — heartbeat reads
      `running` (a lie) but pollers are reachable and stale -> `outage=True`,
      the exact case a single signal gets wrong.
    - **scheduler or executive dead, worker fine** — worker heartbeat fresh,
      pollers healthy -> `outage=False`; the other parts' trouble is `/api/
      health`'s `parts` array's problem, not this verdict's.
    - **Temporal down, runtime healthy** — `poller.reachable` is False ->
      trust the self-report alone; `outage=False` if the worker heartbeat is
      fresh. Never reported as `outage=True` from an unreachable probe alone
      (design 3.2: "unreachable is not served... never zero").

    Args:
        beats: Every stored heartbeat row (duck-typed: `.part_name`,
            `.state`, `.last_beat_at` — the same rows `HeartbeatStore.rows()`
            already returns; not type-imported here so this package never
            needs `jarvis.persistence` in scope, D-038).
        poller: One `PollerReading`, already read by the composition root.
        now: The instant to assess freshness against (D-004, D-038 — no
            uninjected clock).
        heartbeat_stale_after_seconds: `settings.heartbeat.
            heartbeat_stale_after_seconds` — the same threshold `/api/
            health`'s `runtime` component reads, so the two never disagree
            about what "fresh" means (design Part 11's sequencing note,
            applied to a threshold rather than a figure).
        poller_stale_after_seconds: `settings.heartbeat.
            poller_stale_after_seconds`.

    Returns:
        One verdict. Pure: no clock read, no database, no notification.
    """
    worker = _freshest(beats, "worker")
    worker_serving = (
        worker is not None
        and worker.state == "running"
        and (now - _aware(worker.last_beat_at)).total_seconds() <= heartbeat_stale_after_seconds
    )

    if not poller.reachable:
        if worker_serving:
            return RuntimeLiveness(outage=False, reason="heartbeat fresh; pollers unreachable")
        return RuntimeLiveness(outage=True, reason="heartbeat stale or absent; pollers unreachable")

    pollers_serving = (
        poller.workflow_pollers > 0
        and poller.activity_pollers > 0
        and poller.newest_last_access_at is not None
        and (now - _aware(poller.newest_last_access_at)).total_seconds()
        <= poller_stale_after_seconds
    )

    if worker_serving and pollers_serving:
        return RuntimeLiveness(outage=False, reason="heartbeat fresh; pollers serving")
    if worker_serving and not pollers_serving:
        return RuntimeLiveness(outage=True, reason="heartbeat fresh but pollers stale or zero")
    return RuntimeLiveness(outage=True, reason="heartbeat stale or absent")


def failing_parts(beats: Any, *, part_failing_after_crashes: int) -> tuple[str, ...]:
    """Return every part whose freshest beat has crossed design 5.4's threshold.

    Pure, mirroring `assess_runtime_liveness`'s own shape: every `part_name`
    reduced to its freshest row first (a restart's fresh row must outrun the
    old runtime's stale one, not be counted alongside it), then compared to
    one threshold. Sorted for a result that does not depend on read order
    (D-038's determinism).

    Args:
        beats: Every stored heartbeat row (see :func:`assess_runtime_liveness`).
        part_failing_after_crashes: `settings.heartbeat.
            part_failing_after_crashes` (design 5.4's default 10).

    Returns:
        Part names, sorted, whose `consecutive_crashes` has reached the
        threshold as of their own freshest beat.
    """
    latest: dict[str, Any] = {}
    for beat in beats:
        current = latest.get(beat.part_name)
        if current is None or _aware(beat.last_beat_at) > _aware(current.last_beat_at):
            latest[beat.part_name] = beat
    return tuple(
        sorted(
            name
            for name, row in latest.items()
            if row.consecutive_crashes >= part_failing_after_crashes
        )
    )


# ── operator copy (illustrative shape per design 3.5; §12.5 pass landed
#    packet P0-H — operator-surface-engineer) ───────────────────────────────

PART_LABELS: Final[dict[str, str]] = {
    "api": "Jarvis's dashboard",
    "worker": "the part of Jarvis that runs your companies",
    "scheduler": "the part of Jarvis that keeps things on schedule",
    "executive": "the part of Jarvis that watches spending and health",
    "runtime": "Jarvis",
}
"""`part_name` -> an operator-safe phrase. Never the raw `part_name` itself:
`"worker"` is one of §12.5's own forbidden words (`tests/surface_sources.
FORBIDDEN`), and every one of these values is checked against it
(`tests/test_executive_liveness.py`)."""

OUTAGE_TITLE: Final[str] = "Nothing has been running your companies"
OUTAGE_BODY: Final[str] = (
    "Your companies are waiting on it. Start Jarvis's background service, and "
    "they'll pick up where they left off."
)
"""Mirrors design 3.5's own illustration as closely as an implementation can:
"Nothing has been running your companies for 13 hours... Three companies are
waiting to work. Start Jarvis's background service, and they will pick up
where they left off." No duration and no company count in the *start*
notice — the platform cannot yet know how long this will last, and naming a
count here is a figure `_recovered_body` already owns once it is a fact
(D-011: never a number the caller did not read). §12.5 pass (P0-H): the
title already states what happened (nothing has been running); the body
does not repeat it in mechanism language ("stopped responding" read as a
diagnosis, not a state — the same register `_recovered_body` and
`LATE_WAKE_BODY` avoid with "wasn't running") — it states the consequence
and the one thing to do, same shape as design's own illustration with the
company count dropped for the reason above."""

RECOVERED_TITLE: Final[str] = "Jarvis is running again"


def _recovered_body(duration: timedelta) -> str:
    """Render the recovery notice's body from a measured duration (D-011).

    The only sentence in this module with a computed value in it — the
    duration is a fact this function is handed, not a figure it derives.
    """
    return (
        f"Jarvis wasn't running your companies for {_format_duration(duration)}. It's "
        f"back now, and your companies will pick up where they left off."
    )


def _format_duration(delta: timedelta) -> str:
    """Render a duration in plain language, coarsest unit first.

    Never more precise than minutes: a figure like "13 hours and 4 minutes
    and 12 seconds" reads as a system printing its own internals, not as an
    answer to "how long was it down" (§12.5's register).
    """
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 60:
        return "less than a minute"
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours == 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    hour_word = f"{hours} hour{'s' if hours != 1 else ''}"
    minute_word = f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{hour_word} and {minute_word}"


FAILING_TITLE_FMT: Final[str] = "{label} isn't recovering on its own"
FAILING_BODY: Final[str] = (
    "It has crashed and restarted many times in a row without recovering. It may need attention."
)
"""Design 5.4: "a part that has been 'restarting' for six hours is not
restarting" — the platform stops implying it is coping. No crash count and
no elapsed time in the copy: `part_failing_after_crashes` is owner-adjustable
(Parameter Register), so a number here could go stale against its own
threshold; "many times in a row" is honest at any setting."""


def _runtime_ref(*, part_name: str | None = None) -> str:
    """Return the `link_ref` naming which of `RUNTIME`'s variants a notice is.

    `part_name=None` names the whole-runtime outage/recovery pair (one
    shared ref, since a recovery notice must find the *same* row a start
    notice would have — though neither is deduped by `has_unread`; see the
    module docstring). A part name narrows to that part's own crash-loop
    condition, `has_unread`-deduped exactly like D-053's `UNFINISHED_ROUND`.
    """
    return "runtime-outage" if part_name is None else f"runtime-failing:{part_name}"


# ── the rule: one emit site for `runtime.liveness_verdict` (design 7.1) ─────


@dataclass(frozen=True, slots=True)
class RuntimeLivenessAlert:
    """What one liveness pass announced, for the caller to log or assert on.

    Every field is a read-out of what this pass actually wrote — the same
    discipline `SpendAlert`/`PlatformAlert` hold in `jarvis.executive.alerts`."""

    outage_started: bool
    outage_recovered: bool
    failing_parts: tuple[str, ...]


async def raise_runtime_liveness_alerts(
    heartbeat: HeartbeatStore,
    poller: PollerReading,
    notifications: NotificationService,
    audit: AuditLog,
    *,
    now: datetime,
    heartbeat_stale_after_seconds: float,
    poller_stale_after_seconds: float,
    part_failing_after_crashes: int,
) -> RuntimeLivenessAlert:
    """The single emit site for `runtime.liveness_verdict` (design 7.1, L1,
    approval NONE, AUDIT + NOTIFY_ON_TRANSITION).

    One pass: read every fact, compute the verdict, compare it against the
    last recorded one, announce only what changed. See the module docstring
    for why the outage/recovery pair and the crash-loop notice use two
    different dedup shapes even though both ride this one action.

    Args:
        heartbeat: Read for every part's current beat.
        poller: One already-read `PollerReading` (design 3.3: "the Executive
            receives a reading, not a dependency").
        notifications: Writer for the operator's queue.
        audit: Read for the last recorded transition, written for this one.
        now: Injectable clock (D-004, D-038).
        heartbeat_stale_after_seconds: See :func:`assess_runtime_liveness`.
        poller_stale_after_seconds: See :func:`assess_runtime_liveness`.
        part_failing_after_crashes: See :func:`failing_parts`.

    Returns:
        A report naming exactly what this pass announced.
    """
    beats = await heartbeat.rows()
    verdict = assess_runtime_liveness(
        beats,
        poller,
        now=now,
        heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
        poller_stale_after_seconds=poller_stale_after_seconds,
    )

    last = await audit.latest_platform_entry(RUNTIME_LIVENESS_EVENT)
    was_outage = bool(last.payload.get("outage")) if last is not None else False

    outage_started = False
    outage_recovered = False
    if verdict.outage != was_outage:
        ref = _runtime_ref()
        if verdict.outage:
            outage_started = True
            await audit.record(
                event_type=RUNTIME_LIVENESS_EVENT,
                actor="platform",
                payload={"outage": True, "reason": verdict.reason},
            )
            await notifications.notify(
                notification_id=new_notification_id(),
                kind=NotificationKind.RUNTIME,
                title=OUTAGE_TITLE,
                body=OUTAGE_BODY,
                business_id=None,
                link_ref=ref,
            )
        else:
            outage_recovered = True
            started_at = last.recorded_at if last is not None else now
            duration = now - _aware(started_at)
            await audit.record(
                event_type=RUNTIME_LIVENESS_EVENT,
                actor="platform",
                payload={"outage": False, "duration_seconds": duration.total_seconds()},
            )
            await notifications.notify(
                notification_id=new_notification_id(),
                kind=NotificationKind.RUNTIME,
                title=RECOVERED_TITLE,
                body=_recovered_body(duration),
                business_id=None,
                link_ref=ref,
            )

    failing = failing_parts(beats, part_failing_after_crashes=part_failing_after_crashes)
    for part_name in failing:
        ref = _runtime_ref(part_name=part_name)
        if await notifications.has_unread(None, kind=NotificationKind.RUNTIME, link_ref=ref):
            continue
        await audit.record(
            event_type=RUNTIME_LIVENESS_EVENT,
            actor="platform",
            payload={"failing_part": part_name},
        )
        await notifications.notify(
            notification_id=new_notification_id(),
            kind=NotificationKind.RUNTIME,
            title=FAILING_TITLE_FMT.format(label=PART_LABELS.get(part_name, "Part of Jarvis")),
            body=FAILING_BODY,
            business_id=None,
            link_ref=ref,
        )

    if outage_started or outage_recovered or failing:
        logger.warning(
            "runtime liveness verdict changed",
            extra={
                "context": {
                    "outage_started": outage_started,
                    "outage_recovered": outage_recovered,
                    "failing_parts": failing,
                }
            },
        )
    return RuntimeLivenessAlert(
        outage_started=outage_started, outage_recovered=outage_recovered, failing_parts=failing
    )


__all__ = [
    "FAILING_BODY",
    "FAILING_TITLE_FMT",
    "OUTAGE_BODY",
    "OUTAGE_TITLE",
    "PART_LABELS",
    "RECOVERED_TITLE",
    "RUNTIME_LIVENESS_EVENT",
    "RuntimeLiveness",
    "RuntimeLivenessAlert",
    "assess_runtime_liveness",
    "failing_parts",
    "raise_runtime_liveness_alerts",
]
