"""Circuit breaker tests (spec §9, §12.5; precedence per D-003)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import CircuitBreakerOpenError
from jarvis.kernel.ids import DecisionId
from jarvis.observability.decision_log import DecisionLog


def _breaker(session: AsyncSession, ceiling: str) -> tuple[CircuitBreaker, BudgetLedger]:
    ledger = BudgetLedger(session, platform_ceiling_usd=Decimal(ceiling))
    return CircuitBreaker(ledger, DecisionLog(session), ceiling_usd=Decimal(ceiling)), ledger


async def test_closed_breaker_permits_dispatch(session: AsyncSession) -> None:
    breaker, _ = _breaker(session, "500.00")
    await breaker.assert_closed()


async def test_breaker_opens_at_the_ceiling(
    session: AsyncSession, contract: BusinessContract
) -> None:
    breaker, ledger = _breaker(session, "10.00")
    await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.assert_closed()


async def test_released_spend_does_not_hold_the_breaker_open(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Work that failed never spent, so it must not keep the platform halted."""
    breaker, ledger = _breaker(session, "10.00")
    reservation = await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))
    await ledger.release(reservation)
    await breaker.assert_closed()


async def test_trip_writes_an_operator_readable_explanation(
    session: AsyncSession,
) -> None:
    """§12.5 promises "Jarvis paused spending — here's why"; v1.4 names no writer.

    §11.5 also requires that "why" be answerable without reading raw logs, so
    the narrative must exist in the Decision Log at the moment of the halt.
    """
    breaker, _ = _breaker(session, "500.00")
    log = DecisionLog(session)
    await breaker.trip(decision_id=DecisionId("dec_trip"), spend_usd=Decimal("500.00"))

    entries = await log.platform_feed()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.business_id is None
    assert entry.summary == "Jarvis paused spending across all companies."
    for jargon in ("circuit", "breaker", "workflow", "dispatch", "ledger"):
        assert jargon not in entry.rationale.lower()
    assert "$500.00" in entry.rationale


async def test_trip_rationale_never_promises_raising_the_limit(session: AsyncSession) -> None:
    """M9-9 product REVISE item 5: the rationale used to end "...resets or you
    raise it", and nothing on this surface exposes the platform ceiling
    (`jarvis/kernel/config.py`) as an editable setting an operator can reach —
    the recovery copy must say where the number lives, not imply a control
    that isn't there."""
    breaker, _ = _breaker(session, "500.00")
    await breaker.trip(decision_id=DecisionId("dec_trip3"), spend_usd=Decimal("500.00"))

    entry = (await DecisionLog(session).platform_feed())[0]
    assert "raise" not in entry.rationale.lower()


async def test_trip_can_name_the_triggering_company(session: AsyncSession) -> None:
    breaker, _ = _breaker(session, "500.00")
    await breaker.trip(
        decision_id=DecisionId("dec_trip2"),
        spend_usd=Decimal("500.00"),
        triggering_business="Test Affiliate Co",
    )
    entries = await DecisionLog(session).platform_feed()
    assert "Test Affiliate Co" in entries[0].rationale
