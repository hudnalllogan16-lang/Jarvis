"""Notification read-path reconciliation (M6 product re-review F1).

The M6 closure recorded that only the decide route (`_decide` in
`jarvis/api/app.py`) resolved an approval-linked notification, by calling
`NotificationService.resolve_for` in the same transaction as the decision.
That is real, but it is an *eager* path: anything that changes an approval's
state without also remembering to call `resolve_for` — the scheduler's 7-day
expiry sweep did exactly this (`Scheduler._expire_and_pause` in
`jarvis/scheduler/service.py` never calls it) — leaves the notification
sitting in the operator's queue forever, contradicting an approval the
operator can no longer act on.

These tests exercise the fix directly at the service layer: `unread()` now
joins against `ApprovalRow` and excludes any row whose linked approval is no
longer pending, regardless of which code path (or lack of one) changed that
approval's state. The eager `resolve_for` call is unaffected and still
exercised here so both halves are proven to coexist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalRequest
from jarvis.approvals.service import ApprovalService
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.ids import DecisionId, new_notification_id
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _approvals(session: AsyncSession) -> ApprovalService:
    return ApprovalService(session, AuditLog(session), DecisionLog(session))


def _request(contract: BusinessContract, *, approval_id: str = "apr_1") -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=approval_id,
        business_id=contract.business_id,
        action_type="affiliate.publish_post",
        action_summary="publish today's post",
        triggering_condition="Today's post is ready.",
        downside="A weak post could lose a few readers.",
    )


async def _notify_needs_approval(
    session: AsyncSession, contract: BusinessContract, approval_id: str
) -> str:
    notification_id = new_notification_id()
    await NotificationService(session).notify(
        notification_id=notification_id,
        kind=NotificationKind.NEEDS_APPROVAL,
        title=f"{contract.display_name} needs your OK",
        body="publish today's post",
        business_id=contract.business_id,
        link_ref=approval_id,
    )
    return notification_id


async def test_notification_disappears_once_approved_without_any_resolve_call(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The read-path guarantee itself: even if nothing ever calls
    `resolve_for` for this decision, the notification stops rendering as
    needing the operator the moment the approval it names is no longer
    pending."""
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)
    notification_id = await _notify_needs_approval(session, contract, "apr_1")

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id in unread_ids

    await approvals.approve("apr_1", contract=contract, decision_id=DecisionId("dec_1"), now=NOW)
    # Deliberately not calling NotificationService.resolve_for here — that is
    # exactly the gap the scheduler's expiry path left, per the M6 closure.

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id not in unread_ids


async def test_notification_disappears_once_denied_without_any_resolve_call(
    session: AsyncSession, contract: BusinessContract
) -> None:
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)
    notification_id = await _notify_needs_approval(session, contract, "apr_1")

    await approvals.deny("apr_1", contract=contract, decision_id=DecisionId("dec_1"), now=NOW)

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id not in unread_ids


async def test_24h_reminder_notification_clears_once_the_approval_is_decided(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The packet's named case: a REMINDER notification (raised by the
    scheduler's `_renotify` after 24 hours unanswered) carries the same
    `link_ref` as the original request and must reconcile the same way."""
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)

    reminder_id = new_notification_id()
    await NotificationService(session).notify(
        notification_id=reminder_id,
        kind=NotificationKind.REMINDER,
        title=f"{contract.display_name} is still waiting on you",
        body="Publish today's post — this has been waiting a day.",
        business_id=contract.business_id,
        link_ref="apr_1",
    )

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert reminder_id in unread_ids

    await approvals.approve(
        "apr_1", contract=contract, decision_id=DecisionId("dec_1"), now=NOW + timedelta(hours=25)
    )

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert reminder_id not in unread_ids


async def test_notification_clears_when_its_approval_expires_unanswered(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The exact stranding the M6 closure recorded: `Scheduler._expire_and_pause`
    moves the approval to `EXPIRED_PAUSED` and never calls `resolve_for` for
    the notification that asked about it. Before this fix that notification
    sat in the queue forever; now the read path itself checks reality."""
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)
    notification_id = await _notify_needs_approval(session, contract, "apr_1")

    expired_businesses = await approvals.expire_stale(
        decision_id=DecisionId("dec_exp"), now=NOW + timedelta(days=8)
    )
    assert expired_businesses == [contract.business_id]

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id not in unread_ids


async def test_needs_approval_notification_with_no_matching_approval_row_is_excluded(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Found live (M7 verification, real dev DB): two `needs_approval`
    notifications whose `link_ref` named no row in `approvals` at all —
    not "decided", not "expired", just no pending approval behind them by any
    name. A filter that only checked "is the matched row still pending"
    would have let these through, since an outer join against a
    `link_ref` naming nothing at all matches nothing to disqualify it on.
    Reconciling by *kind* instead closes that gap: a `needs_approval`
    notification with no backing approval is exactly as not-pending as one
    whose approval was denied.
    """
    notification_id = await _notify_needs_approval(session, contract, "apr_never_written")

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id not in unread_ids


async def test_notification_stays_visible_while_its_approval_is_still_pending(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Negative control: the filter must not hide a notification whose
    approval genuinely still needs the operator."""
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)
    notification_id = await _notify_needs_approval(session, contract, "apr_1")

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id in unread_ids


async def test_unlinked_notification_is_unaffected_by_reconciliation(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A notification with no `link_ref` (e.g. `PAUSED`) names no approval to
    reconcile against, so it is untouched by this filter — it clears only
    through an operator's own dismissal (`mark_read`)."""
    notification_id = new_notification_id()
    await NotificationService(session).notify(
        notification_id=notification_id,
        kind=NotificationKind.PAUSED,
        title=f"{contract.display_name} is paused",
        body="A request went unanswered for a week.",
        business_id=contract.business_id,
    )

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id in unread_ids


async def test_resolve_for_still_clears_eagerly_alongside_the_read_path_filter(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The decide-path eager resolve (`resolve_for`) is not removed by this
    fix — it stays the fast path, and the read-path filter is the backstop.
    Both are exercised together here."""
    approvals = _approvals(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)
    notification_id = await _notify_needs_approval(session, contract, "apr_1")

    await approvals.approve("apr_1", contract=contract, decision_id=DecisionId("dec_1"), now=NOW)
    resolved = await NotificationService(session).resolve_for("apr_1")
    assert resolved == 1

    unread_ids = [row.notification_id for row in await NotificationService(session).unread()]
    assert notification_id not in unread_ids
