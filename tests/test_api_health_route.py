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

from datetime import UTC, datetime

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.approvals.rendering import contains_technical_language
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.observability.heartbeat import HeartbeatStore, RuntimeIdentity
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
        assert {c["name"] for c in body["components"]} == {
            "database",
            "workflows",
            "thinking",
            "runtime",
            "workers",
        }
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


async def test_health_components_carry_no_internal_vocabulary() -> None:
    """§12.5 static guard, scoped to `/api/health` (P0-H).

    Nothing previously scanned this route's *assembled* response — which is
    exactly how the "temporal service" leak in `workflows_component`'s
    remedy (`jarvis/observability/checks.py`) shipped unnoticed until this
    packet flagged and fixed it. `contains_technical_language` reuses the
    one FORBIDDEN list every other surface is already checked against
    (`test_executive_liveness.py`, `test_operator_language.py`) — "temporal"
    is already on it, so this closes the gap by pointing the same guard at
    a surface it never reached, rather than inventing a second list.

    "postgres"/"redis" are backend datastore names in the same class as
    "temporal" but nothing currently emits them, so they are not added to
    the shared FORBIDDEN list (that would widen every other surface's scan
    for a term with no live occurrence) — checked directly here instead,
    where a health route is exactly the place such a name would leak from
    next. "docker" is deliberately not checked: `docker compose up -d`/`ps`
    are the operator's own deployment commands on a self-hosted product,
    already shipped in the database remedy (checks.py) — user-facing
    tooling, not an internal mechanism name.
    """
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        body = response.json()
        assert body["components"], "nothing to check — the route's shape changed"
        for component in body["components"]:
            for field in ("summary", "remedy"):
                text = component[field]
                assert not contains_technical_language(text), (
                    f"{component['name']}.{field} leaks forbidden vocabulary: {text!r}"
                )
                lowered = text.lower()
                for term in ("postgres", "redis"):
                    assert term not in lowered, (
                        f"{component['name']}.{field} names a backend datastore: {text!r}"
                    )
    finally:
        await kernel.aclose()


async def test_thinking_check_names_the_model_remedy_not_the_key_remedy() -> None:
    """M10-F40: a key set but no model named must remedy the model, not the
    key — the api's inline copy (`jarvis/api/app.py`) had drifted onto the
    key remedy for this case, which `jarvis/observability/checks.py::
    check_llm` (the DEBT-1 unification's reference implementation) already
    had right. Pins the corrected text so the two cannot drift again
    unnoticed; the two checks stay hand-kept duplicates for now (DEBT-1's
    flagged, not-yet-decided fold)."""
    kernel = await _kernel()
    kernel.settings.llm.api_key = SecretStr("fake-key")
    kernel.settings.llm.model = ""
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        body = response.json()
        thinking = next(c for c in body["components"] if c["name"] == "thinking")
        assert thinking["status"] == "degraded"
        assert thinking["summary"] == "No model is configured."
        assert thinking["remedy"] == "Set JARVIS_LLM__MODEL in .env.", (
            "the model-missing case must not print the API-key remedy (M10-F40)"
        )
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


async def test_health_route_reports_runtime_down_with_no_heartbeat_rows() -> None:
    """M10-F2: even api-only (no Supervisor) must answer honestly — a
    platform that has never reported a heartbeat is `down`, not silent."""
    kernel = await _kernel()
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        runtime = next(c for c in response.json()["components"] if c["name"] == "runtime")
        assert runtime["status"] == "down"
    finally:
        await kernel.aclose()


async def test_health_route_reports_runtime_ok_with_a_fresh_beat() -> None:
    kernel = await _kernel()
    try:
        identity = RuntimeIdentity(
            runtime_id="r1", hostname="h", pid=1, started_at=datetime.now(UTC)
        )
        async with kernel.services() as svc:
            store = HeartbeatStore(svc.session)
            for part in ("api", "worker", "scheduler", "executive"):
                await store.beat(identity, part_name=part, state="running")

        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        runtime = next(c for c in response.json()["components"] if c["name"] == "runtime")
        assert runtime["status"] == "ok"
    finally:
        await kernel.aclose()
