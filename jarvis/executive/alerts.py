"""The CFO's cap alerts and the halt narrative's missing caller.

Design `EXECUTIVE-LAYER.md` 2.3 and 2.4 — packet C. Two things the platform
has owned for milestones without ever using:

- **`NotificationKind.SPENDING`**, declared at M3 with zero writers and zero
  readers. :func:`raise_spend_alerts` is its first writer.
- **`CircuitBreaker.trip()`**, written at M2 with no caller anywhere in
  `jarvis/`, so §12.5's promised "Jarvis paused spending — here's why" has
  never been written and `decision_log` holds zero platform-scoped rows
  (M9-F2). :func:`record_platform_halt` is its caller.

**Extended in packet D (M9-1c) with the platform ceiling's own 50%/80%
warning bands** (M9-F83): the ceiling had a breach narrative and no advance
notice, unlike a company's own cap. :func:`raise_platform_ceiling_alerts`
reuses :func:`spend_band` and the `SPENDING` kind rather than inventing either
a second comparison or a second vocabulary — see the section below.

**Nothing here computes a figure.** Every number it announces is read off
`PortfolioRollup` — the rollup's fields, never a second aggregation of the
same rows. Design Part 12's sequencing note is the reason it is written this
way round: the bands are percentages *of the rollup's own* `lifetime_
utilisation_pct`, and computing them twice in two places is how two numbers
that must agree stop agreeing. The one thing this module asks anybody else is
whether the platform is *actually* halted, and it asks the breaker itself
(below), not a second comparison of spend to a ceiling.

**D-011 holds by construction.** Every sentence below renders from stored
values — a company's display name, its recorded spend, its recorded cap —
through a fixed template chosen by a band. No model authors any part of an
operator notice here, and there is no path by which one could: D-038's import
rule keeps `jarvis.llm` out of this package entirely.

**D-003 rule 4 holds by construction too.** This module writes a notification
and a Decision Log entry and does nothing else. It cancels no invocation,
touches no reservation, and revokes nothing. New dispatch was already refused
at the pool boundary by `CircuitBreaker.assert_closed`; the gap M9-F2 names is
that the refusal was never *explained*, and an explanation is all that is added
here.

**The open escalation is respected, not resolved.** Whether `business_cap_usd`
is meant as a lifetime budget or a windowed one is an owner decision (design
Part 10.1). These alerts fire on the figures as recorded — a running total
since a company started — and every sentence says so in the same breath as the
number (D-040). If the escalation later rules the cap is windowed, the copy
becomes wrong and must change; it will not be *silently* wrong, which is the
most this packet is allowed to guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from jarvis.budget.breaker import PLATFORM_HALT_ACTION_TYPE, CircuitBreaker
from jarvis.budget.ledger import PLATFORM_SPEND_WINDOW
from jarvis.executive.rollup import CompanyBudget, PortfolioRollup
from jarvis.kernel.errors import CircuitBreakerOpenError
from jarvis.kernel.ids import BusinessId, new_decision_id, new_notification_id
from jarvis.kernel.logging import get_logger
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.observability.decision_log import DecisionLog

logger = get_logger(__name__)

SPEND_BANDS: tuple[int, ...] = (100, 80, 50)
"""Percentages of a company's recorded cap that are worth announcing, highest
first (design 2.3).

Chosen against live data rather than by convention: the largest utilisation on
the platform is 23.63%, so 50% is a threshold nothing has yet crossed — the
right property for a first alert, which should arrive while there is still
something an operator can do. At the observed rate 50% leaves ~15 cycles and
80% leaves ~6, so the two lower bands are "there is time to decide" and
"decide now" rather than two arbitrary numbers. 100 is the breach.

Ordered high-to-low because :func:`spend_band` returns the *highest* band a
company has crossed and nothing below it: a company that goes from 0% to 90%
between two passes is told "close to the limit" once, not "half used" and then
"close" in the same breath.

