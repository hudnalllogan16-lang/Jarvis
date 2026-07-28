"""Approval service and autonomy ladder (spec §8, §9).

Three rules from §8 are enforced here rather than left to callers:

1. Approval is required by default. `requires_approval` returns True for any
   action type with no configured policy — absence of configuration is never
   permission.
2. Graduation needs an unbroken streak of clean approvals. A denial *or a
   correction* resets it to zero. v1.4 never defines "correction"; A-003 defines
   it as an approval where the operator changed the parameters, which is the
   reading that protects the operator — silently counting an edited approval as
   an endorsement of the original would graduate an action the human actually
   rejected.
3. Trade execution and direct capital movement are never eligible for
   graduation in v1. That is a hard constraint, so it is checked against the
   action itself as well as its policy: a policy misconfigured as eligible
   cannot graduate an action that moves money.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalRequest, ApprovalState
from jarvis.domain.contract import BusinessContract
from jarvis.events.bus import Event, EventBus
from jarvis.events.types import APPROVAL_DECIDED
from jarvis.kernel.errors import JarvisError
from jarvis.kernel.ids import BusinessId, DecisionId, EventId, new_event_id
from jarvis.kernel.logging import get_logger
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import (
    ApprovalRow,
    AutonomyCounterRow,
    BusinessInstanceRow,
    BusinessTypeRow,
)

logger = get_logger(__name__)

RENOTIFY_AFTER = timedelta(hours=24)
"""Spec §9: pending approvals MUST trigger re-notification after 24 hours."""

AUTO_PAUSE_AFTER = timedelta(days=7)
"""Spec §9: unresolved after 7 days MUST auto-pause, never auto-approve."""

APPROVAL_EXPIRED_ACTION_TYPE = "platform.approval_expired"
"""`action_type` on the Decision Log entry :meth:`ApprovalService.expire_stale`
writes. Exported (the same shape as `jarvis.budget.breaker.
PLATFORM_HALT_ACTION_TYPE`) so a reader elsewhere can recognise this entry by
identifier rather than repeating the literal — `tests/test_action_registry.py`
treats a second bare occurrence of a governed action string as an undeclared
emit site, and `jarvis.api.app` needs to recognise this one to know its text
is platform fixed-copy, never live synthesis (M9-9 product REVISE item 4)."""


class ApprovalError(JarvisError):
    """An approval could not be created or decided."""

    default_operator_message = "That approval isn't available anymore."


class ApprovalService:
    """Creates, decides, and expires approval requests (spec §8, §9)."""

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditLog,
        decisions: DecisionLog,
        bus: EventBus | None = None,
    ) -> None:
        """Args:
        session: Active session.
        audit: Audit log (spec §11).
        decisions: Decision Log (spec §11.5) — an approval outcome is a
            business decision and owes the operator a readable record.
        bus: Event bus (spec §2). Required in production: without it the
            decision is recorded but the Manager that raised the request is
            never woken, and the business stops permanently (D-006). Optional
            only so unit tests can exercise ladder arithmetic in isolation;
            `tests/test_event_loop_closure.py` asserts the wired path.
        """
        self._session = session
        self._audit = audit
        self._decisions = decisions
        self._bus = bus

    # ── policy ─────────────────────────────────────────────────────────────

    async def requires_approval(self, contract: BusinessContract, action_type: str) -> bool:
        """Return whether ``action_type`` needs human approval right now.

        Args:
            contract: The acting business's contract.
            action_type: Namespaced action identifier (A-003).

        Returns:
            True unless the action has graduated. Unknown action types always
            require approval (spec §8).
        """
        policy = contract.autonomy_for(action_type)
        if policy is None or policy.requires_approval is False:
            return policy is None
        counter = await self._counter(contract.business_id, action_type)
        return not counter.graduated

    # ── request ────────────────────────────────────────────────────────────

    async def request(
        self,
        *,
        request: ApprovalRequest,
        contract: BusinessContract,
        now: datetime | None = None,
    ) -> str:
        """Record a pending approval request.

        Args:
            request: The structured request (spec §8's four required facts).
            contract: The acting business's contract.
            now: Injectable clock (D-004).

        Returns:
            The approval id.

        Raises:
            ApprovalError: If a capital-moving action arrives without an amount
                (§8 requires the exact amount be displayed; an approval that
                cannot show one must not reach the operator at all), or if the
                action type is not one the business's type declares (D-013).
        """
        # Ordering is deliberate: the §8 amount rule is checked first so a
        # capital action missing its amount is refused for that reason and not
        # incidentally caught by the declaration check below.
        if request.action_type.endswith(("execute_trade", "transfer_funds")) and (
            request.amount_usd is None
        ):
            raise ApprovalError(
                f"action {request.action_type} moves capital but carries no amount (spec §8)"
            )

        # D-013 / M6-F11. The model proposes an intent; the platform decides
        # whether that intent names an action. Observed live: a Manager authored
        # `affiliate.Hold publication and re-run compliance review` as an action
        # type, which reached the operator's queue as an approvable action. It
        # is not one — no tool implements it, no policy can graduate it, and
        # A-003's identity would key the graduation counter on a sentence.
        #
        # This is the backstop, not the primary check: `synthesize_results`
        # degrades an undeclared proposal to no action at all. It exists because
        # an approval row is the *only* thing standing between a model's prose
        # and an operator's authorisation, so the write itself must refuse
        # rather than trust every caller to have validated first.
        if not contract.declares_action(request.action_type):
            raise ApprovalError(
                f"action type {request.action_type!r} is not declared by business type "
                f"{contract.business_type}; declared: {sorted(contract.declared_action_types)} "
                "(D-013, A-003)",
                operator_message=(
                    "Jarvis didn't act on that — it isn't something this company does."
                ),
            )

        moment = now or datetime.now(UTC)
        self._session.add(
            ApprovalRow(
                approval_id=request.approval_id,
                business_id=request.business_id,
                action_type=request.action_type,
                state=ApprovalState.PENDING.value,
                action_summary=request.action_summary,
                amount_usd=request.amount_usd,
                counterparty=request.counterparty,
                triggering_condition=request.triggering_condition,
                downside=request.downside,
                parameters=dict(request.parameters),
                decision_ref=request.decision_ref,
                requested_at=moment,
                last_notified_at=moment,
            )
        )
        await self._session.flush()
        await self._audit.record(
            event_type="approval.requested",
            actor=request.business_id,
            business_id=request.business_id,
            payload={"approval_id": request.approval_id, "action_type": request.action_type},
        )
        logger.info(
            "approval requested",
            extra={"context": {"approval_id": request.approval_id}},
        )
        return request.approval_id

    # ── decision ───────────────────────────────────────────────────────────

    async def approve(
        self,
        approval_id: str,
        *,
        contract: BusinessContract,
        decision_id: DecisionId,
        modified_parameters: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> ApprovalState:
        """Approve a pending request.

        Args:
            approval_id: The request to approve.
            contract: The acting business's contract.
            decision_id: Decision Log entry id, minted in an activity (D-004).
            modified_parameters: Parameters the operator changed before
                approving. Any difference makes this a *correction*, which
                advances the action but resets the graduation streak (A-003).
            now: Injectable clock.

        Returns:
            The resulting state.

        Raises:
            ApprovalError: If the request is missing or already decided.
        """
        row = await self._require_pending(approval_id)

        # Both facts derive from one test, written so the narrowing is visible to
        # a type checker: `corrected` implies `modified_parameters is not None`,
        # but that implication cannot be read back out of a stored bool. What is
        # persisted is unchanged — the operator's edited parameters on a
        # correction, NULL otherwise. That value is load-bearing: the approved
        # action executes `decided_parameters or parameters`, so storing NULL on
        # a correction would run the original the operator rejected.
        if modified_parameters is not None and modified_parameters != row.parameters:
            corrected = True
            decided_parameters: dict[str, object] | None = dict(modified_parameters)
        else:
            corrected = False
            decided_parameters = None

        row.state = ApprovalState.APPROVED.value
        row.decided_at = now or datetime.now(UTC)
        row.decided_parameters = decided_parameters
        await self._session.flush()

        if corrected:
            await self._reset_counter(row.business_id, row.action_type, reason="correction")
        else:
            await self._advance_counter(row, contract)

        await self._record_outcome(
            row,
            contract,
            decision_id=decision_id,
            summary=(
                f"You approved {contract.display_name}'s request with changes."
                if corrected
                else f"You approved {contract.display_name}'s request."
            ),
            rationale=row.action_summary,
        )
        return ApprovalState.APPROVED

    async def deny(
        self,
        approval_id: str,
        *,
        contract: BusinessContract,
        decision_id: DecisionId,
        reason: str = "",
        now: datetime | None = None,
    ) -> ApprovalState:
        """Deny a pending request and reset its graduation streak.

        Raises:
            ApprovalError: If the request is missing or already decided.
        """
        row = await self._require_pending(approval_id)
        row.state = ApprovalState.DENIED.value
        row.decided_at = now or datetime.now(UTC)
        await self._session.flush()

        await self._reset_counter(row.business_id, row.action_type, reason="denied")
        await self._record_outcome(
            row,
            contract,
            decision_id=decision_id,
            summary=f"You said no to {contract.display_name}'s request.",
            rationale=reason or row.action_summary,
        )
        return ApprovalState.DENIED

    # ── timers (spec §9) ───────────────────────────────────────────────────

    async def due_for_renotification(self, *, now: datetime | None = None) -> Sequence[ApprovalRow]:
        """Return pending approvals unanswered for 24 hours (spec §9)."""
        cutoff = (now or datetime.now(UTC)) - RENOTIFY_AFTER
        stmt = (
            select(ApprovalRow)
            .where(ApprovalRow.state == ApprovalState.PENDING.value)
            .where(ApprovalRow.last_notified_at <= cutoff)
        )
        return (await self._session.scalars(stmt)).all()

    async def mark_notified(self, approval_id: str, *, now: datetime | None = None) -> None:
        """Record that a reminder was sent, restarting the 24h clock."""
        row = await self._session.get(ApprovalRow, approval_id)
        if row is not None:
            row.last_notified_at = now or datetime.now(UTC)
            await self._session.flush()

    async def expire_stale(
        self, *, decision_id: DecisionId, now: datetime | None = None
    ) -> list[str]:
        """Expire approvals unresolved for 7 days (spec §9).

        Expiry moves the request to `EXPIRED_PAUSED` and never to approved. Spec
        §9 is explicit that an unanswered approval must auto-pause the dependent
        workflow rather than auto-approve, so silence is treated as refusal.

        Returns:
            Ids of the businesses whose approvals expired, for the caller to
            pause. Pausing is not performed here — the Registry owns lifecycle
            transitions and this service owns approvals.
        """
        moment = now or datetime.now(UTC)
        cutoff = moment - AUTO_PAUSE_AFTER
        stmt = (
            select(ApprovalRow)
            .where(ApprovalRow.state == ApprovalState.PENDING.value)
            .where(ApprovalRow.requested_at <= cutoff)
        )
        expired = list((await self._session.scalars(stmt)).all())

        businesses: list[str] = []
        for row in expired:
            row.state = ApprovalState.EXPIRED_PAUSED.value
            row.decided_at = moment
            businesses.append(row.business_id)
            await self._audit.record(
                event_type="approval.expired",
                actor="platform",
                business_id=BusinessId(row.business_id),
                payload={"approval_id": row.approval_id, "days_pending": 7},
            )
        await self._session.flush()

        if expired:
            await self._decisions.record(
                decision_id=decision_id,
                business_id=BusinessId(expired[0].business_id),
                summary="A request went unanswered for a week, so Jarvis paused the company.",
                rationale=(
                    "Jarvis never assumes yes. When a request waits seven days without an "
                    "answer, the company pauses until you decide."
                ),
                action_type=APPROVAL_EXPIRED_ACTION_TYPE,
            )
        return businesses

    # ── internals ──────────────────────────────────────────────────────────

    async def _require_pending(self, approval_id: str) -> ApprovalRow:
        row = await self._session.get(ApprovalRow, approval_id)
        if row is None:
            raise ApprovalError(f"approval {approval_id} does not exist")
        if row.state != ApprovalState.PENDING.value:
            raise ApprovalError(
                f"approval {approval_id} is already {row.state}",
                operator_message="You've already answered this one.",
            )
        return row

    async def _counter(self, business_id: str, action_type: str) -> AutonomyCounterRow:
        row = await self._session.get(AutonomyCounterRow, (business_id, action_type))
        if row is None:
            row = AutonomyCounterRow(
                business_id=business_id,
                action_type=action_type,
                plugin_major_version=await self._installed_major(business_id),
            )
            self._session.add(row)
            await self._session.flush()
        return row

    async def _installed_major(self, business_id: str) -> int:
        """Return the major version of this company's installed type (A-003).

        Stamped on the counter when it is created so the column says which
        version's behaviour the streak was earned under. Until M8-8 it defaulted
        to 1 and was never set from a definition, which made it a schema-backed
        assertion with no reader and no writer (M8-F8); the reader is
        `BusinessRegistry._reset_graduation_on_major_bump`.

        Falls back to 1 when the row cannot be read. A counter that cannot name
        its version is one a later major bump resets — over-eager in the
        direction of *more* human approval, which is the only direction §8
        permits being wrong in.
        """
        stmt = (
            select(BusinessTypeRow.version)
            .join(BusinessInstanceRow, BusinessInstanceRow.business_type == BusinessTypeRow.name)
            .where(BusinessInstanceRow.business_id == business_id)
        )
        version = await self._session.scalar(stmt)
        return int(version.split(".")[0]) if version else 1

    async def _advance_counter(self, row: ApprovalRow, contract: BusinessContract) -> None:
        """Advance the streak and graduate if the threshold is met (spec §8)."""
        counter = await self._counter(row.business_id, row.action_type)
        counter.consecutive_approvals += 1

        policy = contract.autonomy_for(row.action_type)
        if policy is None:
            await self._session.flush()
            return

        # Two independent guards. The policy flag can be misconfigured; the
        # amount cannot lie about whether money moved.
        capital_action = row.amount_usd is not None
        eligible = policy.graduation_eligible and not capital_action

        if eligible and counter.consecutive_approvals >= policy.graduation_threshold:
            counter.graduated = True
            await self._audit.record(
                event_type="autonomy.graduated",
                actor="platform",
                business_id=BusinessId(row.business_id),
                payload={
                    "action_type": row.action_type,
                    "threshold": policy.graduation_threshold,
                },
            )
        await self._session.flush()

    async def _reset_counter(self, business_id: str, action_type: str, *, reason: str) -> None:
        counter = await self._counter(business_id, action_type)
        counter.consecutive_approvals = 0
        counter.graduated = False
        await self._session.flush()
        await self._audit.record(
            event_type="autonomy.reset",
            actor="operator",
            business_id=BusinessId(business_id),
            payload={"action_type": action_type, "reason": reason},
        )

    async def _record_outcome(
        self,
        row: ApprovalRow,
        contract: BusinessContract,
        *,
        decision_id: DecisionId,
        summary: str,
        rationale: str,
    ) -> None:
        audit_ref = await self._audit.record(
            event_type="approval.decided",
            actor="operator",
            business_id=BusinessId(row.business_id),
            payload={"approval_id": row.approval_id, "state": row.state},
        )
        await self._decisions.record(
            decision_id=decision_id,
            business_id=BusinessId(row.business_id),
            summary=summary,
            rationale=rationale,
            action_type=row.action_type,
            structured_action={
                "action": row.action_summary,
                "amount_usd": str(row.amount_usd) if row.amount_usd is not None else None,
                "counterparty": row.counterparty,
            },
            audit_ref=audit_ref,
        )
        await self._publish_decided(row)

    async def _publish_decided(self, row: ApprovalRow) -> None:
        """Publish the decision so the waiting Manager resumes (D-006, spec §2).

        The Manager ended its cycle when the request was raised; this is what
        starts the next one. Publishing to the bus rather than calling the
        Manager directly is required by §2 — workers never call workers — and
        gives deduplication for free (A-002), so a redelivered decision cannot
        wake the Manager twice.
        """
        if self._bus is None:
            return
        await self._bus.publish(
            Event(
                event_id=EventId(new_event_id()),
                event_type=APPROVAL_DECIDED,
                business_id=BusinessId(row.business_id),
                payload={"approval_id": row.approval_id, "state": row.state},
            )
        )

    # ── queries for the operator surface ───────────────────────────────────

    async def pending(self, *, limit: int = 50) -> Sequence[ApprovalRow]:
        """Return pending approvals, oldest first — the operator's queue."""
        stmt = (
            select(ApprovalRow)
            .where(ApprovalRow.state == ApprovalState.PENDING.value)
            .order_by(ApprovalRow.requested_at)
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def graduated_actions(self, business_id: BusinessId) -> Sequence[AutonomyCounterRow]:
        """Return action types this business may now perform on its own.

        Surfaced so §12.5's "[Company] can now do this on its own" can be shown
        with an easy way to revoke it.
        """
        stmt = (
            select(AutonomyCounterRow)
            .where(AutonomyCounterRow.business_id == business_id)
            .where(AutonomyCounterRow.graduated.is_(True))
        )
        return (await self._session.scalars(stmt)).all()

    async def revoke_graduation(self, business_id: BusinessId, action_type: str) -> None:
        """Return an action to requiring approval (spec §12.5).

        §12.5 requires graduation be shown "with an easy way to revoke it", so
        revocation is a first-class operation rather than a database edit.
        """
        await self._reset_counter(business_id, action_type, reason="revoked_by_operator")


def amount_or_none(value: str | None) -> Decimal | None:
    """Parse an operator-supplied amount, returning None for blanks."""
    return Decimal(value) if value else None
