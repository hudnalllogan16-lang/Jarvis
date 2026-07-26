"""Hierarchical budget ledger (D-003 and D-022, spec §2.1 / §2.2 / §5 / §9).

v1.4 defines four independent ceilings and never relates them. D-003 relates
them: every unit of spend debits, in order,

    invocation allocation -> wake-cycle ceiling -> business budget -> platform 24h

and a debit that would breach *any* enclosing ceiling is refused before the
spend occurs. Ceilings are pre-flight checks, not post-hoc alarms — a post-hoc
alarm tells you the money is gone.

Reservations, not settlements, are what gate the check. A reservation counts
against every ceiling from the moment it is taken and stops counting only when
released, so two concurrent invocations cannot both pass a check against the
same remaining headroom and then both spend it.

**D-022: that last sentence was false until the reservation got its own
transaction.** Each dispatch activity held its own session and `kernel.services()`
committed only when the activity finished, so one dispatch's pre-flight
``SELECT sum(...)`` could not see a sibling's uncommitted reservation. Observed
live, not inferred (M6-F12): two reservations of one cycle each read 0.00 prior
spend, both passed, and 1.40 committed against a 1.00 ceiling.

So a reservation now runs in its own short transaction, committed before the
work starts, with the check-then-insert serialized per scope by advisory
transaction locks. Two things follow, both deliberate:

- The serialized section spans three indexed aggregates and one insert, never
  the work itself. Parallel dispatch stays parallel (M4-F1 guard).
- The reservation no longer commits atomically with the audit entry describing
  it. A crash in between leaves a reservation row with no audit entry — the row
  still carries business, invocation, cycle, amount and state, and an
  unexplained *hold* only ever under-reports headroom. The reverse ordering,
  which the shared-session arrangement gave us, under-reports spend, which is
  the failure D-003 rule 1 exists to prevent.

Serialization is a Postgres mechanism. The suite's SQLite substitution is honest
for every property here except this one — advisory locks do not exist there and
concurrent sessions are not what the in-memory fixture creates. The live
Postgres proof is `tests/test_budget_reservation_concurrency.py`; a SQLite-only
concurrency claim would be vacuous (M5-F5).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import BudgetExceededError, CircuitBreakerOpenError
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.kernel.logging import get_logger
from jarvis.llm.base import CompletionRequest, Usage
from jarvis.persistence.engine import session_scope
from jarvis.persistence.models import BudgetLedgerRow

logger = get_logger(__name__)

RESERVED = "RESERVED"
SETTLED = "SETTLED"
RELEASED = "RELEASED"

_COUNTING_STATES = (RESERVED, SETTLED)
"""States that consume headroom. RELEASED entries are refunds and do not."""

KNOWN_STATES = (RESERVED, SETTLED, RELEASED)
"""Every state the ledger may hold. Mirrored as a database CHECK constraint in
migration 0006: a row whose state is none of these counts toward no ceiling, so
an unrecognised value is silently spendable budget."""

MONEY = Decimal("0.000001")
"""Quantum of `budget_ledger.amount_usd` (``Numeric(12, 6)``). Amounts are
rounded *up* to it, so rounding can only over-state a hold, never under-state
one."""

LOCK_NAMESPACE = "jarvis.budget.reservation"

_PLATFORM_SCOPE = "platform"


def _lock_key(scope: str) -> int:
    """Return a stable 64-bit advisory-lock key for one budget scope.

    Hashed rather than enumerated because scope keys are business and cycle
    identifiers, which are minted at runtime. A digest collision makes two
    unrelated scopes share one lock — that over-serializes and can never
    under-serialize, so it costs throughput and never correctness.
    """
    digest = hashlib.blake2b(f"{LOCK_NAMESPACE}:{scope}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def _serialize_scopes(
    session: AsyncSession, *, business_id: BusinessId, cycle_id: str | None
) -> None:
    """Hold every enclosing scope's lock for the rest of this transaction.

    D-022 point 1. Taken outermost-first and always in the same order, which is
    what makes a set of overlapping reservations deadlock-free: two transactions
    that both want the platform and a business lock cannot each hold the other's
    first lock.

    The platform scope is locked on every reservation because spec §9's ceiling
    is global — the M6-F12 race applies to it exactly as it applies to a cycle.
    That makes reservation a globally serialized section; it is affordable
    because the section is three indexed aggregates and one insert, and it is
    *required* because a ceiling nobody serializes is not a ceiling.

    Advisory locks are a Postgres facility. On any other dialect this is a no-op
    and the guarantee reduces to whatever that dialect's own write serialization
    gives — see the module docstring.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    scopes = [_PLATFORM_SCOPE, f"business:{business_id}"]
    if cycle_id is not None:
        scopes.append(f"cycle:{cycle_id}")
    for scope in scopes:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(scope)})


