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

PLATFORM_HALT_ACTION_TYPE = "platform.circuit_breaker"
"""`action_type` on the platform Decision Log entry :meth:`CircuitBreaker.trip`
writes.

Exported because the caller that finally arrived (`jarvis.executive.alerts`,
design EXECUTIVE-LAYER.md 2.4) has to recognise its own prior entry to record
one halt rather than one per scheduled pass, and recognising it by a literal
copied into another module would make the identity of the entry depend on two
strings staying equal. A structured column, never the prose beside it: design
Part 4 forbids reading the Decision Log's sentences as a fact source, and this
is the escape hatch that makes obeying it possible."""


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

        **This records; it never cancels.** D-003 rule 4 forbids killing an
        in-flight invocation on a ceiling breach, and nothing here touches one:
        the refusal of *new* dispatch is :meth:`assert_closed` at the pool
        boundary and was already wired. Deliberately separate from that check —
        a check that writes is no longer a check, and the pool boundary runs per
        dispatch, so recording there would write one entry per refused
        invocation instead of one per halt (design EXECUTIVE-LAYER.md 2.4).
        Calling this more than once per halt is therefore the caller's error to
        avoid, not this method's: it appends unconditionally, as an append-only
        log must.
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
            action_type=PLATFORM_HALT_ACTION_TYPE,
            inputs_considered={"spend_usd": str(spend_usd), "ceiling_usd": str(self._ceiling)},
        )
        logger.warning("circuit breaker tripped", extra={"context": {"spend": str(spend_usd)}})
