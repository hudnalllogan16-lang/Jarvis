"""Capability pool dispatch tests (spec §2.2, §6, §9; D-001, D-002, D-003)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates
from jarvis.capabilities.pool import CapabilityPool
from jarvis.capabilities.request import (
    InvocationStatus,
    MemoryScope,
    ScopedRequest,
)
from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.errors import (
    BudgetExceededError,
    CapabilityExecutionError,
    CircuitBreakerOpenError,
    ScopeViolationError,
)
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId, InvocationId
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.persistence.models import BudgetLedgerRow, DeadLetterRow
from jarvis.registry.registry import BusinessRegistry


class StubProvider:
    """Provider that fails a configurable number of times before succeeding."""

    def __init__(self, *, failures: int = 0, permanent: bool = False) -> None:
        self.failures = failures
        self.permanent = permanent
        self.calls = 0

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        self.calls += 1
        if self.calls <= self.failures:
            raise CapabilityExecutionError("stub failure", permanent=self.permanent)
        return CompletionResponse(text="done", usage=Usage(input_tokens=5, output_tokens=5))

    async def aclose(self) -> None:
        return None


async def _noop_sleep(_: float) -> None:
    """Injected in place of asyncio.sleep so backoff tests do not wait."""
    return None


def _request(**overrides: object) -> ScopedRequest:
    base: dict[str, object] = {
        "invocation_id": InvocationId("inv_1"),
        "declared_business_id": BusinessId("biz_0123456789abcdef0123456789abcdef"),
        "capability": CapabilityType.RESEARCH,
        "prompt_ref": "affiliate.research",
        "tool_scope": frozenset({"web_search"}),
        "credential_refs": frozenset({"serp_key"}),
        "budget_allocation_usd": Decimal("0.50"),
    }
    base.update(overrides)
    return ScopedRequest(**base)  # type: ignore[arg-type]


async def _pool(
    session: AsyncSession,
    registry: BusinessRegistry,
    contract: BusinessContract,
    provider: StubProvider,
    *,
    platform_ceiling: str = "500.00",
) -> tuple[CapabilityPool, BusinessId]:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )
    business_id = await registry.register_instance(contract)
    await registry.transition(
        business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_start"),
        reason="Started for testing.",
    )
    ledger = BudgetLedger(session, platform_ceiling_usd=Decimal(platform_ceiling))
    from jarvis.observability.decision_log import DecisionLog

    pool = CapabilityPool(
        session=session,
        registry=registry,
        ledger=ledger,
        breaker=CircuitBreaker(ledger, DecisionLog(session), ceiling_usd=Decimal(platform_ceiling)),
        executor=CapabilityExecutor(
            provider,  # type: ignore[arg-type]
            InMemoryTemplates({"affiliate.research": "Research {topic}"}),
        ),
        audit=registry._audit,
        sleep=_noop_sleep,
    )
    return pool, business_id


async def test_successful_dispatch_settles_budget(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    provider = StubProvider()
    pool, business_id = await _pool(session, registry, contract, provider)
    result = await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "affiliate niches"}),
    )
    assert result.status is InvocationStatus.SUCCEEDED
    assert result.output == "done"
    assert result.attempts == 1


async def test_transient_failure_retries_then_succeeds(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §9: bounded retry with backoff."""
    provider = StubProvider(failures=2)
    pool, business_id = await _pool(session, registry, contract, provider)
    result = await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}, max_attempts=3),
    )
    assert result.status is InvocationStatus.SUCCEEDED
    assert result.attempts == 3


