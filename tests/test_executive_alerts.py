"""Cap alerts and the halt narrative (design EXECUTIVE-LAYER.md 2.3, 2.4).

Two components that existed without a caller until this packet:
`NotificationKind.SPENDING` (M3, zero writers) and `CircuitBreaker.trip()`
(M2, zero callers — M9-F2). Both are exercised here against the same in-memory
platform the rollup tests use, so the alerts fire on the rollup's own fields
rather than on numbers a test computed for them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.rendering import contains_technical_language
from jarvis.budget.breaker import PLATFORM_HALT_ACTION_TYPE, CircuitBreaker
from jarvis.budget.ledger import RESERVED, BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.executive.alerts import (
    BAND_COPY,
    PLATFORM_BAND_COPY,
    PLATFORM_BANDS,
    SPEND_BANDS,
    platform_band_ref,
    raise_platform_ceiling_alerts,
    raise_spend_alerts,
    record_platform_halt,
    spend_band,
    spend_band_ref,
)
from jarvis.executive.rollup import compute_portfolio_rollup
from jarvis.kernel.ids import BusinessId, BusinessTypeName
from jarvis.kpi.engine import KpiEngine
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import BudgetLedgerRow, NotificationRow
from jarvis.registry.registry import BusinessRegistry

CEILING = Decimal("500.00")


async def _install(registry: BusinessRegistry) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )


def _ledger(session: AsyncSession, ceiling: Decimal = CEILING) -> BudgetLedger:
    return BudgetLedger(session, platform_ceiling_usd=ceiling)


async def _rollup(
    session: AsyncSession,
    registry: BusinessRegistry,
    *,
    ledger: BudgetLedger | None = None,
    ceiling: Decimal = CEILING,
):
    return await compute_portfolio_rollup(
        registry,
        ledger or _ledger(session, ceiling),
        KpiEngine(session),
        platform_ceiling_usd=ceiling,
    )


async def _company_spending(
    session: AsyncSession,
    registry: BusinessRegistry,
    contract: BusinessContract,
    *,
    spend: str,
) -> tuple[BusinessId, BudgetLedger]:
    """Register the fixture company (cap $50.00) and spend ``spend`` of it."""
    await _install(registry)
    business_id = await registry.register_instance(contract)
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal(spend))
    return business_id, ledger


# ── bands ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("utilisation", "expected"),
    [
        ("0", None),
        ("49.99", None),
        ("50", 50),
        ("79.9", 50),
        ("80", 80),
        ("99.999", 80),
        ("100", 100),
        ("140", 100),
    ],
)
def test_the_band_is_the_highest_one_crossed(utilisation: str, expected: int | None) -> None:
    """Design 2.3: 50 / 80 / breach, and a company that jumps straight to 90%
    is told "close to the limit" once rather than "half used" first."""
    assert spend_band(Decimal(utilisation)) == expected


def test_every_band_has_copy_and_every_copy_has_a_band() -> None:
    """A band with no sentence would raise a KeyError at the worst moment —
    on a live company crossing a limit — and a sentence with no band is copy
    nothing can ever produce."""
    assert set(BAND_COPY) == set(SPEND_BANDS)


@pytest.mark.parametrize("band", SPEND_BANDS)
def test_the_alert_sentences_are_written_for_the_operator(band: int) -> None:
    """§12.5 applies to a notification exactly as it does to the feed.

    Parametrized over the table rather than spot-checked for the reason
    `DROPPED_WAKE_COPY`'s test gives: the failure mode is a row added later in
    the wrong register. "business" is in `surface_sources.FORBIDDEN` — D-007's
    own Business -> Company term — and is the single easiest word to reach for
    in a sentence about a company's budget.
    """
    copy = BAND_COPY[band]
    title = copy.title.format(name="Summit Trail Gear")
    assert not contains_technical_language(title)
    assert not contains_technical_language(copy.consequence)
    assert title[0].isupper()
    assert copy.consequence.endswith(".")
    assert title not in copy.consequence, "a body that restates its title says nothing new"


@pytest.mark.parametrize("band", SPEND_BANDS)
def test_the_consequence_never_names_an_action_this_surface_does_not_offer(band: int) -> None:
    """M9-9 product REVISE item 5: the old copy said "raise the limit" /
    "you raise it", and nothing on this surface lets an operator do that —
    `business_cap_usd` is set once at creation (`newco.js`) and is never an
    editable field afterward (design PLUGIN-FRAMEWORK.md Part 6: explicitly
    excluded from every refresh band, "the operator's money"). Recovery copy
    must say where the number came from, not imply a control that isn't
    there."""
    consequence = BAND_COPY[band].consequence.lower()
    assert "raise" not in consequence
    assert "you can" not in consequence


def test_the_breach_band_keeps_d007s_own_sentence() -> None:
    """Design 2.3: the alert says what D-007 already promised, earlier — it
    does not introduce operator-visible behaviour beyond D-007's table."""
    assert BAND_COPY[100].title.format(name="Summit Trail Gear") == (
        "Summit Trail Gear hit its spending limit"
    )


