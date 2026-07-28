"""Audit Log writer (spec §11).

Append-only and complete. Every tool call, model call, approval decision,
workflow step, event, expense, retry, and Business Manager decision is recorded
here. There is deliberately no update or delete method on this class (A-006).

Callers inside Temporal workflows must not call this directly: writes are I/O
and therefore belong in activities (D-004).

**A record of a refusal must outlive the refusal.** `record` writes into the
caller's transaction, which is right for an entry describing something that
happened — if the work rolls back, so should the claim that it occurred. It is
exactly wrong for a denial: `session_scope` rolls back on exception, so a
security refusal audited and then raised loses its own record, and the platform
reports nothing where it most needs to report something (M6-F38). Denials
therefore use `record_independently`, which commits in its own short transaction
before the refusal propagates — the same independence D-022 gave budget
reservations, for the same reason: a write that commits only when the caller
succeeds cannot describe the caller failing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis.kernel.ids import BusinessId
from jarvis.kernel.logging import get_logger, redact
from jarvis.persistence.engine import session_scope
from jarvis.persistence.models import AuditLogRow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlatformAuditEntry:
    """One platform-level (``business_id IS NULL``) audit row, decoupled from
    the ORM.

    Returned by :meth:`AuditLog.latest_platform_entry` rather than the raw
    `AuditLogRow` so a caller outside `jarvis.observability` never needs
    `jarvis.persistence` in scope to read it — `jarvis.executive` is the
    reason this exists (D-038's import list has no room for `persistence`),
    but the same shape suits any caller occupying a package this restricted.
    """

    payload: dict[str, Any]
    recorded_at: datetime


class AuditLog:
    """Append-only writer and reader for the forensic event record (spec §11)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        denial_sessions: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Args:
        session: Active session, injected by the caller.
        denial_sessions: Factory for `record_independently`'s own short
            transaction (M6-F38). Without it a denial record shares the
            caller's transaction and is rolled back by the refusal it
            describes — the Kernel always supplies one, and
            `test_kernel_wires_denial_transactions` keeps it that way. It
            stays optional so a single-session test can drive the log
            directly, matching `BudgetLedger.reservation_sessions`.
        """
        self._session = session
        self._denial_sessions = denial_sessions

    async def record(
        self,
        *,
        event_type: str,
        actor: str,
        business_id: BusinessId | None = None,
        workflow_id: str | None = None,
        run_id: str | None = None,
        sequence: int | None = None,
        payload: dict[str, Any] | None = None,
        cost_usd: Decimal | None = None,
    ) -> int:
        """Append one audit entry.

        Args:
            event_type: Dotted event name, e.g. ``business.state_changed``.
            actor: What performed the action — a business id, ``executive.cfo``,
                ``platform``, or ``operator``.
            business_id: Owning business, or None for platform-level events.
            workflow_id: Temporal workflow id, when applicable.
            run_id: Temporal run id — the join key to the replay substrate (D-004).
            sequence: Ordering hint within a workflow run.
            payload: Structured detail. Redacted before storage (spec §10).
            cost_usd: Spend attributable to this event, for the budget ledger
                and the rolling 24h aggregate (spec §9, D-003).

        Returns:
            The generated audit row id, usable as a Decision Log ``audit_ref``.
        """
        row = self._row(
            event_type=event_type,
            actor=actor,
            business_id=business_id,
            workflow_id=workflow_id,
            run_id=run_id,
            sequence=sequence,
            payload=payload,
            cost_usd=cost_usd,
        )
        self._session.add(row)
        await self._session.flush()
        logger.debug("audit recorded", extra={"context": {"event_type": event_type}})
        return row.id

    async def record_independently(
        self,
        *,
        event_type: str,
        actor: str,
        business_id: BusinessId | None = None,
        workflow_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append one entry in its own committed transaction (M6-F38).

        For refusals only. A denial is recorded so that something is known to
        have tried, and that knowledge cannot be conditional on the attempt
        having succeeded — which is what `record` makes it, because the caller's
        scope rolls back when the refusal is raised. The probe that found this
        showed one refused dispatch and zero persisted rows.

        Returns nothing on purpose: the row id is a handle for linking an entry
        to a Decision Log entry written in the *caller's* transaction, and this
        row is deliberately not in that transaction. Offering the id would
        invite exactly the cross-transaction reference that cannot be relied on.

        Failure posture: a denial record that cannot be written must not turn a
        refusal into a success, so a write failure is logged and swallowed and
        the caller still refuses. Losing the record is bad; losing the refusal
        is a §10 breach.
        """
        if self._denial_sessions is None:
            # Single-session callers (unit tests) keep the old behaviour. The
            # Kernel always wires the factory, so production never lands here.
            await self.record(
                event_type=event_type,
                actor=actor,
                business_id=business_id,
                workflow_id=workflow_id,
                payload=payload,
            )
            return

        try:
            async with session_scope(self._denial_sessions) as session:
                session.add(
                    self._row(
                        event_type=event_type,
                        actor=actor,
                        business_id=business_id,
                        workflow_id=workflow_id,
                        payload=payload,
                    )
                )
        except Exception:
            logger.exception(
                "could not persist a denial record; the denial still stands",
                extra={"context": {"event_type": event_type}},
            )
            return
        logger.debug("denial recorded", extra={"context": {"event_type": event_type}})

    def _row(
        self,
        *,
        event_type: str,
        actor: str,
        business_id: BusinessId | None = None,
        workflow_id: str | None = None,
        run_id: str | None = None,
        sequence: int | None = None,
        payload: dict[str, Any] | None = None,
        cost_usd: Decimal | None = None,
    ) -> AuditLogRow:
        """Build one redacted row. Shared so both writers redact identically."""
        return AuditLogRow(
            event_type=event_type,
            actor=actor,
            business_id=business_id,
            workflow_id=workflow_id,
            run_id=run_id,
            sequence=sequence,
            payload=redact(payload or {}),
            cost_usd=cost_usd,
        )

    async def latest_entry_time(self, business_id: BusinessId, event_type: str) -> datetime | None:
        """Return when this business last recorded ``event_type``, or None.

        §11 makes this log the place a thing is *recorded to have happened*, so
        "when did this company last finish a piece of work" has an answer here
        and nowhere else: a capability result is terminal and does not persist
        (D-001), and the ledger row records what the work cost rather than when
        it landed. D-027.2 admits exactly this class of fact as a KPI source.

        Returns the timestamp as stored. Postgres keeps its offset; SQLite,
        under test, hands it back naive — so a caller doing arithmetic against
        an aware `now` has to say what a naive value means rather than assume.
        This returns the fact; it does not paper over the dialect.
        """
        stmt = (
            select(AuditLogRow.recorded_at)
            .where(AuditLogRow.business_id == business_id)
            .where(AuditLogRow.event_type == event_type)
            .order_by(AuditLogRow.recorded_at.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def latest_platform_entry(self, event_type: str) -> PlatformAuditEntry | None:
        """Return the most recent platform-level entry of ``event_type``, or None.

        The read half of a transition detector for a caller with no "current
        state" table of its own (D-046: "current state is re-derived on read,
        never stored"). `jarvis.executive.liveness.raise_runtime_liveness_alerts`
        is the first caller (packet P0-C): comparing this call's result against
        a freshly computed verdict is how a two-signal outage is told apart
        from a still-ongoing one, without a second, separately-maintained
        "current state" column that could drift out of sync with this log.

        Platform-scoped (``business_id IS NULL``) for the same reason
        `DecisionLog.platform_feed` is: an outage or a crash-looping part
        belongs to no single company (spec §3.1, §9).

        Args:
            event_type: Dotted event name to look up the newest record of.

        Returns:
            The newest matching entry, or None if this event type has never
            been recorded at the platform level.
        """
        stmt = (
            select(AuditLogRow.payload, AuditLogRow.recorded_at)
            .where(AuditLogRow.business_id.is_(None))
            .where(AuditLogRow.event_type == event_type)
            .order_by(AuditLogRow.recorded_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        payload, recorded_at = row
        return PlatformAuditEntry(payload=payload, recorded_at=recorded_at)

    async def for_business(
        self, business_id: BusinessId, *, limit: int = 100
    ) -> Sequence[AuditLogRow]:
        """Return recent audit entries for one business, newest first.

        Drill-down only: this is never the operator's default view (spec §12.5).
        """
        stmt = (
            select(AuditLogRow)
            .where(AuditLogRow.business_id == business_id)
            .order_by(AuditLogRow.recorded_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()
