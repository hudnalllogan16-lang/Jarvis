"""`PollerReading` and `summarise_worker_health` (design OPERATIONAL-RUNTIME.md
Part 3.2 Signal 2 / 3.4, D-058, packet P0-C).

Pure and exercised as a table of `(poller, now) -> (status, summary)` cases,
mirroring `tests/test_heartbeat.py`'s own shape for `summarise_runtime_health`
— no clock, no database, no Temporal client in the loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jarvis.observability.poller import (
    UNREACHABLE_POLLER_READING,
    PollerReading,
    summarise_worker_health,
)

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


def test_unreachable_reads_as_unknown_never_zero() -> None:
    """design 3.2: "unreachable is not served... never zero" — an unreachable
    probe must not be mistaken for a confirmed absence of pollers."""
    status, _ = summarise_worker_health(
        UNREACHABLE_POLLER_READING, now=NOW, poller_stale_after_seconds=300
    )
    assert status == "unknown"


def test_zero_pollers_reads_as_down() -> None:
    reading = PollerReading(reachable=True, workflow_pollers=0, activity_pollers=0)
    status, _ = summarise_worker_health(reading, now=NOW, poller_stale_after_seconds=300)
    assert status == "down"


def test_one_queue_type_with_zero_pollers_still_reads_as_down() -> None:
    """Both queue types must be served — a workflow poller with no activity
    poller (or vice versa) cannot actually run a company's round."""
    reading = PollerReading(
        reachable=True,
        workflow_pollers=1,
        activity_pollers=0,
        newest_last_access_at=NOW,
    )
    status, _ = summarise_worker_health(reading, now=NOW, poller_stale_after_seconds=300)
    assert status == "down"


def test_fresh_pollers_of_both_types_read_as_ok() -> None:
    reading = PollerReading(
        reachable=True,
        workflow_pollers=1,
        activity_pollers=1,
        newest_last_access_at=NOW - timedelta(seconds=10),
    )
    status, _ = summarise_worker_health(reading, now=NOW, poller_stale_after_seconds=300)
    assert status == "ok"


def test_stale_last_access_reads_as_degraded_not_down() -> None:
    """Pollers are present and reachable — the queue is connected, just slow
    to pick up work — which is a different fact from zero pollers."""
    reading = PollerReading(
        reachable=True,
        workflow_pollers=1,
        activity_pollers=1,
        newest_last_access_at=NOW - timedelta(seconds=999),
    )
    status, _ = summarise_worker_health(reading, now=NOW, poller_stale_after_seconds=300)
    assert status == "degraded"


def test_a_reading_exactly_at_the_threshold_still_counts_as_fresh() -> None:
    reading = PollerReading(
        reachable=True,
        workflow_pollers=1,
        activity_pollers=1,
        newest_last_access_at=NOW - timedelta(seconds=300),
    )
    status, _ = summarise_worker_health(reading, now=NOW, poller_stale_after_seconds=300)
    assert status == "ok"


def test_summary_text_carries_no_technical_vocabulary() -> None:
    """spec §12.5: this feeds /api/health directly."""
    from jarvis.approvals.rendering import contains_technical_language

    cases = [
        summarise_worker_health(
            UNREACHABLE_POLLER_READING, now=NOW, poller_stale_after_seconds=300
        ),
        summarise_worker_health(
            PollerReading(reachable=True, workflow_pollers=0, activity_pollers=0),
            now=NOW,
            poller_stale_after_seconds=300,
        ),
        summarise_worker_health(
            PollerReading(
                reachable=True,
                workflow_pollers=1,
                activity_pollers=1,
                newest_last_access_at=NOW,
            ),
            now=NOW,
            poller_stale_after_seconds=300,
        ),
        summarise_worker_health(
            PollerReading(
                reachable=True,
                workflow_pollers=1,
                activity_pollers=1,
                newest_last_access_at=NOW - timedelta(seconds=999),
            ),
            now=NOW,
            poller_stale_after_seconds=300,
        ),
    ]
    for _, summary in cases:
        assert not contains_technical_language(summary), summary
