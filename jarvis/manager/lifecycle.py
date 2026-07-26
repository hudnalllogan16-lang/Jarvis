"""Manager workflow lifecycle (spec §2.1, §0.1).

§2.1 requires each business to have exactly one Business Manager. The
architecture states the invariant; nothing said *when* the workflow starts, and
until now nothing started it — an ACTIVE business had no Manager at all.

Started here, on `business.activated`, rather than inside the Registry: §0.1
makes the Registry bookkeeping infrastructure, and reaching into the workflow
runtime is not bookkeeping. The Registry publishes; this listens.

Exactly-one is enforced by Temporal rather than by a check. The workflow id is
derived from the business id (`bm-{business_id}`), so a second start attempt is
an id collision the server rejects. A check-then-start would race.
"""

from __future__ import annotations

from jarvis.domain.lifecycle import LifecycleState
from jarvis.events.types import BUSINESS_ACTIVATED
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessId
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import business_workflow_id
from jarvis.manager.state import KpiTargetState, ManagerState

logger = get_logger(__name__)

CONSUMER_ID = "manager-lifecycle"
"""Bus consumer identity. Deduplication is per consumer (A-002), so a redelivered
activation cannot start a second Manager."""


class ManagerLifecycle:
    """Starts and stops Manager workflows in step with lifecycle state."""

    def __init__(self, kernel: PlatformKernel) -> None:
        """Args:
        kernel: Platform Kernel supplying sessions and the Temporal client.
        """
        self._kernel = kernel

    async def reconcile(self) -> int:
        """Ensure every ACTIVE business has a running Manager.

        Reconciliation rather than pure event handling: an event consumed while
        the worker was down would otherwise leave a business permanently
        Manager-less, and §2.1's invariant would hold on paper only. Starting an
        already-running Manager is a no-op by workflow-id collision, so this is
        safe to run on every sweep.

        Returns:
            How many Managers were started.
        """
        client = await self._kernel.temporal_client()
        if client is None:
            return 0

        started = 0
        async with self._kernel.services() as svc:
            # Drain activations so the bus does not accumulate; the authority
            # for what should be running is the Registry, not the backlog.
            await self._kernel.build_bus(svc).claim(CONSUMER_ID, [BUSINESS_ACTIVATED])

            for row in await svc.registry.list_instances(state=LifecycleState.ACTIVE):
                business_id = BusinessId(row.business_id)
                contract = await svc.registry.get_contract(business_id)
                state = ManagerState(
                    business_id=business_id,
                    kpi_targets=tuple(
                        KpiTargetState(
                            key=target.key,
                            target_value=target.target_value,
                            operator_label=target.operator_label,
                        )
                        for target in contract.kpi_targets
                    ),
                )
                if await self._start(client, business_id, state):
                    started += 1
        return started

    async def _start(self, client: object, business_id: BusinessId, state: ManagerState) -> bool:
        """Start one Manager, treating an existing one as success."""
        from temporalio.client import WorkflowFailureError

        try:
            await client.start_workflow(  # type: ignore[attr-defined]
                "BusinessManager",
                state,
                id=business_workflow_id(business_id),
                task_queue=self._kernel.settings.temporal.task_queue,
            )
        except Exception as exc:
            # An already-running Manager is the desired state, not an error.
            if "already" in str(exc).lower() or isinstance(exc, WorkflowFailureError):
                return False
            logger.warning(
                "could not start manager",
                extra={"context": {"business_id": business_id, "error": type(exc).__name__}},
            )
            return False
        logger.info("manager started", extra={"context": {"business_id": business_id}})
        return True

    async def stop(self, business_id: BusinessId) -> None:
        """Terminate a Manager whose business is no longer ACTIVE.

        Called on retirement. Pausing does *not* stop the Manager: D-008 I-1
        cancels wake timers but lets an in-flight cycle finish, and a paused
        Manager parked on `wait_condition` costs nothing while remaining ready
        to resume.
        """
        client = await self._kernel.temporal_client()
        if client is None:
            return
        try:
            handle = client.get_workflow_handle(business_workflow_id(business_id))
            await handle.terminate("business retired")
        except Exception:
            logger.info("no manager to stop", extra={"context": {"business_id": business_id}})
