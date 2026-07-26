"""Business lifecycle state machine (spec §0.1, decision D-008).

Spec §0.1 requires the Registry to track lifecycle state but names only
"active, paused, retired" without transition semantics. D-008 fills that gap.
Undefined transitions are the classic source of orphaned workflows and stranded
approvals, so the machine is explicit and total.

This module is deliberately dependency-free (standard library only) so the state
machine can be exercised in isolation and reused inside Temporal workflow code,
where imports must stay deterministic and side-effect free (D-004).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final, NamedTuple

from jarvis.kernel.errors import InvalidLifecycleTransitionError


class LifecycleState(StrEnum):
    """Lifecycle states of a registered business instance.

    Operator-facing wording for each state is fixed by D-007 and must be used on
    every UI surface (spec §12.5).
    """

    PROVISIONING = "provisioning"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRING = "retiring"
    RETIRED = "retired"


OPERATOR_LABELS: Final[Mapping[LifecycleState, str]] = {
    LifecycleState.PROVISIONING: "Setting up",
    LifecycleState.ACTIVE: "Running",
    LifecycleState.PAUSED: "Paused by you",
    LifecycleState.RETIRING: "Closing down",
    LifecycleState.RETIRED: "Closed",
}
"""Operator-facing labels (spec §12.5, D-007). The only strings the UI may show."""


_TRANSITIONS: Final[Mapping[LifecycleState, frozenset[LifecycleState]]] = {
    LifecycleState.PROVISIONING: frozenset({LifecycleState.ACTIVE, LifecycleState.RETIRING}),
    LifecycleState.ACTIVE: frozenset({LifecycleState.PAUSED, LifecycleState.RETIRING}),
    LifecycleState.PAUSED: frozenset({LifecycleState.ACTIVE, LifecycleState.RETIRING}),
    LifecycleState.RETIRING: frozenset({LifecycleState.RETIRED}),
    LifecycleState.RETIRED: frozenset(),
}


class TransitionEffects(NamedTuple):
    """Side effects the Registry must apply when a transition is committed.

    Returned rather than performed, so the state machine stays pure and the
    Registry remains the single component that touches infrastructure. Each
    field maps to an invariant in D-008.

    Attributes:
        cancel_wake_timers: Cancel all scheduled Manager wake timers (I-1).
        drain_in_flight: Allow in-flight cycles and invocations to terminate
            rather than killing them (I-1, I-3).
        block_new_dispatch: Refuse new capability dispatch for this business
            (I-4).
        revoke_credentials: Revoke this business's credential grants (I-5).
            Only ever true on entry to RETIRED.
    """

    cancel_wake_timers: bool
    drain_in_flight: bool
    block_new_dispatch: bool
    revoke_credentials: bool


_EFFECTS: Final[Mapping[LifecycleState, TransitionEffects]] = {
    LifecycleState.PROVISIONING: TransitionEffects(True, False, True, False),
    LifecycleState.ACTIVE: TransitionEffects(False, False, False, False),
    LifecycleState.PAUSED: TransitionEffects(True, True, True, False),
    LifecycleState.RETIRING: TransitionEffects(True, True, True, False),
    LifecycleState.RETIRED: TransitionEffects(True, False, True, True),
}


def allowed_transitions(state: LifecycleState) -> frozenset[LifecycleState]:
    """Return the states reachable in one step from ``state``.

    Args:
        state: Current lifecycle state.

    Returns:
        Frozen set of legal next states. Empty for terminal states.
    """
    return _TRANSITIONS[state]


def is_terminal(state: LifecycleState) -> bool:
    """Return whether ``state`` admits no further transitions."""
    return not _TRANSITIONS[state]


def accepts_dispatch(state: LifecycleState) -> bool:
    """Return whether a business in ``state`` may receive new capability dispatch.

    Only ACTIVE businesses accept new work (D-008, I-4).
    """
    return state is LifecycleState.ACTIVE


def validate_transition(current: LifecycleState, target: LifecycleState) -> TransitionEffects:
    """Validate a lifecycle transition and return the effects to apply.

    Args:
        current: The business's current state.
        target: The requested next state.

    Returns:
        The side effects the caller must apply on commit (D-008 invariants).

    Raises:
        InvalidLifecycleTransitionError: If the transition is not permitted.
            Raised for self-transitions too — re-pausing an already paused
            business is a caller bug, not a no-op, and silently absorbing it
            hides double-dispatch defects.
    """
    if target not in _TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(
            f"illegal lifecycle transition {current.value} -> {target.value}; "
            f"allowed: {sorted(s.value for s in _TRANSITIONS[current])}",
            operator_message=(
                f"This company is {OPERATOR_LABELS[current].lower()} "
                f"and can't be moved to {OPERATOR_LABELS[target].lower()} right now."
            ),
        )
    return _EFFECTS[target]
