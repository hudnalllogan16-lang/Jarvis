"""Scheduler tests (spec §9 timers, §2.1 event wakes).

These close M3-F3: the 24h and 7-day rules were implemented in Milestone 3 and
had no caller. The scheduler is that caller, so the rules are now driven rather
than merely present.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalRequest, ApprovalState
from jarvis.approvals.service import ApprovalService
from jarvis.domain.contract import BusinessContract
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.ids import BusinessTypeName, DecisionId
from jarvis.notifications.service import NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import ApprovalRow, NotificationRow
from jarvis.registry.registry import BusinessRegistry

NOW = datetime(2026, 7, 1, tzinfo=UTC)


async def _live_business(registry: BusinessRegistry, contract: BusinessContract) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )
    await registry.register_instance(contract)
    await registry.transition(
        contract.business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_start"),
        reason="Started for testing.",
    )


def _service(session: AsyncSession) -> ApprovalService:
    return ApprovalService(session, AuditLog(session), DecisionLog(session))


def _request(contract: BusinessContract) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id="apr_1",
        business_id=contract.business_id,
        action_type="affiliate.publish_post",
        action_summary="publish today's post",
        triggering_condition="Today's post is ready.",
        downside="A weak post could lose a few readers.",
    )


async def test_renotification_fires_once_per_day(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §9: re-notify after 24 hours, not repeatedly on every sweep."""
    await _live_business(registry, contract)
    approvals = _service(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)

    day_later = NOW + timedelta(hours=25)
    due = await approvals.due_for_renotification(now=day_later)
    assert len(due) == 1

    await approvals.mark_notified("apr_1", now=day_later)
    assert await approvals.due_for_renotification(now=day_later) == []
    assert len(await approvals.due_for_renotification(now=day_later + timedelta(hours=25))) == 1


async def test_expiry_pauses_the_business(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §9: auto-pause after 7 days, never auto-approve."""
    await _live_business(registry, contract)
    approvals = _service(session)
    await approvals.request(request=_request(contract), contract=contract, now=NOW)

    to_pause = await approvals.expire_stale(
        decision_id=DecisionId("d_exp"), now=NOW + timedelta(days=8)
    )
    assert to_pause == [contract.business_id]

    row = await session.get(ApprovalRow, "apr_1")
    assert row is not None
    assert row.state == ApprovalState.EXPIRED_PAUSED.value

    await registry.transition(
        contract.business_id,
        LifecycleState.PAUSED,
        decision_id=DecisionId("d_pause"),
        reason="A request went unanswered for a week.",
        actor="platform",
    )
    assert await registry.get_state(contract.business_id) is LifecycleState.PAUSED


async def test_notifications_carry_no_technical_language(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §12.5 applies to notifications as much as to the dashboard."""
    from jarvis.kernel.ids import new_notification_id
    from jarvis.notifications.service import NotificationKind

    await _live_business(registry, contract)
    await NotificationService(session).notify(
        notification_id=new_notification_id(),
        kind=NotificationKind.PAUSED,
        title=f"{contract.display_name} is paused",
        body=(
            "A request went unanswered for a week. Jarvis never assumes yes, "
            "so the company paused until you decide."
        ),
        business_id=contract.business_id,
    )
    rows = list((await session.scalars(select(NotificationRow))).all())
    assert len(rows) == 1
    for term in ("workflow", "retry", "dead-letter", "temporal", "capability"):
        assert term not in (rows[0].title + rows[0].body).lower()


@pytest.mark.parametrize(
    ("cron", "fires_at", "period_ends"),
    [
        ("0 9 * * *", "2026-07-28T09:00:00+00:00", "2026-07-29T09:00:00+00:00"),
        ("0 * * * *", "2026-07-27T23:00:00+00:00", "2026-07-28T00:00:00+00:00"),
        # The sharper edge the ratification review measured: a legitimate
        # twice-daily schedule that `_interval_seconds` turned into an hourly
        # one — twelve times the intended cycles, every one of them billable,
        # bounded only by `max_cycles_per_day` (M10-F4).
        ("0 9,16 * * *", "2026-07-28T09:00:00+00:00", "2026-07-28T16:00:00+00:00"),
        (None, None, None),
    ],
)
def test_the_schedule_is_read_as_a_calendar_not_an_interval(
    cron: str | None, fires_at: str | None, period_ends: str | None
) -> None:
    """M10-F4/M10-F13's fix, at the seam the Manager actually reads (design 4.2).

    Until M10 this function's ancestor (`_interval_seconds`) reduced every
    five-field expression to 3600 or 86400 seconds, so the stored value did not
    mean what it said and — worse — that interval was re-anchored on every park,
    which is how a daily schedule drifted 22:40 -> 06:14 in a single incident.

    The anchor is 22:40 on the 27th deliberately: it is the instant M10-F13
    measured, and the daily row asserts the next fire is 09:00 the following
    morning rather than 22:40 the following night. That one comparison is the
    drift, ended.
    """
    from jarvis.domain.contract import WakeConditions
    from jarvis.manager.activities import _schedule_instants

    anchor = datetime(2026, 7, 27, 22, 40, 31, tzinfo=UTC)
    next_fire, period_end = _schedule_instants(WakeConditions(schedule_cron=cron), anchor)

    assert next_fire == (datetime.fromisoformat(fires_at) if fires_at else None)
    assert period_end == (datetime.fromisoformat(period_ends) if period_ends else None)


def test_an_expression_the_platform_cannot_keep_is_refused_not_flattened() -> None:
    """The other half of 4.2, and the half that used to be silent.

    `_interval_seconds("bad")` returned `None`, which the workflow reads as
    "this company has no schedule at all" — so a typo in a cron expression
    turned a scheduled company into one that only ever woke on events, with
    nothing anywhere saying so. The expression is now refused where a person can
    still fix it: at contract validation.
    """
    from pydantic import ValidationError

    from jarvis.domain.contract import WakeConditions

    with pytest.raises(ValidationError):
        WakeConditions(schedule_cron="bad")
