"""The COO's portfolio census (spec §3, design EXECUTIVE-LAYER.md Part 3, D-039).

D-009 put the Health Score in the platform so it would be comparable across
companies. Aggregating it with a mean throws that away: on the three live
companies every mean (unweighted 77.67, capital-weighted 75.31) reads
"healthy" while a third of the portfolio sits on `watch` with zero goal
attainment after seven cycles — a mean of comparable scores is comparable to
nothing (design Part 3, argument 1). So a portfolio has a census, never a
single number: counts per band, the worst company named, and the distinct
reasons behind a non-empty `watch`/`at_risk` count.

This module recomputes nothing D-009 already computes — every input is a
read through `KpiEngine.health`, the same frozen call the per-company badge
uses (design Part 1). It never invents a portfolio-level formula.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.ids import BusinessId
from jarvis.kpi.engine import KpiEngine
from jarvis.registry.registry import BusinessRegistry


@dataclass(frozen=True, slots=True)
class PortfolioHealth:
    """The COO's deterministic portfolio census. No single portfolio score.

    Produced by :func:`compute_portfolio_health`, a pure function over the
    same per-company `HealthScore`s D-009 already computes (D-038): no new
    arithmetic, no new persistence, no model call.
    """

    healthy_count: int
    watch_count: int
    at_risk_count: int

    never_measured_count: int
    """Companies with zero recorded wake cycles **and** zero stuck work —
    genuinely never measured, as opposed to measured and found wanting.
    D-027.4's grace period reads such a company's band as `healthy`, which is
    correct for that company (a young company is not unhealthy), but folding
    it into `healthy_count` here would count an absence of goal-attainment
    evidence as a reading about the *portfolio* — M7-F21's failure one layer
    up (design Part 3, "one honest limitation"). Reported on its own,
    subtracted from none of the three bands above.

    A company with stuck work but zero recorded cycles (dead-lettered before
    its first cycle completed) is *not* swept in here: stuck work is real
    evidence, so it counts under `watch_count`/`at_risk_count` as D-020
    already caps its band."""

    worst_company: str | None
    """Display name of the lowest-scoring company in `watch` or `at_risk`,
    ties broken by name for a result that does not depend on read order
    (D-038's determinism). `None` when nothing is below `healthy` — including
    when every company is `never_measured`, since absence of evidence never
    names a "worst" company."""

    reasons: tuple[str, ...]
    """Distinct `HealthScore.summary` sentences among the companies behind
    `watch_count`/`at_risk_count`, sorted for a stable result. The "why"
    behind a non-empty count, without an operator having to drill down
    (design Part 3); `never_measured` companies never contribute a reason,
    for the same cause as above."""


async def _has_been_measured(
    kpi: KpiEngine, contract: BusinessContract, business_id: BusinessId
) -> bool:
    """Whether this company has evidence of an actual measurement, for
    `never_measured_count` (M9-9 product REVISE item 2).

    A wake cycle's Decision Log entry — what `KpiEngine.completed_cycle_count`
    counts — records only that a *round ran*, whatever its outcome
    (`_completed_cycle_count`'s own docstring: "whatever its outcome"). A
    company can run several rounds that each fail before dispatch and never
    write a single `KpiValueRow`; gating `never_measured` on that count (the
    original shape here) let such a company fall through to `watch`/`at_risk`
    with a `zero_attainment_stall` reading — "Set goals but hasn't hit any of
    them yet.", which reads as a tried-and-missed goal — and even be named the
    census's `worst_company`, for a reason that never actually happened: it
    was never measured, not measured and found wanting. Recounting on
    recorded readings instead catches exactly that company, in both
    directions: cycles with no reading still read `never_measured`, and a
    company that has a genuine recorded observation is never swept in here
    just because its work has since had a rough patch.

    Mirrors `jarvis.api.app._ever_measured`'s per-target read (latest value
    per key this company's own contract currently targets) rather than a bare
    existence check across every key ever recorded for it — a target the
    company no longer carries is not evidence about it today.

    A company with no `kpi_targets` at all has no per-metric observation this
    check could ever find — there is nothing to be missing — so it falls back
    to the original cycle-count read for that one case: D-027.4's grace
    period already treats a young, target-less company as fine until its
    cycles say otherwise, and that reasoning does not change here.
    """
    if not contract.kpi_targets:
        return await kpi.completed_cycle_count(business_id) > 0
    for target in contract.kpi_targets:
        if await kpi.latest(contract.business_id, target.key) is not None:
            return True
    return False


async def compute_portfolio_health(
    registry: BusinessRegistry,
    ledger: BudgetLedger,
    kpi: KpiEngine,
) -> PortfolioHealth:
    """Read the COO's portfolio census from stored values (design Part 3).

    Falsifiable by construction: a portfolio where every company is healthy
    and measured produces `watch_count == at_risk_count == 0` and
    `worst_company is None`; today, on the live three companies, it must
    name Summit Trail Gear.

    RETIRED companies are excluded — the same reasoning as
    `jarvis.executive.rollup.compute_portfolio_rollup`: a closed company
    contributes nothing to a portfolio's current health.

    Args:
        registry: Read-only source of company existence and contracts.
        ledger: Read-only source of spend (`KpiEngine.health` needs it).
        kpi: Read-only source of health scores and recorded cycle counts.

    Returns:
        The census. Never a single score (D-039).
    """
    instances = await registry.list_instances()
    live = [
        instance
        for instance in instances
        if LifecycleState(instance.lifecycle_state) is not LifecycleState.RETIRED
    ]

    healthy = watch = at_risk = never_measured = 0
    candidates: list[tuple[int, str, str]] = []
    """(score, display_name, summary) for every company in watch or at_risk,
    sorted before naming a worst so the result does not depend on the order
    `list_instances` happened to return."""

    for instance in live:
        business_id = BusinessId(instance.business_id)
        contract = await registry.get_contract(business_id)
        spend = await ledger.business_spend(business_id)
        score = await kpi.health(contract, spend_usd=spend)

        if score.stuck_count == 0 and not await _has_been_measured(kpi, contract, business_id):
            never_measured += 1
            continue

        if score.band == "healthy":
            healthy += 1
        elif score.band == "watch":
            watch += 1
            candidates.append((score.score, contract.display_name, score.summary))
        else:
            at_risk += 1
            candidates.append((score.score, contract.display_name, score.summary))

    worst_company: str | None = None
    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]))
        worst_company = candidates[0][1]

    reasons = tuple(sorted({summary for _, _, summary in candidates}))

    return PortfolioHealth(
        healthy_count=healthy,
        watch_count=watch,
        at_risk_count=at_risk,
        never_measured_count=never_measured,
        worst_company=worst_company,
        reasons=reasons,
    )
