"""KPI engine and Health Score tests (spec §5, §3)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.domain.contract import BusinessContract, KpiTarget
from jarvis.kpi.engine import KpiEngine
from jarvis.persistence.models import DeadLetterRow, DecisionLogRow


def _with_target(contract: BusinessContract) -> BusinessContract:
    payload = contract.model_dump()
    payload["kpi_targets"] = [
        KpiTarget(
            key="revenue_mtd",
            operator_label="Monthly Revenue",
            target_value=Decimal("1000"),
            unit="USD",
        ).model_dump()
    ]
    return BusinessContract.model_validate(payload)


async def test_kpi_series_is_append_only(session: AsyncSession, contract: BusinessContract) -> None:
    """Overwriting a value would make a trend report unreproducible (§3)."""
    engine = KpiEngine(session)
    for value in ("10", "20", "30"):
        await engine.record(
            business_id=contract.business_id, key="revenue_mtd", value=Decimal(value)
        )
    series = await engine.series(contract.business_id, "revenue_mtd")
    assert [str(row.value) for row in series][-1].startswith("30")
    assert len(series) == 3


async def test_latest_returns_the_newest_value(
    session: AsyncSession, contract: BusinessContract
) -> None:
    engine = KpiEngine(session)
    await engine.record(business_id=contract.business_id, key="posts", value=Decimal("4"))
    await engine.record(business_id=contract.business_id, key="posts", value=Decimal("9"))
    assert await engine.latest(contract.business_id, "posts") == Decimal("9")


async def test_new_company_with_no_targets_is_not_penalised(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A company cannot be failing objectives nobody set."""
    assert await KpiEngine(session).attainment(contract) == 100


async def test_attainment_is_capped_at_target(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Beating a goal is 100%, not 400% — otherwise one runaway metric would
    mask every other target being missed."""
    engine = KpiEngine(session)
    with_target = _with_target(contract)
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("4000"))
    assert await engine.attainment(with_target) == 100


async def test_partial_attainment(session: AsyncSession, contract: BusinessContract) -> None:
    engine = KpiEngine(session)
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("250"))
    assert await engine.attainment(_with_target(contract)) == 25


async def test_healthy_company_scores_well(
    session: AsyncSession, contract: BusinessContract
) -> None:
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("0"))
    assert health.band == "healthy"
    assert health.summary == "Running normally."


async def test_stuck_work_dominates_the_score(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A company that cannot finish its work is broken in a way budget headroom
    cannot compensate for."""
    for n in range(3):
        session.add(
            DeadLetterRow(
                invocation_id=f"inv_{n}",
                business_id=contract.business_id,
                capability="research",
                attempts=3,
                operator_summary="Couldn't finish a task.",
                technical_detail="stub",
            )
        )
    await session.flush()
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("0"))
    assert health.reliability == 40
    assert health.band != "healthy"
    assert "stuck" in health.summary


async def test_health_summary_names_the_budget_when_it_is_the_problem(
    session: AsyncSession, contract: BusinessContract
) -> None:
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("49.00"))
    assert health.budget_headroom < 20
    assert "spending limit" in health.summary


async def _add_completed_cycles(
    session: AsyncSession, contract: BusinessContract, count: int, *, prefix: str
) -> None:
    for n in range(count):
        session.add(
            DecisionLogRow(
                decision_id=f"dec_{prefix}_{n}",
                business_id=contract.business_id,
                cycle_id=f"cyc_{prefix}_{n}",
                summary="A wake cycle finished.",
                rationale="Nothing more to do this round.",
            )
        )
    await session.flush()


async def test_sustained_zero_attainment_caps_the_band_at_watch(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-020 amendment: a company that ships nothing is not healthy no matter
    how much budget headroom it has, once the pattern is sustained."""
    with_target = _with_target(contract)
    await _add_completed_cycles(session, contract, 5, prefix="stalled")
    health = await KpiEngine(session).health(with_target, spend_usd=Decimal("0"))
    assert health.kpi_attainment == 0
    assert health.zero_attainment_stall is True
    assert health.band == "watch"
    assert "goals" in health.summary


async def test_a_shipping_company_stays_healthy(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The amendment targets zero attainment specifically — a company hitting
    even part of its goals is not pulled down by the same override."""
    engine = KpiEngine(session)
    with_target = _with_target(contract)
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("250"))
    await _add_completed_cycles(session, contract, 5, prefix="shipping")
    health = await engine.health(with_target, spend_usd=Decimal("0"))
    assert health.kpi_attainment == 25
    assert health.zero_attainment_stall is False
    assert health.band == "healthy"


async def test_a_new_company_gets_a_grace_period(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Fewer than the threshold of completed cycles is not "sustained" — a
    brand-new company with targets and no observations yet stays healthy."""
    with_target = _with_target(contract)
    await _add_completed_cycles(session, contract, 4, prefix="new")
    health = await KpiEngine(session).health(with_target, spend_usd=Decimal("0"))
    assert health.kpi_attainment == 0
    assert health.zero_attainment_stall is False
    assert health.band == "healthy"


async def test_health_exposes_its_components(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """§12.5: the operator must be able to ask why without a drill-down."""
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("10"))
    assert 0 <= health.budget_headroom <= 100
    assert 0 <= health.reliability <= 100
    assert 0 <= health.kpi_attainment <= 100
    assert health.summary
