"""Preflight checks and health reporting.

Every check returns a `ComponentHealth` rather than raising, because the shell's
job is to start what it can and *say clearly* what it could not. A launcher that
dies on the first unreachable service teaches the developer to read stack
traces; one that starts degraded and shows a banner teaches them where to look.

Diagnoses are written in the same register as the rest of the operator surface
(§12.5): what it means and what to do, not which exception fired. The exception
text is kept as `detail` for the drill-down.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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


class Posture(StrEnum):
    """What a caller does when preflight says the platform cannot serve (M10-F15).

    An interactive command and an unattended service must answer a missing
    database differently, and the difference is a parameter of one bootstrap
    rather than a fork of it (design OPERATIONAL-RUNTIME.md 1.4): a developer
    who typed a command is present to read the ladder and fix it, while a
    service that exits because it started three seconds before Postgres has
    outsourced a dependency-ordering problem to its restarter and every later
    symptom gets reported as "the restart loop".

    Lives here rather than beside `bootstrap` because `jarvis/shell/service.py`
    is an entrypoint root: `tests/test_layering.py::test_entrypoint_roots_hold_no_logic`
    keeps those files free of type definitions, and a posture is a value the
    preflight result is interpreted against.
    """

    REFUSE = "refuse"
    """Print the ladder and stop. The console (`jarvis`)."""

    WAIT = "wait"
    """Retry preflight indefinitely; a dependency that is still starting is not
    a reason to give up. The service (`jarvis-run`)."""


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


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Overall system health."""

    components: tuple[ComponentHealth, ...] = field(default_factory=tuple)

    @property
    def can_serve(self) -> bool:
        """Return whether the API and dashboard can run at all.

        Only the database is truly load-bearing: without it there is nothing to
        show. Everything else degrades.
        """
        return all(c.status is not Status.DOWN for c in self.components if c.name == "database")

    @property
    def fully_operational(self) -> bool:
        """Return whether every component is OK."""
        return all(c.status is Status.OK for c in self.components)

    def to_payload(self) -> dict[str, object]:
        """Serialise for the /api/health endpoint."""
        return {
            "ok": self.fully_operational,
            "can_serve": self.can_serve,
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "summary": c.summary,
                    "remedy": c.remedy,
                }
                for c in self.components
            ],
        }


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


async def check_temporal(kernel: PlatformKernel) -> ComponentHealth:
    """Check the workflow runtime is reachable.

    Down Temporal is DEGRADED, not DOWN: the dashboard, approvals, and company
    management all work without it — companies just can't wake up and act, and
    the shell must say exactly that.
    """
    client = await kernel.temporal_client()
    if client is None:
        return ComponentHealth(
            "workflows",
            Status.DEGRADED,
            "Companies can't act right now — the part that runs them isn't reachable.",
            remedy="Check `docker compose ps`; the temporal service may still be starting.",
        )
    return ComponentHealth("workflows", Status.OK, "Companies can run.")


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


async def run_preflight(kernel: PlatformKernel) -> HealthReport:
    """Run every check concurrently and return the report."""
    database, temporal = await asyncio.gather(check_database(kernel), check_temporal(kernel))
    return HealthReport(components=(database, temporal, check_llm(kernel)))