# ── alerts ─────────────────────────────────────────────────────────────────


async def test_a_company_below_every_band_is_left_alone(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """$5 of a $50 cap is 10%. An alert here would be the ninety-six-notices-
    a-day failure with a different trigger."""
    await _company_spending(session, registry, contract, spend="5.00")
    notifications = NotificationService(session)

    assert await raise_spend_alerts(await _rollup(session, registry), notifications) == ()
    assert await notifications.unread_count() == 0


async def test_crossing_fifty_percent_announces_once(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The first band, and the deduplication in the same test: a second pass
    over an unchanged platform must add nothing."""
    business_id, _ = await _company_spending(session, registry, contract, spend="26.00")
    notifications = NotificationService(session)

    alerts = await raise_spend_alerts(await _rollup(session, registry), notifications)
    assert [(a.business_id, a.band) for a in alerts] == [(business_id, 50)]

    assert await raise_spend_alerts(await _rollup(session, registry), notifications) == ()
    assert await notifications.unread_count() == 1


async def test_the_notice_quotes_the_stored_figures_and_names_its_window(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-011 and D-040 together: the amounts are the recorded ones, formatted
    rather than regenerated, and the sentence says which window they cover
    without ruling on the window question (design Part 10.1)."""
    await _company_spending(session, registry, contract, spend="26.00")
    notifications = NotificationService(session)
    await raise_spend_alerts(await _rollup(session, registry), notifications)

    row = (await notifications.unread())[0]
    assert row.kind == NotificationKind.SPENDING.value
    assert row.title == "Test Affiliate Co has used half its spending limit"
    assert "$26.00" in row.body
    assert "$50.00" in row.body
    assert "since it started" in row.body
    assert not contains_technical_language(row.body)


async def test_crossing_the_next_band_announces_again(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.3's "the band is the state".

    The 50% notice is still unread when 80% is crossed, so a per-kind
    deduplication would swallow the one that matters — the same information
    loss `WAITING_ON_RESUME` exists to prevent, arriving through the dedup
    rather than through a shared kind.
    """
    _, ledger = await _company_spending(session, registry, contract, spend="26.00")
    notifications = NotificationService(session)
    await raise_spend_alerts(await _rollup(session, registry, ledger=ledger), notifications)

    await ledger.reserve(contract=contract, amount_usd=Decimal("15.00"))  # 41/50 = 82%
    rollup = await _rollup(session, registry, ledger=ledger)
    alerts = await raise_spend_alerts(rollup, notifications)

    assert [a.band for a in alerts] == [80]
    titles = {row.title for row in await notifications.unread()}
    assert titles == {
        "Test Affiliate Co has used half its spending limit",
        "Test Affiliate Co is close to its spending limit",
    }


async def test_a_dismissed_notice_is_raised_again_while_the_condition_holds(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """`has_unread`'s recorded posture, inherited deliberately: an operator who
    dismissed the notice has said they know, and a limit that is still 82%
    spent on the next pass is worth saying again."""
    await _company_spending(session, registry, contract, spend="41.00")
    notifications = NotificationService(session)
    await raise_spend_alerts(await _rollup(session, registry), notifications)

    for row in await notifications.unread():
        await notifications.mark_read(row.notification_id)

    alerts = await raise_spend_alerts(await _rollup(session, registry), notifications)
    assert [a.band for a in alerts] == [80]


async def test_a_breach_is_announced_even_though_nothing_tried_to_spend(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The case the point-of-refusal sentence cannot cover (design 2.3).

    `BudgetExceededError` carries D-007's sentence only when something attempts
    a debit. A company that reaches its cap and is then never dispatched raises
    no error at all, so this notice is the only thing that tells its operator.
    """
    await _company_spending(session, registry, contract, spend="50.00")
    notifications = NotificationService(session)

    alerts = await raise_spend_alerts(await _rollup(session, registry), notifications)

    assert [a.band for a in alerts] == [100]
    assert (await notifications.unread())[0].title == "Test Affiliate Co hit its spending limit"


async def test_the_band_ref_is_recorded_on_the_row_not_parsed_from_the_sentence(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design 2.3's "this needs no table": the row itself records which band it
    announced, in a column."""
    await _company_spending(session, registry, contract, spend="41.00")
    await raise_spend_alerts(await _rollup(session, registry), NotificationService(session))

    refs = (await session.scalars(select(NotificationRow.link_ref))).all()
    assert list(refs) == [spend_band_ref(80)]


async def test_alerts_read_the_rollups_figure_rather_than_the_ledger(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 12's sequencing note, made executable.

    The rollup handed in here reports a utilisation the ledger does not: if
    `raise_spend_alerts` re-derived the number from spend and cap it would find
    10% and stay silent. It must announce, because the rollup's field is its
    only input — which is what stops the alert threshold and the reported
    figure from ever being two numbers.
    """
    await _company_spending(session, registry, contract, spend="5.00")
    real = await _rollup(session, registry)
    doctored = replace(
        real,
        per_company=(replace(real.per_company[0], lifetime_utilisation_pct=Decimal(85)),),
    )

    alerts = await raise_spend_alerts(doctored, NotificationService(session))
    assert [a.band for a in alerts] == [80]


# ── the platform ceiling's own warning bands (M9-F83) ───────────────────────


@pytest.mark.parametrize(
    ("utilisation", "expected"),
    [
        ("0", None),
        ("49.99", None),
        ("50", 50),
        ("79.9", 50),
        ("80", 80),
        ("99.999", 80),
    ],
)
def test_the_platform_band_is_the_highest_one_crossed_below_breach(
    utilisation: str, expected: int | None
) -> None:
    """Same 50/80 shape as the company bands, on the platform's own scheme —
    `PLATFORM_BANDS` has no 100 entry (see the breach test below)."""
    assert spend_band(Decimal(utilisation), PLATFORM_BANDS) == expected


def test_every_platform_band_has_copy_and_every_copy_has_a_band() -> None:
    assert set(PLATFORM_BAND_COPY) == set(PLATFORM_BANDS)


@pytest.mark.parametrize("band", PLATFORM_BANDS)
def test_the_platform_alert_sentences_are_written_for_the_operator(band: int) -> None:
    """§12.5 applies here exactly as `test_the_alert_sentences_are_written_for_
    the_operator` proves it for the company bands — "company", never
    "business", and no other forbidden term."""
    copy = PLATFORM_BAND_COPY[band]
    assert not contains_technical_language(copy.title)
    assert not contains_technical_language(copy.consequence)
    assert copy.title[0].isupper()
    assert copy.consequence.endswith(".")
    assert copy.title not in copy.consequence


@pytest.mark.parametrize("band", PLATFORM_BANDS)
def test_the_platform_consequence_never_names_an_action_this_surface_does_not_offer(
    band: int,
) -> None:
    """M9-9 product REVISE item 5, the platform ceiling's own copy: nothing on
    this surface exposes `platform_rolling_24h_usd` (`jarvis/kernel/
    config.py`) as an editable setting an operator can reach."""
    consequence = PLATFORM_BAND_COPY[band].consequence.lower()
    assert "raise" not in consequence


async def test_a_platform_ceiling_below_every_band_is_left_alone(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _company_spending(session, registry, contract, spend="5.00")
    notifications = NotificationService(session)
    rollup = await _rollup(session, registry, ceiling=Decimal("500.00"))

    assert await raise_platform_ceiling_alerts(rollup, notifications) == ()
    assert await notifications.unread_count() == 0


async def test_crossing_the_platform_eighty_band_announces_once(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The first pass raises it; an unchanged second pass over the same rollup
    figure does not raise it again — dedup with no new state, `has_unread`
    against a platform-wide (`business_id=None`) notice."""
    await _company_spending(session, registry, contract, spend="26.00")
    ceiling = Decimal("28.00")  # 26/28 = 92.86% -> band 80
    notifications = NotificationService(session)
    rollup = await _rollup(session, registry, ceiling=ceiling)

    alerts = await raise_platform_ceiling_alerts(rollup, notifications)
    assert [a.band for a in alerts] == [80]

    assert await raise_platform_ceiling_alerts(rollup, notifications) == ()
    assert await notifications.unread_count() == 1


async def test_the_platform_notice_names_its_window_and_quotes_the_stored_figures(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _company_spending(session, registry, contract, spend="26.00")
    ceiling = Decimal("28.00")
    notifications = NotificationService(session)
    rollup = await _rollup(session, registry, ceiling=ceiling)
    await raise_platform_ceiling_alerts(rollup, notifications)

    row = (await notifications.unread())[0]
    assert row.business_id is None
    assert row.kind == NotificationKind.SPENDING.value
    assert row.title == "Spending across every company is close to the daily limit"
    assert "$26.00" in row.body
    assert "$28.00" in row.body
    assert "in the last 24 hours" in row.body
    assert not contains_technical_language(row.body)
    assert row.link_ref == platform_band_ref(80)


async def test_a_platform_breach_raises_no_stale_warning_notice(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """M9-F83's own guard: once the platform is at or past its ceiling, the
    50/80 scheme steps aside rather than telling the operator the platform is
    merely "close to" a limit it has actually reached — `record_platform_halt`
    is the accurate narrative for that moment, not this function."""
    await _company_spending(session, registry, contract, spend="28.00")
    ceiling = Decimal("28.00")  # 100% exactly
    notifications = NotificationService(session)
    rollup = await _rollup(session, registry, ceiling=ceiling)
    assert rollup.rolling_24h_utilisation_pct == 100

    assert await raise_platform_ceiling_alerts(rollup, notifications) == ()
    assert await notifications.unread_count() == 0


async def test_platform_and_company_bands_are_independent_notices(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """One spend crosses both a company band and the platform band in the same
    pass, and both are recorded — distinct `link_ref`s under distinct
    `business_id`s, neither suppressing the other."""
    await _company_spending(session, registry, contract, spend="26.00")
    ceiling = Decimal("28.00")
    notifications = NotificationService(session)
    rollup = await _rollup(session, registry, ceiling=ceiling)

    company_alerts = await raise_spend_alerts(rollup, notifications)
    platform_alerts = await raise_platform_ceiling_alerts(rollup, notifications)

    assert [a.band for a in company_alerts] == [50]
    assert [a.band for a in platform_alerts] == [80]
    refs = {row.link_ref for row in await notifications.unread()}
    assert refs == {spend_band_ref(50), platform_band_ref(80)}


# ── the halt narrative (M9-F2) ─────────────────────────────────────────────


async def test_a_closed_breaker_writes_nothing(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _company_spending(session, registry, contract, spend="5.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session), decisions, ceiling_usd=CEILING)

    assert await record_platform_halt(await _rollup(session, registry), breaker, decisions) is False
    assert await decisions.platform_feed() == []


async def test_a_halt_is_explained_once_not_once_per_pass(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """M9-F2's fix, and the reason it belongs beside `assert_closed`'s caller
    rather than inside it: the pool boundary runs per dispatch, so recording
    there would write one entry per refused invocation."""
    await _company_spending(session, registry, contract, spend="10.00")
    ceiling = Decimal("10.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session, ceiling), decisions, ceiling_usd=ceiling)
    rollup = await _rollup(session, registry, ceiling=ceiling)

    assert await record_platform_halt(rollup, breaker, decisions) is True
    assert await record_platform_halt(rollup, breaker, decisions) is False

    entries = await decisions.platform_feed()
    assert len(entries) == 1
    assert entries[0].business_id is None
    assert entries[0].action_type == PLATFORM_HALT_ACTION_TYPE
    assert entries[0].summary == "Jarvis paused spending across all companies."
    assert not contains_technical_language(entries[0].rationale)


async def test_the_narrative_quotes_the_rollups_recorded_figure(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The Executive supplies the number; the breaker supplies the ceiling it
    enforces with. Both are recorded values, neither is recomputed here."""
    await _company_spending(session, registry, contract, spend="12.00")
    ceiling = Decimal("10.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session, ceiling), decisions, ceiling_usd=ceiling)

    rollup = await _rollup(session, registry, ceiling=ceiling)
    await record_platform_halt(rollup, breaker, decisions)

    rationale = (await decisions.platform_feed())[0].rationale
    assert "$12.00" in rationale
    assert "$10.00" in rationale


async def test_a_halt_outlasting_the_window_is_announced_again(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The ledger's window has fully rolled over by then, so being at the
    ceiling again is a fresh fact rather than an echo of the old one."""
    await _company_spending(session, registry, contract, spend="10.00")
    ceiling = Decimal("10.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session, ceiling), decisions, ceiling_usd=ceiling)
    rollup = await _rollup(session, registry, ceiling=ceiling)

    assert await record_platform_halt(rollup, breaker, decisions) is True
    later = datetime.now(UTC) + timedelta(hours=25)
    # The spend rolls out of the window at the same moment the entry does, so
    # the ledger row is aged back to keep the breaker open at `later`.
    row = (await session.scalars(select(BudgetLedgerRow))).first()
    assert row is not None
    row.recorded_at = later - timedelta(minutes=1)
    await session.flush()

    assert await record_platform_halt(rollup, breaker, decisions, now=later) is True
    assert len(await decisions.platform_feed()) == 2


async def test_the_enforcing_check_decides_not_the_reported_ceiling(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """A rollup reporting a ceiling the breaker does not enforce must never
    produce "Jarvis paused spending".

    An operator told the platform has stopped when dispatch is in fact still
    running has been told something false about its safety, and the only
    arrangement in which that cannot happen is the one where the check that
    refuses dispatch is also the one that decides there is a halt to explain.
    """
    await _company_spending(session, registry, contract, spend="12.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session), decisions, ceiling_usd=CEILING)
    # The rollup is told the ceiling is $10 — 120% utilisation — while the
    # breaker still enforces $500 and lets every dispatch through.
    rollup = await _rollup(session, registry, ceiling=Decimal("10.00"))
    assert rollup.rolling_24h_utilisation_pct > 100

    assert await record_platform_halt(rollup, breaker, decisions) is False
    assert await decisions.platform_feed() == []


async def test_recording_the_halt_never_touches_in_flight_work(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-003 rule 4: a ceiling breach never kills an invocation mid-execution.

    The packet's own escalation trigger — trip semantics that would kill
    in-flight work — asserted rather than argued: the held reservation that
    pushed the platform over its ceiling is still RESERVED afterwards, so the
    invocation holding it is untouched and will settle or release normally.
    """
    await _company_spending(session, registry, contract, spend="10.00")
    ceiling = Decimal("10.00")
    decisions = DecisionLog(session)
    breaker = CircuitBreaker(_ledger(session, ceiling), decisions, ceiling_usd=ceiling)

    assert (
        await record_platform_halt(
            await _rollup(session, registry, ceiling=ceiling), breaker, decisions
        )
        is True
    )

    rows = (await session.scalars(select(BudgetLedgerRow))).all()
    assert [row.state for row in rows] == [RESERVED]
    assert await _ledger(session, ceiling).platform_spend_24h() == Decimal("10.00")
