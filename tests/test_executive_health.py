"""Portfolio health census tests (design EXECUTIVE-LAYER.md Part 3, D-039)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract, KpiTarget
from jarvis.domain.lifecycle import LifecycleState
from jarvis.executive.health import compute_portfolio_health
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId
from jarvis.kpi.engine import KpiEngine
from jarvis.persistence.models import DeadLetterRow, DecisionLogRow
from jarvis.registry.registry import BusinessRegistry


async def _install(registry: BusinessRegistry) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )


def _renamed(
    contract: BusinessContract, *, business_id: str, display_name: str
) -> BusinessContract:
    payload = contract.model_dump()
    payload["business_id"] = business_id
    payload["display_name"] = display_name
    return BusinessContract.model_validate(payload)


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


def _ledger(session: AsyncSession) -> BudgetLedger:
    return BudgetLedger(session, platform_ceiling_usd=Decimal("500.00"))


async def _add_completed_cycles(
    session: AsyncSession, business_id: BusinessId, count: int, *, prefix: str
) -> None:
    for n in range(count):
        session.add(
            DecisionLogRow(
                decision_id=f"dec_{prefix}_{n}",
                business_id=business_id,
                cycle_id=f"cyc_{prefix}_{n}",
                summary="A wake cycle finished.",
                rationale="Nothing more to do this round.",
            )
        )
    await session.flush()


async def _record_zero_reading(session: AsyncSession, business_id: BusinessId) -> None:
    """Record an actual (zero) observation against `_with_target`'s one KPI
    target — a genuine measurement, as opposed to a company that merely ran
    cycles. Value zero keeps attainment at zero (a real miss), the same
    reading `_add_completed_cycles` alone was standing in for before M9-9
    item 2 — see `test_a_stalled_company_is_named_worst`."""
    await KpiEngine(session).record(business_id=business_id, key="revenue_mtd", value=Decimal("0"))


async def test_all_healthy_and_measured_names_nobody(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 3's falsifiability requirement: a portfolio with nothing
    wrong produces a zero watch/at_risk count and names no one."""
    await _install(registry)
    biz = await registry.register_instance(contract)
    await _add_completed_cycles(session, biz, 2, prefix="m")

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.healthy_count == 1
    assert census.watch_count == 0
    assert census.at_risk_count == 0
    assert census.never_measured_count == 0
    assert census.worst_company is None
    assert census.reasons == ()


