"""The Command Center's `/api/summary`: the portfolio census tile (design
EXECUTIVE-LAYER.md Part 3/8, D-039) and `platform_feed`'s first reader
(Part 8, M9-F2, M9-F76) — both packet M9-1d.

`compute_portfolio_health`'s own correctness (bands, never-measured, worst-
company tiebreak) is `tests/test_executive_health.py`'s territory and is not
re-proven here. This file is the thin wiring layer: does `/api/summary` shape
`kernel.portfolio_census`'s return into the JSON the tile reads, does it
resolve the worst company's id off the same roster read rather than teaching
the census package a new field, and does `_platform_halt_reason` surface the
halt narrative without ever naming its internal ref.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.budget.ledger import BudgetLedger
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.domain.contract import BusinessContract, KpiTarget
from jarvis.kernel.config import BudgetSettings, LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import new_decision_id
from jarvis.persistence.models import Base, DecisionLogRow


class _NoProvider:
    """No test here calls a model; this makes that an assertion."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("this surface never calls a model")

    async def aclose(self) -> None:
        return None


def _settings(ceiling: str = "500.00") -> Settings:
    return Settings(
        llm=LLMSettings(model="stub-model"),
        budget=BudgetSettings(platform_rolling_24h_usd=Decimal(ceiling)),
        _env_file=None,  # type: ignore[call-arg]
    )


async def _make_kernel(ceiling: str = "500.00") -> PlatformKernel:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PlatformKernel(  # type: ignore[arg-type,call-arg]
        _settings(ceiling), engine=engine, provider=_NoProvider()
    )


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    built = await _make_kernel()
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def api(kernel: PlatformKernel) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _add_completed_cycles(kernel: PlatformKernel, business_id: str, count: int) -> None:
    """The same shape `test_executive_health.py` uses to make a company
    'measured' without a real Manager cycle: a Decision Log entry is what
    `KpiEngine.completed_cycle_count` actually counts."""
    async with kernel.services() as svc:
        for n in range(count):
            svc.session.add(
                DecisionLogRow(
                    decision_id=f"dec_cc_{business_id}_{n}",
                    business_id=business_id,
                    cycle_id=f"cyc_cc_{business_id}_{n}",
                    summary="A round of work finished.",
                    rationale="Nothing more to do this round.",
                )
            )


async def test_census_names_nobody_when_the_portfolio_is_healthy_and_measured(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        business_id = str(
            await provisioning.create_company(definition=AFFILIATE, display_name="Weekend Reviews")
        )
    await _add_completed_cycles(kernel, business_id, 2)

    body = (await api.get("/api/summary")).json()

    assert body["census"] == {
        "healthy": 1,
        "watch": 0,
        "at_risk": 0,
        "never_measured": 0,
        "worst_company": None,
    }


async def test_census_reports_never_measured_separately_and_names_nobody(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """D-039's "one honest limitation": a freshly created company has zero
    recorded cycles — genuinely never measured, not evidence of health either
    way — and must not be folded into `healthy` on the tile any more than it
    is in `PortfolioHealth` itself."""
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        await provisioning.create_company(definition=AFFILIATE, display_name="Trailhead Gear")

    body = (await api.get("/api/summary")).json()

    assert body["census"]["healthy"] == 0
    assert body["census"]["never_measured"] == 1
    assert body["census"]["worst_company"] is None


async def test_census_names_the_worst_company_with_an_id_the_roster_recognises(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The census tile's link needs an id, and `PortfolioHealth` names only a
    display name (Part 1: a pure function over D-009's own reads, no new
    field for one caller) — `/api/summary` must resolve it off the same
    roster read rather than guessing or leaving the link dead."""
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        business_id = await provisioning.create_company(
            definition=AFFILIATE, display_name="Summit Trail Gear"
        )
        contract = await svc.registry.get_contract(business_id)
        payload = contract.model_dump()
        payload["kpi_targets"] = [
            KpiTarget(
                key="posts_published",
                operator_label="Posts published",
                target_value=Decimal("10"),
                unit="posts",
            ).model_dump()
        ]
        retargeted = BusinessContract.model_validate(payload)
        await svc.registry.refresh_contract(
            business_id, retargeted, audit_ref_payload={"reason": "test fixture"}
        )
    await _add_completed_cycles(kernel, str(business_id), 5)

    body = (await api.get("/api/summary")).json()

    assert body["census"]["watch"] == 1
    assert body["census"]["worst_company"] == {"id": str(business_id), "name": "Summit Trail Gear"}

    companies = (await api.get("/api/companies")).json()
    assert companies[0]["id"] == body["census"]["worst_company"]["id"], (
        "the census names an id the roster actually carries, so the tile's link "
        "and the card it points at agree on which company that is"
    )


async def test_spending_paused_reason_is_absent_when_nothing_is_paused(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    body = (await api.get("/api/summary")).json()
    assert body["spending_paused"] is False
    assert body["spending_paused_reason"] is None


async def test_spending_paused_reason_reads_platform_feed_without_naming_its_ref() -> None:
    """`platform_feed`'s first reader (M9-F2, M9-F76): once the breaker has
    actually tripped, `/api/summary` must carry the same "why" `CircuitBreaker.
    trip` wrote to the Decision Log — and never the structured `action_type`
    the reader used to recognise that entry, ref or not (M9-F76's finding is
    that an internal ref must never reach the operator, independent of
    whether anything renders it as a link).

    Self-contained (its own kernel, not the module fixtures): it needs a
    platform ceiling tight enough to trip, which the other tests in this file
    deliberately do not carry."""
    kernel = await _make_kernel("1.00")
    try:
        async with kernel.services() as svc:
            provisioning = kernel.build_provisioning(svc)
            await provisioning.install(AFFILIATE)
            business_id = await provisioning.create_company(
                definition=AFFILIATE, display_name="Weekend Reviews"
            )
            contract = await svc.registry.get_contract(business_id)
            # Reserved against a generously-ceilinged ledger sharing this same
            # session — `reserve` itself enforces the platform ceiling it is
            # given, and the point here is spend that has *already* crossed
            # the tight one, not a reservation attempt that would refuse at
            # the door. `platform_spend_24h` reads the stored rows themselves,
            # not the ceiling any particular ledger instance was built with.
            generous_ledger = BudgetLedger(svc.session, platform_ceiling_usd=Decimal("500.00"))
            await generous_ledger.reserve(contract=contract, amount_usd=Decimal("5.00"))
            breaker = kernel.build_breaker(svc)
            await breaker.trip(decision_id=new_decision_id(), spend_usd=Decimal("5.00"))

        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            body = (await client.get("/api/summary")).json()

        assert body["spending_paused"] is True
        reason = body["spending_paused_reason"]
        assert reason is not None
        assert "5.00" in reason and "1.00" in reason
        assert "platform.circuit_breaker" not in reason, (
            "the entry's internal ref must never reach the operator (M9-F76)"
        )
    finally:
        await kernel.aclose()
