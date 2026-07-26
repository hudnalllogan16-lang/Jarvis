"""`/api/health` exists under every topology that serves `create_app` (M6-5a
item 8: M6-5's false-red).

`jarvis/shell/launcher.py` registers its own, richer `/api/health` (it adds
Supervisor part statuses), but that only happens under the full developer
shell. `jarvis.api.server` — and any other caller of `create_app` directly —
served no such route at all, so the dashboard's health banner 404'd and read
"Jarvis isn't responding" even though everything else worked. This asserts
the route exists on the app `create_app` returns, independent of topology.
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
    """The exact bug: `create_app` alone (the `jarvis.api.server` topology)
    served no `/api/health` at all."""
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