Breach has its own reason for being here even though `BudgetExceededError`
already carries D-007's sentence at the point of refusal: that refusal only
happens if something tries to spend again. A company that reaches its cap and
is then never dispatched raises no error, ever, and this notice is the only
thing that tells its operator it has stopped."""


def _money(amount: Decimal) -> str:
    """Format a stored dollar figure for an operator (never regenerate it)."""
    return f"${amount:,.2f}"


@dataclass(frozen=True, slots=True)
class _BandCopy:
    """One band's operator sentences. `{name}` is the company's display name.

    Kept as data beside the band rather than built inline so
    `tests/test_operator_language.py`-shaped checks can walk every sentence
    this module can ever produce, including bands nothing has crossed yet —
    the discipline `DROPPED_WAKE_COPY` already established for D-035's notices.
    """

    title: str
    consequence: str


BAND_COPY: dict[int, _BandCopy] = {
    50: _BandCopy(
        title="{name} has used half its spending limit",
        consequence=(
            "Nothing has stopped. There is still time to raise the limit if you want this "
            "company to keep going past it."
        ),
    ),
    80: _BandCopy(
        title="{name} is close to its spending limit",
        consequence="When it reaches the limit this company stops, and only you can raise it.",
    ),
    100: _BandCopy(
        title="{name} hit its spending limit",
        consequence="It has stopped, and it will not start again until you raise the limit.",
    ),
}
"""D-007's own sentence for a reached cap — "[Company] hit its spending limit"
— plus the same thing said earlier, twice.

