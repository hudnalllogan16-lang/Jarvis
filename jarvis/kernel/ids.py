"""Typed identifiers.

Identifiers are permanent and never reused (spec §0.1). They are generated
outside workflow code — `new_*` helpers must be called from activities only, per
decision D-004, because UUID generation is nondeterministic and would break
replay if invoked inside a workflow.
"""

from __future__ import annotations

import uuid
from typing import NewType

BusinessId = NewType("BusinessId", str)
"""Permanent unique identifier for a business *instance* (spec §0.1)."""

BusinessTypeName = NewType("BusinessTypeName", str)
"""Stable name of an installed business *type*, e.g. ``affiliate``."""

InvocationId = NewType("InvocationId", str)
"""Identifier for a single capability invocation (spec §2.2)."""

DecisionId = NewType("DecisionId", str)
"""Identifier for one Decision Log entry (spec §11.5)."""

EventId = NewType("EventId", str)
"""Identifier for one event-bus event; the deduplication key per A-002."""

ApprovalId = NewType("ApprovalId", str)
"""Identifier for one approval request (spec §8)."""

NotificationId = NewType("NotificationId", str)
"""Identifier for one operator notification."""

CycleId = NewType("CycleId", str)
"""Identifier for one Business Manager wake cycle (spec §2.1, D-021).

A cycle begins when planning begins, so this is minted by the ``plan_cycle``
activity and threaded through dispatch, synthesis, and the decision record. It
is what gives §2.1's per-cycle cost ceiling something to count against."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_business_id() -> BusinessId:
    """Mint a permanent business instance identifier. Activity-only (D-004)."""
    return BusinessId(_new_id("biz"))


def new_invocation_id() -> InvocationId:
    """Mint a capability invocation identifier. Activity-only (D-004)."""
    return InvocationId(_new_id("inv"))


def new_decision_id() -> DecisionId:
    """Mint a Decision Log entry identifier. Activity-only (D-004)."""
    return DecisionId(_new_id("dec"))


def new_event_id() -> EventId:
    """Mint an event identifier. Activity-only (D-004)."""
    return EventId(_new_id("evt"))


def new_approval_id() -> ApprovalId:
    """Mint an approval identifier. Activity-only (D-004)."""
    return ApprovalId(_new_id("apr"))


def new_notification_id() -> NotificationId:
    """Mint a notification identifier. Activity-only (D-004)."""
    return NotificationId(_new_id("ntf"))


def new_cycle_id() -> CycleId:
    """Mint a wake-cycle identifier. Activity-only (D-004, D-021).

    Called from ``plan_cycle`` and nowhere else: D-021 fixes the start of a
    cycle at the start of planning, and minting it anywhere earlier would let a
    Manager parked for hours open its cycle before it began reasoning, which
    makes the §2.1 ceiling's window meaningless.
    """
    return CycleId(_new_id("cyc"))
