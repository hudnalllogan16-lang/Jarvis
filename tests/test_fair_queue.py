"""Capability contention tests (spec §2.2, policy per A-004)."""

from __future__ import annotations

from decimal import Decimal

from jarvis.capabilities.queue import MIN_SHARE, FairQueue


def test_empty_queue_has_nothing_to_dispatch() -> None:
    assert FairQueue().next_business() is None
    assert FairQueue().shares() == {}


def test_shares_are_budget_proportional() -> None:
    queue = FairQueue()
    queue.enqueue("rich", Decimal("300"))
    queue.enqueue("poor", Decimal("100"))
    shares = queue.shares()
    assert shares["rich"] > shares["poor"]
    assert sum(shares.values()) == Decimal(1)


def test_low_budget_business_is_never_starved() -> None:
    """A-004's whole purpose.

    Budget-proportional weighting alone starves a small business whenever a
    large one has work. §12.5 would surface that to the operator as a company
    that mysteriously never does anything.
    """
    queue = FairQueue()
    queue.enqueue("whale", Decimal("10000"))
    queue.enqueue("minnow", Decimal("1"))

    served = {"whale": 0, "minnow": 0}
    for _ in range(200):
        chosen = queue.next_business()
        assert chosen is not None
        served[chosen] += 1
        queue.record_dispatch(chosen)

    assert served["minnow"] / 200 >= float(MIN_SHARE) * 0.9


def test_fifo_is_not_the_default():
    """Spec §2.2 forbids undefined-behaviour FIFO as the default policy.

    Under FIFO the first-enqueued business would win every time. It must not.
    """
    queue = FairQueue()
    queue.enqueue("first", Decimal("1"))
    queue.enqueue("second", Decimal("1000"))

    order = []
    for _ in range(10):
        chosen = queue.next_business()
        assert chosen is not None
        order.append(chosen)
        queue.record_dispatch(chosen)
    assert set(order) == {"first", "second"}
    assert order != ["first"] * 10


def test_floors_normalise_rather_than_over_allocating() -> None:
    """With enough waiters the floors would sum past 1; shares must still be valid."""
    queue = FairQueue()
    for i in range(30):
        queue.enqueue(f"b{i}", Decimal(i + 1))
    shares = queue.shares()
    assert abs(sum(shares.values()) - Decimal(1)) < Decimal("0.0001")
    assert all(share > 0 for share in shares.values())


def test_zero_weights_fall_back_to_equal_shares() -> None:
    """A business with no remaining budget must not divide by zero the queue."""
    queue = FairQueue()
    queue.enqueue("a", Decimal("0"))
    queue.enqueue("b", Decimal("0"))
    shares = queue.shares()
    assert shares["a"] == shares["b"]


def test_requeueing_does_not_improve_position() -> None:
    """Otherwise a business could jump the queue by resubmitting."""
    queue = FairQueue()
    queue.enqueue("a", Decimal("1"))
    queue.enqueue("b", Decimal("1"))
    queue.record_dispatch("a")
    queue.enqueue("a", Decimal("5000"))
    assert queue.next_business() == "b"


def test_removal_drops_a_business_from_contention() -> None:
    queue = FairQueue()
    queue.enqueue("a", Decimal("1"))
    queue.enqueue("b", Decimal("1"))
    queue.remove("a")
    assert queue.waiting == {"b"}
    assert queue.next_business() == "b"
