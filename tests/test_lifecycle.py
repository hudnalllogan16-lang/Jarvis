"""Lifecycle state machine tests (spec §0.1, D-008)."""

from __future__ import annotations

import itertools

import pytest

from jarvis.domain.lifecycle import (
    OPERATOR_LABELS,
    LifecycleState,
    accepts_dispatch,
    allowed_transitions,
    is_terminal,
    validate_transition,
)
from jarvis.kernel.errors import InvalidLifecycleTransitionError


def test_every_state_has_an_operator_label() -> None:
    """Spec §12.5 requires an operator-facing surface for every concept."""
    assert set(OPERATOR_LABELS) == set(LifecycleState)
    assert all(label for label in OPERATOR_LABELS.values())


def test_retired_is_the_only_terminal_state() -> None:
    terminal = {s for s in LifecycleState if is_terminal(s)}
    assert terminal == {LifecycleState.RETIRED}


def test_every_state_can_reach_retired() -> None:
    """No business may become unclosable, or the operator cannot shut it down."""
    for start in LifecycleState:
        seen, frontier = {start}, [start]
        while frontier:
            for nxt in allowed_transitions(frontier.pop()):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        assert LifecycleState.RETIRED in seen


def test_only_active_accepts_dispatch() -> None:
    """D-008 I-4: draining and paused businesses accept no new work."""
    accepting = {s for s in LifecycleState if accepts_dispatch(s)}
    assert accepting == {LifecycleState.ACTIVE}


def test_pause_cancels_timers_but_drains_rather_than_kills() -> None:
    """D-008 I-1 and I-3."""
    effects = validate_transition(LifecycleState.ACTIVE, LifecycleState.PAUSED)
    assert effects.cancel_wake_timers
    assert effects.drain_in_flight
    assert effects.block_new_dispatch
    assert not effects.revoke_credentials


def test_credentials_revoked_only_on_retired() -> None:
    """D-008 I-5: a draining business still needs credentials to finish work."""
    draining = validate_transition(LifecycleState.ACTIVE, LifecycleState.RETIRING)
    assert not draining.revoke_credentials
    retired = validate_transition(LifecycleState.RETIRING, LifecycleState.RETIRED)
    assert retired.revoke_credentials


def test_illegal_transition_raises_with_operator_message() -> None:
    with pytest.raises(InvalidLifecycleTransitionError) as exc:
        validate_transition(LifecycleState.RETIRED, LifecycleState.ACTIVE)
    assert "stack" not in exc.value.operator_message.lower()
    assert exc.value.operator_message


def test_self_transition_is_rejected_not_absorbed() -> None:
    """Re-pausing a paused business is a caller bug, not a no-op."""
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_transition(LifecycleState.PAUSED, LifecycleState.PAUSED)


# ── Exhaustive transition matrix (all 25 state pairs) ────────────────────────
#
# The earlier tests above named two illegal transitions out of eighteen. Spot
# checks are how an accidentally-permitted transition survives review, so the
# matrix is enumerated rather than sampled.

_LEGAL: frozenset[tuple[LifecycleState, LifecycleState]] = frozenset(
    {
        (LifecycleState.PROVISIONING, LifecycleState.ACTIVE),
        (LifecycleState.PROVISIONING, LifecycleState.RETIRING),
        (LifecycleState.ACTIVE, LifecycleState.PAUSED),
        (LifecycleState.ACTIVE, LifecycleState.RETIRING),
        (LifecycleState.PAUSED, LifecycleState.ACTIVE),
        (LifecycleState.PAUSED, LifecycleState.RETIRING),
        (LifecycleState.RETIRING, LifecycleState.RETIRED),
    }
)
"""The complete legal set, written out independently of the implementation.

Deliberately a second, hand-maintained copy of the transition table: asserting
the implementation against itself would pass no matter what the table said.
"""

_ALL_PAIRS = list(itertools.product(LifecycleState, repeat=2))


@pytest.mark.parametrize(("current", "target"), _ALL_PAIRS, ids=lambda s: s.value)
def test_transition_matrix_is_exhaustively_specified(
    current: LifecycleState, target: LifecycleState
) -> None:
    """Every one of the 25 state pairs is either explicitly legal or rejected."""
    if (current, target) in _LEGAL:
        assert validate_transition(current, target) is not None
    else:
        with pytest.raises(InvalidLifecycleTransitionError):
            validate_transition(current, target)


def test_no_self_transition_is_legal() -> None:
    """Re-entering a state is always a caller bug, never absorbed as a no-op."""
    assert not any((s, s) in _LEGAL for s in LifecycleState)


def test_implementation_and_expected_matrix_agree_in_size() -> None:
    """Guards against a legal transition being added without updating _LEGAL."""
    implemented = {(a, b) for a in LifecycleState for b in allowed_transitions(a)}
    assert implemented == _LEGAL
