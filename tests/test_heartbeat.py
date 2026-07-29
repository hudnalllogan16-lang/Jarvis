"""`HeartbeatStore` and `summarise_runtime_health` (design OPERATIONAL-RUNTIME.md
Part 3.2/3.4, D-058/D-059, packet P0-B).

The store is exercised against a real (in-memory) database, since its whole
job is the upsert semantics SQL gives it; `summarise_runtime_health` is pure
and exercised as a table of `(rows, now) -> (status, summary)` cases, with no
clock and no database in the loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.observability.heartbeat import (
    STOPPED_STATE,
    HeartbeatStore,
    RuntimeIdentity,
    summarise_runtime_health,
)
from jarvis.persistence.models import Base, RuntimeHeartbeatRow

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


def _row(
    *,
    part_name: str,
    state: str,
    age_seconds: float = 0.0,
    runtime_id: str = "r1",
) -> RuntimeHeartbeatRow:
    return RuntimeHeartbeatRow(
        runtime_id=runtime_id,
        part_name=part_name,
        hostname="h",
        pid=1,
        started_at=NOW,
        last_beat_at=NOW - timedelta(seconds=age_seconds),
        state=state,
        consecutive_crashes=0,
        last_error="",
    )


# ── HeartbeatStore: upsert semantics against a real database ────────────────


async def _session_factory() -> async_sessionmaker:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_beat_inserts_one_row_per_runtime_and_part() -> None:
    factory = await _session_factory()
    identity = RuntimeIdentity(runtime_id="r1", hostname="h", pid=1, started_at=NOW)
    async with factory() as session:
        store = HeartbeatStore(session)
        await store.beat(identity, part_name="api", state="running")
        await store.beat(identity, part_name="worker", state="running")
        await session.commit()

    async with factory() as session:
        rows = await HeartbeatStore(session).rows()
    assert {row.part_name for row in rows} == {"api", "worker"}


async def test_a_second_beat_for_the_same_part_upserts_rather_than_appends() -> None:
    """design 3.2: "the row is bounded and never grows" for one runtime."""
    factory = await _session_factory()
    identity = RuntimeIdentity(runtime_id="r1", hostname="h", pid=1, started_at=NOW)
    async with factory() as session:
        store = HeartbeatStore(session)
        await store.beat(identity, part_name="api", state="starting")
        await store.beat(identity, part_name="api", state="running", consecutive_crashes=2)
        await session.commit()

    async with factory() as session:
        rows = await HeartbeatStore(session).rows()
    assert len(rows) == 1
    assert rows[0].state == "running"
    assert rows[0].consecutive_crashes == 2


async def test_a_new_runtime_id_writes_a_separate_row() -> None:
    """A restart mints a fresh `runtime_id` (design 3.2) — the old runtime's
    row is not overwritten, only outrun by staleness."""
    factory = await _session_factory()
    async with factory() as session:
        store = HeartbeatStore(session)
        await store.beat(
            RuntimeIdentity(runtime_id="old", hostname="h", pid=1, started_at=NOW),
            part_name="api",
            state="stopped",
        )
        await store.beat(
            RuntimeIdentity(runtime_id="new", hostname="h", pid=2, started_at=NOW),
            part_name="api",
            state="running",
        )
        await session.commit()

    async with factory() as session:
        rows = await HeartbeatStore(session).rows()
    assert {row.runtime_id for row in rows} == {"old", "new"}


# ── summarise_runtime_health: pure, no clock or database ────────────────────


def test_no_rows_reads_as_down() -> None:
    status, _ = summarise_runtime_health([], now=NOW, stale_after_seconds=45)
    assert status == "down"


def test_every_part_fresh_and_running_reads_as_ok() -> None:
    rows = [_row(part_name="api", state="running"), _row(part_name="worker", state="running")]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


def test_one_part_restarting_reads_as_degraded() -> None:
    rows = [_row(part_name="api", state="running"), _row(part_name="worker", state="restarting")]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "degraded"


def test_one_part_stale_among_fresh_parts_reads_as_degraded() -> None:
    rows = [
        _row(part_name="api", state="running"),
        _row(part_name="worker", state="running", age_seconds=999),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "degraded"


def test_every_part_stale_reads_as_down() -> None:
    rows = [
        _row(part_name="api", state="running", age_seconds=999),
        _row(part_name="worker", state="running", age_seconds=999),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "down"


def test_a_clean_stop_reads_as_stopped_not_down() -> None:
    """D-060: a recorded clean stop is a different fact than silence, even
    though the row is (necessarily) not "fresh" by the time anyone reads it."""
    rows = [_row(part_name="runtime", state=STOPPED_STATE, age_seconds=999)]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "stopped"


def test_only_the_freshest_row_per_part_counts() -> None:
    """A restart's fresh row must outrun the old runtime's stale one, not
    average against it."""
    rows = [
        _row(part_name="api", state="running", age_seconds=999, runtime_id="old"),
        _row(part_name="api", state="running", age_seconds=0, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


def test_a_beat_exactly_at_the_threshold_still_counts_as_fresh() -> None:
    rows = [_row(part_name="api", state="running", age_seconds=45)]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


# ── generation scoping (packet M10-F39): superseded generations never
#    degrade the current verdict, and a newest-generation clean stop reads
#    "stopped", not "degraded" ──────────────────────────────────────────────


def test_a_restart_with_a_stale_predecessor_reads_as_ok() -> None:
    """A superseded generation's parts, however stale, never drag the newest
    generation — beating fine on its own — down to degraded."""
    rows = [
        _row(part_name="api", state="running", age_seconds=999, runtime_id="old"),
        _row(part_name="worker", state="running", age_seconds=999, runtime_id="old"),
        _row(part_name="api", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="worker", state="running", age_seconds=0, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


def test_a_taskkilled_predecessor_does_not_degrade_the_successor() -> None:
    """D-060: a predecessor that vanished (never marked `stopped`, correctly
    left `state=running`) is exactly as excluded as one that stopped
    cleanly — both are simply a superseded generation now."""
    rows = [
        _row(part_name="api", state="running", age_seconds=999, runtime_id="taskkilled"),
        _row(part_name="worker", state="running", age_seconds=999, runtime_id="taskkilled"),
        _row(part_name="runtime", state="running", age_seconds=999, runtime_id="taskkilled"),
        _row(part_name="api", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="worker", state="running", age_seconds=0, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


def test_the_current_generations_own_stale_part_still_degrades() -> None:
    """Scoping to the newest generation must not paper over a genuine
    problem in that same generation."""
    rows = [
        _row(part_name="api", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="worker", state="running", age_seconds=999, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "degraded"


def test_a_newest_generation_clean_stop_reads_as_stopped_not_degraded() -> None:
    """packet M10-F39 item 3: the newest generation's own `runtime` row
    saying `stopped` closes it, even though its other parts' rows are
    necessarily stale by the time anyone reads them (no more beats after
    a clean shutdown)."""
    rows = [
        _row(part_name="api", state="running", age_seconds=999, runtime_id="new"),
        _row(part_name="worker", state="running", age_seconds=999, runtime_id="new"),
        _row(part_name="runtime", state=STOPPED_STATE, age_seconds=1, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "stopped"


def test_a_smoothly_started_generation_with_no_runtime_marker_row_reads_as_ok() -> None:
    """The defect this packet fixes: a generation that never needed
    `bootstrap`'s `WAIT` posture and has not yet stopped never writes a
    `'runtime'` marker row at all — its absence must not be filled in by a
    superseded generation's stale or stopped one."""
    rows = [
        _row(part_name="runtime", state=STOPPED_STATE, age_seconds=99999, runtime_id="ancient"),
        _row(part_name="api", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="worker", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="scheduler", state="running", age_seconds=0, runtime_id="new"),
        _row(part_name="executive", state="running", age_seconds=0, runtime_id="new"),
    ]
    status, _ = summarise_runtime_health(rows, now=NOW, stale_after_seconds=45)
    assert status == "ok"


def test_summary_text_carries_no_technical_vocabulary() -> None:
    """spec §12.5: this feeds /api/health directly, so its prose is bound by
    the same rule the dashboard's own copy is, even though this specific
    string is not yet wired into the markup a runtime scan would catch."""
    from jarvis.approvals.rendering import contains_technical_language

    cases = [
        summarise_runtime_health([], now=NOW, stale_after_seconds=45),
        summarise_runtime_health(
            [_row(part_name="api", state="running")], now=NOW, stale_after_seconds=45
        ),
        summarise_runtime_health(
            [_row(part_name="runtime", state=STOPPED_STATE, age_seconds=999)],
            now=NOW,
            stale_after_seconds=45,
        ),
        summarise_runtime_health(
            [
                _row(part_name="api", state="running"),
                _row(part_name="worker", state="restarting"),
            ],
            now=NOW,
            stale_after_seconds=45,
        ),
    ]
    for _, summary in cases:
        assert not contains_technical_language(summary), summary
