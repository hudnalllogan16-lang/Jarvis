"""Concurrency proof for D-022, against a live Postgres (M6-F12).

**Why this file is not part of the SQLite suite.** M6-F12 is a race between two
database sessions: each dispatch activity holds its own session, so one
dispatch's pre-flight ``SELECT sum(...)`` cannot see a sibling's uncommitted
reservation. The rest of the suite runs against one in-memory SQLite session,
where that shape does not exist and where advisory locks do not exist either — a
concurrency claim proved there would pass without proving anything, which is the
M5-F5 failure mode this project has already been burned by once.

So these tests connect to the real Postgres, create their **own schema**, build
only the ledger table inside it, and drop the schema afterwards. No business
data is read or written. If Postgres is not reachable they skip, and the skip is
visible in the run — never a silent pass.

`test_the_race_is_real_on_this_database` is the negative control: it replays the
pre-D-022 code path in raw SQL and asserts the ceiling *is* breached. Without
it, a passing serialization test could just mean the tasks never actually
overlapped.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from jarvis.budget.ledger import RESERVED, BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import BudgetExceededError
from jarvis.kernel.ids import BusinessId
from jarvis.persistence.models import BudgetLedgerRow

pytestmark = pytest.mark.postgres

DATABASE_URL = os.environ.get(
    "JARVIS_TEST_DATABASE_URL", "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
)
"""Same default as `migrations/env.py`. Overridable, so this can be pointed at a
throwaway instance without editing the test."""

PLATFORM_CEILING = Decimal("500.00")
CYCLE = "cyc_race"
RACERS = 6
"""Enough contenders that a ceiling admitting two is unambiguous."""


@pytest_asyncio.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory over a disposable schema on the live database."""
    admin = create_async_engine(DATABASE_URL, poolclass=NullPool)
    schema = f"jarvis_reservation_probe_{uuid.uuid4().hex[:12]}"
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:
        await admin.dispose()
        pytest.skip(f"live Postgres unavailable ({type(exc).__name__}); D-022 race UNPROVEN here")

    engine = create_async_engine(
        DATABASE_URL, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(BudgetLedgerRow.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


def _ledger(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession] | None = None
) -> BudgetLedger:
    return BudgetLedger(
        session, platform_ceiling_usd=PLATFORM_CEILING, reservation_sessions=factory
    )


async def _cycle_spend(factory: async_sessionmaker[AsyncSession], cycle_id: str) -> Decimal:
    """Read committed cycle spend on a fresh session, outside any writer."""
    async with factory() as session:
        return await _ledger(session).cycle_spend(cycle_id)


# ── the M6-F12 shape ───────────────────────────────────────────────────────


async def test_concurrent_reservations_cannot_both_pass_one_cycle_ceiling(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """D-022 point 1, on the exact shape observed live.

    Six reservations of $0.50 race for a $1.00 wake-cycle ceiling, each on its
    own session the way each dispatch activity has its own. Exactly two may pass.
    Before D-022 all six read a prior spend of 0.00 and all six committed.

    The barrier makes them arrive together every run. Without it the outcome
    depends on connection-pool timing, and a test that only sometimes overlaps
    only sometimes tests anything.
    """
    amount = Decimal("0.50")
    barrier = asyncio.Barrier(RACERS)

    async def reserve() -> str:
        async with sessions() as session:
            ledger = _ledger(session, sessions)
            await barrier.wait()
            try:
                await ledger.reserve(contract=contract, amount_usd=amount, cycle_id=CYCLE)
            except BudgetExceededError as exc:
                return exc.scope
            return "reserved"

    outcomes = await asyncio.gather(*(reserve() for _ in range(RACERS)))

    assert outcomes.count("reserved") == 2, outcomes
    assert set(outcomes) - {"reserved"} == {"wake_cycle"}
    assert await _cycle_spend(sessions, CYCLE) == contract.budget.wake_cycle_ceiling_usd


async def test_the_race_is_real_on_this_database(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """Negative control: the pre-D-022 path, replayed here, still breaches.

    Check on your own session, insert, commit at the end — which is what
    `kernel.services()` did for every dispatch activity. If this passed *and*
    the test above passed, the test above would prove nothing about
    serialization; it would only prove the tasks never overlapped.
    """
    amount = Decimal("0.50")
    ceiling = contract.budget.wake_cycle_ceiling_usd
    barrier = asyncio.Barrier(RACERS)

    async def unserialized_reserve() -> bool:
        async with sessions() as session:
            spend = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(BudgetLedgerRow.amount_usd), 0))
                        .where(BudgetLedgerRow.cycle_id == CYCLE)
                        .where(BudgetLedgerRow.state.in_((RESERVED, "SETTLED")))
                    )
                    or 0
                )
            )
            # The pre-flight sum is taken; the row is not committed yet. This is
            # the window M6-F12 lives in. The barrier removes scheduling luck
            # from the demonstration — it does not create the window.
            await barrier.wait()
            if spend + amount > ceiling:
                return False
            session.add(
                BudgetLedgerRow(
                    business_id=contract.business_id,
                    cycle_id=CYCLE,
                    amount_usd=amount,
                    state=RESERVED,
                )
            )
            await session.commit()
            return True

    passed = await asyncio.gather(*(unserialized_reserve() for _ in range(RACERS)))

    assert all(passed), "the control did not overlap; it proves nothing"
    assert await _cycle_spend(sessions, CYCLE) > ceiling


