"""M7-5a: a company's kind survives creation, and its goals are askable.

The M7-5 product verdict (REVISE) found two things invisible on the operator
surface once a company exists: what *kind* of company it is (all three live
companies rendered identically — the Finance sentence "it places no trades
and moves no money" never reached the operator who most needs to read it),
and `health_parts` — the plain-language KPI components the API has computed
on every card request since M7-3b, consumed by nothing in the repository.

These tests exercise the real API (`create_app`) against a real Kernel and a
real (in-memory) database, the same shape as `test_activation_path.py`'s route
tests — no model is ever called, so a stub provider that raises on `complete`
keeps that true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.finance import FINANCE
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessId
from jarvis.kpi.engine import KpiEngine
from jarvis.persistence.models import Base


class _NoProvider:
    """No test here calls a model; this makes that an assertion."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("this surface never calls a model")

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    """`_env_file=None`: the repository holds a real `.env`, and a test that
    read it would reach a live provider."""
    return Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        _env_file=None,
    )


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(_settings(), engine=engine, provider=_NoProvider())  # type: ignore[arg-type]
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def api(kernel: PlatformKernel) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _create(kernel: PlatformKernel, definition, name: str) -> str:  # type: ignore[no-untyped-def]
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(definition)
        business_id = await provisioning.create_company(definition=definition, display_name=name)
        return str(business_id)


# ── item 1: a company's kind survives creation ─────────────────────────────


async def test_the_card_names_the_companys_kind(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The M7-5 verdict's own example: every company card looked identical."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    assert len(companies) == 1
    assert companies[0]["kind"] == AFFILIATE.display_name
    assert companies[0]["kind_description"] == AFFILIATE.description


async def test_finance_companys_read_only_sentence_reaches_details(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """Details must carry the sentence an owner most needs on a Finance
    company: it places no trades and moves no money."""
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert detail["kind"] == "Finance tracker"
    assert "places no trades and moves no money" in detail["kind_description"]


async def test_two_kinds_of_company_are_visibly_different(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The verdict's defect exactly: two companies of different kinds must
    not read the same. Only two built-in types exist, so this is the whole
    space of "different kind" pairs available without a third type."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    await _create(kernel, FINANCE, "Portfolio Watch")
    companies = {c["name"]: c for c in (await api.get("/api/companies")).json()}

    assert companies["Weekend Reviews"]["kind"] != companies["Portfolio Watch"]["kind"]
    assert (
        companies["Weekend Reviews"]["kind_description"]
        != (companies["Portfolio Watch"]["kind_description"])
    )


# ── item 2 / item 5: health_parts render, honestly labelled ────────────────


async def test_health_parts_uses_the_honest_label(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """M7-F60: "Finishing its work" is invocation-based, not useful-output —
    renamed rather than left to imply a metric that does not exist."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    parts = companies[0]["health_parts"]
    assert "Rounds completed" in parts
    assert "Finishing its work" not in parts
    assert set(parts) == {"Budget left", "Rounds completed", "Hitting its goals"}


# ── item 2: the goals drill-down ────────────────────────────────────────────


async def test_goals_drill_down_shows_measured_against_target(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The operator can see what was measured against what (M7-5 verdict item
    2) — not just a bare "60" with no unit and no goal beside it."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    async with kernel.services() as svc:
        await KpiEngine(svc.session).record(
            business_id=BusinessId(business_id), key="posts_published", value=Decimal("5")
        )

    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert detail["goals"] == [
        {
            "label": "Posts published",
            "measured": 5.0,
            "target": 20.0,
            "unit": "posts/month",
            "direction": "above",
        }
    ]


async def test_goals_drill_down_says_not_measured_yet_before_any_observation(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """A target with no recorded value yet must read as "not measured", not
    as a false zero — a company one hour old has not failed its goal."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert detail["goals"][0]["measured"] is None
    assert detail["goals"][0]["target"] == 20.0


async def test_goals_drill_down_is_opt_in_not_on_the_default_card(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """§12.5: drill-down loads only when the operator opens it. The card list
    is the default view, so it must not carry the per-metric breakdown."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    assert "goals" not in companies[0]
