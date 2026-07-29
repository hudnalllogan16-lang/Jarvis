"""The two-signal liveness verdict (design OPERATIONAL-RUNTIME.md Part 3.2/
3.3/5.4/7.1, D-058, D-061, packet P0-C).

Three layers, tested at the level each deserves:

- `assess_runtime_liveness` and `failing_parts` are pure — exercised as
  tables of `(beats, poller) -> RuntimeLiveness` cases against design 3.2's
  own four-row table, no clock read and no database, mirroring
  `tests/test_heartbeat.py`'s and `tests/test_poller.py`'s own shape.
- `raise_runtime_liveness_alerts` is exercised against the same in-memory
  platform `tests/test_executive_alerts.py` already uses, proving the two
  different dedup shapes the module docstring explains: the outage/recovery
  pair (D-046, audit-transition dedup) and a crash-looping part (design 5.4,
  `has_unread` dedup "exactly like D-053's `UNFINISHED_ROUND`").
- The copy tables are checked against §12.5's forbidden vocabulary, the same
  parametrized shape `test_executive_alerts.py` holds `BAND_COPY` to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.approvals.rendering import contains_technical_language
from jarvis.executive.liveness import (
    FAILING_BODY,
    FAILING_TITLE_FMT,
    OUTAGE_BODY,
    OUTAGE_TITLE,
    PART_LABELS,
    RECOVERED_TITLE,
    RUNTIME_LIVENESS_EVENT,
    RuntimeLivenessAlert,
    _format_duration,
    _recovered_body,
    assess_runtime_liveness,
    failing_parts,
    raise_runtime_liveness_alerts,
)
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.heartbeat import HeartbeatStore
from jarvis.observability.poller import UNREACHABLE_POLLER_READING, PollerReading
from jarvis.persistence.models import RuntimeHeartbeatRow

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
FRESH_POLLER = PollerReading(
    reachable=True, workflow_pollers=1, activity_pollers=1, newest_last_access_at=NOW
)
STALE_POLLER = PollerReading(
    reachable=True,
    workflow_pollers=1,
    activity_pollers=1,
    newest_last_access_at=NOW - timedelta(seconds=999),
)
ZERO_POLLER = PollerReading(reachable=True, workflow_pollers=0, activity_pollers=0)


def _beat(
    *, part_name: str, state: str = "running", age_seconds: float = 0.0, crashes: int = 0
) -> RuntimeHeartbeatRow:
    return RuntimeHeartbeatRow(
        runtime_id="r1",
        part_name=part_name,
        hostname="h",
        pid=1,
        started_at=NOW,
        last_beat_at=NOW - timedelta(seconds=age_seconds),
        state=state,
        consecutive_crashes=crashes,
        last_error="",
    )


# ── assess_runtime_liveness: design 3.2's own table, pure ───────────────────


def test_process_killed_reads_as_outage() -> None:
    """Row 1: heartbeat stale, pollers reachable and zero."""
    verdict = assess_runtime_liveness(
        [_beat(part_name="worker", age_seconds=999)],
        ZERO_POLLER,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is True


def test_a_wedged_worker_reads_as_outage_even_though_it_self_reports_running() -> None:
    """Row 2: heartbeat says `running` (a lie) but pollers are stale — the
    exact case design 3.2 says a single signal gets wrong."""
    verdict = assess_runtime_liveness(
        [_beat(part_name="worker", state="running", age_seconds=0)],
        STALE_POLLER,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is True


def test_scheduler_or_executive_dead_worker_fine_reads_as_no_outage() -> None:
    """Row 3: the worker's own heartbeat is fresh and pollers are healthy —
    another part's trouble is not this verdict's territory."""
    verdict = assess_runtime_liveness(
        [
            _beat(part_name="worker", state="running", age_seconds=0),
            _beat(part_name="scheduler", state="restarting", age_seconds=999),
        ],
        FRESH_POLLER,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is False


def test_temporal_down_runtime_healthy_reads_as_no_outage_never_zero() -> None:
    """Row 4: an unreachable probe is never conflated with zero pollers
    (design 3.2's own warning against manufacturing a false alarm)."""
    verdict = assess_runtime_liveness(
        [_beat(part_name="worker", state="running", age_seconds=0)],
        UNREACHABLE_POLLER_READING,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is False


def test_no_heartbeat_at_all_and_unreachable_pollers_reads_as_outage() -> None:
    """Neither signal has anything to say for the worker — a fresh install
    or a fully dead host both read `outage=True`, never a silent `False`."""
    verdict = assess_runtime_liveness(
        [],
        UNREACHABLE_POLLER_READING,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is True


def test_only_the_freshest_worker_row_counts() -> None:
    """A restart's fresh row must outrun an old runtime's stale one."""
    verdict = assess_runtime_liveness(
        [
            RuntimeHeartbeatRow(
                runtime_id="old",
                part_name="worker",
                hostname="h",
                pid=1,
                started_at=NOW,
                last_beat_at=NOW - timedelta(seconds=999),
                state="running",
                consecutive_crashes=0,
                last_error="",
            ),
            RuntimeHeartbeatRow(
                runtime_id="new",
                part_name="worker",
                hostname="h",
                pid=2,
                started_at=NOW,
                last_beat_at=NOW,
                state="running",
                consecutive_crashes=0,
                last_error="",
            ),
        ],
        FRESH_POLLER,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is False


def test_a_stopped_predecessors_runtime_marker_never_reaches_this_verdict() -> None:
    """Regression for packet M10-F39 item 4.

    `assess_runtime_liveness` never inspects `part_name == "runtime"` at
    all — it only ever reduces `"worker"` to its freshest row via
    `_freshest`, which is a straight max over every row sharing that
    `part_name`. A superseded generation's `worker` row can never win that
    max once the current generation has beaten even once (wall-clock time
    only moves forward, so an older generation's frozen timestamp cannot
    exceed a live one's), and the synthetic `'runtime'` marker row — the
    one `jarvis.observability.heartbeat.summarise_runtime_health` had to
    learn to scope past, since a smoothly-started generation never writes
    one at all — is simply never read here. This is why the soak's four
    superseded generations (two clean-stopped, two taskkilled) never made
    `assess_runtime_liveness` false-alarm even though they did make
    `/api/health`'s `runtime` component false-alarm: this function was
    already, by construction, scoped to what matters."""

    def _row(
        *, runtime_id: str, part_name: str, state: str, age_seconds: float
    ) -> RuntimeHeartbeatRow:
        return RuntimeHeartbeatRow(
            runtime_id=runtime_id,
            part_name=part_name,
            hostname="h",
            pid=1,
            started_at=NOW - timedelta(seconds=age_seconds),
            last_beat_at=NOW - timedelta(seconds=age_seconds),
            state=state,
            consecutive_crashes=0,
            last_error="",
        )

    beats = [
        # A generation that stopped cleanly: its own `runtime` marker row
        # is `stopped`, ancient, and would corrupt an `all(...)`-shaped
        # check the way it used to corrupt `summarise_runtime_health`.
        _row(runtime_id="clean-stopped", part_name="runtime", state="stopped", age_seconds=99999),
        _row(runtime_id="clean-stopped", part_name="worker", state="running", age_seconds=99999),
        # A generation that vanished under taskkill: never marked stopped,
        # `state=running` frozen forever at the moment it died (D-060).
        _row(runtime_id="taskkilled", part_name="worker", state="running", age_seconds=50000),
        # The current, live generation: fresh and serving.
        _row(runtime_id="current", part_name="worker", state="running", age_seconds=0),
    ]
    verdict = assess_runtime_liveness(
        beats,
        FRESH_POLLER,
        now=NOW,
        heartbeat_stale_after_seconds=45,
        poller_stale_after_seconds=300,
    )
    assert verdict.outage is False


# ── failing_parts: pure ──────────────────────────────────────────────────────


def test_a_part_below_threshold_is_not_failing() -> None:
    beats = [_beat(part_name="worker", crashes=9)]
    assert failing_parts(beats, part_failing_after_crashes=10) == ()


def test_a_part_at_threshold_is_failing() -> None:
    assert failing_parts(
        [_beat(part_name="worker", crashes=10)], part_failing_after_crashes=10
    ) == ("worker",)


def test_multiple_failing_parts_are_returned_sorted() -> None:
    assert failing_parts(
        [_beat(part_name="worker", crashes=10), _beat(part_name="api", crashes=15)],
        part_failing_after_crashes=10,
    ) == ("api", "worker")


def test_only_the_freshest_row_per_part_is_checked_for_failure() -> None:
    """A part that crash-looped in a prior runtime and is fine now must not
    be reported as failing off a stale row."""
    rows = [
        RuntimeHeartbeatRow(
            runtime_id="old",
            part_name="worker",
            hostname="h",
            pid=1,
            started_at=NOW,
            last_beat_at=NOW - timedelta(seconds=999),
            state="restarting",
            consecutive_crashes=99,
            last_error="",
        ),
        RuntimeHeartbeatRow(
            runtime_id="new",
            part_name="worker",
            hostname="h",
            pid=2,
            started_at=NOW,
            last_beat_at=NOW,
            state="running",
            consecutive_crashes=0,
            last_error="",
        ),
    ]
    assert failing_parts(rows, part_failing_after_crashes=10) == ()


# ── _format_duration: pure ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (10, "less than a minute"),
        (60, "1 minute"),
        (150, "2 minutes"),
        (3600, "1 hour"),
        (7200, "2 hours"),
        (3660, "1 hour and 1 minute"),
        (48600, "13 hours and 30 minutes"),
    ],
)
def test_format_duration(seconds: int, expected: str) -> None:
    assert _format_duration(timedelta(seconds=seconds)) == expected


# ── raise_runtime_liveness_alerts: the emit site, against a real database ──


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "now": NOW,
        "heartbeat_stale_after_seconds": 45,
        "poller_stale_after_seconds": 300,
        "part_failing_after_crashes": 10,
    }
    base.update(overrides)
    return base


async def _insert_beat(
    session, *, part_name: str, state: str = "running", crashes: int = 0
) -> None:
    """Write one heartbeat row at the fixed `NOW`, bypassing `HeartbeatStore.
    beat` (which stamps the real wall clock) so every test in this section
    compares against the same controlled instant `_kwargs()` defaults `now`
    to, rather than against whenever the test happens to actually run."""
    session.add(
        RuntimeHeartbeatRow(
            runtime_id="r1",
            part_name=part_name,
            hostname="h",
            pid=1,
            started_at=NOW,
            last_beat_at=NOW,
            state=state,
            consecutive_crashes=crashes,
            last_error="",
        )
    )
    await session.flush()


async def test_the_first_ever_healthy_tick_announces_nothing(session) -> None:
    """No prior audit record, and the verdict itself reads healthy: no
    transition, so nothing is written at all — not even a baseline row."""
    heartbeat = HeartbeatStore(session)
    await _insert_beat(session, part_name="worker")
    notifications = NotificationService(session)
    audit = AuditLog(session)

    report = await raise_runtime_liveness_alerts(
        heartbeat, FRESH_POLLER, notifications, audit, **_kwargs()
    )

    assert report == RuntimeLivenessAlert(
        outage_started=False, outage_recovered=False, failing_parts=()
    )
    assert await audit.latest_platform_entry(RUNTIME_LIVENESS_EVENT) is None
    assert await notifications.unread_count() == 0


async def test_an_outage_from_the_start_announces_once(session) -> None:
    """No prior record, verdict reads down: `was_outage` defaults False, so
    this is treated as a transition and announced (design 3.5's own case)."""
    heartbeat = HeartbeatStore(session)  # no beats at all
    notifications = NotificationService(session)
    audit = AuditLog(session)

    report = await raise_runtime_liveness_alerts(
        heartbeat, UNREACHABLE_POLLER_READING, notifications, audit, **_kwargs()
    )

    assert report.outage_started is True
    entry = await audit.latest_platform_entry(RUNTIME_LIVENESS_EVENT)
    assert entry is not None
    assert entry.payload["outage"] is True
    unread = await notifications.unread()
    assert [n.kind for n in unread] == [NotificationKind.RUNTIME.value]
    assert unread[0].title == OUTAGE_TITLE
    assert unread[0].body == OUTAGE_BODY


async def test_an_unchanged_outage_is_not_re_announced(session) -> None:
    heartbeat = HeartbeatStore(session)
    notifications = NotificationService(session)
    audit = AuditLog(session)

    await raise_runtime_liveness_alerts(
        heartbeat, UNREACHABLE_POLLER_READING, notifications, audit, **_kwargs()
    )
    second = await raise_runtime_liveness_alerts(
        heartbeat, UNREACHABLE_POLLER_READING, notifications, audit, **_kwargs()
    )

    assert second.outage_started is False
    assert second.outage_recovered is False
    assert await notifications.unread_count() == 1  # still just the first notice


async def test_recovery_is_announced_with_its_duration(session) -> None:
    heartbeat = HeartbeatStore(session)
    notifications = NotificationService(session)
    audit = AuditLog(session)

    # Tick 1: down.
    await raise_runtime_liveness_alerts(
        heartbeat, UNREACHABLE_POLLER_READING, notifications, audit, **_kwargs(now=NOW)
    )

    # `AuditLogRow.recorded_at` stamps the real wall clock at write time
    # (`default=_utcnow`, not injectable through `AuditLog.record`) — pinned
    # to the fixed `NOW` here so the duration computed below is against a
    # controlled two-hour gap rather than whatever the real clock happened
    # to read when this test ran.
    from sqlalchemy import update

    from jarvis.persistence.models import AuditLogRow

    await session.execute(
        update(AuditLogRow)
        .where(AuditLogRow.event_type == RUNTIME_LIVENESS_EVENT)
        .values(recorded_at=NOW)
    )
    await session.flush()

    # Tick 2, two hours later: the worker is now beating fresh and pollers
    # serve. Inserted directly (bypassing `HeartbeatStore.beat`, which stamps
    # the real wall clock) so `last_beat_at` sits at a controlled instant
    # relative to `later` rather than whenever this test happens to run.
    later = NOW + timedelta(hours=2)
    session.add(
        RuntimeHeartbeatRow(
            runtime_id="r1",
            part_name="worker",
            hostname="h",
            pid=1,
            started_at=NOW,
            last_beat_at=later,
            state="running",
            consecutive_crashes=0,
            last_error="",
        )
    )
    await session.flush()
    fresh_now = PollerReading(
        reachable=True, workflow_pollers=1, activity_pollers=1, newest_last_access_at=later
    )
    report = await raise_runtime_liveness_alerts(
        heartbeat, fresh_now, notifications, audit, **_kwargs(now=later)
    )

    assert report.outage_recovered is True
    entry = await audit.latest_platform_entry(RUNTIME_LIVENESS_EVENT)
    assert entry is not None
    assert entry.payload["outage"] is False
    assert entry.payload["duration_seconds"] == pytest.approx(7200, abs=1)
    unread = await notifications.unread()
    recovered = next(n for n in unread if n.title == RECOVERED_TITLE)
    assert recovered.body == _recovered_body(timedelta(hours=2))


async def test_a_crash_looping_part_is_announced_once_per_condition(session) -> None:
    """design 5.4: "deduped exactly like D-053's UNFINISHED_ROUND" —
    `has_unread`, not the audit-transition mechanism the outage pair uses."""
    heartbeat = HeartbeatStore(session)
    await _insert_beat(session, part_name="worker")
    await _insert_beat(session, part_name="scheduler", state="restarting", crashes=10)
    notifications = NotificationService(session)
    audit = AuditLog(session)

    first = await raise_runtime_liveness_alerts(
        heartbeat, FRESH_POLLER, notifications, audit, **_kwargs()
    )
    assert first.failing_parts == ("scheduler",)
    unread = await notifications.unread()
    failing_notice = next(n for n in unread if "isn't recovering" in n.title)
    assert failing_notice.title == FAILING_TITLE_FMT.format(label=PART_LABELS["scheduler"])
    assert failing_notice.body == FAILING_BODY

    # Same condition, a second pass: no repeat while the notice is unread.
    second = await raise_runtime_liveness_alerts(
        heartbeat, FRESH_POLLER, notifications, audit, **_kwargs()
    )
    assert second.failing_parts == ("scheduler",)  # still true
    assert len([n for n in await notifications.unread() if "isn't recovering" in n.title]) == 1


async def test_a_crash_looping_part_is_announced_again_after_being_read(session) -> None:
    """`has_unread`'s own posture (design 5.4's explicit choice): a condition
    still true when the operator has dismissed the notice is worth saying
    again, unlike the outage pair's stricter once-per-transition rule."""
    heartbeat = HeartbeatStore(session)
    await _insert_beat(session, part_name="worker")
    await _insert_beat(session, part_name="scheduler", state="restarting", crashes=10)
    notifications = NotificationService(session)
    audit = AuditLog(session)

    await raise_runtime_liveness_alerts(heartbeat, FRESH_POLLER, notifications, audit, **_kwargs())
    for notice in await notifications.unread():
        await notifications.mark_read(notice.notification_id)

    second = await raise_runtime_liveness_alerts(
        heartbeat, FRESH_POLLER, notifications, audit, **_kwargs()
    )
    assert second.failing_parts == ("scheduler",)
    assert len([n for n in await notifications.unread() if "isn't recovering" in n.title]) == 1


# ── copy: §12.5 (provisional pending operator-surface-engineer review) ──────


def test_outage_copy_carries_no_technical_vocabulary() -> None:
    assert not contains_technical_language(OUTAGE_TITLE)
    assert not contains_technical_language(OUTAGE_BODY)
    assert not contains_technical_language(RECOVERED_TITLE)
    assert not contains_technical_language(_recovered_body(timedelta(hours=1)))
    assert not contains_technical_language(FAILING_BODY)


@pytest.mark.parametrize("part_name", sorted(PART_LABELS))
def test_part_labels_and_failing_title_carry_no_technical_vocabulary(part_name: str) -> None:
    label = PART_LABELS[part_name]
    assert not contains_technical_language(label)
    assert not contains_technical_language(FAILING_TITLE_FMT.format(label=label))
