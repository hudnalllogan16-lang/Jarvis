"""`/api/health` exists under every topology that serves `create_app` (M6-5a
item 8: M6-5's false-red), and reports real Supervisor parts under the
launcher topology (M10-F1).

Before M10-F1's fix, `jarvis/shell/launcher.py` registered a *second*,
richer `/api/health` route (it added Supervisor part statuses) on top of the
app `create_app` already returned. Starlette matches routes in registration
order and `create_app`'s route — registered first — always won, so the
launcher's route was permanently dead code and `parts` was `[]` under every
topology, including the one topology with real parts to report. M9-7's
docstring claim that a rejected model shows "Company runner — restarting"
in the health banner was false as shipped.

`create_app` now takes an optional `parts_provider`; the launcher supplies
one backed by `Supervisor.statuses()` instead of registering a competing
route, so there is exactly one `/api/health` route under every topology.
`test_health_route_exists_without_the_shell_topology` pins the honest
api-only behaviour (no supervisor exists, so `parts` stays truthfully
empty — not faked); `test_health_route_reports_supervisor_parts_under_the_launcher_topology`
pins the previously-dead behaviour by reproducing the launcher's actual
wiring — a `parts_provider` closure — rather than a competing route.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.persistence.models import Base


class _NoProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("the health route calls no model")

    async def aclose(self) -> None:
        return None


async def _kernel() -> PlatformKernel:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    return PlatformKernel(settings, engine=engine, provider=_NoProvider())  # type: ignore[arg-type]


async def test_health_route_exists_without_the_shell_topology() -> None:
    """The exact M6-5a bug: `create_app` alone (the `jarvis.api.server`
    topology, and any other caller that supplies no `parts_provider`) served
    no `/api/health` at all.

    `parts == []` here is the honest api-only answer, not a fake: this
    topology runs no Supervisor, so there is nothing to report and the route
    must not pretend otherwise."""
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["components"], list)
        assert {c["name"] for c in body["components"]} == {"database", "workflows", "thinking"}
        assert body["parts"] == []
    finally:
        await kernel.aclose()


async def test_health_route_reports_supervisor_parts_under_the_launcher_topology() -> None:
    """M10-F1: pins the fix, not just the symptom.

    Reproduces `jarvis/shell/launcher.py::_serve_api`'s actual wiring — a
    `parts_provider` closure handed to `create_app` — rather than the old,
    permanently-shadowed second route. Two things must both hold: exactly one
    `/api/health` route exists (the regression was registration-order
    shadowing between two routes at the same path, so counting routes is the
    part of the fix a response-body assertion alone would miss), and the
    served response actually carries the supplied parts.
    """
    kernel = await _kernel()
    try:
        supplied_parts: list[dict[str, object]] = [
            {"name": "Company runner", "state": "restarting", "restarts": 3},
            {"name": "Dashboard", "state": "running", "restarts": 0},
        ]
        app = create_app(kernel, parts_provider=lambda: supplied_parts)

        health_routes = [r for r in app.routes if getattr(r, "path", None) == "/api/health"]
        assert len(health_routes) == 1, "exactly one /api/health route; no shadowing pair"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["parts"] == supplied_parts
    finally:
        await kernel.aclose()


async def test_health_route_reports_the_database_as_ok_when_reachable() -> None:
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        database = next(c for c in response.json()["components"] if c["name"] == "database")
        assert database["status"] == "ok"
    finally:
        await kernel.aclose()
