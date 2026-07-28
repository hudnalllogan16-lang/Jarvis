"""M9-2a: the kpi-series read endpoint.

design 13-company-workspace.md reserves the trend indicator until "a
per-company KPI series read" exists (`kpi_values` is a real append-only
series since D-027 and `KpiEngine.series()` already reads it, but no route
served it). This is that route: `GET /api/companies/{id}/kpi-series`, one
entry per contract `kpi_target`, `KpiEngine.series` reused verbatim — no new
query, no engine change, no client-side attainment.

Same fixture shape as `test_company_identity_and_goals.py`: the real API
(`create_app`) against a real Kernel and an in-memory database, no model
ever called.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from jarvis.persistence.models import Base, KpiValueRow


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


async def _record_at(
    kernel: PlatformKernel, business_id: str, key: str, value: str, when: datetime
) -> None:
    """Insert one observation with an explicit `recorded_at`.

    `KpiEngine.record` timestamps at insert time, which does not give a test
    enough control to prove ordering — two calls in the same test can land in
    the same microsecond on some backends. Writing the row directly (the same
    pattern `test_company_identity_and_goals.py`'s `_add_completed_cycles`
    uses for `DecisionLogRow`) makes the oldest-first assertion below actually
    prove something.
    """
    async with kernel.services() as svc:
        svc.session.add(
            KpiValueRow(business_id=business_id, key=key, value=Decimal(value), recorded_at=when)
        )
        await svc.session.flush()


# ── 404 unknown company ─────────────────────────────────────────────────────


async def test_404_for_unknown_company(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/companies/no-such-company/kpi-series")
    assert resp.status_code == 404


# ── one entry per contract kpi_target, label never key ─────────────────────


async def test_one_entry_per_contract_kpi_target(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """FINANCE ships three targets; the series read must answer for all three,
    not just the one the operator happens to have looked at."""
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    resp = await api.get(f"/api/companies/{business_id}/kpi-series")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 3
    assert {entry["label"] for entry in body} == {
        "Metrics tracked",
        "Data freshness",
        "Reports delivered",
    }


async def test_labels_never_keys(kernel: PlatformKernel, api: httpx.AsyncClient) -> None:
    """spec §12.5: the raw contract key must never reach the operator surface,
    only `operator_label`."""
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    resp = await api.get(f"/api/companies/{business_id}/kpi-series")
    body = resp.json()

    raw_keys = {"metrics_tracked", "data_freshness_hours", "reports_delivered"}
    labels = {entry["label"] for entry in body}
    assert labels.isdisjoint(raw_keys)
    assert "key" not in body[0]


async def test_entry_carries_unit_direction_and_target(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The BELOW-direction target proves `direction` is not hardcoded to the
    default (`_goal_readings`' own shape, reused verbatim)."""
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    body = (await api.get(f"/api/companies/{business_id}/kpi-series")).json()

    freshness = next(e for e in body if e["label"] == "Data freshness")
    assert freshness["unit"] == "hours since last check"
    assert freshness["direction"] == "below"
    assert freshness["target"] == 24.0


# ── points: [] never omitted; empty-vs-zero ─────────────────────────────────


async def test_points_is_empty_list_not_omitted_when_unmeasured(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    body = (await api.get(f"/api/companies/{business_id}/kpi-series")).json()

    assert len(body) == 1
    assert "points" in body[0]
    assert body[0]["points"] == []


async def test_a_real_zero_reading_is_a_point_not_emptiness(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The distinction the packet calls out by name: a target that was
    measured and came back zero must produce one point with `value: 0.0`,
    never an empty `points` list — that would misreport a real zero as
    "never measured", the exact confusion `KpiEngine.attainment` already
    guards against for the health score (D-020's `zero_attainment_stall`)."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    when = datetime(2026, 1, 1, tzinfo=UTC)
    await _record_at(kernel, business_id, "posts_published", "0", when)

    body = (await api.get(f"/api/companies/{business_id}/kpi-series")).json()

    assert len(body[0]["points"]) == 1
    assert body[0]["points"][0]["value"] == 0.0


# ── oldest-first ─────────────────────────────────────────────────────────────


async def test_points_are_oldest_first(kernel: PlatformKernel, api: httpx.AsyncClient) -> None:
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _record_at(kernel, business_id, "posts_published", "5", base)
    await _record_at(kernel, business_id, "posts_published", "8", base + timedelta(days=1))
    await _record_at(kernel, business_id, "posts_published", "12", base + timedelta(days=2))

    body = (await api.get(f"/api/companies/{business_id}/kpi-series")).json()
    points = body[0]["points"]

    assert [p["value"] for p in points] == [5.0, 8.0, 12.0]
    assert points[0]["when"] < points[1]["when"] < points[2]["when"]


# ── limit is bounded, not trusted ───────────────────────────────────────────


async def test_limit_bounds_how_many_points_return(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for n in range(5):
        await _record_at(kernel, business_id, "posts_published", str(n), base + timedelta(days=n))

    body = (await api.get(f"/api/companies/{business_id}/kpi-series?limit=2")).json()
    points = body[0]["points"]

    # Most recent 2, still oldest-first among themselves.
    assert [p["value"] for p in points] == [3.0, 4.0]


async def test_a_hostile_limit_does_not_500(kernel: PlatformKernel, api: httpx.AsyncClient) -> None:
    """`limit` is an operator-controlled query param; a negative or absurdly
    large value must clamp rather than reach `KpiEngine.series`'s SQL `LIMIT`
    unchecked."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")

    negative = await api.get(f"/api/companies/{business_id}/kpi-series?limit=-5")
    huge = await api.get(f"/api/companies/{business_id}/kpi-series?limit=999999999")

    assert negative.status_code == 200
    assert huge.status_code == 200


# ── opt-in: never on the default card list ──────────────────────────────────


async def test_series_is_a_dedicated_route_not_on_the_card_list(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    assert "kpi_series" not in companies[0]
    assert "points" not in companies[0]
