"""Budget hierarchy tests (D-003, D-022; spec §2.1 / §2.2 / §5 / §9).

The concurrency half of D-022 is not here: it is a race between sessions, which
the in-memory SQLite fixture cannot stage. It lives in
`test_budget_reservation_concurrency.py` against the real Postgres.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.ledger import (
    BudgetLedger,
    reasoning_call_cost_usd,
    reasoning_call_reservation_usd,
)
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import BudgetExceededError, CircuitBreakerOpenError
from jarvis.kernel.ids import InvocationId
from jarvis.llm.base import CompletionRequest, Message, Role, Usage


def _ledger(session: AsyncSession, ceiling: str = "500.00") -> BudgetLedger:
    return BudgetLedger(session, platform_ceiling_usd=Decimal(ceiling))


async def test_reservation_counts_before_settlement(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Reservations gate the check, not settlements.

    Without this, two concurrent invocations could each pass a pre-flight check
    against the same headroom and then both spend it.
    """
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))
    assert await ledger.business_spend(contract.business_id) == Decimal("10.00")


async def test_invocation_allocation_is_the_innermost_ceiling(
    session: AsyncSession, contract: BusinessContract
) -> None:
    with pytest.raises(BudgetExceededError) as exc:
        await _ledger(session).reserve(
            contract=contract,
            amount_usd=Decimal("2.00"),
            invocation_allocation_usd=Decimal("0.50"),
        )
    assert exc.value.scope == "invocation"


async def test_wake_cycle_ceiling_enforced(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §2.1: a Manager cannot loop indefinitely within one wake cycle."""
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("0.90"), cycle_id="cycle-1")
    with pytest.raises(BudgetExceededError) as exc:
        await ledger.reserve(contract=contract, amount_usd=Decimal("0.50"), cycle_id="cycle-1")
    assert exc.value.scope == "wake_cycle"
    assert "stay in budget" in exc.value.operator_message


async def test_business_cap_halts_that_business_only(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-003 rule 2: per-business caps are the first line, not the breaker."""
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("49.00"))
    with pytest.raises(BudgetExceededError) as exc:
        await ledger.reserve(contract=contract, amount_usd=Decimal("5.00"))
    assert exc.value.scope == "business"
    assert "spending limit" in exc.value.operator_message


