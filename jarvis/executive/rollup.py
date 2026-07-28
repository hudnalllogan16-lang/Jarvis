"""The CFO's portfolio rollup (spec §3, design EXECUTIVE-LAYER.md Part 2.2).

Builds `PortfolioRollup` only. Cap-tracking bands and `SPENDING` alerts
(design 2.3) and the circuit-breaker halt narrative (design 2.4) are packet C
— not built here. This module never writes anything: it computes and reports
over stored values (D-038).

D-040 is the rule that shapes every field name here. `BudgetLedger.business_spend`
sums a business's ledger with no time bound — **a lifetime budget that only
depletes** — while `BudgetLedger.platform_spend_24h` bounds its aggregate to a
rolling 24 hours — **a daily flow that refills**. The two are not
commensurable: a rollup that added them would compare a stock to a flow
(design 2.1). So every dollar and percentage figure below states its own
window in its name, and this module never sums a lifetime figure with a 24h
one.

**Whether `business_cap_usd` is meant as a lifetime budget or a windowed one
is an open owner escalation (design Part 10.1) and this module does not
resolve it.** `lifetime_cap_usd` reports the contract field AS RECORDED,
under the name design 2.1 gives it, which is the honest thing to do either
way the escalation is eventually ruled.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.ids import BusinessId
from jarvis.kpi.engine import KpiEngine
from jarvis.registry.registry import BusinessRegistry

_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class CompanyBudget:
    """One company's budget standing. Every field names its own window (D-040)."""

    business_id: BusinessId
    display_name: str

    lifetime_cap_usd: Decimal
    """`business_cap_usd` as recorded on the contract — reported, not
    interpreted (design Part 10.1's open escalation)."""

    lifetime_spend_usd: Decimal

    lifetime_headroom_usd: Decimal
    """`lifetime_cap_usd - lifetime_spend_usd`, floored at zero. Never
    negative: `BudgetLedger.reserve` refuses a debit that would push spend
    past the cap (D-003 rule 2), so the ledger cannot itself produce one."""

    lifetime_utilisation_pct: Decimal
    """`lifetime_spend_usd / lifetime_cap_usd * 100` — design Part 0's "Cap
    used" column."""

    runway_cycles: Decimal | None
    """Remaining lifetime headroom divided by this company's own mean cost
    per recorded cycle (`lifetime_spend_usd / KpiEngine.completed_cycle_count`).
    The one cycle-level read design Part 4 permits: dividing a company's own
    spend by its own recorded cycle *count* states something about the
    company's budget, not about how it spends any one cycle.

    `None`, never zero, when the company has no recorded cycles — Trailhead's
    live state. A default of zero would render as "no runway" for a company
    simply never measured; a default of infinity would render as "fine" for
    the same reason. Both would be M7-F21's failure with a different number
    (design 2.2)."""


@dataclass(frozen=True, slots=True)
class PortfolioRollup:
    """The CFO's deterministic budget aggregation over every non-retired company.

    A frozen value produced by :func:`compute_portfolio_rollup`, a pure
    function of stored ledger rows and contracts (D-038): no model call, no
    uninjected clock, no contract write.
    """

    committed_capital_usd: Decimal
    """Lifetime. Sum of `lifetime_cap_usd` over every non-RETIRED company."""

    lifetime_spend_usd: Decimal
    """Lifetime. Sum of `lifetime_spend_usd` over every non-RETIRED company."""

    lifetime_headroom_usd: Decimal
    lifetime_headroom_pct: Decimal

    rolling_24h_spend_usd: Decimal
    """24h. `BudgetLedger.platform_spend_24h` — never added to a lifetime
    figure above; a stock and a flow are not commensurable (design 2.1)."""

    platform_ceiling_usd: Decimal
    """24h. The platform's rolling spend ceiling (spec §9)."""

    rolling_24h_utilisation_pct: Decimal

    per_company: tuple[CompanyBudget, ...]


