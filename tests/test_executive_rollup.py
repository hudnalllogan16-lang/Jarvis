"""Portfolio rollup tests (design EXECUTIVE-LAYER.md 2.2, D-038, D-040)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.domain.lifecycle import LifecycleState
from jarvis.executive.rollup import compute_portfolio_rollup
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId
from jarvis.kpi.engine import KpiEngine
from jarvis.persistence.models import DecisionLogRow
from jarvis.registry.registry import BusinessRegistry


async def _install(registry: BusinessRegistry) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )


def _renamed(
    contract: BusinessContract, *, business_id: str, display_name: str, cap: str | None = None
) -> BusinessContract:
    payload = contract.model_dump()
    payload["business_id"] = business_id
    payload["display_name"] = display_name
    if cap is not None:
        payload["budget"]["business_cap_usd"] = Decimal(cap)
    return BusinessContract.model_validate(payload)


def _ledger(session: AsyncSession, ceiling: str = "500.00") -> BudgetLedger:
    return BudgetLedger(session, platform_ceiling_usd=Decimal(ceiling))


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


async def test_committed_capital_sums_caps_over_every_company(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.2: `committed_capital_usd` is the lifetime sum of every
    non-RETIRED company's cap. Cap fixture is $50.00; a second company adds
    $25.00 more."""
    await _install(registry)
    biz1 = await registry.register_instance(contract)
    second = _renamed(
        contract,
        business_id="biz_00000000000000000000000000000002",
        display_name="Second Co",
        cap="25.00",
    )
    biz2 = await registry.register_instance(second)

    rollup = await compute_portfolio_rollup(
        registry, _ledger(session), KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.committed_capital_usd == Decimal("75.00")
    assert {c.business_id for c in rollup.per_company} == {biz1, biz2}


async def test_retired_companies_are_excluded(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """A closed company commits no capital and reports no runway."""
    await _install(registry)
    biz = await registry.register_instance(contract)
    await registry.transition(
        biz, LifecycleState.RETIRING, decision_id=DecisionId("d1"), reason="closing"
    )
    await registry.transition(
        biz, LifecycleState.RETIRED, decision_id=DecisionId("d2"), reason="closed"
    )

    rollup = await compute_portfolio_rollup(
        registry, _ledger(session), KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.committed_capital_usd == Decimal("0")
    assert rollup.per_company == ()


async def test_a_paused_company_still_counts(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.2's "non-RETIRED", not "ACTIVE": a paused company's capital
    is still committed."""
    await _install(registry)
    biz = await registry.register_instance(contract)
    await registry.transition(
        biz, LifecycleState.ACTIVE, decision_id=DecisionId("d1"), reason="start"
    )
    await registry.transition(
        biz, LifecycleState.PAUSED, decision_id=DecisionId("d2"), reason="pause"
    )

    rollup = await compute_portfolio_rollup(
        registry, _ledger(session), KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.committed_capital_usd == Decimal("50.00")


async def test_every_field_names_its_own_window(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-040: a lifetime figure and a 24h figure are never the same number by
    coincidence of naming — both are read here from the same $10 of spend,
    and the rollup must still carry them as two separately-named fields."""
    await _install(registry)
    await registry.register_instance(contract)
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))

    rollup = await compute_portfolio_rollup(
        registry, ledger, KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.lifetime_spend_usd == Decimal("10.00")
    assert rollup.rolling_24h_spend_usd == Decimal("10.00")
    assert rollup.committed_capital_usd == Decimal("50.00")
    assert rollup.platform_ceiling_usd == Decimal("500.00")
    assert rollup.rolling_24h_utilisation_pct == Decimal("2")  # 10 / 500 * 100


async def test_runway_is_undefined_not_zero_with_no_recorded_cycles(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.2: a company with no recorded cycles gets `None`, never `0`
    — Trailhead's live state. Zero would render as "no runway" for a company
    simply never measured."""
    await _install(registry)
    await registry.register_instance(contract)
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("5.00"))

    rollup = await compute_portfolio_rollup(
        registry, ledger, KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.per_company[0].runway_cycles is None


async def test_runway_is_headroom_over_mean_cost_per_recorded_cycle(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.1's live-shaped arithmetic: headroom / (spend / cycles)."""
    await _install(registry)
    biz = await registry.register_instance(contract)  # cap $50.00
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))
    await _add_completed_cycles(session, biz, 5, prefix="c")

    rollup = await compute_portfolio_rollup(
        registry, ledger, KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    company = rollup.per_company[0]
    # headroom 40.00, mean cost 10.00 / 5 = 2.00/cycle -> 20 cycles.
    assert company.runway_cycles == Decimal("20")


async def test_lifetime_utilisation_pct_matches_cap_used(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 0's "Cap used" column: spend / cap * 100."""
    await _install(registry)
    await registry.register_instance(contract)  # cap $50.00
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("25.00"))

    rollup = await compute_portfolio_rollup(
        registry, ledger, KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.per_company[0].lifetime_utilisation_pct == Decimal("50")


async def test_an_empty_portfolio_reports_zero_rather_than_dividing_by_zero(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """No companies registered at all: every percentage must fall back to
    zero rather than raising `ZeroDivisionError`."""
    rollup = await compute_portfolio_rollup(
        registry, _ledger(session), KpiEngine(session), platform_ceiling_usd=Decimal("500.00")
    )

    assert rollup.committed_capital_usd == Decimal("0")
    assert rollup.lifetime_headroom_pct == Decimal("0")
    assert rollup.per_company == ()
