"""The platform's long-lived parts (spec §2): the worker, the sweep, the tick.

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

**This is where parts are composed, not where a process is defined** (design
OPERATIONAL-RUNTIME.md 1.2, packet P0-A). `main()` — a bare `asyncio.gather`
over the three run loops, which SETUP.md called the production topology — is
**deleted**, along with `python -m jarvis.runtime.worker`. It ran the parts with
no supervision, so a crash ended that part silently for the life of the process,
and it was a second opinion about what the platform runs. The three loops below
are unchanged: they are the parts, they are good, and the one place that
composes them into a runtime is `jarvis/shell/service.py::build_supervisor`.
The composition-root exemption this module keeps is for the Executive tick
(D-041), which is the object graph it still builds.
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from jarvis.executive.runner import run_executive_tick
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.errors import ConfigurationError
from jarvis.kernel.logging import get_logger
from jarvis.llm.validation import ModelVerdict, verify_configured_model
from jarvis.manager.activities import all_manager_activities
from jarvis.manager.workflow import BusinessManagerWorkflow
from jarvis.observability.heartbeat import HeartbeatStore
from jarvis.observability.poller import UNREACHABLE_POLLER_READING, PollerReading
from jarvis.runtime.activities import all_activities
from jarvis.scheduler.service import Scheduler

logger = get_logger(__name__)


async def run_worker(kernel: PlatformKernel) -> None:
    """Run the Jarvis worker until cancelled.

    Refuses to start against a model the configured provider does not offer
    (M9-F118). The verdict is `jarvis/llm/validation.py`'s; what a verdict does
    to startup is decided here, because that is a fact about this topology
    rather than about the provider — this process is the one that runs
    companies, and a company that cannot think cannot do anything else either.

    **A rejection stops this part and nothing else.** Under the launcher the
    worker is a supervised part (`jarvis/shell/supervisor.py`): raising here
    shows the operator "Company runner — restarting" with a crash count in the
    health banner, logs the reason once per attempt at a backoff that caps at a
    minute, and leaves the dashboard, the activity feed and the approvals queue
    serving throughout. That is the loud-but-contained failure the incident
    asked for — the silent alternative is what M9-F118 was.

    An unverifiable model is a warning and the worker starts. A provider that
    is down is exactly when an operator most needs the read surfaces, and
    refusing to run companies because a *catalog* could not be read would
    manufacture an outage out of a failed diagnostic.

    Args:
        kernel: Initialised Platform Kernel.

    Raises:
        ConfigurationError: If the provider's own list says it does not serve
            the configured model.
    """
    settings = kernel.settings
    check = await verify_configured_model(kernel.llm, settings.llm.model)
    if check.verdict is ModelVerdict.REJECTED:
        logger.error(
            "refusing to start: the configured model is not one this provider offers",
            extra={"context": {"provider": settings.llm.provider.value, "detail": check.detail}},
        )
        raise ConfigurationError(check.detail, operator_message=check.summary)
    if check.verdict is ModelVerdict.UNVERIFIED:
        logger.warning(
            "could not confirm the configured model; starting anyway",
            extra={"context": {"provider": settings.llm.provider.value, "detail": check.detail}},
        )

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


async def probe_task_queue_pollers(client: Any, task_queue: str) -> PollerReading:
    """Read design 3.2's Signal 2 — `DescribeTaskQueue` for both queue types.

    The probe design 3.3 says is "built by the composition root and handed
    to the Executive tick as a value" — this is that function, and its
    result is the value. It is also importable by `jarvis/api/app.py` (M3,
    earlier than nothing this file touches — an ordinary backward import,
    no composition-root exemption needed) for `/api/health`'s `workers`
    component, so both readers of Signal 2 share one implementation rather
    than two copies of a protobuf-shaped comparison drifting apart.

    Two requests, not one: `DescribeTaskQueueRequest.task_queue_type` is
    singular, and design 3.2 asks for "the workflow and activity queue
    types" — the legacy per-type shape every Temporal SDK version speaks,
    rather than the newer plural `task_queue_types` field this platform's
    pinned SDK version may or may not report pollers for identically.

    **Never raises.** Any failure here — including a Temporal that answers
    but does not recognise the queue — reads as `UNREACHABLE_POLLER_READING`
    (design 3.2: unreachable is `unknown`, never `zero`), so one bad probe
    cannot take an entire Executive tick down with it (the same contained-
    failure posture `run_scheduler`/`run_executive` already hold their own
    loops to).

    Args:
        client: A connected `temporalio.client.Client` (or any object
            exposing the same `workflow_service.describe_task_queue`, for
            tests — never type-imported as `Client` here so a caller does
            not have to construct a real one to satisfy a signature).
        task_queue: `settings.temporal.task_queue`.

    Returns:
        A reading covering both queue types, or the unreachable sentinel.
    """
    try:
        workflow_response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace,
                task_queue=TaskQueue(name=task_queue),
                task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                report_pollers=True,
            )
        )
        activity_response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace,
                task_queue=TaskQueue(name=task_queue),
                task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
                report_pollers=True,
            )
        )
    except Exception:
        logger.warning("could not probe task queue pollers; liveness reads as unknown")
        return UNREACHABLE_POLLER_READING

    newest = None
    for poller in (*workflow_response.pollers, *activity_response.pollers):
        if not poller.HasField("last_access_time"):
            continue
        at = poller.last_access_time.ToDatetime(tzinfo=UTC)
        if newest is None or at > newest:
            newest = at

    return PollerReading(
        reachable=True,
        workflow_pollers=len(workflow_response.pollers),
        activity_pollers=len(activity_response.pollers),
        newest_last_access_at=newest,
    )


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

    **The poller probe, read once per tick (design 3.3, packet P0-C).**
    `kernel.temporal_client()` is the same cached client `/api/health`'s
    `workflows` component already uses — a second connection is not opened
    here. `None` (Temporal unreachable) reads as `UNREACHABLE_POLLER_READING`
    rather than skipping the probe, so the verdict still runs and correctly
    renders "unknown" (design 3.2) instead of silently omitting Signal 2 for
    this tick.

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
            client = await kernel.temporal_client()
            if client is None:
                poller = UNREACHABLE_POLLER_READING
            else:
                poller = await probe_task_queue_pollers(client, kernel.settings.temporal.task_queue)
            async with kernel.services() as services:
                await run_executive_tick(
                    registry=services.registry,
                    ledger=kernel.build_ledger(services),
                    kpi=kernel.build_kpis(services),
                    notifications=kernel.build_notifications(services),
                    breaker=kernel.build_breaker(services),
                    decisions=services.decisions,
                    heartbeat=HeartbeatStore(services.session),
                    audit=services.audit,
                    poller=poller,
                    platform_ceiling_usd=kernel.settings.budget.platform_rolling_24h_usd,
                    heartbeat_stale_after_seconds=kernel.settings.heartbeat.heartbeat_stale_after_seconds,
                    poller_stale_after_seconds=kernel.settings.heartbeat.poller_stale_after_seconds,
                    part_failing_after_crashes=kernel.settings.heartbeat.part_failing_after_crashes,
                )
        except Exception:
            logger.exception("executive tick failed; retrying next tick")
        await asyncio.sleep(interval)
