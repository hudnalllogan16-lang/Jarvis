"""Shared Capability Pool dispatch (spec §2.2, §6, §9; D-001, D-002, D-003).

This is where the decisions locked in Milestone 1 become executable. One
dispatch runs, in order:

1. Authorization against the runtime-derived identity (D-002).
2. Circuit breaker check (spec §9).
3. Budget reservation across the full hierarchy (D-003).
4. Execution with bounded retry and backoff (spec §9).
5. Settlement or release of the reservation.
6. On retry exhaustion, dead-lettering — *and* a terminal result (D-001).

Step 6 is the one that is easy to get wrong. Spec §2.1 requires a Business
Manager to wait for and synthesize all results; spec §9 routes exhausted
invocations to a dead-letter queue. If dead-lettering were a silent sink, the
Manager would wait forever on a result that will never arrive, and the business
would deadlock permanently on its first exhausted retry. So dispatch always
returns a `CapabilityResult`, and `DEAD_LETTERED` is one of its terminal states.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger, Reservation
from jarvis.capabilities.contention import CapabilityGate
from jarvis.capabilities.executor import CapabilityExecutor
from jarvis.capabilities.idempotency import IdempotencyStore, idempotency_key
from jarvis.capabilities.request import (
    CapabilityResult,
    InvocationStatus,
    MemoryScope,
    ScopedRequest,
)
from jarvis.domain.contract import BusinessContract
from jarvis.events.bus import Event, EventBus
from jarvis.events.types import CAPABILITY_RESULT
from jarvis.kernel.errors import (
    CapabilityExecutionError,
    ScopeViolationError,
)
from jarvis.kernel.ids import EventId, new_event_id
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import Usage
from jarvis.observability.audit import AuditLog
from jarvis.persistence.models import DeadLetterRow
from jarvis.registry.registry import BusinessRegistry

logger = get_logger(__name__)

BASE_BACKOFF_SECONDS = 0.5
"""Multiplied by 2**attempt. Bounded because the retry count is bounded."""


class CapabilityPool:
    """Dispatches scoped requests to stateless capabilities (spec §2.2)."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        registry: BusinessRegistry,
        ledger: BudgetLedger,
        breaker: CircuitBreaker,
        executor: CapabilityExecutor,
        audit: AuditLog,
        idempotency: IdempotencyStore | None = None,
        gate: CapabilityGate | None = None,
        bus: EventBus | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Args:
        session: Active session.
        registry: Authorization anchor (D-002).
        ledger: Budget hierarchy (D-003).
        breaker: Platform circuit breaker (spec §9).
        executor: Stateless execution shell (spec §6).
        audit: Audit log (spec §11).
        idempotency: Store guarding external-facing actions (spec §6, A-001).
            Optional only because a pool serving purely analytical capabilities
            has no external effects to guard.
        gate: Fairness gate across businesses competing for one capability
            (spec §2.2, A-004). Optional only because a single-business
            deployment has nothing to arbitrate.
        bus: Event bus. Publishing each terminal result is what makes
            "capability result returned" usable as a wake condition (§2.1).
        sleep: Injectable delay, so retry-backoff tests do not sleep for real.
        """
        self._session = session
        self._registry = registry
        self._ledger = ledger
        self._breaker = breaker
        self._executor = executor
        self._audit = audit
        self._idempotency = idempotency
        self._gate = gate
        self._bus = bus
        self._sleep = sleep

    async def dispatch(
        self,
        *,
        identity: RuntimeIdentity,
        request: ScopedRequest,
        memory_context: str = "",
    ) -> CapabilityResult:
        """Run one capability invocation to a terminal state (D-001).

        Args:
            identity: Runtime-derived business identity (D-002). Not taken from
                the request, which is untrusted input.
            request: The scoped request.
            memory_context: Memory granted by this request's scope (spec §7).

        Returns:
            A terminal `CapabilityResult`. Always returned — including when the
            invocation is dead-lettered — so an awaiting Manager can synthesize
            over failures instead of blocking forever.

        Raises:
            ScopeViolationError: If authorization fails. Deliberately raised
                rather than returned as a FAILED result: a scope violation is a
                security event, not a task outcome, and collapsing it into an
                ordinary failure would let a Manager retry past it.
            CircuitBreakerOpenError: If platform dispatch is halted (spec §9).
            BudgetExceededError: If a ceiling refuses the reservation (D-003).
                Also raised rather than returned, because no work was attempted
                and there is nothing for a Manager to synthesize.
        """
        business_id = identity.business_id

        await self._registry.authorize_invocation(
            identity=identity,
            declared_business_id=request.declared_business_id,
            capability=request.capability,
            requested_tools=request.tool_scope,
            requested_credentials=request.credential_refs,
        )
        contract = await self._registry.get_contract(business_id)

        if request.memory_scope is MemoryScope.NONE and memory_context:
            raise ScopeViolationError(
                "memory context supplied to an invocation granted no memory scope (spec §7)"
            )

        replayed = await self._replay_if_already_performed(request, contract)
        if replayed is not None:
            return replayed

        await self._breaker.assert_closed()

        reservation = await self._ledger.reserve(
            contract=contract,
            amount_usd=request.budget_allocation_usd,
            invocation_id=request.invocation_id,
            cycle_id=request.cycle_id,
            invocation_allocation_usd=request.budget_allocation_usd,
        )

        await self._audit.record(
            event_type="capability.dispatched",
            actor=business_id,
            business_id=business_id,
            workflow_id=identity.workflow_id,
            payload={
                "invocation_id": request.invocation_id,
                "capability": request.capability.value,
                "allocation_usd": str(request.budget_allocation_usd),
            },
        )

        if self._gate is None:
            return await self._execute_with_retry(
                identity=identity,
                request=request,
                contract=contract,
                reservation=reservation,
                memory_context=memory_context,
            )

        # The slot is taken after the budget reservation and before execution:
        # a business that cannot afford the work should not occupy a queue
        # position it will only give back.
        remaining = contract.budget.business_cap_usd - await self._ledger.business_spend(
            business_id
        )
        async with self._gate.slot(
            request.capability, business_id, weight=max(remaining, Decimal(0))
        ):
            return await self._execute_with_retry(
                identity=identity,
                request=request,
                contract=contract,
                reservation=reservation,
                memory_context=memory_context,
            )

    async def _replay_if_already_performed(
        self, request: ScopedRequest, contract: BusinessContract
    ) -> CapabilityResult | None:
        """Return the prior result if this action already ran (spec §6, A-001).

        Checked before the budget reservation, not after: a replayed action
        performs no work, so charging for it would let a retry storm drain a
        company's budget on effects that never happened twice.

        Only invocations carrying an ``action_type`` are guarded. Spec §6 scopes
        idempotency to external-facing and state-changing actions; a research
        query has no external effect to duplicate, and caching it would return
        stale findings for a question asked again on purpose.
        """
        if self._idempotency is None or request.action_type is None:
            return None

        key = idempotency_key(
            business_id=contract.business_id,
            invocation_id=request.invocation_id,
            action_type=request.action_type,
            payload=request.prompt_inputs,
        )
        existing = await self._idempotency.existing(key)
        if existing is None:
            return None

        await self._audit.record(
            event_type="capability.replayed",
            actor=contract.business_id,
            business_id=contract.business_id,
            payload={"invocation_id": request.invocation_id, "action_type": request.action_type},
        )
        return CapabilityResult(
            invocation_id=request.invocation_id,
            business_id=contract.business_id,
            capability=request.capability,
            status=InvocationStatus.SUCCEEDED,
            output=str(existing.get("output", "")),
            attempts=0,
            operator_summary=f"{contract.display_name} had already done this.",
        )

    async def _record_performed(
        self, request: ScopedRequest, contract: BusinessContract, output: str
    ) -> None:
        """Record a completed external-facing action so a repeat replays it."""
        if self._idempotency is None or request.action_type is None:
            return
        await self._idempotency.record(
            key=idempotency_key(
                business_id=contract.business_id,
                invocation_id=request.invocation_id,
                action_type=request.action_type,
                payload=request.prompt_inputs,
            ),
            business_id=contract.business_id,
            action_type=request.action_type,
            result={"output": output},
        )

    async def _execute_with_retry(
        self,
        *,
        identity: RuntimeIdentity,
        request: ScopedRequest,
        contract: BusinessContract,
        reservation: Reservation,
        memory_context: str,
    ) -> CapabilityResult:
        """Attempt execution up to the request's bounded retry count (spec §9)."""
        business_id = identity.business_id
        last_error: CapabilityExecutionError | None = None

        for attempt in range(1, request.max_attempts + 1):
            try:
                output, usage = await self._executor.execute(
                    request=request,
                    contract=contract,
                    memory_context=memory_context,
                )
            except CapabilityExecutionError as exc:
                last_error = exc
                await self._audit.record(
                    event_type="capability.attempt_failed",
                    actor=business_id,
                    business_id=business_id,
                    payload={
                        "invocation_id": request.invocation_id,
                        "attempt": attempt,
                        "permanent": exc.permanent,
                        "detail": exc.technical_detail,
                    },
                )
                if exc.permanent:
                    break
                if attempt < request.max_attempts:
                    await self._sleep(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue

            actual = self._cost_of(usage, reservation.amount_usd)
            await self._ledger.settle(reservation, actual)
            await self._record_performed(request, contract, output)
            await self._audit.record(
                event_type="capability.succeeded",
                actor=business_id,
                business_id=business_id,
                payload={"invocation_id": request.invocation_id, "attempts": attempt},
                cost_usd=actual,
            )
            succeeded = CapabilityResult(
                invocation_id=request.invocation_id,
                business_id=business_id,
                capability=request.capability,
                status=InvocationStatus.SUCCEEDED,
                output=output,
                usage=usage,
                attempts=attempt,
            )
            await self._announce(succeeded)
            return succeeded

        # Retries exhausted, or a permanent failure short-circuited them.
        await self._ledger.release(reservation)
        return await self._dead_letter(
            identity=identity,
            request=request,
            contract=contract,
            attempts=request.max_attempts,
            error=last_error,
        )

    async def _announce(self, result: CapabilityResult) -> None:
        """Publish a terminal result so it can serve as a wake condition (§2.1).

        Published for failures and dead letters too, not only successes: a
        Manager waiting on "capability result returned" needs to hear that work
        finished badly just as much as that it finished well.
        """
        if self._bus is None:
            return
        await self._bus.publish(
            Event(
                event_id=EventId(new_event_id()),
                event_type=CAPABILITY_RESULT,
                business_id=result.business_id,
                payload={
                    "invocation_id": result.invocation_id,
                    "status": result.status.value,
                },
            )
        )

    async def _dead_letter(
        self,
        *,
        identity: RuntimeIdentity,
        request: ScopedRequest,
        contract: BusinessContract,
        attempts: int,
        error: CapabilityExecutionError | None,
    ) -> CapabilityResult:
        """Route an exhausted invocation to the DLQ and return its result (D-001).

        Both halves matter. The DLQ row satisfies spec §9's visibility
        requirement and surfaces in the dashboard as "[Company] got stuck". The
        returned result is what stops the awaiting Manager from waiting forever.
        """
        business_id = identity.business_id
        display_name = contract.display_name
        operator_summary = (
            error.operator_message if error else f"{display_name} couldn't finish a task."
        )
        technical_detail = error.technical_detail if error else "unknown failure"

        self._session.add(
            DeadLetterRow(
                invocation_id=request.invocation_id,
                business_id=business_id,
                capability=request.capability.value,
                attempts=attempts,
                operator_summary=operator_summary,
                technical_detail=technical_detail,
            )
        )
        await self._session.flush()

        await self._audit.record(
            event_type="capability.dead_lettered",
            actor=business_id,
            business_id=business_id,
            workflow_id=identity.workflow_id,
            payload={
                "invocation_id": request.invocation_id,
                "attempts": attempts,
                "detail": technical_detail,
            },
        )
        logger.warning(
            "invocation dead-lettered",
            extra={"context": {"invocation_id": request.invocation_id, "attempts": attempts}},
        )

        dead = CapabilityResult(
            invocation_id=request.invocation_id,
            business_id=business_id,
            capability=request.capability,
            status=InvocationStatus.DEAD_LETTERED,
            attempts=attempts,
            operator_summary=operator_summary,
            technical_detail=technical_detail,
        )
        await self._announce(dead)
        return dead

    @staticmethod
    def _cost_of(usage: Usage, reserved: Decimal) -> Decimal:
        """Return the settled cost for one execution.

        Per-model pricing is not configured until the Executive Layer's cost
        tracking lands, so the reservation is settled in full rather than
        estimated. Settling the reservation is the conservative direction: it
        can only under-report headroom, never over-report it, so no ceiling in
        D-003 can be silently exceeded by this approximation.
        """
        return reserved if not usage.cost_usd else min(usage.cost_usd, reserved)
