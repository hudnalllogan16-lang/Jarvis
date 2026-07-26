"""Notification service (spec §5, §9; language per §12.5).

Notifications are written in plain consequence language at creation time rather
than templated from an error at read time. §12.5 forbids stack traces and error
codes in the default view, and the reliable way to honour that is to never store
one in a field the dashboard renders.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.kernel.ids import BusinessId
from jarvis.kernel.logging import get_logger
from jarvis.persistence.models import NotificationRow

logger = get_logger(__name__)


class NotificationKind(StrEnum):
    """Why the operator is being told something."""

    NEEDS_APPROVAL = "needs_approval"
    REMINDER = "reminder"
    STUCK = "stuck"
    PAUSED = "paused"
    SPENDING = "spending"
    GRADUATED = "graduated"


class NotificationService:
    """Creates and reads operator notifications."""

    def __init__(self, session: AsyncSession) -> None:
        """Args:
        session: Active session.
        """
        self._session = session

    async def notify(
        self,
        *,
        notification_id: str,
        kind: NotificationKind,
        title: str,
        body: str,
        business_id: BusinessId | None = None,
        link_ref: str | None = None,
    ) -> str:
        """Create one notification.

        Args:
            notification_id: Minted in an activity (D-004).
            kind: Category, used for grouping and iconography.
            title: Short headline in operator language.
            body: One or two sentences of plain consequence language.
            business_id: Owning company, or None for platform-wide notices.
            link_ref: Approval or dead-letter id the operator can act on.

        Returns:
            The notification id.
        """
        self._session.add(
            NotificationRow(
                notification_id=notification_id,
                business_id=business_id,
                kind=kind.value,
                title=title,
                body=body,
                link_ref=link_ref,
            )
        )
        await self._session.flush()
        return notification_id

    async def unread(self, *, limit: int = 50) -> Sequence[NotificationRow]:
        """Return unread notifications, newest first."""
        stmt = (
            select(NotificationRow)
            .where(NotificationRow.read.is_(False))
            .order_by(NotificationRow.created_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def mark_read(self, notification_id: str) -> None:
        """Mark one notification as read (an operator's explicit dismissal)."""
        row = await self._session.get(NotificationRow, notification_id)
        if row is not None:
            row.read = True
            await self._session.flush()

    async def resolve_for(self, link_ref: str) -> int:
        """Mark every unread notification tied to ``link_ref`` as read.

        Called when the thing a notification pointed at is no longer pending
        — an approval gets decided, most often (M6-5a item 5). §12.5's "no
        permanent accumulation" only holds if a resolved event actually clears
        the queue rather than sitting there until the operator notices and
        dismisses it by hand; this is the automatic half of that, and
        :meth:`mark_read` remains the manual half for everything else.

        Returns:
            How many notifications were resolved, for callers that want to
            know whether anything changed.
        """
        stmt = (
            select(NotificationRow)
            .where(NotificationRow.read.is_(False))
            .where(NotificationRow.link_ref == link_ref)
        )
        rows = (await self._session.scalars(stmt)).all()
        for row in rows:
            row.read = True
        if rows:
            await self._session.flush()
        return len(rows)

    async def unread_count(self) -> int:
        """Return how many notifications are unread."""
        return len(await self.unread(limit=1000))
