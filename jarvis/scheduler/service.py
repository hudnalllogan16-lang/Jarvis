"""Scheduler (spec §2.1 wake conditions, §9 timers).

Two jobs, both of which existed as capability without a caller until now.

**Wake conditions (§2.1).** Schedule-based waking is a Temporal timer inside the
Manager workflow itself, so it needs nothing here. Event-based waking does: this
service drains the event bus and signals the Managers that subscribed, which is
what turns "capability result returned" or "approval decision received" from a
configured string into an actual wake.

**Platform timers (§9).** Approvals must be re-notified after 24 hours and
auto-paused after 7 days. Milestone 3 implemented both rules and left them
dormant because nothing ran on a timer. This is that timer.

The sweep is deliberately a plain async service rather than a workflow. It is
deterministic bookkeeping over rows, has no reasoning in it, and running it as a
workflow would put a scheduled loop in the workflow layer for no benefit — §2.1
and §3 reserve that layer for things that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.container import KernelServices, PlatformKernel
from jarvis.kernel.errors import JarvisError
from jarvis.kernel.ids import BusinessId, new_decision_id, new_notification_id
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import business_workflow_id
from jarvis.manager.lifecycle import ManagerLifecycle
from jarvis.notifications.service import NotificationKind, NotificationService

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one sweep did. Returned so a caller can log or assert on it."""

    renotified: int = 0
    expired: int = 0
    paused: tuple[str, ...] = ()
    woken: int = 0
    managers_started: int = 0


class Scheduler:
    """Drives platform timers and event-based Manager wakes."""

    def __init__(self, kernel: PlatformKernel) -> None:
        """Args:
        kernel: Platform Kernel supplying sessions and services.
        """
        self._kernel = kernel

    async def sweep(self, *, now: datetime | None = None) -> SweepReport:
        """Run one full pass: re-notify, expire, pause, wake.

        Args:
            now: Injectable clock, so timer behaviour is testable without
                waiting a real week.

        Returns:
            A report of what changed.
        """
        moment = now or datetime.now(UTC)
        async with self._kernel.services() as svc:
            renotified = await self._renotify(svc, moment)
            expired, paused = await self._expire_and_pause(svc, moment)
        # Reconcile before dispatching: signalling a Manager that was never
        # started is a silent no-op, and a business created while the worker was
        # down would otherwise stay Manager-less indefinitely (§2.1).
        started = await ManagerLifecycle(self._kernel).reconcile()
        woken = await self.dispatch_events()
        return SweepReport(
            renotified=renotified,
            expired=expired,
            paused=paused,
            woken=woken,
            managers_started=started,
        )

    async def _renotify(self, svc: KernelServices, now: datetime) -> int:
        """Re-notify approvals unanswered for 24 hours (spec §9)."""
        approvals = self._kernel.build_approvals(svc)
        notifications = NotificationService(svc.session)
        due = await approvals.due_for_renotification(now=now)

        for row in due:
            contract = await svc.registry.get_contract(BusinessId(row.business_id))
            await notifications.notify(
                notification_id=new_notification_id(),
                kind=NotificationKind.REMINDER,
                title=f"{contract.display_name} is still waiting on you",
                body=(
                    f"{row.action_summary.capitalize()} — this has been waiting a day. "
                    "Nothing happens until you decide."
                ),
                business_id=BusinessId(row.business_id),
                link_ref=row.approval_id,
            )
            await approvals.mark_notified(row.approval_id, now=now)
        return len(due)

    async def _expire_and_pause(
        self, svc: KernelServices, now: datetime
    ) -> tuple[int, tuple[str, ...]]:
        """Expire 7-day-old approvals and pause their businesses (spec §9).

        §9 requires auto-pause and explicitly never auto-approve, so expiry is a
        refusal. Pausing is done here rather than inside the approval service
        because the Registry owns lifecycle transitions (§0.1) — the approval
        service returns which businesses to pause and this coordinates it.
        """
        approvals = self._kernel.build_approvals(svc)
        notifications = NotificationService(svc.session)

        business_ids = await approvals.expire_stale(decision_id=new_decision_id(), now=now)
        paused: list[str] = []
        for business_id in dict.fromkeys(business_ids):
            state = await svc.registry.get_state(BusinessId(business_id))
            if state is not LifecycleState.ACTIVE:
                continue
            try:
                await svc.registry.transition(
                    BusinessId(business_id),
                    LifecycleState.PAUSED,
                    decision_id=new_decision_id(),
                    reason=(
                        "A request waited a week without an answer, so Jarvis paused "
                        "this company rather than assuming yes."
                    ),
                    actor="platform",
                )
            except JarvisError:
                # A concurrent operator pause is not an error; the desired end
                # state is already reached.
                continue
            paused.append(business_id)
            contract = await svc.registry.get_contract(BusinessId(business_id))
            await notifications.notify(
                notification_id=new_notification_id(),
                kind=NotificationKind.PAUSED,
                title=f"{contract.display_name} is paused",
                body=(
                    "A request went unanswered for a week. Jarvis never assumes yes, "
                    "so the company paused until you decide."
                ),
                business_id=BusinessId(business_id),
            )
        return len(business_ids), tuple(paused)

    async def dispatch_events(self) -> int:
        """Deliver bus events to the Managers that subscribed (spec §2.1).

        Each business's configured `event_triggers` are its subscription, and
        the event bus deduplicates per consumer (A-002), so a redelivered event
        cannot produce a second wake.

        Returns:
            How many Managers were signalled.
        """
        client = await self._kernel.temporal_client()
        if client is None:
            return 0

        woken = 0
        async with self._kernel.services() as svc:
            bus = self._kernel.build_bus(svc)
            for row in await svc.registry.list_instances(state=LifecycleState.ACTIVE):
                contract = await svc.registry.get_contract(BusinessId(row.business_id))
                triggers = sorted(contract.wake_conditions.event_triggers)
                if not triggers:
                    continue
                # Scoped to this business: `event_triggers` says which *types*
                # wake it, never that another company's events do (spec §10).
                events = await bus.claim(
                    row.business_id, triggers, business_id=BusinessId(row.business_id)
                )
                if not events:
                    continue
                handle = client.get_workflow_handle(
                    business_workflow_id(BusinessId(row.business_id))
                )
                for event in events:
                    signal = (
                        "approval_decided" if event.event_type.startswith("approval.") else "wake"
                    )
                    payload = (
                        str(event.payload.get("approval_id", ""))
                        if signal == "approval_decided"
                        else event.event_type
                    )
                    await handle.signal(signal, payload)
                    woken += 1
        return woken
