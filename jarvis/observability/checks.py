"""Shared preflight/health check questions (M6-F44, M9-F155, packet DEBT-1).

`jarvis/shell/preflight.py` (the bootstrap path, M5) and `jarvis/api/app.py`'s
`/api/health` route (M3) grew parallel answers to the same questions —
is the database reachable, is the workflow runtime reachable, is a model
configured — because `jarvis.api` could never import `jarvis.shell` without
violating `tests/test_layering.py`'s forward-import rule (M3 < M5) and nobody
wanted to promote `jarvis.api` past `jarvis.shell`'s milestone just to share
three functions. `jarvis.observability` is M1: both `jarvis.shell` (M5) and
`jarvis.api` (M3) may import a milestone at or before their own, so a check
homed here is reachable from both without moving anything else. This module
holds the *question* — one pure/async function per check, returning a
`ComponentHealth` rather than raising. Each caller keeps its own *rendering*
of the answer (preflight's exit codes and WAIT posture; the health route's
component narrative) exactly as it was; only the answer itself is now one
implementation.

`check_database_reachable` is split out from `check_database` because the
two current callers do not, in fact, ask the same depth of question:
`jarvis/shell/preflight.py::check_database` asks "reachable, and separately,
migrated"; `/api/health` has only ever asked "reachable" (M6-F44's own
docstring calling them "the same three checks" was already slightly wrong —
the health route never ran the schema probe). Extending `/api/health` to ask
the migration question too would be a new check for that route, which packet
DEBT-1's boundary rules out; instead the shared, provably-identical half is
the connectivity probe, and `check_database` layers preflight's own
migration probe on top of it, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text

from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)


class Status(StrEnum):
    """Health of one component."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """One component's status with a plain-language diagnosis."""

    name: str
    status: Status
    summary: str
    """What this means for the developer, one sentence."""

    remedy: str = ""
    """What to do about it, when there is something to do."""

    detail: str = ""
    """The underlying error text. Drill-down only."""


async def check_database_reachable(kernel: PlatformKernel) -> ComponentHealth | None:
    """Run the connectivity probe only. Return a DOWN component on failure,
    or `None` on success so a caller can decide what "reachable" means next.

    This is the half of `check_database` that both `jarvis/shell/preflight.py`
    and `jarvis/api/app.py`'s `/api/health` route ask today; see the module
    docstring for why the migration probe stays out of this function.
    """
    try:
        async with kernel.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        return ComponentHealth(
            "database",
            Status.DOWN,
            "Jarvis can't reach its database.",
            remedy="Is Docker running? `docker compose up -d` starts everything.",
            detail=str(exc)[:300],
        )
    return None


async def check_database(kernel: PlatformKernel) -> ComponentHealth:
    """Check the database is reachable, and separately, whether it's migrated.

    These are two different failures and must be distinguished by what was
    being attempted, never by matching an exception's message or class name.

    A prior version tried to recognise "table doesn't exist yet" by checking
    for ``"UndefinedTable"`` in the exception's class name and ``"no such
    table"`` in its text. Both are SQLite-shaped assumptions: on Postgres,
    SQLAlchemy wraps the driver error in ``ProgrammingError`` (so the class
    name never matches) and the message reads "relation ... does not exist"
    (so the text never matches either). The result was every fresh Postgres
    database — the normal state on a first-ever launch, before migrations
    have run — being reported DOWN instead of DEGRADED. The launcher then
    retried a check that could never pass, silently, for two minutes, and
    exited without ever starting the dashboard.

    Fixed by structure instead of string-matching: a failure on ``SELECT 1``
    is a real connectivity problem (DOWN, whatever the underlying error says).
    A failure on the schema probe — reached only after connectivity already
    succeeded — can only mean "reachable, not migrated yet" (DEGRADED), and
    that is true regardless of which driver, wrapper, or wording produced it.
    """
    down = await check_database_reachable(kernel)
    if down is not None:
        return down

    try:
        async with kernel.session_factory() as session:
            result = await session.execute(text("SELECT count(*) FROM business_instances"))
            result.scalar()
    except Exception as exc:
        return ComponentHealth(
            "database",
            Status.DEGRADED,
            "The database is reachable but not set up yet.",
            remedy="Migrations will be applied automatically.",
            detail=str(exc)[:300],
        )
    return ComponentHealth("database", Status.OK, "Database is ready.")


def workflows_component(client: object | None) -> ComponentHealth:
    """Build the "workflows" component from an already-resolved Temporal client.

    Split out from `check_temporal` so a caller that also needs the client
    for something else (`jarvis/api/app.py`'s `/api/health` reuses it for the
    worker-poller probe) resolves it exactly once. `PlatformKernel.temporal_client`
    caches on success but retries the connection attempt — and repeats its
    warning log — on every call while down, so calling it a second time here
    would silently double both when Temporal is unreachable.
    """
    if client is None:
        return ComponentHealth(
            "workflows",
            Status.DEGRADED,
            "Companies can't act right now — the part that runs them isn't reachable.",
            remedy="Check `docker compose ps`; the temporal service may still be starting.",
        )
    return ComponentHealth("workflows", Status.OK, "Companies can run.")


async def check_temporal(kernel: PlatformKernel) -> ComponentHealth:
    """Check the workflow runtime is reachable.

    Down Temporal is DEGRADED, not DOWN: the dashboard, approvals, and company
    management all work without it — companies just can't wake up and act, and
    the shell must say exactly that.
    """
    client = await kernel.temporal_client()
    return workflows_component(client)


def check_llm(kernel: PlatformKernel) -> ComponentHealth:
    """Check LLM configuration without spending a token, or leaving the process.

    Shape only: is there a key, is a model named. Whether the named model is one
    the provider actually serves is M9-F118's question and is deliberately *not*
    asked here — this function runs on every `/api/health` poll, and a live
    catalog read per poll would put an outbound request behind the one surface
    an operator watches while the provider is down. That check belongs to
    startup, runs once, and lives in `jarvis/llm/validation.py`; the worker
    (`jarvis/runtime/worker.py`) is what acts on its verdict.
    """
    try:
        kernel.settings.llm.require_api_key()
    except Exception as exc:
        return ComponentHealth(
            "thinking",
            Status.DEGRADED,
            "Companies can't think yet — no model key is configured.",
            remedy="Set JARVIS_LLM__API_KEY in .env, or use ollama for local-only.",
            detail=str(exc)[:300],
        )
    if not kernel.settings.llm.model:
        return ComponentHealth(
            "thinking",
            Status.DEGRADED,
            "No model is configured.",
            remedy="Set JARVIS_LLM__MODEL in .env.",
        )
    return ComponentHealth("thinking", Status.OK, "Model is configured.")