async def test_concurrent_reservations_cannot_both_pass_the_platform_ceiling(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """M6-F12 applies to spec §9's global ceiling exactly as it does to a cycle.

    Six *different* businesses race, so no per-business lock could catch it —
    only serializing the platform scope does.
    """
    ceiling = Decimal("1.00")
    amount = Decimal("0.50")
    barrier = asyncio.Barrier(RACERS)
    contracts = [
        contract.model_copy(update={"business_id": BusinessId(f"biz_{i:032x}")})
        for i in range(RACERS)
    ]

    async def reserve(own: BusinessContract) -> str:
        async with sessions() as session:
            ledger = BudgetLedger(
                session, platform_ceiling_usd=ceiling, reservation_sessions=sessions
            )
            await barrier.wait()
            try:
                await ledger.reserve(contract=own, amount_usd=amount)
            except BudgetExceededError as exc:
                return exc.scope
            return "reserved"

    outcomes = await asyncio.gather(*(reserve(own) for own in contracts))

    assert outcomes.count("reserved") == 2, outcomes
    assert set(outcomes) - {"reserved"} == {"platform"}
    async with sessions() as session:
        assert await _ledger(session).platform_spend_24h() == ceiling


# ── the two properties the mechanism depends on ────────────────────────────


async def test_a_reservation_survives_its_callers_rollback(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """D-022 point 1: committed *before* the work, not with it.

    The caller here is a stand-in for a dispatch activity, whose own transaction
    is open for the whole invocation. A hold that only became visible when that
    transaction committed could not gate anything the activity was about to do.
    """
    async with sessions() as caller:
        await _ledger(caller, sessions).reserve(
            contract=contract, amount_usd=Decimal("0.25"), cycle_id="cyc_visible"
        )
        assert await _cycle_spend(sessions, "cyc_visible") == Decimal("0.25")
        await caller.rollback()

    assert await _cycle_spend(sessions, "cyc_visible") == Decimal("0.25")


async def test_the_lock_does_not_span_the_work(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """D-022 point 1's other half, and the M4-F1 guard's precondition.

    Four invocations reserve and then work. If the serialized section outlived
    the reservation the work would run one at a time and take four times as
    long — parallel dispatch would have been traded for ceiling correctness.
    """
    work = 0.2

    async def reserve_then_work() -> None:
        async with sessions() as session:
            await _ledger(session, sessions).reserve(
                contract=contract, amount_usd=Decimal("0.10"), cycle_id="cyc_parallel"
            )
            await asyncio.sleep(work)

    started = time.perf_counter()
    await asyncio.gather(*(reserve_then_work() for _ in range(4)))
    elapsed = time.perf_counter() - started

    assert elapsed < work * 2, f"work was serialized with the reservation ({elapsed:.2f}s)"


async def test_the_database_refuses_an_unknown_ledger_state(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """Migration 0006's CHECK constraint, exercised where it actually runs.

    A row in an unrecognised state counts toward no ceiling — it is spend the
    hierarchy cannot see. The database refusing it is the check that survives a
    writer that bypasses `jarvis.budget.ledger`.
    """
    with pytest.raises(Exception, match="ck_ledger_state_known"):
        async with sessions() as session:
            session.add(
                BudgetLedgerRow(
                    business_id=contract.business_id,
                    amount_usd=Decimal("1.00"),
                    state="FORGIVEN",
                )
            )
            await session.commit()