def reasoning_call_reservation_usd(
    request: CompletionRequest, *, price_per_million_tokens_usd: Decimal
) -> Decimal:
    """Return the bounded worst-case cost of one model call (D-022 point 2).

    M6-F14: the Manager's own reasoning was charged to no ceiling at all, though
    D-003 covers "every unit of spend" and those calls are most of a cycle's
    cost. Charging them needs a number known *before* the call, and D-022 says
    it comes from the call's token ceiling rather than a guess.

    Both halves of the token count are bounded here:

    - Output is bounded by `CompletionRequest.max_tokens`, the request's own
      ceiling, which every transport passes to its provider.
    - Input has no ceiling in the provider protocol (a finding). It is bounded
      instead by the encoded length of the prompt, which is known before the
      call and cannot grow after it. Every token of every tokenizer these
      providers use covers at least one byte, so byte length is a strict upper
      bound on token count — loose (roughly 4x on prose), and loose in the
      conservative direction.

    The price is an upper bound supplied by configuration, not a market rate:
    per-model pricing does not exist in Jarvis until the Executive Layer's cost
    tracking lands, and inventing a rate here would be the guess D-022 rejects.

    Args:
        request: The completion about to be issued.
        price_per_million_tokens_usd: Upper-bound price for one million tokens.

    Returns:
        The amount to hold, rounded up to the ledger's quantum.
    """
    prompt_bytes = sum(len(message.content.encode()) for message in request.messages)
    prompt_bytes += len((request.system or "").encode())
    worst_case_tokens = prompt_bytes + request.max_tokens
    return _price(worst_case_tokens, price_per_million_tokens_usd)


def reasoning_call_cost_usd(usage: Usage, *, price_per_million_tokens_usd: Decimal) -> Decimal:
    """Return one model call's settled cost from its reported tokens (D-022 point 3).

    D-022 finalizes a reservation "to actual cost". For a reasoning call the
    actual token counts come back from the provider, so the reservation settles
    against those rather than in full — the reservation's worst case exists to
    gate the pre-flight check, not to become the recorded spend.

    `Usage.cost_usd` is not used: no provider populates it, so trusting it would
    record every reasoning call as free.
    """
    return _price(usage.total_tokens, price_per_million_tokens_usd)


def _price(tokens: int, price_per_million_tokens_usd: Decimal) -> Decimal:
    """Return the cost of ``tokens`` at the configured bound, rounded up."""
    cost = Decimal(tokens) * price_per_million_tokens_usd / Decimal(1_000_000)
    return cost.quantize(MONEY, rounding=ROUND_UP)


@dataclass(frozen=True, slots=True)
class Reservation:
    """A held claim on budget, to be settled or released."""

    ledger_id: int
    business_id: BusinessId
    invocation_id: InvocationId | None
    cycle_id: str | None
    amount_usd: Decimal