async def test_a_stalled_company_is_named_worst(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-020 amendment: sustained zero attainment reads as watch, and its
    summary becomes the census's one reason — for a company that was actually
    measured (M9-9 item 2: cycles alone are not evidence of a measurement)."""
    await _install(registry)
    with_target = _with_target(contract)
    biz = await registry.register_instance(with_target)
    await _add_completed_cycles(session, biz, 5, prefix="stalled")
    await _record_zero_reading(session, biz)

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.watch_count == 1
    assert census.never_measured_count == 0
    assert census.worst_company == with_target.display_name
    assert census.reasons == ("Set goals but hasn't hit any of them yet.",)


async def test_cycles_with_no_recorded_reading_is_never_measured_not_watch(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """M9-9 product REVISE item 2, the defect itself: `never_measured_count`
    used to gate on completed *cycles*, and a Decision Log entry records only
    that a round ran, whatever its outcome — a company can fail five rounds
    before ever dispatching a measurement. That company was being counted as
    `watch` with "Set goals but hasn't hit any of them yet." (a tried-and-
    missed reading, and a candidate for `worst_company`) for a goal it never
    actually got to try. Recounting on recorded readings catches it: the same
    five cycles as the sibling test above, with no reading ever recorded,
    now lands in `never_measured_count`, not `watch_count`."""
    await _install(registry)
    with_target = _with_target(contract)
    biz = await registry.register_instance(with_target)
    await _add_completed_cycles(session, biz, 5, prefix="stalled")

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.never_measured_count == 1
    assert census.watch_count == 0
    assert census.worst_company is None
    assert census.reasons == ()


async def test_a_never_measured_company_is_counted_separately_from_healthy(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 3's "one honest limitation": a company with targets and
    zero recorded cycles is inside D-027.4's grace period and bands
    `healthy` — correctly, for that company. Counting it as portfolio
    evidence of health would count an absence as a reading (M7-F21's class),
    so it must land in its own bucket, not `healthy_count`."""
    await _install(registry)
    with_target = _with_target(contract)  # targets set, zero cycles recorded
    await registry.register_instance(with_target)

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.healthy_count == 0
    assert census.never_measured_count == 1
    assert census.worst_company is None
    assert census.reasons == ()


async def test_a_company_with_no_targets_and_no_cycles_is_also_never_measured(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The blank-slate case: no goals configured yet and no cycles run.
    Nothing about this company is evidence of anything, so it belongs beside
    Trailhead's live case, not folded into `healthy_count`."""
    await _install(registry)
    await registry.register_instance(contract)

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.never_measured_count == 1
    assert census.healthy_count == 0


async def test_stuck_work_with_zero_recorded_cycles_still_counts_as_watch(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The carve-out inside the carve-out: zero recorded cycles is only
    "never measured" when there is also nothing else going on. Stuck work is
    real evidence of a problem even before a cycle has completed, so it must
    not be swallowed by the never-measured bucket."""
    await _install(registry)
    biz = await registry.register_instance(contract)
    session.add(
        DeadLetterRow(
            invocation_id="inv_0",
            business_id=biz,
            capability="research",
            attempts=3,
            operator_summary="Couldn't finish a task.",
            technical_detail="stub",
        )
    )
    await session.flush()

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.never_measured_count == 0
    assert census.watch_count == 1
    assert census.worst_company == contract.display_name


async def test_retired_companies_are_excluded(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _install(registry)
    biz = await registry.register_instance(contract)
    await registry.transition(
        biz, LifecycleState.RETIRING, decision_id=DecisionId("d1"), reason="closing"
    )
    await registry.transition(
        biz, LifecycleState.RETIRED, decision_id=DecisionId("d2"), reason="closed"
    )

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.healthy_count == 0
    assert census.never_measured_count == 0
    assert census.watch_count == 0


async def test_worst_company_tiebreak_is_deterministic_not_read_order(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 1: a deterministic function has "no dependence on the
    order it happened to read things in". Two companies tied on score must
    resolve to the same worst company every time, broken by name."""
    await _install(registry)
    with_target = _with_target(contract)
    zeta = _renamed(
        with_target, business_id="biz_00000000000000000000000000000001", display_name="Zeta Co"
    )
    alpha = _renamed(
        with_target, business_id="biz_00000000000000000000000000000002", display_name="Alpha Co"
    )
    biz_zeta = await registry.register_instance(zeta)
    biz_alpha = await registry.register_instance(alpha)
    await _add_completed_cycles(session, biz_zeta, 5, prefix="z")
    await _add_completed_cycles(session, biz_alpha, 5, prefix="a")
    await _record_zero_reading(session, biz_zeta)
    await _record_zero_reading(session, biz_alpha)

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.watch_count == 2
    assert census.worst_company == "Alpha Co"
    assert census.reasons == ("Set goals but hasn't hit any of them yet.",)


async def test_distinct_reasons_are_deduplicated_and_sorted(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Two companies with two different problems contribute two distinct,
    stably-ordered reasons — not the read order `list_instances` returned."""
    await _install(registry)
    stalled = _renamed(
        _with_target(contract),
        business_id="biz_00000000000000000000000000000003",
        display_name="Stalled Co",
    )
    stuck = _renamed(
        contract, business_id="biz_00000000000000000000000000000004", display_name="Stuck Co"
    )
    biz_stalled = await registry.register_instance(stalled)
    biz_stuck = await registry.register_instance(stuck)
    await _add_completed_cycles(session, biz_stalled, 5, prefix="stalled")
    await _record_zero_reading(session, biz_stalled)
    for n in range(3):
        session.add(
            DeadLetterRow(
                invocation_id=f"inv_{n}",
                business_id=biz_stuck,
                capability="research",
                attempts=3,
                operator_summary="Couldn't finish a task.",
                technical_detail="stub",
            )
        )
    await session.flush()

    census = await compute_portfolio_health(registry, _ledger(session), KpiEngine(session))

    assert census.watch_count == 2
    # "3 tasks got stuck..." sorts before "Set goals..." (digit < letter).
    assert census.reasons == (
        "3 tasks got stuck and need a look.",
        "Set goals but hasn't hit any of them yet.",
    )
    # Stalled Co: 100*0.3 + 100*0.45 + 0*0.25 = 75 (zero_attainment_stall caps
    # the band, not the score). Stuck Co: 100*0.3 + 40*0.45 + 100*0.25 = 73
    # (reliability 100 - 3*20). The lower score is named worst.
    assert census.worst_company == "Stuck Co"
