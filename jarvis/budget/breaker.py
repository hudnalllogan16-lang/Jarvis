"""Platform circuit breaker (spec §9, precedence per D-003 rule 3).

Spec §9 halts *all* new dispatch when aggregate 24h spend exceeds the ceiling.
Read alone that is shared-fate: one misbehaving business freezes every healthy
one, which contradicts spec §10's requirement that a failure in one business
must not affect another's execution.

D-003 resolves it by ordering the checks rather than changing either rule: a
business's own cap (§5) halts that business first, so the platform breaker is
reached only by aggregate drift across many businesses rather than by one
runaway. Both ceilings still hold exactly as written.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from jarvis.budget.ledger import BudgetLedger
from jarvis.kernel.errors import CircuitBreakerOpenError
from jarvis.kernel.ids import DecisionId
from jarvis.kernel.logging import get_logger
from jarvis.observability.decision_log import DecisionLog

logger = get_logger(__name__)


class CircuitBreaker:
    """Platform-wide dispatch halt on aggregate 24h spend (spec §9)."""

    def __init__(
        self,
        ledger: BudgetLedger,
        decisions: DecisionLog,
        *,
        ceiling_usd: Decimal,
    ) -> None:
        """Args:
        ledger: Budget ledger supplying the rolling aggregate.
        decisions: Decision Log. Required, not optional — §12.5 promises the
            operator "Jarvis paused spending — here's why", and v1.4 assigns
            no writer for that narrative. This is the writer.
        ceiling_usd: Rolling 24h ceiling, owner-adjustable only.
        """
        self._ledger = ledger
        self._decisions = decisions
        self._ceiling = ceiling_usd

    async def assert_closed(self, *, now: datetime | None = None) -> None:
        """Raise if platform dispatch is currently halted.

        Args:
            now: Injectable clock (D-004).

        Raises:
            CircuitBreakerOpenError: If the rolling 24h aggregate is at or over
                the ceiling.
        """
        spend = await self._ledger.platform_spend_24h(now=now)
        if spend >= self._ceiling:
            raise CircuitBreakerOpenError(
                f"platform 24h spend {spend} has reached ceiling {self._ceiling} (spec §9)",
                scope="platform",
            )

    async def trip(
        self,
        *,
        decision_id: DecisionId,
        spend_usd: Decimal,
        triggering_business: str | None = None,
    ) -> None:
        """Record the halt so the operator can be told why (spec §12.5).

        Writes a platform-scoped Decision Log entry — the halt belongs to no
        single business, but it is the event most likely to prompt "why did
        everything stop?", and §11.5 requires that be answerable without reading
        raw logs.
        """
        detail = (
            f" The last company to spend was {triggering_business}." if triggering_business else ""
        )
        await self._decisions.record_platform_decision(
            decision_id=decision_id,
            summary="Jarvis paused spending across all companies.",
            rationale=(
                f"Total spending in the last 24 hours reached ${spend_usd}, which is the "
                f"daily limit of ${self._ceiling}. No new work will start until the limit "
                f"resets or you raise it.{detail}"
            ),
            action_type="platform.circuit_breaker",
            inputs_considered={"spend_usd": str(spend_usd), "ceiling_usd": str(self._ceiling)},
        )
        logger.warning("circuit breaker tripped", extra={"context": {"spend": str(spend_usd)}})
