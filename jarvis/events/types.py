"""Bus event type constants (spec §2).

These exist because their absence caused a real defect. The approval subsystem
recorded an *audit* entry named ``approval.decided`` and never published a *bus*
event of the same name. Searching the codebase found matches, the D-006
continuation loop looked closed, and it was not: a business that asked for
approval would never resume.

Two logs and one bus share a naming style, so a name alone proves nothing about
where a message went. Bus event types live here and nowhere else, which makes
"is this published?" answerable by looking at one file — and makes it
mechanically checkable, which `tests/test_event_loop_closure.py` does.
"""

from __future__ import annotations

from typing import Final

APPROVAL_DECIDED: Final = "approval.decided"
"""An operator answered. Wakes the Manager that raised it (D-006)."""

CAPABILITY_RESULT: Final = "capability.result_returned"
"""A dispatched invocation reached a terminal state (§2.1 wake condition)."""

KPI_THRESHOLD_BREACHED: Final = "kpi.threshold_breached"
"""A tracked metric crossed a configured bound (§2.1 wake condition)."""

BUSINESS_ACTIVATED: Final = "business.activated"
"""A business entered ACTIVE and its Manager should begin (§0.1, §2.1)."""

ALL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        APPROVAL_DECIDED,
        CAPABILITY_RESULT,
        KPI_THRESHOLD_BREACHED,
        BUSINESS_ACTIVATED,
    }
)
"""Every type that may be published. A business's `event_triggers` must be a
subset of this: subscribing to a type nobody publishes is a silent dead end,
which is exactly the failure mode this module was created to prevent."""
