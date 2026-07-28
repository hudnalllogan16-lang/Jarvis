"""KPI engine and Health Score (spec §5, §3, §11).

Two gaps closed here.

§13 Step 1 lists a "KPI engine" that no normative section specifies. The minimum
satisfying §5's contract obligation and §11's dashboard requirement is an
append-only series per business per metric, plus attainment against the targets
the Executive Layer set (§3.1).

Health Score is a §5 contract field, while §3 assigns "health score aggregation"
to the COO as a *deterministic* function — leaving open whether the business or
the executive computes it. It is computed here, by the platform, from contract
primitives: it must be comparable across businesses to be aggregatable at all,
and a per-business implementation would make two companies' scores mean
different things.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.domain.contract import BusinessContract, KpiDirection
from jarvis.events.bus import Event, EventBus
from jarvis.events.types import KPI_THRESHOLD_BREACHED
from jarvis.kernel.ids import BusinessId, EventId, new_event_id
from jarvis.persistence.models import DeadLetterRow, DecisionLogRow, KpiValueRow

HEALTHY = 70
"""At or above: the company is fine. Below: something is worth a look."""

AT_RISK = 40
"""Below this, the operator should be told without being asked."""

STALLED_CYCLE_THRESHOLD = 5
"""Completed wake cycles since activation before zero attainment counts as
sustained rather than early-days (D-020 amendment)."""


@dataclass(frozen=True, slots=True)
class HealthScore:
    """A company's health, with the reasons behind it.

    The components are returned alongside the score because §12.5 requires the
    operator be able to ask why. A bare number would force a drill-down into the
    audit log, which §11.5 says must never be the first answer to "why".
    """

    score: int
    budget_headroom: int
    reliability: int
    kpi_attainment: int
    summary: str
    stuck_count: int = 0
    """Unresolved dead-lettered jobs. Non-zero caps :attr:`band` at ``watch``
    regardless of ``score`` (D-020): a company that cannot finish its work is
    broken in a way the weighted score alone does not surface."""

    zero_attainment_stall: bool = False
    """True when the business has configured KPI targets, zero attainment, and
    at least :data:`STALLED_CYCLE_THRESHOLD` completed cycles since activation
    (D-020 amendment). Caps :attr:`band` at ``watch`` for the same reason
    ``stuck_count`` does: a company that ships nothing is not healthy no
    matter how untouched its budget is."""

    early_days: bool = False
    """True when the business has targets and zero attainment but has not yet
    completed :data:`STALLED_CYCLE_THRESHOLD` cycles (D-027.4).

    The other side of the same threshold, and deliberately *not* a band
    override: a young company is genuinely healthy, which is why the grace
    period exists. It changes only what :attr:`summary` says, so the sentence
    an owner reads agrees with the badge beside it (M7-F26)."""

    @property
    def band(self) -> str:
        """Return ``healthy``, ``watch``, or ``at_risk``.

        D-020: unresolved stuck work caps the band at ``watch`` even when the
        weighted score would otherwise read ``healthy``. The D-020 amendment
        adds a second, independent cap for sustained zero goal-attainment.
        The score itself is never altered by either — only the band derived
        from it.
        """
        if self.score >= HEALTHY:
            if self.stuck_count > 0 or self.zero_attainment_stall:
                return "watch"
            return "healthy"
        return "watch" if self.score >= AT_RISK else "at_risk"


class KpiEngine:
    """Records KPI observations and computes health (spec §5)."""

    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        """Args:
        session: Active session.
        bus: Event bus. Without it a threshold breach is recorded but no
            Manager is woken, so "KPI threshold breached" would be a wake
            condition §2.1 permits and nothing ever triggers.
        """
        self._session = session
        self._bus = bus

    async def record(
        self,
        *,
        business_id: BusinessId,
        key: str,
        value: Decimal,
        target: Decimal | None = None,
    ) -> None:
        """Append one KPI observation, announcing a breach if one occurred.

        Append-only: a KPI series is evidence, and overwriting yesterday's value
        would make a trend report unreproducible (spec §3, Strategy row).

        Args:
            business_id: Owning business.
            key: Metric key.
            value: Observed value.
            target: Threshold to compare against. Passed in rather than looked
                up so the caller decides what "breach" means for this metric —
                revenue below target and error rate above target are both
                breaches, and the engine should not guess the direction.
        """
        self._session.add(KpiValueRow(business_id=business_id, key=key, value=value))
        await self._session.flush()

        if target is not None and value < target and self._bus is not None:
            await self._bus.publish(
                Event(
                    event_id=EventId(new_event_id()),
                    event_type=KPI_THRESHOLD_BREACHED,
                    business_id=business_id,
                    payload={"key": key, "value": str(value), "target": str(target)},
                )
            )

    async def latest(self, business_id: BusinessId, key: str) -> Decimal | None:
        """Return the most recent value for one metric, or None."""
        stmt = (
            select(KpiValueRow.value)
            .where(KpiValueRow.business_id == business_id)
            .where(KpiValueRow.key == key)
            .order_by(KpiValueRow.recorded_at.desc())
            .limit(1)
        )
        result = await self._session.scalar(stmt)
        return Decimal(str(result)) if result is not None else None

    async def series(
        self, business_id: BusinessId, key: str, *, limit: int = 30
    ) -> Sequence[KpiValueRow]:
        """Return recent observations for one metric, oldest first."""
        stmt = (
            select(KpiValueRow)
            .where(KpiValueRow.business_id == business_id)
            .where(KpiValueRow.key == key)
            .order_by(KpiValueRow.recorded_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.scalars(stmt)).all())
        return list(reversed(rows))

    async def attainment(self, contract: BusinessContract) -> int:
        """Return percentage attainment against the Executive Layer's targets.

        Args:
            contract: The business's contract, carrying its KPI targets (§3.1).

        Returns:
            0-100. A business with no targets scores 100: it cannot be failing
            objectives nobody set, and scoring it zero would make every new
            company look broken on its first day.
        """
        if not contract.kpi_targets:
            return 100

        ratios: list[Decimal] = []
        for target in contract.kpi_targets:
            actual = await self.latest(contract.business_id, target.key)
            if actual is None or target.target_value == 0:
                continue
            if target.direction is KpiDirection.BELOW:
                # Lower is better (M7-F30): a freshness reading of 1 hour
                # against a 24-hour target is excellent, not a 4% miss. Zero
                # is the best possible actual for this direction and would
                # divide by zero, so it is scored as full attainment rather
                # than guessed at.
                ratios.append(
                    Decimal(1) if actual == 0 else min(target.target_value / actual, Decimal(1))
                )
            else:
                ratios.append(min(actual / target.target_value, Decimal(1)))
        if not ratios:
            return 0
        return int(sum(ratios) / len(ratios) * 100)

    async def health(self, contract: BusinessContract, *, spend_usd: Decimal) -> HealthScore:
        """Compute a company's Health Score (spec §5).

        Args:
            contract: The business's contract.
            spend_usd: Spend to date, from the budget ledger (D-003).

        Returns:
            The score with its components and a plain-language summary.
        """
        cap = contract.budget.business_cap_usd
        headroom = int(max(Decimal(0), (cap - spend_usd) / cap) * 100) if cap else 0

        stuck = await self._session.scalar(
            select(func.count())
            .select_from(DeadLetterRow)
            .where(DeadLetterRow.business_id == contract.business_id)
            .where(DeadLetterRow.resolved.is_(False))
        )
        stuck_count = int(stuck or 0)
        # **This number is blind to a failed round, and knowingly so (M9-F118).**
        # It counts unresolved dead letters, which are what a *dispatched* piece
        # of work leaves behind when it gives up. A round that fails before
        # dispatch — planning refused, the provider unreachable, a ceiling
        # reached — dispatches nothing, so it leaves nothing here: on the
        # morning all three companies failed their rounds within seven seconds
        # of each other, every one of them read 100.
        #
        # Deliberately not fixed here. Widening the input changes what the
        # published series *means* for every company that already has one, and
        # a health band that moves without its definition moving is the M8-F90
        # problem at platform scale. M9-7 makes the failure loud where an
        # operator actually reads it (the notice in
        # `jarvis.manager.activities.record_cycle_decision`); the metric's
        # semantics join the M10 pass with M7-F60, which is already the packet
        # for "what does a result being *useful* mean". Until then the honest
        # reading of this figure is "nothing it started was abandoned", not
        # "this company is working".
        reliability = max(0, 100 - stuck_count * 20)

        attainment = await self.attainment(contract)

        zero_attainment_stall = False
        early_days = False
        if contract.kpi_targets and attainment == 0:
            # One read, two answers: past the threshold this is a stall (D-020
            # amendment), below it the company is simply new (D-027.4). Before
            # D-027 the second case had no name and fell through to "Behind on
            # its goals." beside a healthy badge — M7-F26, and the recurrence
            # of M6-5's finding 5.
            completed_cycles = await self._completed_cycle_count(contract.business_id)
            zero_attainment_stall = completed_cycles >= STALLED_CYCLE_THRESHOLD
            early_days = not zero_attainment_stall

        # Reliability is weighted heaviest because a company that cannot finish
        # its work is broken in a way that budget headroom cannot compensate for.
        score = int(headroom * 0.3 + reliability * 0.45 + attainment * 0.25)

        return HealthScore(
            score=score,
            budget_headroom=headroom,
            reliability=reliability,
            kpi_attainment=attainment,
            summary=_summarise(
                headroom,
                stuck_count,
                attainment,
                zero_attainment_stall,
                early_days,
                score=score,
            ),
            stuck_count=stuck_count,
            zero_attainment_stall=zero_attainment_stall,
            early_days=early_days,
        )

    async def completed_cycle_count(self, business_id: BusinessId) -> int:
        """Return how many of this company's wake cycles have completed.

        Public accessor over :meth:`_completed_cycle_count`, added for the
        Executive Layer's portfolio rollup (design EXECUTIVE-LAYER.md 2.2,
        D-038, D-040): `runway_cycles` divides a company's own recorded
        headroom by its own recorded cycle count, which design Part 4 draws
        as the line between a permitted read (a company's own aggregate) and
        a forbidden one (cycle-level detail — the Manager's internal unit,
        spec §2.1, D-021). `health()` keeps using the private name for its
        own call; this wrapper exists so a caller outside `kpi/` never reaches
        for the underscored method.
        """
        return await self._completed_cycle_count(business_id)

    async def _completed_cycle_count(self, business_id: BusinessId) -> int:
        """Return how many distinct wake cycles have reached a terminal state.

        Every cycle — whatever it outcome — writes exactly one Decision Log
        entry carrying its `cycle_id` (`record_cycle_decision`, D-021). Counting
        distinct cycle ids is therefore a durable count of *completed* cycles
        without a schema change: there is no dedicated counter, and the
        Decision Log is the only place a cycle's terminal state is recorded
        for a business to read back (D-005).
        """
        count = await self._session.scalar(
            select(func.count(func.distinct(DecisionLogRow.cycle_id)))
            .where(DecisionLogRow.business_id == business_id)
            .where(DecisionLogRow.cycle_id.isnot(None))
        )
        return int(count or 0)


EARLY_DAYS_SUMMARY = "Just getting started — no goals hit yet."
"""D-027.4's sentence for a company inside its grace period.

Same fact as "Behind on its goals.", read the way it should be read on day one.
The badge says healthy — correctly, because :data:`STALLED_CYCLE_THRESHOLD`
cycles have not passed — and a summary calling that company behind contradicts
the badge next to it, which is how an owner learns not to trust either
(M7-F26). It only became visible with measurement real: before D-027 nothing
ever wrote a KPI value, so *every* company sat at zero attainment forever and
this sentence would have been wrong for all of them (M7-F21)."""


def _summarise(
    headroom: int,
    stuck_count: int,
    attainment: int,
    zero_attainment_stall: bool,
    early_days: bool = False,
    *,
    score: int = 0,
) -> str:
    """Return the one-line reason behind a health score, in operator language.

    Args:
        score: The company's overall Health Score, already weighted from the
            same `headroom`/`reliability`/`attainment` this function reasons
            about (`health()`'s only caller). Needed for exactly one branch:
            whether a partially-attained company still reads as ``healthy``
            (M7-F53, the live recurrence of M7-F31/M7-F26's class). Every
            branch above the attainment check returns before this matters —
            stuck work and thin headroom explain a low score on their own, and
            sustained/early zero attainment already have their own wording —
            so `score` only decides the wording when attainment alone is what
            is holding a mature company back.
    """
    if stuck_count:
        noun = "task" if stuck_count == 1 else "tasks"
        return f"{stuck_count} {noun} got stuck and need a look."
    if headroom < 20:
        return "Close to its spending limit."
    if zero_attainment_stall:
        return "Set goals but hasn't hit any of them yet."
    if early_days:
        return EARLY_DAYS_SUMMARY
    if attainment < 50:
        if score >= HEALTHY:
            # M7-F53: the live M7 run showed a healthy band beside "Behind on
            # its goals." on a mature company with partial attainment — the
            # badge and the sentence disagreed, which is how an owner learns
            # to trust neither (M7-F26's class, one band up). The badge is
            # right (nothing else about the company is a problem); the old
            # sentence read as though it wasn't, so the sentence changes.
            return "Healthy overall — goals need attention."
        return "Behind on its goals."
    return "Running normally."
