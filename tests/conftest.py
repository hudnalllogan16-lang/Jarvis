"""Shared test fixtures.

Tests run against in-memory SQLite so the suite needs no external services. The
production target is PostgreSQL, and the substitution is honest for everything
here **except two properties, named rather than glossed** (D-025.2, correcting
this file's earlier claim that nothing depended on a Postgres-only feature):

- **Serialized reservations (D-022).** Advisory locks do not exist in SQLite,
  and the shape M6-F12 lives in — two sessions racing one ceiling — is not what
  an in-memory fixture creates. Gated by `test_budget_reservation_concurrency.py`.
- **Independent denial commits (D-025.1).** A denial record must survive the
  transaction its refusal aborts *while that caller's own work rolls back*.
  `StaticPool` shares one connection and sweeps the caller's work in with the
  denial; a file-backed SQLite blocks the independent write behind the
  single-writer lock and loses the denial instead. Both are artefacts of the
  substitution, so the property is gated by `test_denial_independence.py`.

Both files are marked `postgres` and skip — visibly, never silently — when the
stack is down. A skipped gate is reported as unexecuted, never as verified
(M5-F5 discipline).
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from temporalio.testing import ActivityEnvironment

from jarvis.domain.contract import (
    AutonomyPolicy,
    BudgetPolicy,
    BusinessContract,
    CapabilityPermission,
    CapabilityType,
    WakeConditions,
)
from jarvis.kernel.ids import BusinessId, BusinessTypeName
from jarvis.kernel.runtime import business_workflow_id
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import Base
from jarvis.registry.registry import BusinessRegistry


def as_business(business_id: BusinessId, fn: Callable[..., Any], *args: Any) -> Any:
    """Call an activity as though ``business_id``'s Manager had scheduled it.

    D-002 derives identity from `activity.info().workflow_id`, which the
    Temporal server populates from the calling workflow. A test calling an
    activity method directly has no such context, so it has no identity — and
    since the M6-4a hardening every `ManagerActivities` method refuses that
    (a caller the platform cannot identify is the §10 case, not an exemption).
    Routing through `ActivityEnvironment` gives the test the same provenance
    production has, which also means these tests now exercise the derivation
    rather than skipping past it.

    Args:
        business_id: The business whose Manager is the notional caller.
        fn: The activity method.
        *args: Its arguments.

    Returns:
        Whatever ``fn`` returns — a coroutine for async activities, so callers
        await the result.
    """
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=business_workflow_id(business_id))
    return env.run(fn, *args)


@compiles(BigInteger, "sqlite")
def _compile_biginteger_as_integer_on_sqlite(type_, compiler, **kw):
    """Make autoincrementing BigInteger primary keys work on SQLite.

    SQLite only treats a single-column primary key as the ``rowid`` alias
    (which is what makes autoincrement happen) when its declared type is
    exactly ``INTEGER``. SQLAlchemy's sqlite dialect renders ``BigInteger``
    as ``BIGINT``, so on a fresh in-memory database
    ``audit_log.id`` / ``budget_ledger.id`` / ``kpi_values.id`` came back
    NULL on insert and violated NOT NULL. Under Postgres, the production
    target, ``BigInteger`` autoincrements fine via ``BIGSERIAL`` — this is a
    SQLite substitution gap, not a behaviour change, and it is scoped to the
    "sqlite" dialect only so it has no effect outside the test suite.
    """
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session against a fresh in-memory database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def registry(session: AsyncSession) -> BusinessRegistry:
    """Return a Registry wired to the test session."""
    return BusinessRegistry(session, AuditLog(session), DecisionLog(session))


@pytest.fixture
def contract() -> BusinessContract:
    """Return a minimal valid Standard Business Contract (spec §5)."""
    return BusinessContract(
        business_id=BusinessId("biz_0123456789abcdef0123456789abcdef"),
        business_type=BusinessTypeName("affiliate"),
        display_name="Test Affiliate Co",
        budget=BudgetPolicy(
            business_cap_usd=Decimal("50.00"),
            wake_cycle_ceiling_usd=Decimal("1.00"),
        ),
        wake_conditions=WakeConditions(schedule_cron="0 9 * * *"),
        capability_permissions=(
            CapabilityPermission(
                capability=CapabilityType.RESEARCH,
                tool_scope=frozenset({"web_search"}),
                credential_refs=frozenset({"serp_key"}),
            ),
        ),
        autonomy_policies=(
            AutonomyPolicy(
                action_type="affiliate.publish_post",
                graduation_threshold=5,
                # Explicit since M9-G1a: `graduation_eligible` no longer defaults to
                # True (M9-F115), and the graduation suites need the live affiliate
                # type's actual setting rather than whatever the default happens to be.
                graduation_eligible=True,
            ),
        ),
    )
