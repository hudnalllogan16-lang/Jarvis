"""Decision Log (spec §11.5) — first-class, human-readable business narrative.

Per §11.5 this is *not* a filtered view of the audit log. It is a different
artifact for a different audience, and it must answer "why did this company do
X" on its own without anyone reading raw logs.

Two consequences shape this module:

1. Per D-005 this store, not Temporal workflow state, holds a Business Manager's
   decision history. The Manager remains its sole writer.
2. Per §11.5 and §12.5, Executive and platform decisions — capital reallocation,
   company retirement, circuit-breaker trips — also owe the operator a "why",
   even though they belong to no single business. `record_platform_decision`
   exists for exactly that, and writes with `business_id=None`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.kernel.ids import BusinessId, DecisionId
from jarvis.kernel.logging import get_logger
from jarvis.persistence.models import DecisionLogRow

logger = get_logger(__name__)


class DecisionLog:
    """Append-only writer and reader for the operator-facing decision record."""

    def __init__(self, session: AsyncSession) -> None:
        """Args:
        session: Active session, injected by the caller.
        """
        self._session = session

    async def record(
        self,
        *,
        decision_id: DecisionId,
        summary: str,
        rationale: str,
        business_id: BusinessId | None = None,
        cycle_id: str | None = None,
        action_type: str | None = None,
        inputs_considered: dict[str, Any] | None = None,
        alternatives_rejected: list[Any] | None = None,
        structured_action: dict[str, Any] | None = None,
        audit_ref: int | None = None,
    ) -> DecisionId:
        """Append one decision entry at the moment the decision is made (§11.5).

        Args:
            decision_id: Minted in an activity, never in workflow code (D-004).
            summary: One plain sentence for the activity feed. No jargon: the
                operator must never meet the words workflow, capability, token,
                or wake cycle here (spec §12.5).
            rationale: Plain-language why, sufficient on its own.
            business_id: Owning business, or None for Executive/platform
                decisions (spec §3.1, §9).
            cycle_id: Wake cycle this decision belongs to, for grouping.
            action_type: Namespaced action identifier (A-003), when the decision
                concerns a specific action type.
            inputs_considered: What the decision was based on.
            alternatives_rejected: What was considered and not chosen — this is
                what makes the entry answer "why *this*" rather than "what".
            structured_action: Action, amount, counterparty, risk as data, so an
                approval prompt can be rendered from values rather than authored
                as free text (spec §8, §12.5).
            audit_ref: Optional pointer into the audit log for drill-down. The
                entry must stand alone without following it (spec §11.5).

        Returns:
            The decision identifier.

        Raises:
            ValueError: If summary or rationale is empty. An entry that explains
                nothing violates §11.5's purpose, so it is rejected at write time
                rather than discovered later by an operator asking "why".
        """
        if not summary.strip() or not rationale.strip():
            msg = "Decision Log entries require a non-empty summary and rationale (spec §11.5)"
            raise ValueError(msg)

        self._session.add(
            DecisionLogRow(
                decision_id=decision_id,
                business_id=business_id,
                cycle_id=cycle_id,
                action_type=action_type,
                summary=summary.strip(),
                rationale=rationale.strip(),
                inputs_considered=inputs_considered or {},
                alternatives_rejected=alternatives_rejected or [],
                structured_action=structured_action,
                audit_ref=audit_ref,
            )
        )
        await self._session.flush()
        logger.info(
            "decision recorded",
            extra={"context": {"decision_id": decision_id, "business_id": business_id}},
        )
        return decision_id

    async def record_platform_decision(
        self,
        *,
        decision_id: DecisionId,
        summary: str,
        rationale: str,
        action_type: str | None = None,
        inputs_considered: dict[str, Any] | None = None,
    ) -> DecisionId:
        """Record a decision with no owning business (spec §3.1, §9, §12.5).

        Used for Executive capital reallocation, company retirement, and circuit
        breaker trips — the decisions most likely to prompt "why did everything
        stop?" and the ones v1.4 assigns to no writer.
        """
        return await self.record(
            decision_id=decision_id,
            summary=summary,
            rationale=rationale,
            business_id=None,
            action_type=action_type,
            inputs_considered=inputs_considered,
        )

    async def activity_feed(
        self, business_id: BusinessId, *, limit: int = 50
    ) -> Sequence[DecisionLogRow]:
        """Return the operator's default activity feed for one company.

        This is what §12.5 calls "What [Company] is doing". It is the first and
        default answer to any "why" question; the audit log never is.
        """
        stmt = (
            select(DecisionLogRow)
            .where(DecisionLogRow.business_id == business_id)
            .order_by(DecisionLogRow.decided_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def platform_feed(self, *, limit: int = 50) -> Sequence[DecisionLogRow]:
        """Return recent platform-level decisions, newest first."""
        stmt = (
            select(DecisionLogRow)
            .where(DecisionLogRow.business_id.is_(None))
            .order_by(DecisionLogRow.decided_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()
