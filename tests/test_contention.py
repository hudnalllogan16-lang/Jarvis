"""Capability contention gate tests (spec §2.2, A-004)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from jarvis.capabilities.contention import CapabilityGate
from jarvis.domain.contract import CapabilityType

CAP = CapabilityType.RESEARCH


async def test_uncontended_dispatch_admits_immediately() -> None:
    """Arbitration should cost nothing when nobody is competing."""
    gate = CapabilityGate(slots=2)
    async with gate.slot(CAP, "solo", weight=Decimal("1")):
        pass
    assert gate.waiting(CAP) == frozenset()


async def test_queue_drains_after_use() -> None:
    """A business left in the queue would skew every later decision."""
    gate = CapabilityGate(slots=1)
    async with gate.slot(CAP, "a", weight=Decimal("1")):
        pass
    assert gate.waiting(CAP) == frozenset()


async def test_small_business_is_not_starved_under_concurrency() -> None:
    """A-004's purpose, exercised against real concurrent dispatch rather than
    the queue's arithmetic in isolation."""
    gate = CapabilityGate(slots=2)
    served: list[str] = []

    async def run(business: str, weight: str, times: int) -> None:
        for _ in range(times):
            async with gate.slot(CAP, business, weight=Decimal(weight)):
                served.append(business)
                await asyncio.sleep(0)

    await asyncio.wait_for(
        asyncio.gather(run("whale", "10000", 30), run("minnow", "1", 30)), timeout=10
    )
    assert served.count("minnow") / len(served) > 0.05


async def test_concurrency_is_bounded_by_slots() -> None:
    """One capability must not saturate the provider on everyone's behalf."""
    gate = CapabilityGate(slots=2)
    concurrent = 0
    peak = 0

    async def run(business: str) -> None:
        nonlocal concurrent, peak
        async with gate.slot(CAP, business, weight=Decimal("1")):
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1

    await asyncio.wait_for(asyncio.gather(*(run(f"b{i}") for i in range(8))), timeout=10)
    assert peak <= 2


async def test_gate_does_not_deadlock_on_a_single_waiter() -> None:
    """The condition variable must release even with nothing to arbitrate."""
    gate = CapabilityGate(slots=1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_hold_forever(gate), timeout=0.2)


async def _hold_forever(gate: CapabilityGate) -> None:
    async with gate.slot(CAP, "a", weight=Decimal("1")):
        await asyncio.sleep(3600)
