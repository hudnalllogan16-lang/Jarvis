"""Decision Log tests (spec §11.5)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.kernel.ids import BusinessId, DecisionId
from jarvis.observability.decision_log import DecisionLog


async def test_entry_requires_a_real_explanation(session: AsyncSession) -> None:
    """§11.5: an entry that explains nothing defeats the component's purpose."""
    log = DecisionLog(session)
    with pytest.raises(ValueError, match="summary and rationale"):
        await log.record(decision_id=DecisionId("dec_1"), summary="  ", rationale="because")


async def test_activity_feed_is_business_scoped(session: AsyncSession) -> None:
    log = DecisionLog(session)
    await log.record(
        decision_id=DecisionId("dec_a"),
        business_id=BusinessId("biz_a"),
        summary="Published today's post.",
        rationale="It was the highest-value item on the plan.",
    )
    await log.record(
        decision_id=DecisionId("dec_b"),
        business_id=BusinessId("biz_b"),
        summary="Skipped posting.",
        rationale="No approved draft was ready.",
    )
    feed = await log.activity_feed(BusinessId("biz_a"))
    assert [e.decision_id for e in feed] == ["dec_a"]


async def test_platform_decisions_have_no_owning_business(session: AsyncSession) -> None:
    """§9 breaker trips and §3.1 reallocations still owe the operator a why."""
    log = DecisionLog(session)
    await log.record_platform_decision(
        decision_id=DecisionId("dec_breaker"),
        summary="Jarvis paused spending across all companies.",
        rationale="Total spending reached the daily limit you set.",
        action_type="platform.circuit_breaker",
    )
    feed = await log.platform_feed()
    assert len(feed) == 1
    assert feed[0].business_id is None
