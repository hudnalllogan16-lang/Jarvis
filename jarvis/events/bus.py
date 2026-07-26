"""Event bus (spec §2, delivery semantics per A-002).

Cross-business signals MUST travel here rather than as direct calls between
workers (spec §2). Delivery is at-least-once with consumer-side deduplication:
exactly-once delivery is not achievable across a process boundary, so the
guarantee is moved to the consumer, where it can actually be enforced.

That matters more here than in a typical system because A-002 makes events a
Business Manager wake condition (spec §2.1). A duplicate delivery would
otherwise mean a duplicate wake cycle, duplicate model spend, and potentially a
duplicate approval request in front of the operator.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.kernel.ids import BusinessId, EventId
from jarvis.kernel.logging import get_logger, redact
from jarvis.observability.audit import AuditLog
from jarvis.persistence.models import EventConsumptionRow, EventRow

logger = get_logger(__name__)


class Event(BaseModel):
    """An immutable published event."""

    model_config = ConfigDict(frozen=True)

    event_id: EventId
    event_type: str
    business_id: BusinessId | None = None
    payload: dict[str, Any] = {}


class EventBus:
    """Durable publish/consume with per-consumer deduplication (A-002)."""

    def __init__(self, session: AsyncSession, audit: AuditLog) -> None:
        """Args:
        session: Active session.
        audit: Audit log — every event is an auditable occurrence (spec §11).
        """
        self._session = session
        self._audit = audit

    async def publish(self, event: Event) -> EventId:
        """Publish one event.

        Args:
            event: The event. Its ``event_id`` is minted in an activity (D-004)
                and is the deduplication key.

        Returns:
            The event id.
        """
        self._session.add(
            EventRow(
                event_id=event.event_id,
                event_type=event.event_type,
                business_id=event.business_id,
                payload=redact(event.payload),
            )
        )
        await self._session.flush()
        await self._audit.record(
            event_type="event.published",
            actor=event.business_id or "platform",
            business_id=event.business_id,
            payload={"event_id": event.event_id, "type": event.event_type},
        )
        return event.event_id

    async def claim(
        self,
        consumer_id: str,
        event_types: Sequence[str],
        *,
        business_id: BusinessId | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Claim unconsumed events of the given types for one consumer.

        Claiming is the deduplication point: a consumption row is inserted per
        event, and a duplicate delivery collides on the composite primary key
        and is skipped. The claim commits with the caller's transaction, so an
        event is only marked consumed if the work that consumed it also commits.

        Args:
            consumer_id: Stable consumer identity, e.g. a Manager's business id.
            event_types: Event types this consumer subscribes to.
            business_id: Restrict the claim to events belonging to one business.
                A consumer that *is* a business must pass it. Type alone is not
                a filter: a Manager subscribed to `capability.result_returned`
                would otherwise claim every other company's results and wake on
                them, which crosses spec §10's isolation boundary in the one
                direction §2.1 makes expensive — each leaked event is a wake
                cycle, and each wake cycle is a model call. Left optional
                because a platform-wide consumer (the Manager lifecycle reader)
                legitimately watches every business.
            limit: Maximum events to claim in one call.

        Returns:
            Newly claimed events, oldest first. Already-consumed events are
            never returned twice to the same consumer.
        """
        if not event_types:
            return []

        consumed = select(EventConsumptionRow.event_id).where(
            EventConsumptionRow.consumer_id == consumer_id
        )
        stmt = (
            select(EventRow)
            .where(EventRow.event_type.in_(list(event_types)))
            .where(EventRow.event_id.not_in(consumed))
            .order_by(EventRow.published_at)
            .limit(limit)
        )
        if business_id is not None:
            # Strict equality, so an event published without a business reaches
            # no Manager at all. Waking every Manager on one platform-wide event
            # is a mechanism nobody has asked for, and guessing it here would
            # multiply spend across every company on the platform.
            stmt = stmt.where(EventRow.business_id == business_id)
        rows = (await self._session.scalars(stmt)).all()

        claimed: list[Event] = []
        for row in rows:
            if await self._mark_consumed(row.event_id, consumer_id):
                claimed.append(
                    Event(
                        event_id=EventId(row.event_id),
                        event_type=row.event_type,
                        business_id=BusinessId(row.business_id) if row.business_id else None,
                        payload=row.payload,
                    )
                )
        if claimed:
            logger.debug(
                "events claimed",
                extra={"context": {"consumer": consumer_id, "count": len(claimed)}},
            )
        return claimed

    async def _mark_consumed(self, event_id: str, consumer_id: str) -> bool:
        """Record consumption, returning False if this consumer already had it.

        The race this closes: two workers polling for the same consumer at the
        same instant both see the event as unconsumed. One insert wins, the
        other raises IntegrityError and is told to skip. Without this, both
        would proceed and the deduplication guarantee would be advisory only.
        """
        savepoint = await self._session.begin_nested()
        try:
            self._session.add(EventConsumptionRow(event_id=event_id, consumer_id=consumer_id))
            await self._session.flush()
        except IntegrityError:
            await savepoint.rollback()
            return False
        return True

    async def already_consumed(self, event_id: EventId, consumer_id: str) -> bool:
        """Return whether ``consumer_id`` has already handled ``event_id``."""
        row = await self._session.get(EventConsumptionRow, (event_id, consumer_id))
        return row is not None
