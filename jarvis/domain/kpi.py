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

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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
    to the business the activity's runtime identity derives (D-002)."""

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
