"""`/api/ready` (design OPERATIONAL-RUNTIME.md Part 3.4, D-059, M10-F16, packet P0-B).

Readiness gates rather than explains: no narrative, no components, 200 or 503
with one short reason. Distinct from `/api/health`'s own suite
(`tests/test_api_health_route.py`) because the two routes are deliberately
answering different questions and must never be tested as if they answer the
same one.
"""

from __future__ import annotations

import pathlib
import re

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import MIGRATION_HEAD_REVISION, create_app
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.persistence.models import Base


class _NoProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("the readiness route calls no model")

    async def aclose(self) -> None:
        return None


async def _kernel(*, migrated: bool = True, installed: bool = True) -> PlatformKernel:
    """A kernel over an in-memory database, with the readiness gates dialled
    independently so each test can fail exactly one of them.

    `alembic_version` is not part of `Base.metadata` (Alembic owns and
    stamps it itself in production); it is created by hand here, the same
    way a real `alembic upgrade head` would leave it, so `/api/ready`'s
    schema-at-head check has something honest to read.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if migrated:
            await conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": MIGRATION_HEAD_REVISION},
            )
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    kernel = PlatformKernel(settings, engine=engine, provider=_NoProvider())  # type: ignore[arg-type]
    if installed:
        report = await kernel.ensure_builtin_types()
        assert report.installed, "the built-in catalog must install for the 'ready' case to be real"
    return kernel


async def test_ready_returns_200_when_every_gate_passes() -> None:
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 200
        assert response.json() == {"ready": True}
    finally:
        await kernel.aclose()


async def test_ready_returns_503_when_the_schema_is_not_migrated() -> None:
    """No `alembic_version` table at all — a database that has never migrated."""
    kernel = await _kernel(migrated=False)
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["reason"]
    finally:
        await kernel.aclose()


async def test_ready_returns_503_when_the_schema_is_behind_head() -> None:
    kernel = await _kernel()
    try:
        async with kernel.session_factory() as session:
            await session.execute(text("UPDATE alembic_version SET version_num = '0001'"))
            await session.commit()
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 503
        assert response.json()["reason"] == "the database schema is behind"
    finally:
        await kernel.aclose()


async def test_ready_returns_503_when_builtin_types_are_not_installed() -> None:
    kernel = await _kernel(installed=False)
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 503
        assert response.json()["reason"] == "company templates aren't installed yet"
    finally:
        await kernel.aclose()


async def test_ready_returns_503_when_a_supervised_part_is_not_running() -> None:
    kernel = await _kernel()
    try:
        parts = [{"name": "Dashboard", "state": "restarting", "restarts": 1}]
        transport = httpx.ASGITransport(app=create_app(kernel, parts_provider=lambda: parts))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 503
        assert response.json()["reason"] == "still starting"
    finally:
        await kernel.aclose()


async def test_ready_returns_200_when_every_part_is_running() -> None:
    kernel = await _kernel()
    try:
        parts = [{"name": "Dashboard", "state": "running", "restarts": 0}]
        transport = httpx.ASGITransport(app=create_app(kernel, parts_provider=lambda: parts))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 200
    finally:
        await kernel.aclose()


async def test_ready_ignores_parts_when_no_parts_provider_is_given() -> None:
    """Design Part 6, Mode 4 (console-only attach): no local Supervisor, so
    "every part in RUNNING" is vacuously true — there is nothing here to ask."""
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/ready")
        assert response.status_code == 200
    finally:
        await kernel.aclose()


def test_migration_head_constant_matches_the_newest_migration_file() -> None:
    """Keeps `MIGRATION_HEAD_REVISION` from drifting silently from reality —
    the same discipline `KNOWN_M130_EXCEPTIONS` uses for its own hand-kept value."""
    versions = pathlib.Path("migrations/versions").glob("*.py")
    numbers = [int(m.group(1)) for p in versions if (m := re.match(r"(\d+)_", p.name))]
    assert numbers, "no migrations found under migrations/versions"
    assert f"{max(numbers):04d}" == MIGRATION_HEAD_REVISION
