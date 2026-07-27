"""Which platform fact a business type's KPI is measured from (D-027.2).

§5 makes KPIs a contract field and names no writer, so until D-027 the
`kpi_values` table had never held a row: targets were set at creation and never
measured, which made attainment structurally zero for every company that ever
ran (M7-F21). D-027 gives measurement to the wake cycle, and this module is the
vocabulary the two sides share — a business type declares, as data, which
recorded fact each of its metrics *is*, and the Manager activity that records
observations reads that declaration.

It lives in `domain` because it belongs to neither side. `manager` (M4) cannot
import `businesses` (M5) — the layering invariant — so a vocabulary defined
next to the type definitions would be unreadable at the one place obliged to
honour it, and the alternative is two copies of the same strings drifting apart.

**A source is an enumeration, not an expression.** A type says which fact a
metric is; the platform decides how that fact is read. Letting a type describe
an arbitrary computation would move the arithmetic behind a KPI outside the
platform, and a number whose derivation is authored elsewhere is exactly what
D-027.2 refuses when it refuses model-authored values — the provenance problem
is the same whichever file the prose lives in.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from jarvis.domain.contract import CapabilityType, KpiTarget


class KpiObservationScope(StrEnum):
    """Whether a source needs *this* cycle's own results, or stands on its
    own (M7-F32, the D-027 amendment pass).

    `record_cycle_kpis` reads this to decide what a cycle that dispatched
    nothing may still measure. Platform-owned rather than declared per
    mapping: whether a fact needs this cycle's own results is a property of
    the fact itself, true for every type that ever maps to it, not a choice a
    type author makes — the same reasoning `KpiSource` already applies to
    what a member measures, extended to when it may be read.
    """

    CYCLE_RESULT = "cycle_result"
    """Meaningful only for a cycle that actually dispatched something. A
    cycle with no results has nothing for this to count — recording it
    anyway would not be a measurement of zero, it would be no measurement,
    taken and written down regardless (D-027.3's silence, applied to a
    cycle instead of a company)."""

    OBSERVATION = "observation"
    """True independent of this cycle's own results (D-027.2): the fact it
    reads — an audit row already written, the contract's own target count —
    exists whether or not this wake dispatched anything, so it is recorded
    on any completed cycle, NOTHING_TO_DO included (M7-F32)."""


class KpiSource(StrEnum):
    """A platform fact an observation may be derived from (D-027.2).

    Every member names something the platform already records: a cycle's own
    results, or a row it wrote. Nothing here reads model output, and there is
    deliberately no member that could — a metric the platform cannot measure
    from its own records stays unmapped and is reported as such, rather than
    being filled in by the only other thing in the cycle that can produce a
    number.
    """

    SUCCEEDED_RESULTS_IN_CYCLE = "succeeded_results_in_cycle"
    """How many of this cycle's invocations returned a usable result.

    Counted from the terminal results the cycle already holds (D-001), filtered
    to the business the activity's runtime identity derives (D-002), and to a
    mapping's own `capability` when it declares one (M7-F33)."""

    HOURS_SINCE_NEWEST_SUCCEEDED_RESULT = "hours_since_newest_succeeded_result"
    """Hours between now and the newest `capability.succeeded` audit entry.

    The audit log is where a result's completion is *recorded* (§11), so this
    keeps rising across cycles that fail — which is the whole point of a
    freshness metric and would be lost if it were read from the current cycle
    alone, where it would be near zero by construction."""

    CONFIGURED_KPI_TARGET_COUNT = "configured_kpi_target_count"
    """How many KPI targets the contract carries.

    A configuration fact rather than an outcome, and the one metric that is
    already true before a company does anything."""

    @property
    def scope(self) -> KpiObservationScope:
        """Whether `record_cycle_kpis` may read this on a cycle with no
        results (M7-F32).

        Only `SUCCEEDED_RESULTS_IN_CYCLE` counts *this* cycle's own
        invocations; the other two members read a row already on disk (the
        audit log, the contract), so they are observation-scoped by
        construction rather than by an exhaustive per-member table that would
        need updating every time a member is added.
        """
        if self is KpiSource.SUCCEEDED_RESULTS_IN_CYCLE:
            return KpiObservationScope.CYCLE_RESULT
        return KpiObservationScope.OBSERVATION


class KpiMapping(BaseModel):
    """One metric a business type declares the platform can measure (D-027.2).

    Pure data, so a type declaring these stays data (D-014). A type that
    declares none records nothing at all (D-027.3) — silence, not zeros: a
    company measured as zero on a metric nobody defined would read as failing
    rather than as unmeasured.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The metric key. Matches a `KpiTarget.key` for attainment to compare it
    against a target; an unmatched key still records a series, which is a
    trend with no goal rather than an error."""

    source: KpiSource

    capability: CapabilityType | None = None
    """Narrow `SUCCEEDED_RESULTS_IN_CYCLE` to one capability's own results
    (M7-F33). Still pure data (D-014): a type names which capability its
    metric is about, never how the count is computed.

    `None` (the default) counts every capability's successes, as before this
    field existed. A type running two capabilities in one cycle — Finance's
    research-then-analyse shape — would otherwise score two reports for one
    delivered report, because both a research success and a finance success
    are "a succeeded result in the cycle." Setting this to the capability
    that actually produces the reportable thing fixes the double count.

    Meaningful only to `SUCCEEDED_RESULTS_IN_CYCLE`, the one source that
    iterates this cycle's own results one at a time; the other two members
    read a single already-written row and have nothing to filter (demonstrated
    need only, §14 — nothing today asks them to be capability-scoped)."""


def provisioned_kpi_targets(
    default_kpi_targets: tuple[KpiTarget, ...], kpi_mappings: tuple[KpiMapping, ...]
) -> tuple[KpiTarget, ...]:
    """Bake `CONFIGURED_KPI_TARGET_COUNT`'s target to the type's real count
    (M7-F49, the D-027 amendment pass).

    `CONFIGURED_KPI_TARGET_COUNT` observes "how many targets this contract
    carries" — a fact already true before a company does anything. Shipped
    with a hand-picked target (Finance's was 5 against 3 declared targets),
    the metric was structurally capped below 100%: no company could ever
    carry more targets than its own type declares, so the goal was
    unreachable by construction rather than by anything the company did.

    The fix is not a live formula (`KpiEngine.attainment` stays untouched) —
    it derives the number **once, here**, from the same tuple the mapping
    counts, and the caller stores the result on the contract at company
    creation. A type author can no longer let the two drift apart, because
    there is no longer a second number for them to write by hand.

    A type that maps no key to `CONFIGURED_KPI_TARGET_COUNT` is returned
    unchanged — this invents no target for a type that never asked to have
    this measured (D-027.3's silence, applied to targets rather than
    observations). No per-instance target-edit path exists yet (M7-F24), so
    there is nothing today for this derivation to override; when one ships,
    it must win over this function's answer, not the reverse — an operator's
    explicit choice outranks a platform default.
    """
    derived_keys = {
        mapping.key
        for mapping in kpi_mappings
        if mapping.source is KpiSource.CONFIGURED_KPI_TARGET_COUNT
    }
    if not derived_keys:
        return default_kpi_targets
    count = Decimal(len(default_kpi_targets))
    return tuple(
        target.model_copy(update={"target_value": count}) if target.key in derived_keys else target
        for target in default_kpi_targets
    )
