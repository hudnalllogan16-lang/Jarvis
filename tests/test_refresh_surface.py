"""The operator API surface packet M8-9 owns: the pending-update seam on a
company's Details route, its consent routes, and `not_ready_count` wired to a
real caller (M8-F61).

The contract-refresh mechanism itself (`plan_refresh`/`apply_refresh`, design
PLUGIN-FRAMEWORK.md Part 4.4) is packet M8-8's and had not merged into this
lane at the time this packet ran (see the M8-9 report). `_pending_update` in
`jarvis/api/app.py` is therefore a seam that always answers "no pending
update" today — which design Part 4.3 makes today's status quo for every
company, so it is the correct default rather than a placeholder trick. These
tests pin that seam's current, honest behaviour and the consent routes'
until-M8-8-lands response, so a change to either is a visible diff rather
than a silent regression.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
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
    return Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]


async def _make_kernel(builtin_types: Any = None) -> PlatformKernel:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PlatformKernel(  # type: ignore[arg-type,call-arg]
        _settings(), engine=engine, provider=_NoProvider(), builtin_types=builtin_types
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


async def _create(kernel: PlatformKernel, definition: BusinessTypeDefinition, name: str) -> str:
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(definition)
        business_id = await provisioning.create_company(definition=definition, display_name=name)
        return str(business_id)


# ── the pending-update seam ─────────────────────────────────────────────────


async def test_a_freshly_created_company_has_no_pending_update(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """Today's honest answer for every company (see module docstring): the
    mechanism that would detect a Band-B drift is not wired into this lane."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert "pending_update" in detail
    assert detail["pending_update"] is None


async def test_pending_update_is_not_on_the_default_card(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """§12.5: drill-down loads only when the operator opens it — the card
    list must not carry it, the same rule `goals` already follows."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    assert "pending_update" not in companies[0]


# ── consent routes: honest until M8-8 lands ─────────────────────────────────


async def test_applying_a_pending_update_says_its_not_ready_yet(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    res = await api.post(f"/api/companies/{business_id}/pending-update/apply")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert isinstance(detail, str) and detail
    assert "ready" in detail.lower()


async def test_dismissing_a_pending_update_says_its_not_ready_yet(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    res = await api.post(f"/api/companies/{business_id}/pending-update/dismiss")

    assert res.status_code == 409
    assert isinstance(res.json()["detail"], str)


async def test_applying_a_pending_update_for_an_unknown_company_is_404(
    api: httpx.AsyncClient,
) -> None:
    """Never a 409 for a company that doesn't exist — that would say "not
    ready yet" about something that was never there at all."""
    res = await api.post("/api/companies/biz_nonexistent/pending-update/apply")
    assert res.status_code == 404


async def test_dismissing_a_pending_update_for_an_unknown_company_is_404(
    api: httpx.AsyncClient,
) -> None:
    res = await api.post("/api/companies/biz_nonexistent/pending-update/dismiss")
    assert res.status_code == 404


# ── not_ready_count wired to a real caller (M8-F61) ─────────────────────────


async def test_install_builtin_reports_a_contained_failure_by_count() -> None:
    """M8-F61: `not_ready_count` had no UI consumer. `newco.js`'s
    `install-templates` action now reads it (see the M8-9 report); this pins
    the JSON shape that consumer depends on, at the HTTP boundary rather than
    only at the container level `test_builtin_type_installation.py` already
    covers.
    """
    poisoned_templates = dict(AFFILIATE.prompt_templates)
    del poisoned_templates["affiliate.operations"]
    poisoned = BusinessTypeDefinition.model_validate(
        AFFILIATE.model_dump(mode="json") | {"prompt_templates": poisoned_templates}
    )
    kernel = await _make_kernel(builtin_types=(poisoned, FINANCE))
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api:
            res = await api.post("/api/company-templates/install-builtin")
            body = res.json()
            assert body["not_ready_count"] == 1
            assert body["status"] == "Some templates aren't ready."
            assert body["installed"] == [FINANCE.name]
    finally:
        await kernel.aclose()


async def test_install_builtin_reports_zero_when_everything_installs(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    res = await api.post("/api/company-templates/install-builtin")
    body = res.json()

    assert body["not_ready_count"] == 0
    assert body["status"] == "Templates ready."
