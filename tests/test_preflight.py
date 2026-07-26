"""Preflight health-check tests (regression: M5-F5).

`check_database` misclassified a fresh, un-migrated Postgres database as DOWN
instead of DEGRADED, because the original implementation tried to recognise
"table doesn't exist yet" by string-matching an exception's class name and
message — both written to SQLite's shape, not Postgres's. On Postgres,
SQLAlchemy wraps the driver error in ``ProgrammingError`` (so the class name
check never matched) and the message reads "does not exist" rather than
SQLite's "no such table" (so the text check never matched either). Every
first-ever launch against a fresh database was misreported as DOWN, which
made the launcher retry a check that could never pass for two minutes and
exit without ever starting the dashboard.

These tests assert on behaviour, not on any particular exception shape, so a
future driver change cannot silently reintroduce the same failure mode.
"""

from __future__ import annotations

import sys
import types

if "sqlalchemy" not in sys.modules:
    _stub = types.ModuleType("sqlalchemy")
    _stub.text = lambda s: s  # type: ignore[attr-defined]
    sys.modules["sqlalchemy"] = _stub


from jarvis.shell.preflight import Status, check_database


class _ProgrammingError(Exception):
    """Stand-in for SQLAlchemy's wrapper exception on a missing-table error.

    Deliberately shaped like the real Postgres failure: the class name gives
    no hint of "undefined table", and the message uses Postgres's wording.
    """


class _FakeSession:
    def __init__(self, *, fail_on_probe: bool = False, fail_on_schema: bool = False) -> None:
        self._fail_on_probe = fail_on_probe
        self._fail_on_schema = fail_on_schema

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement: str) -> object:
        text = str(statement)
        if "SELECT 1" in text and self._fail_on_probe:
            raise ConnectionRefusedError("could not connect to server")
        if "business_instances" in text and self._fail_on_schema:
            raise _ProgrammingError(
                "(sqlalchemy.dialects.postgresql.asyncpg.Error) <class "
                "'asyncpg.exceptions.UndefinedTableError'>: relation "
                '"business_instances" does not exist'
            )

        class _Result:
            def scalar(self) -> int:
                return 0

        return _Result()


class _FakeKernel:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session_factory(self) -> _FakeSession:
        return self._session


async def test_fresh_unmigrated_database_is_degraded_not_down() -> None:
    """The exact reported failure: a real database, tables not yet created.

    This must be DEGRADED. Migrations run unconditionally right after
    preflight passes, so a schema-only failure is never a reason to refuse to
    start — and DOWN here is what silently kills the dashboard on every
    first-ever launch.
    """
    kernel = _FakeKernel(_FakeSession(fail_on_schema=True))
    result = await check_database(kernel)
    assert result.status is Status.DEGRADED
    assert "not set up yet" in result.summary


async def test_real_connection_failure_is_down() -> None:
    """A failure on the connectivity probe itself is a genuine outage."""
    kernel = _FakeKernel(_FakeSession(fail_on_probe=True))
    result = await check_database(kernel)
    assert result.status is Status.DOWN


async def test_healthy_migrated_database_is_ok() -> None:
    kernel = _FakeKernel(_FakeSession())
    result = await check_database(kernel)
    assert result.status is Status.OK


async def test_schema_check_classification_does_not_depend_on_wording() -> None:
    """Regression guard on the *mechanism*, not just one error's wording.

    Any exception on the schema probe — regardless of class name or message —
    must be DEGRADED, because by the time that query runs, `SELECT 1` already
    succeeded. Parametrising over shapes closes the door the original bug
    walked through: matching specific strings instead of the query that failed.
    """

    class _WeirdDriverError(Exception):
        pass

    class _WeirdSession(_FakeSession):
        async def execute(self, statement: str) -> object:
            if "business_instances" in str(statement):
                raise _WeirdDriverError("some future driver's own wording")
            return await super().execute(statement)

    kernel = _FakeKernel(_WeirdSession())
    result = await check_database(kernel)
    assert result.status is Status.DEGRADED
