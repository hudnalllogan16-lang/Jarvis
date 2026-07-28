"""The wall-clock schedule parser (design OPERATIONAL-RUNTIME.md Part 4).

`jarvis/domain/schedule.py` is a pure module, so this is the one place in the
suite where the platform's schedule semantics can be stated as arithmetic rather
than observed through a Manager. Everything here is a fact about a calendar: no
database, no clock, no workflow.

**What it is replacing.** Until M10 the platform read a cron expression through
`_interval_seconds`, which reduced any five fields to 3600 or 86400 seconds.
Two consequences, and the tests below are organised around them because they are
the two halves of one defect:

- **M10-F4** — the expression did not mean what it said. ``"0 9,16 * * *"``, a
  legitimate twice-daily schedule, was executed *hourly*: twelve times the
  intended rounds, every one billable, bounded only by `max_cycles_per_day`.
- **M10-F13** — the interval's anchor was the last park, so every outage moved
  the schedule permanently. Measured live: a ``"0 9 * * *"`` company started a
  `1 day` timer at 22:40, was served 7h34m late, and re-anchored at 06:14.

The fix is one thing rather than two: computing against the calendar *is* the
anti-drift property, because the next fire does not depend on when the last one
happened to be served.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.domain.schedule import (
    MAX_SEARCH_DAYS,
    ScheduleError,
    next_fire_at,
    parse_cron,
    resolve_timezone,
)

DRIFT_ANCHOR = datetime(2026, 7, 27, 22, 40, 31, tzinfo=UTC)
"""The instant M10-F13 measured: when the live daily Manager last parked."""


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ── M10-F13: the drift, ended ──────────────────────────────────────────────


def test_a_daily_schedule_fires_at_its_hour_not_a_day_after_the_last_park() -> None:
    """The finding, as a single comparison.

    The live execution parked at 22:40 and its replacement timer was another
    24 hours from *there*. A daily 09:00 schedule fires at 09:00 — the next
    morning, seven hours away, not the next night.
    """
    assert next_fire_at("0 9 * * *", "UTC", DRIFT_ANCHOR) == _utc("2026-07-28T09:00:00+00:00")
    assert next_fire_at("0 9 * * *", "UTC", DRIFT_ANCHOR) != DRIFT_ANCHOR + timedelta(days=1)


def test_an_outage_delays_one_round_and_leaves_the_schedule_where_it_was() -> None:
    """The property the fix exists for, stated over three consecutive fires.

    The middle wake is served 7h34m late — the live lateness — and the schedule
    does not notice: the fire after it is still 09:00. Under the old interval
    each of these three numbers would have been "whenever the last one was
    served, plus a day", which is a schedule that walks.
    """
    first = next_fire_at("0 9 * * *", "UTC", DRIFT_ANCHOR)
    assert first is not None
    served_late = first + timedelta(hours=7, minutes=34)

    second = next_fire_at("0 9 * * *", "UTC", served_late)
    assert second == _utc("2026-07-29T09:00:00+00:00")

    third = next_fire_at("0 9 * * *", "UTC", second)
    assert third == _utc("2026-07-30T09:00:00+00:00")


# ── M10-F4: the expression means what it says ──────────────────────────────


@pytest.mark.parametrize(
    ("cron", "after", "expected"),
    [
        # The twice-daily schedule the flattening turned into an hourly one.
        ("0 9,16 * * *", "2026-07-28T08:00:00+00:00", "2026-07-28T09:00:00+00:00"),
        ("0 9,16 * * *", "2026-07-28T09:00:00+00:00", "2026-07-28T16:00:00+00:00"),
        ("0 9,16 * * *", "2026-07-28T16:00:00+00:00", "2026-07-29T09:00:00+00:00"),
        # Steps, which the old reader could not express at all.
        ("*/15 * * * *", "2026-07-28T10:07:00+00:00", "2026-07-28T10:15:00+00:00"),
        ("*/15 * * * *", "2026-07-28T10:45:00+00:00", "2026-07-28T11:00:00+00:00"),
        ("0 9-11 * * *", "2026-07-28T09:30:00+00:00", "2026-07-28T10:00:00+00:00"),
        # Weekdays: Friday evening rolls to Monday, which is the shape market
        # hours will need and the reason 4.2 calls this non-speculative.
        ("0 9 * * 1-5", "2026-07-31T10:00:00+00:00", "2026-08-03T09:00:00+00:00"),
        # Sunday is 0 and also 7, in the same expression.
        ("0 9 * * 0", "2026-07-28T00:00:00+00:00", "2026-08-02T09:00:00+00:00"),
        ("0 9 * * 7", "2026-07-28T00:00:00+00:00", "2026-08-02T09:00:00+00:00"),
        # Month and day-of-month, including a year boundary.
        ("0 0 1 1 *", "2026-07-28T00:00:00+00:00", "2027-01-01T00:00:00+00:00"),
        # Every minute of a single hour: lists and ranges combined.
        ("0,30 9,17 * * *", "2026-07-28T09:10:00+00:00", "2026-07-28T09:30:00+00:00"),
    ],
)
def test_the_supported_subset_fires_where_the_calendar_says(
    cron: str, after: str, expected: str
) -> None:
    """Every shape 4.2 commits to, each read as the calendar reads it."""
    assert next_fire_at(cron, "UTC", _utc(after)) == _utc(expected)


def test_a_fire_time_is_strictly_after_the_instant_it_is_asked_about() -> None:
    """Otherwise one schedule period admits two rounds.

    A Manager served exactly on its fire time asks "when next?" from that same
    instant. An inclusive answer would hand back the fire it has just run and
    the loop would plan a second round against the same period — which is the
    rule 4.4 is about, defeated one layer below where it is enforced.
    """
    on_the_hour = _utc("2026-07-28T09:00:00+00:00")
    assert next_fire_at("0 9 * * *", "UTC", on_the_hour) == _utc("2026-07-29T09:00:00+00:00")


def test_the_day_of_month_and_day_of_week_fields_are_or_ed_when_both_restrict() -> None:
    """Cron's own rule, and the one that surprises people.

    ``"0 9 1 * 1"`` means the first of the month *and also* every Monday, not
    "the first, if it is a Monday". Implemented deliberately rather than
    inherited from a library, so it is stated here where a reader can check it.
    """
    schedule = parse_cron("0 9 1 * 1")
    assert schedule.matches_day(datetime(2026, 7, 1).date()), "the first, a Wednesday"
    assert schedule.matches_day(datetime(2026, 7, 6).date()), "a Monday that is not the first"
    assert not schedule.matches_day(datetime(2026, 7, 7).date())

    only_month_day = parse_cron("0 9 1 * *")
    assert not only_month_day.matches_day(datetime(2026, 7, 6).date()), (
        "with one field unrestricted the two are intersected, not or-ed"
    )


# ── 4.2: refused, never flattened ──────────────────────────────────────────


@pytest.mark.parametrize(
    "expression",
    [
        "bad",
        "",
        "0 9 * *",
        "0 9 * * * *",
        "0 9 * * MON",  # names
        "@daily",  # macros
        "0 9 L * *",  # the extended vocabulary
        "0 9 ? * *",
        "60 9 * * *",  # out of range
        "0 24 * * *",
        "0 9 32 * *",
        "0 9 * 13 *",
        "*/0 * * * *",  # a step that never advances
        "0 9 * * */",
        "9-5 9 * * *",  # backwards range
        "0,, 9 * * *",
    ],
)
def test_an_expression_outside_the_subset_is_refused(expression: str) -> None:
    """The behaviour the whole module exists for.

    `_interval_seconds` answered every one of these — with 3600, or with None,
    which the workflow read as "this company has no schedule". A typo therefore
    turned a scheduled company into an event-only one, silently, and the fix for
    that is not a better guess: it is a refusal that names the expression.
    """
    with pytest.raises(ScheduleError) as caught:
        parse_cron(expression)
    assert repr(expression) in str(caught.value) or "five-field" in str(caught.value)


def test_a_schedule_that_names_no_instant_is_refused_rather_than_searched_forever() -> None:
    """The 30th of February parses field by field and never happens.

    Bounded at `MAX_SEARCH_DAYS` — four years and a day, so a leap-day schedule
    still resolves — because the alternative is an activity that spins inside a
    Manager rather than a message at contract validation.
    """
    assert next_fire_at("0 9 29 2 *", "UTC", DRIFT_ANCHOR) == _utc("2028-02-29T09:00:00+00:00")
    with pytest.raises(ScheduleError, match="names no instant"):
        next_fire_at("0 9 30 2 *", "UTC", DRIFT_ANCHOR)
    assert MAX_SEARCH_DAYS > 366 * 4, "a leap-day schedule must stay inside the bound"


def test_a_business_with_no_schedule_has_no_fire_time() -> None:
    """An event-only company (M7-F2's opposite) is not an error, and not zero.

    `None` travels through to the workflow, which waits on a signal and costs
    nothing. This is the one case where the absence of a fire time is the
    correct answer rather than a payload that predates the field."""
    assert next_fire_at(None, "UTC", DRIFT_ANCHOR) is None


# ── 4.3: the timezone ──────────────────────────────────────────────────────


def test_utc_resolves_without_a_timezone_database() -> None:
    """The platform's clock of record, and every live schedule today.

    Answered from the standard library's own constant rather than through
    `zoneinfo`, which is what keeps the running schedules working on a host
    with no timezone database at all.
    """
    assert resolve_timezone("UTC") is UTC


def test_a_wall_clock_schedule_is_read_in_its_own_zone_across_a_dst_change() -> None:
    """Market hours, which is the reason 4.3 exists.

    09:30 in New York is 14:30 UTC in January and 13:30 UTC in July. A schedule
    stored as UTC would be an hour wrong for half the year — and it would be
    wrong in the direction that matters, firing after the opening bell.
    """
    winter = next_fire_at("30 9 * * 1-5", "America/New_York", _utc("2026-01-05T00:00:00+00:00"))
    summer = next_fire_at("30 9 * * 1-5", "America/New_York", _utc("2026-07-06T00:00:00+00:00"))
    assert winter == _utc("2026-01-05T14:30:00+00:00")
    assert summer == _utc("2026-07-06T13:30:00+00:00")


def test_a_local_time_that_does_not_exist_still_fires_once() -> None:
    """The spring-forward gap: 02:30 never happens on that date in New York.

    It fires at the first instant that does exist rather than being skipped for
    the day, because a company whose daily round silently does not happen twice
    a year is the quiet wrongness this module is about. Asserted rather than
    left to `zoneinfo`'s defaults, since it is a behaviour and not an accident.
    """
    fire = next_fire_at("30 2 * * *", "America/New_York", _utc("2026-03-08T04:00:00+00:00"))
    assert fire == _utc("2026-03-08T07:30:00+00:00")


def test_a_zone_this_host_cannot_resolve_is_refused_by_name() -> None:
    """IANA names only, and a refusal that says what to do about it.

    Never a silent fall back to UTC: a company whose owner asked for market
    hours and quietly got London time is exactly the failure this whole module
    replaces, one layer up.
    """
    with pytest.raises(ScheduleError, match="Mars/Olympus"):
        resolve_timezone("Mars/Olympus")
