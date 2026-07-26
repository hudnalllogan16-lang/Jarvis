"""Event bus tests (spec §2, delivery semantics per A-002)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.events.bus import Event, EventBus
from jarvis.kernel.ids import BusinessId, EventId
from jarvis.observability.audit import AuditLog


def _bus(session: AsyncSession) -> EventBus:
    return EventBus(session, AuditLog(session))


def _event(n: int, event_type: str = "kpi.threshold_breached") -> Event:
    return Event(
        event_id=EventId(f"evt_{n}"),
        event_type=event_type,
        business_id=BusinessId("biz_a"),
        payload={"n": n},
    )


async def test_claim_returns_matching_events(session: AsyncSession) -> None:
    bus = _bus(session)
    await bus.publish(_event(1))
    claimed = await bus.claim("consumer-1", ["kpi.threshold_breached"])
    assert [e.event_id for e in claimed] == ["evt_1"]


async def test_second_claim_returns_nothing(session: AsyncSession) -> None:
    """A-002: a redelivered event must not produce a second wake cycle."""
    bus = _bus(session)
    await bus.publish(_event(1))
    assert len(await bus.claim("consumer-1", ["kpi.threshold_breached"])) == 1
    assert await bus.claim("consumer-1", ["kpi.threshold_breached"]) == []


async def test_distinct_consumers_each_receive_the_event(session: AsyncSession) -> None:
    """Deduplication is per consumer, not global — fan-out must still work."""
    bus = _bus(session)
    await bus.publish(_event(1))
    assert len(await bus.claim("consumer-1", ["kpi.threshold_breached"])) == 1
    assert len(await bus.claim("consumer-2", ["kpi.threshold_breached"])) == 1


async def test_unsubscribed_types_are_not_delivered(session: AsyncSession) -> None:
    bus = _bus(session)
    await bus.publish(_event(1, "approval.decided"))
    assert await bus.claim("consumer-1", ["kpi.threshold_breached"]) == []


async def test_empty_subscription_claims_nothing(session: AsyncSession) -> None:
    """A consumer subscribing to nothing must not receive everything."""
    bus = _bus(session)
    await bus.publish(_event(1))
    assert await bus.claim("consumer-1", []) == []


async def test_events_are_claimed_in_publication_order(session: AsyncSession) -> None:
    bus = _bus(session)
    for n in range(1, 4):
        await bus.publish(_event(n))
    claimed = await bus.claim("consumer-1", ["kpi.threshold_breached"])
    assert [e.event_id for e in claimed] == ["evt_1", "evt_2", "evt_3"]


async def test_already_consumed_is_queryable(session: AsyncSession) -> None:
    bus = _bus(session)
    await bus.publish(_event(1))
    await bus.claim("consumer-1", ["kpi.threshold_breached"])
    assert await bus.already_consumed(EventId("evt_1"), "consumer-1")
    assert not await bus.already_consumed(EventId("evt_1"), "consumer-2")


async def test_publish_redacts_secret_shaped_payload(session: AsyncSession) -> None:
    """Spec §10: secrets must not reach logs or stored payloads."""
    bus = _bus(session)
    await bus.publish(
        Event(event_id=EventId("evt_9"), event_type="x", payload={"api_key": "sk-live"})
    )
    claimed = await bus.claim("c", ["x"])
    assert claimed[0].payload["api_key"] == "[REDACTED]"


async def test_a_business_claim_never_reaches_another_businesss_events(
    session: AsyncSession,
) -> None:
    """Spec §10 isolation, at the wake boundary (M6-F21).

    `Scheduler.dispatch_events` uses a business id as the consumer id and the
    business's configured `event_triggers` as the type filter. Type alone is
    not a filter: every affiliate company subscribes to the same types, so one
    company's `capability.result_returned` claimed the next company's results
    and signalled its Manager to wake on them. §2.1 makes that expensive as
    well as wrong — each leaked event is a wake cycle, and each wake cycle is a
    model call charged to a company that did nothing.
    """
    bus = _bus(session)
    await bus.publish(
        Event(
            event_id=EventId("evt_other"),
            event_type="approval.decided",
            business_id=BusinessId("biz_a"),
            payload={"approval_id": "apr_a"},
        )
    )
    assert await bus.claim("biz_b", ["approval.decided"], business_id=BusinessId("biz_b")) == []
    claimed = await bus.claim("biz_a", ["approval.decided"], business_id=BusinessId("biz_a"))
    assert [e.event_id for e in claimed] == ["evt_other"]


async def test_an_unscoped_claim_still_sees_every_business(session: AsyncSession) -> None:
    """Negative control, and a real requirement: the Manager lifecycle reader
    watches `business.activated` across the whole platform, so the filter must
    stay opt-in rather than become the only behaviour."""
    bus = _bus(session)
    await bus.publish(_event(1))
    assert len(await bus.claim("manager-lifecycle", ["kpi.threshold_breached"])) == 1


async def test_a_platform_event_wakes_no_manager(session: AsyncSession) -> None:
    """An event published without a business belongs to no company's wake
    conditions. Waking every Manager on one such event would multiply spend
    across the platform, and no mechanism asks for it."""
    bus = _bus(session)
    await bus.publish(
        Event(event_id=EventId("evt_platform"), event_type="approval.decided", payload={})
    )
    assert await bus.claim("biz_a", ["approval.decided"], business_id=BusinessId("biz_a")) == []
