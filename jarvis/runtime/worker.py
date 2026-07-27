"""Temporal worker entrypoint (spec §2).

Hosts the Business Manager workflow and every activity it depends on. Also runs
the scheduler sweep, because §9's 24h and 7-day approval timers must fire whether
or not any Manager happens to be awake.
"""

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

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


async def main() -> None:
    """Console entrypoint: run the worker and the scheduler together."""
    kernel = PlatformKernel(Settings())  # type: ignore[call-arg]
    await kernel.ensure_builtin_types()
    try:
        await asyncio.gather(run_worker(kernel), run_scheduler(kernel))
    finally:
        await kernel.aclose()


if __name__ == "__main__":
    asyncio.run(main())