class BudgetLedger:
    """Pre-flight ceiling enforcement and spend accounting (D-003, D-022)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        platform_ceiling_usd: Decimal,
        reservation_sessions: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Args:
        session: Active session, used for the read aggregates.
        platform_ceiling_usd: Rolling 24h platform ceiling (spec §9),
            owner-adjustable only.
        reservation_sessions: Factory for the reservation's own short
            transaction (D-022 point 1). Without it a reservation shares the
            caller's transaction and commits when the caller does, which is the
            M6-F12 race — the Kernel always supplies one, and
            `test_kernel_wires_reservation_transactions` keeps it that way. It
            stays optional so a single-session test can drive the ledger
            directly.
        """
        self._session = session
        self._platform_ceiling = platform_ceiling_usd
        self._reservation_sessions = reservation_sessions

    @asynccontextmanager
    async def _reservation_scope(self) -> AsyncGenerator[AsyncSession]:
        """Yield the session a reservation's own transaction runs in (D-022).

        Committed on exit, independently of whatever long-running activity
        transaction the caller is inside. That independence is the entire point:
        a hold that commits when the work finishes cannot gate the work.
        """
        if self._reservation_sessions is None:
            yield self._session
            return
        async with session_scope(self._reservation_sessions) as session:
            yield session

    async def reserve(
        self,
        *,
        contract: BusinessContract,
        amount_usd: Decimal,
        invocation_id: InvocationId | None = None,
        cycle_id: str | None = None,
        invocation_allocation_usd: Decimal | None = None,
    ) -> Reservation:
        """Check every enclosing ceiling under a per-scope lock, then hold the amount.

        Checks run outermost-last so the error names the tightest binding
        ceiling: an operator told "this company is out of budget" can act on it,
        where "the platform halted" would send them looking in the wrong place.

        Args:
            contract: The spending business's contract, carrying its ceilings.
            amount_usd: Amount to hold.
            invocation_id: Owning invocation, when this is capability spend.
            cycle_id: Owning wake cycle, for the §2.1 per-cycle ceiling.
            invocation_allocation_usd: This invocation's own allocation ceiling
                (spec §2.2), the innermost scope.

        Returns:
            The held reservation, already committed.

        Raises:
            BudgetExceededError: If any of the invocation, cycle, or business
                ceilings would be breached.
            CircuitBreakerOpenError: If the platform rolling 24h ceiling would
                be breached (spec §9).
        """
        if amount_usd < 0:
            msg = "cannot reserve a negative amount"
            raise ValueError(msg)

        # The §2.2 allocation compares two numbers the caller already holds, so
        # it is settled before taking any lock.
        if invocation_allocation_usd is not None and amount_usd > invocation_allocation_usd:
            raise BudgetExceededError(
                f"requested {amount_usd} exceeds invocation allocation "
                f"{invocation_allocation_usd} (spec §2.2)",
                scope="invocation",
            )

        async with self._reservation_scope() as session:
            await _serialize_scopes(session, business_id=contract.business_id, cycle_id=cycle_id)

            if cycle_id is not None:
                cycle_spend = await self._cycle_spend(session, cycle_id)
                ceiling = contract.budget.wake_cycle_ceiling_usd
                if cycle_spend + amount_usd > ceiling:
                    raise BudgetExceededError(
                        f"wake cycle {cycle_id} would reach {cycle_spend + amount_usd} "
                        f"against ceiling {ceiling} (spec §2.1)",
                        scope="wake_cycle",
                        operator_message=(
                            f"{contract.display_name} stopped early to stay in budget."
                        ),
                    )

            business_spend = await self._business_spend(session, contract.business_id)
            if business_spend + amount_usd > contract.budget.business_cap_usd:
                raise BudgetExceededError(
                    f"business {contract.business_id} would reach "
                    f"{business_spend + amount_usd} against cap "
                    f"{contract.budget.business_cap_usd} (D-003 rule 2)",
                    scope="business",
                    operator_message=f"{contract.display_name} hit its spending limit.",
                )

            platform_spend = await self._platform_spend_24h(session)
            if platform_spend + amount_usd > self._platform_ceiling:
                raise CircuitBreakerOpenError(
                    f"platform 24h spend would reach {platform_spend + amount_usd} "
                    f"against ceiling {self._platform_ceiling} (spec §9)",
                    scope="platform",
                )

            row = BudgetLedgerRow(
                business_id=contract.business_id,
                invocation_id=invocation_id,
                cycle_id=cycle_id,
                amount_usd=amount_usd,
                state=RESERVED,
            )
            session.add(row)
            await session.flush()
            ledger_id = row.id

        return Reservation(
            ledger_id=ledger_id,
            business_id=contract.business_id,
            invocation_id=invocation_id,
            cycle_id=cycle_id,
            amount_usd=amount_usd,
        )

    async def settle(self, reservation: Reservation, actual_usd: Decimal) -> None:
        """Convert a reservation to actual spend (D-022 point 3: terminality).

        Args:
            reservation: The held reservation.
            actual_usd: Actual cost. May be lower than reserved — the difference
                is returned to every ceiling. May not exceed the reservation:
                over-spending past a checked ceiling is the exact failure the
                pre-flight check exists to prevent, so it is refused rather than
                absorbed.

        Raises:
            BudgetExceededError: If ``actual_usd`` exceeds the reserved amount.
        """
        if actual_usd > reservation.amount_usd:
            raise BudgetExceededError(
                f"actual spend {actual_usd} exceeds reservation "
                f"{reservation.amount_usd}; ceilings were checked against the reservation",
                scope="invocation",
            )
        async with self._reservation_scope() as session:
            row = await session.get(BudgetLedgerRow, reservation.ledger_id)
            if row is None:  # pragma: no cover - reservation always exists
                msg = f"reservation {reservation.ledger_id} not found"
                raise ValueError(msg)
            row.amount_usd = actual_usd
            row.state = SETTLED
            await session.flush()

    async def release(self, reservation: Reservation) -> None:
        """Return an unspent reservation to every ceiling (D-022 point 3).

        Called when an invocation or reasoning call reaches a terminal state
        without spending — failed, cancelled, or dead-lettered. Without this,
        failed work would permanently consume headroom and a business would
        slowly strangle itself on spend that never happened. Terminality is what
        triggers it, never a timer: D-001 guarantees every invocation terminates,
        so no TTL heuristic is needed to find abandoned holds.
        """
        async with self._reservation_scope() as session:
            row = await session.get(BudgetLedgerRow, reservation.ledger_id)
            if row is None:  # pragma: no cover
                return
            row.state = RELEASED
            await session.flush()

    # ── aggregates ─────────────────────────────────────────────────────────

    async def business_spend(self, business_id: BusinessId) -> Decimal:
        """Return total reserved-plus-settled spend for one business."""
        return await self._business_spend(self._session, business_id)

    async def cycle_spend(self, cycle_id: str) -> Decimal:
        """Return total spend attributed to one wake cycle (spec §2.1)."""
        return await self._cycle_spend(self._session, cycle_id)

    async def platform_spend_24h(self, *, now: datetime | None = None) -> Decimal:
        """Return aggregate spend across all businesses in a rolling 24h window.

        Args:
            now: Injectable clock. Never read from the wall clock inside
                workflow code (D-004); activities pass an explicit value.
        """
        return await self._platform_spend_24h(self._session, now=now)

    @staticmethod
    async def _business_spend(session: AsyncSession, business_id: BusinessId) -> Decimal:
        stmt = (
            select(func.coalesce(func.sum(BudgetLedgerRow.amount_usd), 0))
            .where(BudgetLedgerRow.business_id == business_id)
            .where(BudgetLedgerRow.state.in_(_COUNTING_STATES))
        )
        return Decimal(str(await session.scalar(stmt) or 0))

    @staticmethod
    async def _cycle_spend(session: AsyncSession, cycle_id: str) -> Decimal:
        stmt = (
            select(func.coalesce(func.sum(BudgetLedgerRow.amount_usd), 0))
            .where(BudgetLedgerRow.cycle_id == cycle_id)
            .where(BudgetLedgerRow.state.in_(_COUNTING_STATES))
        )
        return Decimal(str(await session.scalar(stmt) or 0))

    @staticmethod
    async def _platform_spend_24h(session: AsyncSession, *, now: datetime | None = None) -> Decimal:
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        stmt = (
            select(func.coalesce(func.sum(BudgetLedgerRow.amount_usd), 0))
            .where(BudgetLedgerRow.recorded_at >= cutoff)
            .where(BudgetLedgerRow.state.in_(_COUNTING_STATES))
        )
        return Decimal(str(await session.scalar(stmt) or 0))
