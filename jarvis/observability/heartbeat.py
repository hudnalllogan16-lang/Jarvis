"""Runtime heartbeat store and health assessment (design OPERATIONAL-RUNTIME.md
Part 3.2/3.3/3.4, D-058/D-059, packet P0-B).

The facts half of the two-signal liveness design (3.3): "reachable is not
served", and the runtime's own self-report is one of the two signals that
distinguishes them. This module owns the fact — a `HeartbeatStore` that
writes and reads `runtime_heartbeat` rows — and one pure reading of that
fact alone, :func:`summarise_runtime_health`, for `/api/health`'s `runtime`
component.

It deliberately does not build the design's full two-signal
`assess_runtime_liveness` (heartbeat *and* poller staleness, folded into a
transition-deduped verdict): that needs the Temporal poller probe and lands
in the Executive as an L1 rule (`jarvis/executive/liveness.py`, packet
P0-C, D-038's own layering). What is here is the half D-038 requires live in
`observability` regardless — facts, not verdicts — and is exactly what a
console-only attach (design Part 6, Mode 4) needs to answer "is anything
running" with no Supervisor of its own to ask.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.persistence.models import RuntimeHeartbeatRow


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """One process's identity, threaded through every heartbeat row it writes.

    Minted once per process start (design 3.2: `runtime_id` is "generated at
    process start"), not resolved per write — a restart is a new runtime, not
    a continuation of the old one, so every row a process writes across its
    whole lifetime must agree on who is writing it.
    """

    runtime_id: str
    hostname: str
    pid: int
    started_at: datetime


STOPPED_STATE = "stopped"
"""`part_name='runtime'`'s state after a clean shutdown (design 3.2, D-060).
Distinct from a stale/absent row: "stopped cleanly" and "last seen" must stay
different recorded facts, never collapsed into the same silence."""

WAITING_STATE = "waiting"
"""`part_name='runtime'`'s state while `bootstrap`'s `WAIT` posture retries a
missing dependency, before any part exists to report its own state."""


class HeartbeatStore:
    """Writes and reads `runtime_heartbeat` rows (design 3.2's `HeartbeatStore`)."""

    def __init__(self, session: AsyncSession) -> None:
        """Args:
        session: Active session, injected by the caller — the same
            per-call-scoped pattern `AuditLog` and `DecisionLog` use, so a
            beat commits or rolls back with whatever else the caller's
            transaction does.
        """
        self._session = session

    async def beat(
        self,
        identity: RuntimeIdentity,
        *,
        part_name: str,
        state: str,
        consecutive_crashes: int = 0,
        last_error: str = "",
    ) -> None:
        """Upsert the one row for ``(identity.runtime_id, part_name)``.

        Written on every call rather than appended (design 3.2: "the row is
        bounded and never grows") — a history of every beat is the audit
        log's job, not this table's; this table only ever answers "what is
        true of this part right now".

        Args:
            identity: This process's identity (see :class:`RuntimeIdentity`).
            part_name: ``'api' | 'worker' | 'scheduler' | 'executive' |
                'runtime'`` (design 3.2).
            state: The part's current state — a `PartState` value for a real
                part, or :data:`WAITING_STATE`/:data:`STOPPED_STATE` for the
                synthetic ``'runtime'`` part. Passed as a bare string rather
                than an imported enum: `jarvis.shell.supervisor.PartState`
                lives in milestone 5 and this package is milestone 1
                (`tests/test_layering.py` forbids the forward import), so the
                Supervisor hands over `PartState.value` at the call site.
            consecutive_crashes: Mirrors `PartStatus.consecutive_crashes`,
                zero for the synthetic ``'runtime'`` part.
            last_error: Mirrors `PartStatus.last_error`, capped the same way
                the Supervisor already caps it.
        """
        key = (identity.runtime_id, part_name)
        row = await self._session.get(RuntimeHeartbeatRow, key)
        now = datetime.now(UTC)
        if row is None:
            self._session.add(
                RuntimeHeartbeatRow(
                    runtime_id=identity.runtime_id,
                    part_name=part_name,
                    hostname=identity.hostname,
                    pid=identity.pid,
                    started_at=identity.started_at,
                    last_beat_at=now,
                    state=state,
                    consecutive_crashes=consecutive_crashes,
                    last_error=last_error,
                )
            )
        else:
            row.hostname = identity.hostname
            row.pid = identity.pid
            row.last_beat_at = now
            row.state = state
            row.consecutive_crashes = consecutive_crashes
            row.last_error = last_error
        await self._session.flush()

    async def rows(self) -> Sequence[RuntimeHeartbeatRow]:
        """Return every stored heartbeat row, fresh and stale alike.

        Deliberately unfiltered: staleness is a property of *when* a row is
        read against a threshold, not of the row itself, so filtering here
        would bake one reader's threshold into the store. Today's only
        reader is :func:`summarise_runtime_health`; the Executive's
        two-signal verdict (packet P0-C) reads the same rows against its own.
        """
        return (await self._session.scalars(select(RuntimeHeartbeatRow))).all()


def summarise_runtime_health(
    rows: Sequence[RuntimeHeartbeatRow],
    *,
    now: datetime,
    stale_after_seconds: float,
) -> tuple[str, str]:
    """Reduce heartbeat rows to `/api/health`'s `runtime` component (design 3.4).

    Every ``part_name`` is reduced to its freshest row first — a restart
    mints a new ``runtime_id``, so an old runtime's rows are simply the ones
    a newer runtime's writes have outrun, never a second opinion to
    reconcile against the current one. The reduction then folds to one of
    the four states Part 3.4's table names for this component:

    - **down** — no row exists at all, or nothing recorded is fresh and the
      newest state was not a clean stop. A platform that has never reported
      a heartbeat is exactly as invisible as one that has gone silent.
    - **stopped** — every part's freshest row records :data:`STOPPED_STATE`.
      D-060's distinction made literal: this is not "down", it is a
      recorded fact that nothing is running on purpose.
    - **ok** — every part's freshest row is fresh and ``running``.
    - **degraded** — anything short of the two clean cases above: one part
      restarting, one part's beat stale while another's is fresh, or the
      process still starting.

    This function never calls `datetime.now` itself — `now` is a parameter,
    the same discipline `run_preflight`'s callers already keep, so a caller
    can pin a table of `(rows, now) -> expected` cases without a clock in
    the loop.

    Args:
        rows: Every stored `RuntimeHeartbeatRow`, e.g. `HeartbeatStore.rows()`.
        now: The instant to assess freshness against.
        stale_after_seconds: `settings.heartbeat.heartbeat_stale_after_seconds`.

    Returns:
        ``(status, summary)`` — ``status`` is one of ``ok``/``degraded``/
        ``down``/``stopped``, matching `/api/health`'s other components;
        ``summary`` is one plain sentence, safe for the operator surface
        (spec §12.5: no part name, no runtime id, no host, no pid).
    """

    def _aware(value: datetime) -> datetime:
        """Coerce a possibly-naive timestamp to UTC-aware, without mutating
        the row it came from (a persistent ORM instance under a live
        session, in production).

        SQLite hands back naive what Postgres stores with an offset; the
        rows are written from `datetime.now(UTC)` either way (the same
        dialect gap `jarvis.executive.alerts._halt_already_explained` and
        `jarvis.scheduler.service` already document).
        """
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    latest: dict[str, RuntimeHeartbeatRow] = {}
    latest_beat_at: dict[str, datetime] = {}
    for row in rows:
        beat_at = _aware(row.last_beat_at)
        if row.part_name not in latest_beat_at or beat_at > latest_beat_at[row.part_name]:
            latest[row.part_name] = row
            latest_beat_at[row.part_name] = beat_at

    if not latest:
        return "down", "Jarvis hasn't reported in yet."

    if all(row.state == STOPPED_STATE for row in latest.values()):
        return "stopped", "Jarvis is stopped."

    fresh = {
        name: (now - latest_beat_at[name]).total_seconds() <= stale_after_seconds for name in latest
    }
    if all(fresh.values()) and all(row.state == "running" for row in latest.values()):
        return "ok", "Jarvis is running."

    if not any(fresh.values()):
        return "down", "Jarvis hasn't reported in recently."

    return "degraded", "Part of Jarvis is starting up or hasn't reported in recently."


__all__ = [
    "STOPPED_STATE",
    "WAITING_STATE",
    "HeartbeatStore",
    "RuntimeIdentity",
    "summarise_runtime_health",
]
