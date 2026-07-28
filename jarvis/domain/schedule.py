"""Wall-clock schedules (design OPERATIONAL-RUNTIME.md Part 4).

A cron expression names *instants on a calendar*, not an interval. The platform
read it as an interval until M10: `_interval_seconds` reduced every five-field
expression to 3600 or 86400, so ``"0 9 * * *"`` meant "every 24 hours from
whenever the Manager last parked" and ``"0 9,16 * * *"`` — a legitimate
twice-daily schedule — became hourly, a 12x billable over-fire bounded only by
`max_cycles_per_day` (M10-F4). Two consequences, and they are one defect:

1. **The interval is not the schedule.** ``"0 9 * * *"`` means 09:00.
2. **An interval's anchor is the last park, so every outage moves it.** M10-F13
   measured it live: a daily schedule drifted 22:40 -> 06:14 in one incident and
   would have kept drifting. Computing the next fire from the calendar *is* the
   anti-drift property — an outage then delays one cycle and leaves the schedule
   where it was.

Everything here is pure: no clock read, no I/O beyond `zoneinfo`'s own database
lookup, no platform state. `after` is always supplied by the caller, which is
what lets the Manager's activity compute a fire time whose result is recorded in
workflow history and therefore replays identically (D-004).

**Hand-rolled rather than `croniter`.** The design's dependency note binds, and
the justification is one line: the supported subset is five numeric fields with
lists, ranges and steps — roughly eighty lines of arithmetic — while the
behaviour that actually matters here is the *refusal* of everything else
(4.2: an expression this cannot express is rejected at contract validation, never
silently flattened), which a third-party parser's own permissiveness would have
to be fought rather than inherited.

**The timezone database is not vendored.** ``"UTC"`` resolves without one, which
is every schedule the platform runs today; any other IANA name is resolved
through `zoneinfo` and **refused loudly** where the host has no database — which
is the ordinary state of a Windows host, the platform's host of record, unless
`tzdata` is installed. That refusal is the flag, not a silent fallback to UTC:
a company whose owner asked for market hours and silently got London time is the
kind of quiet wrongness this whole module exists to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.kernel.errors import JarvisError

__all__ = [
    "MAX_SEARCH_DAYS",
    "VALIDATION_REFERENCE",
    "CronSchedule",
    "ScheduleError",
    "next_fire_at",
    "parse_cron",
    "resolve_timezone",
]


class ScheduleError(JarvisError, ValueError):
    """A schedule the platform cannot execute exactly as written.

    A `ValueError` as well as a `JarvisError` so a pydantic validator raising it
    becomes an ordinary `ValidationError` at contract creation (4.2's "refused at
    contract validation, loudly"), rather than escaping as an unhandled error
    from whichever caller happened to be constructing the contract.
    """

    default_operator_message = "That schedule isn't one Jarvis knows how to keep."


MAX_SEARCH_DAYS = 366 * 4 + 1
"""How far ahead a fire time is looked for before the expression is called
unsatisfiable.

Four years and a day, because the longest legitimate gap in a five-field
expression is a leap-day schedule (``"0 9 29 2 *"``), and anything longer is an
expression that names no instant at all — ``"0 9 30 2 *"`` — which is refused
rather than parked on. The bound is what turns "never fires" from an infinite
loop inside an activity into a message at contract validation."""

VALIDATION_REFERENCE = datetime(2000, 1, 1, tzinfo=UTC)
"""The instant satisfiability is probed from at validation time.

Fixed rather than "now": validating the same contract twice must give the same
answer, and a validator that reads a clock makes a stored contract's
admissibility depend on the day it was re-read."""

_FIELD_NAMES = ("minute", "hour", "day of month", "month", "day of week")
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _parse_field(raw: str, index: int, expression: str) -> tuple[frozenset[int], bool]:
    """Return the values one cron field admits, and whether it restricts anything.

    Args:
        raw: The field's text, e.g. ``"9,16"`` or ``"*/15"``.
        index: Which of the five fields this is, for bounds and messages.
        expression: The whole expression, so a refusal names what was refused.

    Returns:
        The admitted values, and False when the field is ``*`` (or a full-range
        equivalent) — which is what the day-of-month/day-of-week rule below
        needs to know.

    Raises:
        ScheduleError: For anything outside the supported subset. Every branch
            here is a refusal rather than a fallback, deliberately: the defect
            this module replaces was a fallback.
    """
    name = _FIELD_NAMES[index]
    low, high = _FIELD_BOUNDS[index]
    if not raw:
        msg = f"{expression!r} has an empty {name} field"
        raise ScheduleError(msg)

    values: set[int] = set()
    restricted = False
    for part in raw.split(","):
        if not part:
            msg = f"{expression!r} has an empty entry in its {name} field"
            raise ScheduleError(msg)
        body, slash, step_text = part.partition("/")
        step = 1
        if slash and not step_text:
            msg = f"{expression!r} has a {name} step with no interval"
            raise ScheduleError(msg)
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                msg = f"{expression!r} has a {name} step that is not a positive whole number"
                raise ScheduleError(msg)
            step = int(step_text)

        if body == "*":
            start, end = low, high
        elif "-" in body:
            start_text, _, end_text = body.partition("-")
            start = _bounded(start_text, index, expression)
            end = _bounded(end_text, index, expression)
            if start > end:
                msg = f"{expression!r} has a backwards {name} range ({body})"
                raise ScheduleError(msg)
            restricted = True
        else:
            start = _bounded(body, index, expression)
            end = high if step_text else start
            restricted = True

        values.update(range(start, end + 1, step))
        if step > 1 and body == "*":
            restricted = True

    if index == 4:
        # Both 0 and 7 name Sunday in the standard five-field form, and a
        # schedule that said `7` must match the same days one that said `0` does.
        values = {0 if value == 7 else value for value in values}
    return frozenset(values), restricted


def _bounded(text: str, index: int, expression: str) -> int:
    """Return one numeric field value, or refuse it by name and by range."""
    name = _FIELD_NAMES[index]
    low, high = _FIELD_BOUNDS[index]
    if not text.isdigit():
        msg = (
            f"{expression!r} has a {name} value ({text!r}) that is not a whole number — "
            f"names, macros and the extended cron vocabulary (L, W, #, ?) are not supported"
        )
        raise ScheduleError(msg)
    value = int(text)
    if not low <= value <= high:
        msg = f"{expression!r} has a {name} value out of range: {value} is not in {low}..{high}"
        raise ScheduleError(msg)
    return value


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """A parsed five-field schedule, and the calendar it names.

    Immutable and comparable by value, so a parsed schedule can be cached,
    compared in a test, and carried across a boundary without anyone wondering
    whether it still means what it did.
    """

    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    day_of_month_restricted: bool
    day_of_week_restricted: bool
    expression: str

    def matches_day(self, day: date) -> bool:
        """Return whether this schedule fires at all on ``day``.

        The day-of-month/day-of-week rule is cron's own and is the one piece of
        this that surprises people: when *both* fields are restricted they are
        **or**-ed, not and-ed — ``"0 9 1 * 1"`` means the first of the month *and
        also* every Monday. When only one is restricted the other is `*` and
        contributes nothing, so plain intersection gives the same answer.
        """
        if day.month not in self.months:
            return False
        # Sunday is 0 here; `date.weekday()` calls Monday 0.
        weekday = (day.weekday() + 1) % 7
        by_month_day = day.day in self.days_of_month
        by_weekday = weekday in self.days_of_week
        if self.day_of_month_restricted and self.day_of_week_restricted:
            return by_month_day or by_weekday
        return by_month_day and by_weekday

    def times_of_day(self) -> tuple[time, ...]:
        """Return every wall-clock time this schedule fires at, in order."""
        return tuple(
            time(hour, minute) for hour in sorted(self.hours) for minute in sorted(self.minutes)
        )

    def next_fire_at(self, after: datetime, *, timezone: str = "UTC") -> datetime:
        """Return the first instant this schedule fires **strictly after** ``after``.

        Strictly after, because the alternative re-fires the instant a cycle was
        just served on and turns one schedule period into two cycles.

        Args:
            after: Any aware instant. Converted to ``timezone`` for the
                calendar walk and never read from a clock here.
            timezone: IANA name the expression's wall-clock times are read in.

        Returns:
            The fire time, as an aware UTC instant — UTC because it is the
            platform's clock of record and every stored instant already is one.

        Raises:
            ScheduleError: If the expression names no instant inside
                :data:`MAX_SEARCH_DAYS`, or the timezone cannot be resolved.
        """
        zone = resolve_timezone(timezone)
        local = after.astimezone(zone)
        times = self.times_of_day()
        day = local.date()
        for _ in range(MAX_SEARCH_DAYS):
            if self.matches_day(day):
                for moment in times:
                    # `> after` rather than a comparison in local time, and it
                    # does both jobs: it skips the earlier part of the first
                    # day, and it skips a repeated wall-clock hour on the day a
                    # zone falls back — where the same local time names two
                    # instants and only the later one is still in the future.
                    fire = datetime.combine(day, moment, tzinfo=zone).astimezone(UTC)
                    if fire > after:
                        return fire
            day += timedelta(days=1)
        msg = (
            f"{self.expression!r} names no instant within {MAX_SEARCH_DAYS} days of "
            f"{after.isoformat()} — a schedule that never fires is a company that never runs"
        )
        raise ScheduleError(msg)


def parse_cron(expression: str) -> CronSchedule:
    """Parse a five-field cron expression, or refuse it (design 4.2).

    Supported: the five standard fields, each admitting ``*``, a number, a
    ``a-b`` range, a ``x,y`` list, and any of those with a ``/step``. That is
    exactly what the platform's own schedules need — ``"0 9 * * *"``,
    ``"0 9,16 * * *"``, ``"*/15 * * * *"``, ``"0 9 * * 1-5"`` — and everything
    else is refused rather than approximated.

    Args:
        expression: The cron text, e.g. from a contract's wake conditions.

    Returns:
        The parsed schedule.

    Raises:
        ScheduleError: Naming the expression and the field that refused it, so
            the message an operator's log carries says which part to fix.
    """
    fields = expression.split()
    if len(fields) != 5:
        msg = (
            f"{expression!r} is not a five-field schedule (minute hour day-of-month "
            f"month day-of-week); it has {len(fields)} field(s)"
        )
        raise ScheduleError(msg)

    parsed = [_parse_field(raw, index, expression) for index, raw in enumerate(fields)]
    return CronSchedule(
        minutes=parsed[0][0],
        hours=parsed[1][0],
        days_of_month=parsed[2][0],
        months=parsed[3][0],
        days_of_week=parsed[4][0],
        day_of_month_restricted=parsed[2][1],
        day_of_week_restricted=parsed[4][1],
        expression=expression,
    )


def resolve_timezone(name: str) -> tzinfo:
    """Return the timezone ``name`` denotes, or refuse it.

    ``"UTC"`` is answered from the standard library's own constant rather than
    from the timezone database, which is why the platform's live schedules keep
    working on a host that has no database at all. Any other name is resolved
    through `zoneinfo`, and a host with no database refuses it — see this
    module's own docstring for why that refusal is deliberate rather than a
    missing dependency nobody noticed.

    Args:
        name: An IANA timezone name.

    Returns:
        Something `datetime.astimezone` accepts.

    Raises:
        ScheduleError: If the name is not an IANA zone this host can resolve.
    """
    if name == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        msg = (
            f"timezone {name!r} cannot be resolved on this host: {error}. Every stored "
            f"instant is UTC and 'UTC' always resolves; another zone needs a timezone "
            f"database present (the 'tzdata' package on a host without a system one)"
        )
        raise ScheduleError(msg) from error
    except (ValueError, KeyError) as error:  # malformed key, e.g. an absolute path
        msg = f"timezone {name!r} is not an IANA timezone name"
        raise ScheduleError(msg) from error


def next_fire_at(cron: str | None, timezone: str, after: datetime) -> datetime | None:
    """Return when a schedule next fires, or None when there is no schedule.

    The one function the Manager's context activity calls, so the "no schedule
    at all" case — a business woken only by events (M7-F2's opposite) — is
    answered here rather than by every caller re-deciding what `None` means.

    Args:
        cron: The contract's expression, or None for an event-only business.
        timezone: The contract's IANA timezone.
        after: The instant to compute from — the activity's own clock read.

    Returns:
        The next fire time in UTC, or None if this business has no schedule.

    Raises:
        ScheduleError: If the expression or the timezone is one this platform
            cannot execute. Loud on purpose: a stored schedule that cannot be
            parsed must stop the Manager visibly rather than quietly turn a
            company into one that never wakes.
    """
    if cron is None:
        return None
    return parse_cron(cron).next_fire_at(after, timezone=timezone)
