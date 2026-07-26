"""Capability contention policy (spec §2.2, policy per A-004).

Spec §2.2 requires a fairness/priority policy and explicitly forbids
undefined-behaviour FIFO as the default, but names only examples. A-004 picks
one: weighted fair queueing with budget-proportional weights *and a guaranteed
minimum share per waiting business*.

The minimum share is the part that matters at scale. Budget-proportional
weighting alone starves a low-budget business indefinitely whenever a
high-budget one has work, and §12.5 would surface that to the operator as a
company that mysteriously never does anything — a fairness bug wearing the
costume of a broken product.

This module is pure and synchronous: given the waiting set, it decides who goes
next. Keeping the decision free of I/O is what makes the starvation property
testable rather than a claim about production behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

MIN_SHARE = Decimal("0.05")
"""Floor on any waiting business's share of dispatch (A-004).

At twenty or more concurrently waiting businesses the floors would sum past 1,
so the implementation normalises rather than over-allocating; the guarantee
degrades to equal shares, which is still not starvation.
"""


@dataclass(frozen=True, slots=True)
class Waiter:
    """One business waiting for a capability."""

    business_id: str
    budget_weight: Decimal
    """Typically the business's remaining budget. Relative magnitude is all that
    matters; absolute units are irrelevant."""

    enqueued_seq: int
    """Monotonic arrival order, used only to break exact ties deterministically.
    Determinism matters here because dispatch order feeds the audit log."""

    served: int = 0
    """Dispatches already granted in the current accounting window."""


@dataclass
class FairQueue:
    """Weighted fair queue with a starvation floor (A-004)."""

    _waiters: dict[str, Waiter] = field(default_factory=dict[str, Waiter])
    _seq: int = 0

    def enqueue(self, business_id: str, budget_weight: Decimal) -> None:
        """Add or refresh a waiting business.

        Re-enqueueing an already-waiting business updates its weight and keeps
        its original arrival order, so a business cannot improve its position by
        resubmitting.
        """
        if business_id in self._waiters:
            existing = self._waiters[business_id]
            self._waiters[business_id] = Waiter(
                business_id,
                budget_weight,
                existing.enqueued_seq,
                existing.served,
            )
            return
        self._waiters[business_id] = Waiter(business_id, budget_weight, self._seq)
        self._seq += 1

    def remove(self, business_id: str) -> None:
        """Remove a business from the waiting set."""
        self._waiters.pop(business_id, None)

    def shares(self) -> dict[str, Decimal]:
        """Return each waiting business's target share of dispatch.

        Returns:
            Business id to share, summing to 1. Every waiting business receives
            at least `MIN_SHARE` unless the floors cannot all be honoured, in
            which case shares are equal.
        """
        if not self._waiters:
            return {}

        ids = list(self._waiters)
        if MIN_SHARE * len(ids) >= 1:
            equal = Decimal(1) / Decimal(len(ids))
            return dict.fromkeys(ids, equal)

        floor_total = MIN_SHARE * len(ids)
        remaining = Decimal(1) - floor_total
        weights = {i: max(self._waiters[i].budget_weight, Decimal(0)) for i in ids}
        total = sum(weights.values())

        if total <= 0:
            equal_extra = remaining / Decimal(len(ids))
            return dict.fromkeys(ids, MIN_SHARE + equal_extra)
        return {i: MIN_SHARE + remaining * (weights[i] / total) for i in ids}

    def next_business(self) -> str | None:
        """Return the business that should be dispatched next.

        Chooses whoever is furthest behind its target share, so a business that
        has been passed over repeatedly rises to the front regardless of budget.

        Returns:
            The selected business id, or None if nothing is waiting.
        """
        if not self._waiters:
            return None

        shares = self.shares()
        total_served = sum(w.served for w in self._waiters.values()) or 1

        def deficit(business_id: str) -> tuple[Decimal, int]:
            waiter = self._waiters[business_id]
            actual = Decimal(waiter.served) / Decimal(total_served)
            return (actual - shares[business_id], waiter.enqueued_seq)

        return min(self._waiters, key=deficit)

    def record_dispatch(self, business_id: str) -> None:
        """Record that ``business_id`` was dispatched, for share accounting."""
        waiter = self._waiters.get(business_id)
        if waiter is not None:
            self._waiters[business_id] = Waiter(
                waiter.business_id,
                waiter.budget_weight,
                waiter.enqueued_seq,
                waiter.served + 1,
            )

    @property
    def waiting(self) -> frozenset[str]:
        """Return the current waiting set."""
        return frozenset(self._waiters)
