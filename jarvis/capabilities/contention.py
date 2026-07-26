"""Concurrency gate over the capability pool (spec §2.2, policy per A-004).

`FairQueue` decides *who goes next*; this is what asks it. Milestone 2 built the
policy and left it dormant because dispatch was synchronous and nothing
contended. Now that Managers dispatch concurrently, contention is real.

One gate per capability type, each with a bounded number of concurrent slots.
When slots are free a caller proceeds immediately — arbitration only costs
something when businesses are actually competing, which is the only time §2.2's
fairness requirement means anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal

from jarvis.capabilities.queue import FairQueue
from jarvis.domain.contract import CapabilityType
from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SLOTS = 4
"""Concurrent invocations per capability. Bounded so one capability cannot
saturate the provider's rate limit on behalf of every business at once."""


class CapabilityGate:
    """Admits invocations in weighted-fair order under contention (A-004)."""

    def __init__(self, *, slots: int = DEFAULT_SLOTS) -> None:
        """Args:
        slots: Concurrent invocations permitted per capability type.
        """
        self._slots = slots
        self._queues: dict[CapabilityType, FairQueue] = {}
        self._semaphores: dict[CapabilityType, asyncio.Semaphore] = {}
        self._turn = asyncio.Condition()

    @asynccontextmanager
    async def slot(
        self,
        capability: CapabilityType,
        business_id: str,
        *,
        weight: Decimal,
    ) -> AsyncGenerator[None]:
        """Wait for this business's turn, hold a slot, then release it.

        Args:
            capability: The capability being invoked.
            business_id: The invoking business.
            weight: Budget-proportional weight — typically remaining budget.
                Relative magnitude is all that matters.

        Yields:
            Once admitted. The queue guarantees every waiting business a
            minimum share, so a small business cannot be starved by a large one
            no matter how long the large one keeps work queued.
        """
        queue = self._queues.setdefault(capability, FairQueue())
        semaphore = self._semaphores.setdefault(capability, asyncio.Semaphore(self._slots))
        queue.enqueue(business_id, weight)

        async with self._turn:
            await self._turn.wait_for(lambda: queue.next_business() == business_id)
            queue.record_dispatch(business_id)

        await semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()
            queue.remove(business_id)
            async with self._turn:
                self._turn.notify_all()

    def waiting(self, capability: CapabilityType) -> frozenset[str]:
        """Return which businesses are currently waiting for ``capability``."""
        queue = self._queues.get(capability)
        return queue.waiting if queue else frozenset()
