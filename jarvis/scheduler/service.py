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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.container import KernelServices, PlatformKernel
from jarvis.kernel.errors import JarvisError
from jarvis.kernel.ids import BusinessId, new_decision_id, new_notification_id
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import business_workflow_id
from jarvis.manager.lifecycle import ManagerLifecycle
from jarvis.notifications.service import NotificationKind, NotificationService
from jarvis.persistence.models import BudgetLedgerRow, DeadLetterRow

logger = get_logger(__name__)

ORPHANED_RESERVATION_AGE = timedelta(hours=1)
"""How old a held reservation must be before age alone releases it (D-034.3).

The backstop, not the mechanism. Terminality is the mechanism — D-022 point 3
resolves a hold when its invocation reaches a terminal state, and that is right
for every case where a terminal result arrives. Process death is the case where
none does, and no evidence of it survives either: the dead worker's transaction
never committed, so there is no dead-letter row and no audit entry to read
terminality off. Something has to bound the hold, and an age is the only fact
left.

One hour, against a longest legitimate hold of fifteen minutes — a reservation
lives inside one activity, and `DISPATCH_TIMEOUT` bounds the longest of them
(`jarvis/manager/workflow.py`). Four times the bound, because releasing a *live*
reservation is the one outcome this sweep must never produce: it would hand a
running invocation's headroom to a concurrent one and reopen M6-F12 from the
other side. `tests/test_reservation_reconcile.py` pins the margin against the
timeout constants themselves, so raising a timeout cannot silently make this
number unsafe."""

MAX_RECONCILED_PER_SWEEP = 200
"""Bound on one sweep's reconciliation work.

The sweep runs on a timer beside the §9 approval timers, so it has to finish in
a predictable amount of time whatever the backlog. Oldest-first ordering makes a
bounded pass the right kind of incomplete: it always releases the orphans that
have been costing headroom longest, and the remainder wait one sweep."""


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one sweep did. Returned so a caller can log or assert on it."""

    renotified: int = 0
    expired: int = 0
    paused: tuple[str, ...] = ()
    woken: int = 0
    managers_started: int = 0
    reservations_released: int = 0
    """Orphaned budget holds returned to their ceilings (D-034.3, M6-F18)."""


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
            released = await self._reconcile_reservations(svc, moment)
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
            reservations_released=released,
        )

    async def _reconcile_reservations(self, svc: KernelServices, now: datetime) -> int:
        """Release orphaned budget holds and audit every one (D-034.3, M6-F18).

        D-022 point 3 rides D-001: every invocation terminates, so a terminal
        result is what resolves a reservation and no TTL heuristic is needed to
        find abandoned holds. That is true of every invocation the platform
        finishes and false of one whose worker died mid-flight — the settle and
        the release both live in the process that stopped. The hold then counts
        against the cycle, the business, and the platform ceiling forever, and
        the business loses that headroom permanently while spending nothing.

        Owned by the scheduler because it is deterministic bookkeeping over rows
        with no reasoning in it — the same argument this module's docstring makes
        for the §9 timers, and the reason D-012 keeps this out of the workflow
        layer. It runs here rather than in the ledger for a second reason: the
        ledger has no idea whether an invocation is finished, and finding out
        means reading the dead-letter queue, which belongs to the pool.

        Two grounds, terminality first:

        1. **The invocation reached a terminal state.** A dead-lettered
           invocation's release is supposed to have happened already
           (`CapabilityPool._execute_with_retry` releases *before* it writes the
           dead-letter row), so a row still RESERVED beside a dead letter is a
           release that did not land. Success needs no rule here for the same
           ordering reason inverted: `settle` commits before the
           `capability.succeeded` entry is written, so a settled invocation
           cannot leave a held row behind — and releasing a *successful*
           invocation's hold would erase spend that really happened, which is the
           one direction D-003 rule 1 must never be wrong in.
        2. **Age**, past `ORPHANED_RESERVATION_AGE` — the backstop for the case
           that leaves no evidence at all.

        Every release is audited in this same transaction (see
        `BudgetLedger.release_reconciled`), because a hold that returns to a
        ceiling with no record of why is exactly the kind of unexplained
        headroom §11 exists to prevent.

        Args:
            svc: The sweep's session-scoped services.
            now: Injectable clock, so the age bound is testable.

        Returns:
            How many reservations were released.
        """
        ledger = self._kernel.build_ledger(svc)
        held = await ledger.open_reservations(limit=MAX_RECONCILED_PER_SWEEP)
        if not held:
            return 0

        invocations = {row.invocation_id for row in held if row.invocation_id}
        terminal: set[str] = set()
        if invocations:
            terminal = set(
                (
                    await svc.session.scalars(
                        select(DeadLetterRow.invocation_id).where(
                            DeadLetterRow.invocation_id.in_(invocations)
                        )
                    )
                ).all()
            )

        released = 0
        for row in held:
            reason = self._orphan_reason(row, now=now, terminal=terminal)
            if reason is None:
                continue
            # Audited before the row changes, in the same transaction as the
            # change: neither is visible unless both are.
            await svc.audit.record(
                event_type="budget.reservation_reconciled",
                actor="platform",
                business_id=BusinessId(row.business_id),
                payload={
                    "invocation_id": row.invocation_id,
                    "cycle_id": row.cycle_id,
                    "amount_usd": str(row.amount_usd),
                    "reason": reason,
                    "held_since": row.recorded_at.isoformat(),
                },
            )
            await ledger.release_reconciled(row)
            released += 1

        if released:
            logger.warning(
                "released orphaned budget reservations",
                extra={"context": {"released": released, "examined": len(held)}},
            )
        return released

    @staticmethod
    def _orphan_reason(row: BudgetLedgerRow, *, now: datetime, terminal: set[str]) -> str | None:
        """Return why this held reservation is an orphan, or None if it is live.

        Returning None for anything it cannot prove is the whole safety posture:
        an in-flight invocation's hold is what stops a sibling from spending the
        same headroom twice (D-022 point 1), so a sweep that guessed would
        reintroduce M6-F12 by another route.
        """
        if row.invocation_id and row.invocation_id in terminal:
            return "invocation reached a terminal state"

        recorded_at = row.recorded_at
        if recorded_at.tzinfo is None:
            # SQLite hands back naive what Postgres stores with an offset; the
            # rows are written from `datetime.now(UTC)` either way (the same
            # dialect gap `AuditLog.latest_entry_time` documents). Said rather
            # than assumed, because the alternative is a TypeError in the one
            # dialect the suite runs on.
            recorded_at = recorded_at.replace(tzinfo=UTC)
        if now - recorded_at >= ORPHANED_RESERVATION_AGE:
            return "held past the age bound with no terminal result"
        return None

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