async def test_business_cap_trips_before_platform_breaker(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """The §9 / §10 reconciliation: one company cannot freeze the platform.

    With a platform ceiling below the business cap, a naive implementation would
    report the platform breaker. The ordering in D-003 means the business hears
    about its own limit first.
    """
    ledger = _ledger(session, ceiling="10.00")
    with pytest.raises(BudgetExceededError) as exc:
        await ledger.reserve(contract=contract, amount_usd=Decimal("60.00"))
    assert exc.value.scope == "business"


async def test_platform_breaker_is_the_outermost_ceiling(
    session: AsyncSession, contract: BusinessContract
) -> None:
    ledger = _ledger(session, ceiling="5.00")
    with pytest.raises(CircuitBreakerOpenError) as exc:
        await ledger.reserve(contract=contract, amount_usd=Decimal("6.00"))
    assert exc.value.scope == "platform"


async def test_settlement_below_reservation_returns_headroom(
    session: AsyncSession, contract: BusinessContract
) -> None:
    ledger = _ledger(session)
    reservation = await ledger.reserve(contract=contract, amount_usd=Decimal("10.00"))
    await ledger.settle(reservation, Decimal("2.00"))
    assert await ledger.business_spend(contract.business_id) == Decimal("2.00")


async def test_settlement_above_reservation_refused(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Overspending past a checked ceiling is the exact failure the pre-flight
    check exists to prevent, so it is refused rather than absorbed."""
    ledger = _ledger(session)
    reservation = await ledger.reserve(contract=contract, amount_usd=Decimal("1.00"))
    with pytest.raises(BudgetExceededError):
        await ledger.settle(reservation, Decimal("5.00"))


async def test_release_frees_headroom_for_failed_work(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Failed work must not permanently consume budget it never spent."""
    ledger = _ledger(session)
    reservation = await ledger.reserve(contract=contract, amount_usd=Decimal("40.00"))
    await ledger.release(reservation)
    assert await ledger.business_spend(contract.business_id) == Decimal("0")
    await ledger.reserve(contract=contract, amount_usd=Decimal("40.00"))


async def test_negative_reservation_rejected(
    session: AsyncSession, contract: BusinessContract
) -> None:
    with pytest.raises(ValueError, match="negative"):
        await _ledger(session).reserve(contract=contract, amount_usd=Decimal("-1"))


async def test_cycle_spend_is_scoped_to_its_cycle(
    session: AsyncSession, contract: BusinessContract
) -> None:
    ledger = _ledger(session)
    await ledger.reserve(contract=contract, amount_usd=Decimal("0.40"), cycle_id="a")
    await ledger.reserve(contract=contract, amount_usd=Decimal("0.30"), cycle_id="b")
    assert await ledger.cycle_spend("a") == Decimal("0.40")
    assert await ledger.cycle_spend("b") == Decimal("0.30")


async def test_reservation_ties_to_invocation_for_traceability(
    session: AsyncSession, contract: BusinessContract
) -> None:
    reservation = await _ledger(session).reserve(
        contract=contract,
        amount_usd=Decimal("1.00"),
        invocation_id=InvocationId("inv_1"),
    )
    assert reservation.invocation_id == "inv_1"


# ── D-022 point 2: what a reasoning call reserves (M6-F14) ─────────────────

PRICE = Decimal("50.00")


def _completion(prompt: str = "plan the next round", **over: object) -> CompletionRequest:
    base: dict[str, object] = {
        "messages": (Message(role=Role.USER, content=prompt),),
        "system": "you plan work",
    }
    base.update(over)
    return CompletionRequest(**base)  # type: ignore[arg-type]


def test_reservation_grows_with_the_calls_token_ceiling() -> None:
    """D-022: the amount is *derived* from the ceiling, not a fixed guess.

    A call permitted twice the output must hold more, or the reservation is a
    constant wearing a derivation's clothes.
    """
    small = reasoning_call_reservation_usd(
        _completion(max_tokens=1024), price_per_million_tokens_usd=PRICE
    )
    large = reasoning_call_reservation_usd(
        _completion(max_tokens=4096), price_per_million_tokens_usd=PRICE
    )
    assert large > small


def test_reservation_covers_the_prompt_as_well_as_the_reply() -> None:
    """The input side has no ceiling in the provider protocol, so it is bounded
    by the prompt itself — a longer prompt cannot cost the same."""
    short = reasoning_call_reservation_usd(_completion("hi"), price_per_million_tokens_usd=PRICE)
    long = reasoning_call_reservation_usd(
        _completion("hi" * 5000), price_per_million_tokens_usd=PRICE
    )
    assert long > short


def test_reservation_is_an_upper_bound_on_what_the_call_can_report() -> None:
    """The property the whole mechanism rests on: settlement can never exceed
    the hold, so a checked ceiling cannot be overrun after the fact.

    Bytes bound tokens because every token of a byte-pair tokenizer covers at
    least one byte — so the worst case really is a worst case, not an estimate.
    """
    prompt = "plan the next round of work for this company"
    request = _completion(prompt, max_tokens=256)
    reserved = reasoning_call_reservation_usd(request, price_per_million_tokens_usd=PRICE)

    worst_usage = Usage(
        input_tokens=len(prompt.encode()) + len(b"you plan work"),
        output_tokens=256,
    )
    assert reasoning_call_cost_usd(worst_usage, price_per_million_tokens_usd=PRICE) <= reserved


def test_settlement_uses_reported_tokens_not_the_worst_case() -> None:
    """D-022 point 3 finalizes to actual cost. The worst case gates the check;
    recording it as spend would charge every cycle for tokens it never used."""
    request = _completion("plan the next round", max_tokens=2048)
    reserved = reasoning_call_reservation_usd(request, price_per_million_tokens_usd=PRICE)
    settled = reasoning_call_cost_usd(
        Usage(input_tokens=40, output_tokens=60), price_per_million_tokens_usd=PRICE
    )
    assert Decimal("0") < settled < reserved


def test_a_free_looking_call_still_costs_something() -> None:
    """`Usage.cost_usd` is populated by no provider Jarvis has. Deriving from it
    would record every reasoning call as free and reopen M6-F14."""
    usage = Usage(input_tokens=1000, output_tokens=1000)
    assert usage.cost_usd == Decimal("0")
    assert reasoning_call_cost_usd(usage, price_per_million_tokens_usd=PRICE) > Decimal("0")


# ── D-022 point 1: the wiring that makes it real ───────────────────────────


async def test_kernel_gives_the_ledger_its_own_reservation_transactions() -> None:
    """Without this the ledger silently falls back to the caller's transaction,
    which is M6-F12 reopened with every test still green — the failure mode this
    project treats as a defect in its own right (M5-F5).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    kernel = PlatformKernel(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            llm=LLMSettings(model="configured-model", api_key="unused-in-this-test"),
        ),
        engine=engine,
        provider=_NoProvider(),  # type: ignore[arg-type]
    )
    async with kernel.services() as svc:
        ledger = kernel.build_ledger(svc)
    assert ledger._reservation_sessions is kernel.session_factory
    await engine.dispose()


class _NoProvider:
    """Provider that would fail loudly if this test ever called a model."""

    @property
    def name(self) -> str:
        return "none"

    async def complete(self, request: object) -> object:
        raise AssertionError("this test must not reach a provider")

    async def aclose(self) -> None:
        return None
