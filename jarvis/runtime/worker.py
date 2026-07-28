"""Temporal worker entrypoint (spec §2).

Hosts the Business Manager workflow and every activity it depends on. Also runs
the scheduler sweep, because §9's 24h and 7-day approval timers must fire whether
or not any Manager happens to be awake — and, since D-041 (design
EXECUTIVE-LAYER.md Part 7), the Executive's own deterministic tick, for the same
reason: rollup, census, cap alerts and the halt narrative must run whether or not
any Manager happens to be awake either. Composing it here rather than inside
`Scheduler.sweep` is not a style choice — `scheduler` is milestone 4 and
`executive` is milestone 9, so `Scheduler.sweep` calling into it would be a
forward import outside a composition root (`tests/test_layering.py`). This
module already is one, and is named as the Executive's home for exactly that
reason.
"""

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from jarvis.executive.runner import run_executive_tick
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.logging import get_logger
from jarvis.manager.activities import all_manager_activities
from jarvis.manager.workflow import BusinessManagerWorkflow
from jarvis.runtime.activities import all_activities
from jarvis.scheduler.service import Scheduler

logger = get_logger(__name__)


async def run_worker(kernel: PlatformKernel) -> None:
    """Run the Jarvis worker until cancelled.

    Args:
        kernel: Initialised Platform Kernel.
    """
    settings = kernel.settings
    # Every payload crossing the workflow/activity boundary is a pydantic model
    # (jarvis/manager/types.py). Temporal's default converter cannot encode one —
    # it fails on the first Decimal field — so a worker on the default converter
    # never runs a cycle (M6-F5). The converter must match on both client and
    # worker or a payload written by one is unreadable by the other.
    client = await Client.connect(
        settings.temporal.host,
        namespace=settings.temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal.task_queue,
        workflows=[BusinessManagerWorkflow],
        activities=[*all_activities(kernel), *all_manager_activities(kernel)],
    )
    logger.info(
        "worker starting",
        extra={"context": {"task_queue": settings.temporal.task_queue}},
    )
    await worker.run()


async def run_scheduler(kernel: PlatformKernel, *, interval_seconds: int = 300) -> None:
    """Run the platform timer sweep on a loop (spec §9).

    Deliberately outside the workflow layer: the sweep is deterministic
    bookkeeping with no reasoning in it, and §2.1 and §3 reserve workflows for
    things that reason.

    A failed sweep is logged and retried on the next tick rather than killing
    the loop — an approval that expires five minutes late is a nuisance, but a
    scheduler that stops means approvals never expire at all.
    """
    scheduler = Scheduler(kernel)
    while True:
        try:
            report = await scheduler.sweep()
            if report.renotified or report.expired or report.woken or report.reservations_released:
                logger.info(
                    "sweep complete",
                    extra={
                        "context": {
                            "renotified": report.renotified,
                            "expired": report.expired,
                            "woken": report.woken,
                            # D-034.3: budget headroom returned to its ceilings.
                            # In the trigger as well as the context, so a sweep
                            # whose only work was reconciliation still says so.
                            "reservations_released": report.reservations_released,
                        }
                    },
                )
        except Exception:
            logger.exception("sweep failed; retrying next tick")
        await asyncio.sleep(interval_seconds)


async def run_executive(kernel: PlatformKernel, *, interval_seconds: int | None = None) -> None:
    """Run the Executive Layer's deterministic tick on a loop (D-041, packet D).

    One asyncio timer, never a workflow (nothing here replays, D-004) and
    never `Scheduler.sweep` (the module docstring explains why). Each tick
    opens its own Kernel-scoped transaction — never reused across ticks, so a
    long-lived session cannot drift from what a concurrent request just
    committed — and builds every collaborator the same way every other Kernel
    caller does.

    **M9-F78 resolved here, not upstream.** `platform_ceiling_usd` is read
    from `Settings.budget.platform_rolling_24h_usd` exactly once per tick and
    handed to the rollup; `kernel.build_breaker` reads the identical setting
    for the breaker it constructs (`jarvis/kernel/container.py`). One
    Settings value, two consumers, the same way `PlatformKernel.build_ledger`
    and `build_breaker` already share it for every other caller — no second
    source is introduced here.

    **Tick failure is contained, same family as `run_scheduler` above
    (M6-F9's contained-failure discipline applied to a timer rather than a
    workflow activity): logged, and the next tick is unaffected.** A failed
    rollup this minute is a nuisance; a loop that dies on the first
    transient DB hiccup means cap alerts and the halt narrative never fire
    again until something restarts the process.

    **No tick overlap.** This loop awaits each tick to completion — success
    or contained failure — before sleeping and starting the next one, the
    same shape `run_scheduler` already uses. Nothing here schedules a second
    tick while the first is still running.

    Args:
        kernel: Initialised Platform Kernel.
        interval_seconds: Overrides `Settings.executive.tick_interval_seconds`
            when given — tests use this to avoid a real sleep; production
            leaves it None and the configured cadence applies.
    """
    interval = (
        interval_seconds
        if interval_seconds is not None
        else kernel.settings.executive.tick_interval_seconds
    )
    while True:
        try:
            async with kernel.services() as services:
                await run_executive_tick(
                    registry=services.registry,
                    ledger=kernel.build_ledger(services),
                    kpi=kernel.build_kpis(services),
                    notifications=kernel.build_notifications(services),
                    breaker=kernel.build_breaker(services),
                    decisions=services.decisions,
                    platform_ceiling_usd=kernel.settings.budget.platform_rolling_24h_usd,
                )
        except Exception:
            logger.exception("executive tick failed; retrying next tick")
        await asyncio.sleep(interval)


async def main() -> None:
    """Console entrypoint: run the worker, the scheduler, and the Executive together."""
    kernel = PlatformKernel(Settings())  # type: ignore[call-arg]
    await kernel.ensure_builtin_types()
    try:
        await asyncio.gather(run_worker(kernel), run_scheduler(kernel), run_executive(kernel))
    finally:
        await kernel.aclose()


if __name__ == "__main__":
    asyncio.run(main())