That is the whole operator-visible contribution of this packet, and it is why
cap alerting adds no operator-facing behaviour beyond D-007's table: it changes
*when* an existing sentence arrives, not what an operator is told exists
(design 2.3). "Company", never "business" — D-007's own term, and one of the
seventeen `tests/surface_sources.FORBIDDEN` words."""


@dataclass(frozen=True, slots=True)
class SpendAlert:
    """One announcement made, returned so a caller can log or assert on it."""

    business_id: BusinessId
    display_name: str
    band: int


def spend_band(utilisation_pct: Decimal, bands: tuple[int, ...] = SPEND_BANDS) -> int | None:
    """Return the highest of ``bands`` that ``utilisation_pct`` has crossed, or None.

    Pure, and the only arithmetic in this module: a comparison of a figure the
    rollup already computed against a constant. It recomputes no spend.

    Args:
        utilisation_pct: A cap-utilisation figure the rollup already computed
            — a company's lifetime one or the platform's rolling 24h one.
        bands: Which thresholds to check, highest first. Defaults to
            :data:`SPEND_BANDS`; :func:`raise_platform_ceiling_alerts` passes
            :data:`PLATFORM_BANDS` instead so the two schemes share one
            comparison rather than two copies of it (design Part 12's
            sequencing note, applied to this function rather than to a
            module).
    """
    for band in bands:
        if utilisation_pct >= band:
            return band
    return None


def spend_band_ref(band: int) -> str:
    """Return the internal ref recording *which* band a notice announced.

    Stored on the notification row's `link_ref` and compared there — the band
    is the state (design 2.3), so a notice saying "half used" must not suppress
    the later one saying "close to the limit". Read back from a column rather
    than from the sentence: parsing a number out of operator copy would build a
    second, unstated schema on top of prose written for a person, which is the
    thing design Part 4 refuses to do to the Decision Log and is no better done
    to a notification.

    Never rendered. `/api/notifications` returns title, body, kind and time.
    """
    return f"spend-band:{band}"


async def raise_spend_alerts(
    rollup: PortfolioRollup, notifications: NotificationService
) -> tuple[SpendAlert, ...]:
    """Announce every company that has crossed a spend band (design 2.3).

    Deduplicated with no new state: a band is announced unless this company
    already has an unread `SPENDING` notice for *that same band*. An operator
    who dismissed the notice has said they know, and a condition still true at
    the next pass is worth saying again — `NotificationService.has_unread`'s
    recorded posture, which is exactly right here.

    Args:
        rollup: The CFO's rollup. Read, never recomputed — `lifetime_
            utilisation_pct` and the two dollar figures beside it are this
            function's entire input.
        notifications: Writer for the operator's queue.

    Returns:
        One :class:`SpendAlert` per notice actually written. A suppressed
        band is absent rather than reported as sent.
    """
    announced: list[SpendAlert] = []
    for company in rollup.per_company:
        band = spend_band(company.lifetime_utilisation_pct)
        if band is None:
            continue
        ref = spend_band_ref(band)
        if await notifications.has_unread(
            company.business_id, kind=NotificationKind.SPENDING, link_ref=ref
        ):
            continue
        await notifications.notify(
            notification_id=new_notification_id(),
            kind=NotificationKind.SPENDING,
            title=BAND_COPY[band].title.format(name=company.display_name),
            body=_spend_body(company, band),
            business_id=company.business_id,
            link_ref=ref,
        )
        announced.append(
            SpendAlert(
                business_id=company.business_id,
                display_name=company.display_name,
                band=band,
            )
        )
    if announced:
        logger.info(
            "spend alerts raised",
            extra={"context": {"count": len(announced), "bands": [a.band for a in announced]}},
        )
    return tuple(announced)


def _spend_body(company: CompanyBudget, band: int) -> str:
    """Render one alert's body from stored values only (D-011, D-040).

    The window is stated in the same sentence as the number, because a total
    that only ever depletes reads very differently from a daily allowance and
    the two are one word apart in English (design 2.1). What it must not do is
    tell an operator which of the two a spending limit *ought* to be — that is
    the open escalation in design Part 10.1, and this sentence describes the
    figure as recorded rather than ruling on it.
    """
    return (
        f"It has spent {_money(company.lifetime_spend_usd)} of its "
        f"{_money(company.lifetime_cap_usd)} limit — a running total since it started, not "
        f"an amount for today. {BAND_COPY[band].consequence}"
    )


# ── the platform ceiling's own warning bands (M9-F83) ───────────────────────
#
# §9's ceiling had a breach narrative (`record_platform_halt`, M9-F2) and no
# advance notice — a company's own cap gets 50%/80% warnings, the platform's
# rolling 24h ceiling got nothing until it actually halted every company at
# once. Same fixed-copy table pattern as 2.3, one band scheme reused via
# `spend_band`'s `bands` argument rather than a second comparison written
# beside it, and the same rollup field a caller could otherwise be tempted to
# recompute: `rolling_24h_utilisation_pct` is already `PortfolioRollup`'s own
# (design 2.2), never re-derived from spend and ceiling here.

PLATFORM_BANDS: tuple[int, ...] = (80, 50)
"""Percentages of the platform's rolling 24h ceiling worth a warning.

No 100 entry: breach already has its own operator narrative —
`record_platform_halt`'s "Jarvis paused spending across all companies" — and
it is written from the breaker's own decision (2.4's argument: the enforcing
check decides a halt, never a percentage crossing read off the rollup). These
two bands exist only to give an operator the same lead time on the shared
ceiling that 2.3 already gives them on their own company's."""

PLATFORM_BAND_COPY: dict[int, _BandCopy] = {
    50: _BandCopy(
        title="Spending across every company has passed half the daily limit",
        consequence=(
            "Nothing has stopped. There is still time to see what is driving it before new "
            "work starts stopping everywhere."
        ),
    ),
    80: _BandCopy(
        title="Spending across every company is close to the daily limit",
        consequence=(
            "When it reaches the limit, new work stops across every company until it resets "
            "or you raise it."
        ),
    ),
}
"""Same register as `BAND_COPY`, and the same phrasing the breach narrative
already uses — `CircuitBreaker.trip`'s rationale says "Total spending in the
last 24 hours reached ... which is the daily limit of ..." — so an operator
who later reads the halt meets a word they were already warned with, not a
new one. "Company", never "business"; "Jarvis" is the implied actor
throughout, never "the Executive Layer" (D-007)."""


@dataclass(frozen=True, slots=True)
class PlatformAlert:
    """One platform-ceiling announcement made (M9-F83)."""

    band: int


def platform_band_ref(band: int) -> str:
    """Return the internal ref recording which platform band a notice announced.

    Namespaced apart from :func:`spend_band_ref`'s company refs even though
    the two never collide on `business_id` (a platform notice's is None, a
    company's never is) — a distinct prefix is one string, and it is the
    difference between a ref that is self-explanatory in a raw row and one
    that needs its `business_id` column read alongside it to mean anything.
    """
    return f"platform-spend-band:{band}"


async def raise_platform_ceiling_alerts(
    rollup: PortfolioRollup, notifications: NotificationService
) -> tuple[PlatformAlert, ...]:
    """Announce the platform ceiling crossing 50% or 80% of its rolling 24h cap.

    Same shape as :func:`raise_spend_alerts`, singular rather than per-company:
    one figure (`rollup.rolling_24h_utilisation_pct`), one band, one notice,
    deduplicated the same way — an unread `SPENDING` notice already carrying
    this exact band's ref suppresses a repeat, and a still-true condition on
    the next pass is announced again (`NotificationService.has_unread`'s
    recorded posture, `business_id=None` for a platform-wide notice — the same
    meaning :meth:`NotificationService.notify` already gives it).

    **Stays silent at or past breach.** `PLATFORM_BANDS` has no 100 entry, and
    without a guard `spend_band` would still return 80 for a utilisation of
    say 140% — an operator would then read "close to the daily limit" in the
    queue in the same moment `record_platform_halt` writes the accurate "Jarvis
    paused spending" to the feed. Two sentences for one event, one of them
    stale, is exactly the failure 2.4 avoids by making the enforcing check the
    one that describes a halt; this function deliberately steps aside once the
    ceiling is actually reached rather than reusing the highest warning band.

    Args:
        rollup: The CFO's rollup. Read, never recomputed.
        notifications: Writer for the operator's queue.

    Returns:
        A one-element tuple if a notice was written, empty if the ceiling is
        below every band, at or past breach (the halt narrative's territory),
        or the crossing was already announced and unread.
    """
    if rollup.rolling_24h_utilisation_pct >= 100:
        return ()
    band = spend_band(rollup.rolling_24h_utilisation_pct, PLATFORM_BANDS)
    if band is None:
        return ()
    ref = platform_band_ref(band)
    if await notifications.has_unread(None, kind=NotificationKind.SPENDING, link_ref=ref):
        return ()
    await notifications.notify(
        notification_id=new_notification_id(),
        kind=NotificationKind.SPENDING,
        title=PLATFORM_BAND_COPY[band].title,
        body=_platform_spend_body(rollup, band),
        business_id=None,
        link_ref=ref,
    )
    logger.info("platform ceiling alert raised", extra={"context": {"band": band}})
    return (PlatformAlert(band=band),)


def _platform_spend_body(rollup: PortfolioRollup, band: int) -> str:
    """Render the platform ceiling's alert body from stored values only (D-011, D-040).

    Mirrors `CircuitBreaker.trip`'s own rationale phrasing ("spending in the
    last 24 hours ... the daily limit") rather than `_spend_body`'s "since it
    started": this figure is the rolling 24h one, not a lifetime total, and
    §12.5 is only honoured if the two windows keep reading differently.
    """
    return (
        f"Spending in the last 24 hours has reached {_money(rollup.rolling_24h_spend_usd)} of "
        f"the {_money(rollup.platform_ceiling_usd)} daily limit. "
        f"{PLATFORM_BAND_COPY[band].consequence}"
    )


async def record_platform_halt(
    rollup: PortfolioRollup,
    breaker: CircuitBreaker,
    decisions: DecisionLog,
    *,
    now: datetime | None = None,
) -> bool:
    """Write §12.5's "Jarvis paused spending" when the platform halts (2.4).

    The caller `CircuitBreaker.trip()` has never had (M9-F2). It lives here,
    outside `jarvis/budget/`, for the reason design 2.4 gives: the halt is a
    *transition*, and a transition is only observable by something that looks
    at the platform repeatedly, which the ledger and the pool boundary are not.
    The pool calls `assert_closed` per dispatch, so recording there would write
    one entry per refused invocation instead of one per halt — and a check that
    writes is no longer a check.

    **The breaker itself decides whether the platform is halted.** This asks
    `assert_closed`, the same call the pool boundary enforces with, rather than
    comparing the rollup's `rolling_24h_spend_usd` to its
    `platform_ceiling_usd`. The two would normally agree — the rollup's ceiling
    is injected from the same setting — but "normally" is the wrong standard
    for this particular sentence: an operator told that spending is paused when
    dispatch is in fact still running has been told something false about the
    platform's safety, and the only way that cannot happen is for the enforcing
    check to be the one that decides. The rollup still supplies the *figure*
    the narrative quotes, which is the packet's rule that Executive alerts
    report recorded numbers.

    **Once per halt, derived from stored values rather than remembered.** A
    prior halt entry inside the same rolling window means this halt is already
    explained, so nothing is written. That keeps the rule true across a
    restart, which an in-memory "was it open last time" flag would not: a
    worker restarting during a halt would announce it a second time, and the
    operator would read two "everything stopped" entries for one event. The
    check reads `action_type` — a structured column, never the prose beside it
    (design Part 4).

    A halt that outlasts the window is announced again, which is deliberate:
    the ledger's window has fully rolled over by then, so the platform being
    at its ceiling *again* is a fresh fact rather than an echo of the old one.

    Nothing is cancelled here (D-003 rule 4). See `CircuitBreaker.trip`.

    Args:
        rollup: Supplies the recorded 24h figure the narrative quotes.
        breaker: The enforcing breaker — asked, not second-guessed.
        decisions: Platform Decision Log, read for the prior entry and written
            through `trip`.
        now: Injectable clock (D-004, D-038 — no uninjected clock).

    Returns:
        True if a halt narrative was written by this call.
    """
    moment = now or datetime.now(UTC)

    try:
        await breaker.assert_closed(now=moment)
    except CircuitBreakerOpenError:
        pass
    else:
        return False

    if await _halt_already_explained(decisions, now=moment):
        return False

    await breaker.trip(
        decision_id=new_decision_id(),
        spend_usd=rollup.rolling_24h_spend_usd,
    )
    return True


async def _halt_already_explained(decisions: DecisionLog, *, now: datetime) -> bool:
    """Return whether this halt already has its Decision Log entry.

    Reads the platform feed — a read design Part 1 explicitly permits — and
    matches on `action_type` alone. Fifty entries is the feed's own default and
    is generous against a store that holds zero platform rows live and gains
    one per halt; a platform that ever wrote fifty other platform decisions
    inside one window would re-announce a halt, which is the harmless direction
    for this check to fail in.
    """
    cutoff = now - PLATFORM_SPEND_WINDOW
    for entry in await decisions.platform_feed():
        if entry.action_type != PLATFORM_HALT_ACTION_TYPE:
            continue
        decided_at = entry.decided_at
        if decided_at.tzinfo is None:
            # SQLite hands back naive what Postgres stores with an offset; the
            # rows are written from `datetime.now(UTC)` either way (the same
            # dialect gap `Scheduler._orphan_reason` documents).
            decided_at = decided_at.replace(tzinfo=UTC)
        if decided_at >= cutoff:
            return True
    return False