async def compute_portfolio_rollup(
    registry: BusinessRegistry,
    ledger: BudgetLedger,
    kpi: KpiEngine,
    *,
    platform_ceiling_usd: Decimal,
) -> PortfolioRollup:
    """Read the CFO's portfolio rollup from stored values (design 2.2).

    Every read stays inside the frozen surface design Part 1 enumerates:
    `registry.list_instances`/`get_contract` for which companies exist and
    their budget policy, `ledger.business_spend`/`platform_spend_24h` for
    spend, and `kpi.completed_cycle_count` for a company's own recorded
    cycle count. No `cycle_spend` read, no Decision Log parse — design
    Part 4's line between a company's own aggregate and cycle-level detail.

    RETIRED companies are excluded: a closed company commits no capital and
    reports no runway (D-008's lifecycle machine already revokes its
    credentials and blocks its dispatch on entry to RETIRED).

    Args:
        registry: Read-only source of company existence and contracts.
        ledger: Read-only source of spend.
        kpi: Read-only source of a company's own recorded cycle count.
        platform_ceiling_usd: The platform's rolling 24h ceiling (spec §9).
            Passed in rather than read off `ledger`, which holds it only as a
            private constructor argument — the caller is expected to source
            it from the same place `PlatformKernel` does
            (`Settings.budget.platform_rolling_24h_usd`), so the enforced
            ceiling and the reported one are never two numbers computed
            twice in two places (design Part 12's sequencing note).

    Returns:
        The rollup, every field naming its window (D-040).
    """
    instances = await registry.list_instances()
    live = [
        instance
        for instance in instances
        if LifecycleState(instance.lifecycle_state) is not LifecycleState.RETIRED
    ]

    per_company: list[CompanyBudget] = []
    committed_capital = Decimal(0)
    lifetime_spend = Decimal(0)

    for instance in live:
        business_id = BusinessId(instance.business_id)
        contract = await registry.get_contract(business_id)
        spend = await ledger.business_spend(business_id)
        cap = contract.budget.business_cap_usd

        headroom = max(Decimal(0), cap - spend)
        utilisation_pct = (spend / cap) * _HUNDRED if cap else Decimal(0)

        cycles = await kpi.completed_cycle_count(business_id)
        runway_cycles: Decimal | None = None
        if cycles > 0:
            mean_cost_per_cycle = spend / cycles
            if mean_cost_per_cycle > 0:
                runway_cycles = headroom / mean_cost_per_cycle

        per_company.append(
            CompanyBudget(
                business_id=business_id,
                display_name=contract.display_name,
                lifetime_cap_usd=cap,
                lifetime_spend_usd=spend,
                lifetime_headroom_usd=headroom,
                lifetime_utilisation_pct=utilisation_pct,
                runway_cycles=runway_cycles,
            )
        )
        committed_capital += cap
        lifetime_spend += spend

    lifetime_headroom = max(Decimal(0), committed_capital - lifetime_spend)
    lifetime_headroom_pct = (
        (lifetime_headroom / committed_capital) * _HUNDRED if committed_capital else Decimal(0)
    )

    rolling_24h_spend = await ledger.platform_spend_24h()
    rolling_24h_utilisation_pct = (
        (rolling_24h_spend / platform_ceiling_usd) * _HUNDRED
        if platform_ceiling_usd
        else Decimal(0)
    )

    return PortfolioRollup(
        committed_capital_usd=committed_capital,
        lifetime_spend_usd=lifetime_spend,
        lifetime_headroom_usd=lifetime_headroom,
        lifetime_headroom_pct=lifetime_headroom_pct,
        rolling_24h_spend_usd=rolling_24h_spend,
        platform_ceiling_usd=platform_ceiling_usd,
        rolling_24h_utilisation_pct=rolling_24h_utilisation_pct,
        per_company=tuple(per_company),
    )
