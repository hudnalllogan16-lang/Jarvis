"""Preflight checks and health reporting.

Every check returns a `ComponentHealth` rather than raising, because the shell's
job is to start what it can and *say clearly* what it could not. A launcher that
dies on the first unreachable service teaches the developer to read stack
traces; one that starts degraded and shows a banner teaches them where to look.

Diagnoses are written in the same register as the rest of the operator surface
(§12.5): what it means and what to do, not which exception fired. The exception
text is kept as `detail` for the drill-down.

The checks themselves (`Status`, `ComponentHealth`, `check_database`,
`check_temporal`, `check_llm`) now live in `jarvis/observability/checks.py`
(M6-F44, M9-F155, packet DEBT-1): `jarvis/api/app.py`'s `/api/health` route
asks the same three questions and, being M3, can never import this M5 module
without violating `tests/test_layering.py` — so the one shared implementation
had to move down to `jarvis.observability` (M1), reachable from both. Imported
back here so every existing caller of `jarvis.shell.preflight` keeps working
unchanged; `Posture`, `HealthReport`, and `run_preflight` stay in this module
because they are preflight's own aggregation and posture, not a question
either surface asks twice.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.logging import get_logger
from jarvis.observability.checks import (
    ComponentHealth,
    Status,
    check_database,
    check_llm,
    check_temporal,
)

logger = get_logger(__name__)


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


async def run_preflight(kernel: PlatformKernel) -> HealthReport:
    """Run every check concurrently and return the report."""
    database, temporal = await asyncio.gather(check_database(kernel), check_temporal(kernel))
    return HealthReport(components=(database, temporal, check_llm(kernel)))
