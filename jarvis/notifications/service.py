"""Notification service (spec §5, §9; language per §12.5).

Notifications are written in plain consequence language at creation time rather
than templated from an error at read time. §12.5 forbids stack traces and error
codes in the default view, and the reliable way to honour that is to never store
one in a field the dashboard renders.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalState
from jarvis.kernel.ids import BusinessId
from jarvis.kernel.logging import get_logger
from jarvis.persistence.models import ApprovalRow, NotificationRow

logger = get_logger(__name__)


class NotificationKind(StrEnum):
    """Why the operator is being told something."""

    NEEDS_APPROVAL = "needs_approval"
    REMINDER = "reminder"
    STUCK = "stuck"
    PAUSED = "paused"
    SPENDING = "spending"
    GRADUATED = "graduated"
    # A D-035 "something arrived while paused" kind was drafted here
    # (ANSWERED_WHILE_PAUSED) against this packet's own description. It is
    # withdrawn: packet M8-10 merged into `main` mid-packet with the real
    # kind, `WAITING_ON_RESUME`, covering every dropped wake reason rather
    # than only decided approvals — see `jarvis/manager/activities.py`'s
    # note and the M8-9 report for the reviewed copy that goes with it. This
    # lane branched before that merge and has no path to `main`'s file.


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
        """Return unread notifications, newest first.

        Reconciled against reality on every read (M6 product re-review F1):
        a notification of an approval-linked kind (`NEEDS_APPROVAL`,
        `REMINDER` — both always carry `link_ref = approval_id`, see
        `request_approval` in `jarvis/manager/activities.py` and `_renotify`
        in `jarvis/scheduler/service.py`) is excluded unless that approval
        still exists *and* is still pending. "No longer pending" covers every
        way that can happen — decided through `/api/decide` (which also
        resolves it eagerly, in `_decide`), expired by the scheduler's 7-day
        sweep, or any future path that changes `ApprovalRow.state` without
        remembering to call `resolve_for` — and so does "never existed at
        all": live data held exactly this case, two `needs_approval`
        notifications whose `link_ref` named no row in `approvals` at all
        (M7 verification, real dev DB). Both are "not currently pending", so
        both are excluded the same way. The eager resolve on decide stays;
        this is the backstop so a gap in event coverage — or a row that was
        simply never written — strands a notification in the operator's
        queue forever instead of for one read.

        A notification of any other kind is untouched by this filter even if
        it happens to carry a `link_ref` (e.g. a future kind pointing at a
        dead-letter id) — reconciling against `ApprovalRow` is only correct
        for the kinds that are actually approval-linked.
        """
        stmt = (
            select(NotificationRow)
            .outerjoin(ApprovalRow, ApprovalRow.approval_id == NotificationRow.link_ref)
            .where(NotificationRow.read.is_(False))
            .where(
                or_(
                    NotificationRow.kind.not_in(
                        [NotificationKind.NEEDS_APPROVAL.value, NotificationKind.REMINDER.value]
                    ),
                    ApprovalRow.state == ApprovalState.PENDING.value,
                )
            )
            .order_by(NotificationRow.created_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def has_unread(self, business_id: BusinessId, *, kind: NotificationKind) -> bool:
        """Return whether this company already has an unread notice of ``kind``.

        Asked before raising a repeatable notice, so a condition that recurs on
        a timer produces one entry in the operator's queue rather than one per
        check (D-034.1's park is the first such condition: a Manager that cannot
        read its context looks again every fifteen minutes for as long as the
        outage lasts). §12.5 forbids permanent accumulation, and ninety-six
        identical notices a day is that, arriving faster than anyone can dismiss
        them.

        Deliberately *unread*, not *exists*: an operator who has dismissed the
        notice has said they know, and a condition that is still true when the
        next check comes round is worth telling them about again. This is the
        same reconciliation posture :meth:`unread` takes — the queue reflects
        what is still outstanding, not what has ever happened.

        Args:
            business_id: The company to check.
            kind: Which category of notice.

        Returns:
            True if at least one unread notification of that kind exists.
        """
        stmt = (
            select(NotificationRow.notification_id)
            .where(NotificationRow.business_id == business_id)
            .where(NotificationRow.kind == kind.value)
            .where(NotificationRow.read.is_(False))
            .limit(1)
        )
        return await self._session.scalar(stmt) is not None

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
