"""KPI engine and Health Score tests (spec §5, §3)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.domain.contract import BusinessContract, KpiDirection, KpiTarget
from jarvis.kpi.engine import EARLY_DAYS_SUMMARY, STALLED_CYCLE_THRESHOLD, KpiEngine
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


def _with_below_target(contract: BusinessContract, target_value: str = "24") -> BusinessContract:
    payload = contract.model_dump()
    payload["kpi_targets"] = [
        KpiTarget(
            key="data_freshness_hours",
            operator_label="Data freshness",
            target_value=Decimal(target_value),
            unit="hours since last check",
            direction=KpiDirection.BELOW,
        ).model_dump()
    ]
    return BusinessContract.model_validate(payload)


async def test_a_below_target_scores_a_good_reading_as_full_attainment(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """M7-F30, the fix: 1 hour against a 24-hour lower-is-better target is an
    excellent reading, not the 4% miss `KpiEngine.attainment` used to compute
    when it compared every metric as higher-is-better."""
    engine = KpiEngine(session)
    below = _with_below_target(contract)
    await engine.record(
        business_id=contract.business_id, key="data_freshness_hours", value=Decimal("1")
    )
    assert await engine.attainment(below) == 100


async def test_a_below_target_still_scores_a_bad_reading_as_a_miss(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Negative control on the fix itself: direction changes which way the
    ratio runs, not whether it can still register a miss. Stale data (48h
    against a 24h target) must score below full attainment."""
    engine = KpiEngine(session)
    below = _with_below_target(contract)
    await engine.record(
        business_id=contract.business_id, key="data_freshness_hours", value=Decimal("48")
    )
    assert await engine.attainment(below) == 50  # 24 / 48


async def test_a_zero_actual_on_a_below_target_is_the_best_reading_not_an_error(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Guards the zero-actual division the direction-aware ratio introduces:
    zero hours since the last check is the best possible freshness reading,
    not an undefined ``target / 0``."""
    engine = KpiEngine(session)
    below = _with_below_target(contract)
    await engine.record(
        business_id=contract.business_id, key="data_freshness_hours", value=Decimal("0")
    )
    assert await engine.attainment(below) == 100


async def test_an_above_target_is_unaffected_by_the_direction_field(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Negative control: a target that never sets `direction` defaults to
    ABOVE and scores exactly as it did before M7-F30's fix."""
    engine = KpiEngine(session)
    with_target = _with_target(contract)
    assert with_target.kpi_targets[0].direction is KpiDirection.ABOVE
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("250"))
    assert await engine.attainment(with_target) == 25


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


async def test_a_healthy_company_with_partial_attainment_reads_as_healthy(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """M7-F53 (M7-F31's live recurrence): the live M7 run showed a healthy
    band beside "Behind on its goals." on a mature company hitting part of
    its goals — the same disagreement M7-F26/D-027.4 fixed for young
    companies, one band up. The badge is right; the old sentence read as
    though it wasn't.
    """
    with_target = _with_target(contract)
    engine = KpiEngine(session)
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("250"))
    await _add_completed_cycles(session, contract, 5, prefix="mature")

    health = await engine.health(with_target, spend_usd=Decimal("0"))

    assert health.kpi_attainment == 25
    assert health.band == "healthy"
    assert health.summary == "Healthy overall — goals need attention."
    assert "Behind" not in health.summary


async def test_partial_attainment_still_reads_as_behind_when_the_band_is_not_healthy(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The other direction of M7-F53's fix: thin headroom pulling the score
    below `HEALTHY` must keep the old wording. The fix answers "does the band
    disagree with the sentence", not "always talk up partial attainment".
    """
    with_target = _with_target(contract)
    engine = KpiEngine(session)
    await engine.record(business_id=contract.business_id, key="revenue_mtd", value=Decimal("250"))

    # headroom 20 (spend 40 of a 50 cap) keeps the "Close to its spending
    # limit" branch from firing (it triggers under 20) while dragging the
    # weighted score below HEALTHY: 20*0.3 + 100*0.45 + 25*0.25 = 57.
    health = await engine.health(with_target, spend_usd=Decimal("40.00"))

    assert health.kpi_attainment == 25
    assert health.budget_headroom == 20
    assert health.band == "watch"
    assert health.summary == "Behind on its goals."


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


async def test_a_young_company_reads_as_new_rather_than_behind(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-027.4, closing M7-F26: the words must agree with the badge.

    The live M7 run showed a healthy band beside "Behind on its goals." on a
    company that had not finished a round of work yet — the recurrence of M6-5's
    finding 5. Inside the grace period the band is right and the sentence was
    not, so the sentence changes: the same fact (nothing hit yet) read the way
    it should be read on day one.
    """
    with_target = _with_target(contract)
    await _add_completed_cycles(session, contract, 2, prefix="young")
    health = await KpiEngine(session).health(with_target, spend_usd=Decimal("0"))

    assert health.band == "healthy"
    assert health.early_days is True
    assert health.summary == EARLY_DAYS_SUMMARY
    assert "Behind" not in health.summary


async def test_the_stall_wording_is_unchanged_past_the_threshold(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The other direction of the same threshold (D-020 amendment, D-027.4).

    A company past the grace period has stopped being new, and its summary must
    stop saying so. Without this the new sentence would be an excuse a stalled
    company could hide behind indefinitely.
    """
    with_target = _with_target(contract)
    await _add_completed_cycles(session, contract, 5, prefix="past")
    health = await KpiEngine(session).health(with_target, spend_usd=Decimal("0"))

    assert health.early_days is False
    assert health.zero_attainment_stall is True
    assert health.band == "watch"
    assert health.summary == "Set goals but hasn't hit any of them yet."


async def test_a_healthy_young_company_never_reads_as_behind(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Wording and band agree across the whole grace period, not at one point.

    Walked cycle by cycle up to the threshold, because the disagreement M7-F26
    found was at a specific age and a single-point test can pass on either side
    of it while the boundary is wrong.
    """
    with_target = _with_target(contract)
    engine = KpiEngine(session)
    for completed in range(STALLED_CYCLE_THRESHOLD):
        health = await engine.health(with_target, spend_usd=Decimal("0"))
        assert health.band == "healthy", f"after {completed} cycles"
        assert health.summary == EARLY_DAYS_SUMMARY, f"after {completed} cycles"
        await _add_completed_cycles(session, contract, 1, prefix=f"walk_{completed}")

    health = await engine.health(with_target, spend_usd=Decimal("0"))
    assert health.band == "watch", "the grace period has to end somewhere"
    assert health.summary != EARLY_DAYS_SUMMARY


async def test_the_new_company_wording_needs_targets_to_appear(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Negative control: a company with no targets is not "not hitting" them.

    It scores 100 on attainment by design — it cannot fail objectives nobody
    set — so the grace-period sentence must not reach it.
    """
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("0"))
    assert health.early_days is False
    assert health.summary == "Running normally."


async def test_health_exposes_its_components(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """§12.5: the operator must be able to ask why without a drill-down."""
    health = await KpiEngine(session).health(contract, spend_usd=Decimal("10"))
    assert 0 <= health.budget_headroom <= 100
    assert 0 <= health.reliability <= 100
    assert 0 <= health.kpi_attainment <= 100
    assert health.summary