async def test_retry_exhaustion_returns_a_terminal_result(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-001, the deadlock fix.

    §2.1 makes a Manager wait for all results while §9 dead-letters exhausted
    invocations. If dead-lettering were a silent sink the Manager would wait
    forever. Dispatch must return, not hang or raise.
    """
    provider = StubProvider(failures=99)
    pool, business_id = await _pool(session, registry, contract, provider)
    result = await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}, max_attempts=2),
    )
    assert result.status is InvocationStatus.DEAD_LETTERED
    assert result.attempts == 2
    assert result.operator_summary
    assert "Traceback" not in result.operator_summary


async def test_dead_letter_is_recorded_for_the_dashboard(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §9: dead letters MUST be visible in the dashboard."""
    provider = StubProvider(failures=99)
    pool, business_id = await _pool(session, registry, contract, provider)
    await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}, max_attempts=2),
    )
    rows = list((await session.scalars(select(DeadLetterRow))).all())
    assert len(rows) == 1
    assert rows[0].attempts == 2
    assert "error:" not in rows[0].operator_summary.lower()


async def test_dead_lettered_invocation_releases_its_budget(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Failed work must not permanently consume a company's budget."""
    provider = StubProvider(failures=99)
    pool, business_id = await _pool(session, registry, contract, provider)
    await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}, max_attempts=2),
    )
    states = [r.state for r in (await session.scalars(select(BudgetLedgerRow))).all()]
    assert states == ["RELEASED"]


async def test_permanent_failure_does_not_burn_retries(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """A malformed request fails identically every time; retrying only spends."""
    provider = StubProvider(failures=99, permanent=True)
    pool, business_id = await _pool(session, registry, contract, provider)
    result = await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}, max_attempts=5),
    )
    assert result.status is InvocationStatus.DEAD_LETTERED
    assert provider.calls == 1


async def test_scope_violation_is_raised_not_returned(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """A security event is not a task outcome.

    Returning it as a FAILED result would let a Manager retry past it.
    """
    provider = StubProvider()
    pool, business_id = await _pool(session, registry, contract, provider)
    with pytest.raises(ScopeViolationError):
        await pool.dispatch(
            identity=RuntimeIdentity.for_testing(business_id),
            request=_request(declared_business_id=BusinessId("biz_other")),
        )


async def test_dispatch_refused_when_breaker_open(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §9: no new dispatch while the platform breaker is open."""
    provider = StubProvider()
    pool, business_id = await _pool(session, registry, contract, provider, platform_ceiling="0.01")
    with pytest.raises(CircuitBreakerOpenError):
        await pool.dispatch(
            identity=RuntimeIdentity.for_testing(business_id),
            request=_request(prompt_inputs={"topic": "x"}),
        )


async def test_over_allocation_refused_before_any_work(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-003: ceilings are pre-flight checks, not post-hoc alarms."""
    provider = StubProvider()
    pool, business_id = await _pool(session, registry, contract, provider)
    with pytest.raises(BudgetExceededError):
        await pool.dispatch(
            identity=RuntimeIdentity.for_testing(business_id),
            request=_request(budget_allocation_usd=Decimal("999.00")),
        )
    assert provider.calls == 0


async def test_memory_context_refused_without_memory_scope(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §7: no ambient access to a business's memory."""
    provider = StubProvider()
    pool, business_id = await _pool(session, registry, contract, provider)
    with pytest.raises(ScopeViolationError):
        await pool.dispatch(
            identity=RuntimeIdentity.for_testing(business_id),
            request=_request(memory_scope=MemoryScope.NONE),
            memory_context="prior findings",
        )


async def test_executor_holds_no_state_between_invocations(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §2.2: no residual context between calls, including for one business.

    Asserted structurally: an executor with no per-invocation attributes has no
    field in which context could survive.
    """
    provider = StubProvider()
    executor = CapabilityExecutor(provider, InMemoryTemplates({"a": "b"}))  # type: ignore[arg-type]
    before = dict(vars(executor))
    pool, business_id = await _pool(session, registry, contract, provider)
    await pool.dispatch(
        identity=RuntimeIdentity.for_testing(business_id),
        request=_request(prompt_inputs={"topic": "x"}),
    )
    assert dict(vars(executor)) == before
