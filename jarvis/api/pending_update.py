"""Operator rendering for a pending company-template update (design Part 6, D-030).

Design Part 4 (`docs/design/PLUGIN-FRAMEWORK.md`) splits a contract refresh into
two questions. *Whether* a company's stored contract differs from its
installed type's current definition — the Band-B diff — is `plan_refresh`
(Part 4.4, packet M8-8, platform-engineer, opus-reviewed because its sibling
`apply_refresh` is a stored-contract write path). *What the operator reads*
about that diff is Part 6, this packet, this module: "the diff is rendered per
changed field, from a platform-owned table of sentences keyed on the field,
filled from stored values — never a generic serializer, and never model
prose." A field with no sentence below is not renderable and therefore not
refreshable — Part 6 calls this out as a feature, not a gap: a new Band-B
field cannot reach an operator until someone writes the sentence.

**Coordination note for whoever reconciles this against M8-8's merge.** This
module owns the render half only. `FieldChange` is this lane's best-effort
shape for "one Band-B field that differs" — built from Part 4.2's own table,
not from M8-8's `ContractRefreshPlan` (which had not merged into this worktree
at the time this packet ran; see the M8-9 report). `jarvis/api/app.py`'s
`_pending_update` seam always returns `None` today, which is the correct and
safe default while no diff mechanism is wired in (Part 4.3: the un-consented
state is today's status quo, so this is not a regression). Wiring the real
`plan_refresh` output through to :func:`render_pending_update` — adapting
either shape to the other — is the integration step that lands with M8-8.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

_KNOWN_EVENT_TRIGGERS: dict[str, dict[str, str]] = {
    # M6-F10: every capability result is already awaited inside the cycle that
    # requested it (D-001), so a company still subscribed to this event wakes
    # itself from its own output — a self-sustaining loop bounded only by
    # `max_cycles_per_day`. This is the design doc's own worked example
    # (Part 6, Trailhead Gear Reviews) and the wording is taken verbatim from
    # it. The raw event name is a dict KEY here, never interpolated into a
    # sentence — it is machinery vocabulary and must never reach the operator.
    "capability.result_returned": {
        "dropped": "It will stop starting a new round of work when its own work comes back.",
        "added": "It will start a new round of work automatically when its own work comes back.",
    },
    "approval.decided": {
        "dropped": "It will stop starting a new round of work after you answer a request for it.",
        "added": (
            "It will start a new round of work automatically after you answer a request for it."
        ),
    },
}
"""Which wake triggers have an approved sentence. `event_triggers` is a
`frozenset` of platform event names (`jarvis/events/types.py`) — exactly the
kind of raw machinery vocabulary Part 6 forbids rendering directly ("never a
generic serializer"). A trigger not listed here does not render, by the same
rule that makes an unmapped field unrenderable."""


@dataclass(frozen=True)
class FieldChange:
    """One Band-B field that differs between a stored contract and the
    installed type's current definition (design Part 4.2).

    `field` is a closed vocabulary — see :data:`SENTENCES` and
    :data:`_KNOWN_EVENT_TRIGGERS` for the complete set this module can render.
    Every other attribute is a stored value already: a KPI's own
    `operator_label`/`unit`, an owner's own compliance sentence, a platform
    event name — never free text authored at diff time (D-011).
    """

    field: str
    label: str = ""
    old: str = ""
    new: str = ""
    unit: str = ""
    trigger: str = ""
    direction: str = ""


def _kpi_target_direction(c: FieldChange) -> str | None:
    if c.direction == "below":
        return f"{c.label} — lower is better; this company was measuring it the wrong way round."
    if c.direction == "above":
        return f"{c.label} — higher is better now, not lower."
    return None


def _kpi_target_label(c: FieldChange) -> str:
    return f'This company\'s goal called "{c.old}" is now called "{c.new}".'


def _kpi_target_unit(c: FieldChange) -> str:
    return f"{c.label} is now measured in {c.new} instead of {c.old}."


def _kpi_target_added(c: FieldChange) -> str:
    return f"Jarvis will start tracking a new goal for this company: {c.label}."


def _kpi_target_dropped(c: FieldChange) -> str:
    return f"Jarvis will stop tracking {c.label} as a goal for this company."


def _kpi_target_value(c: FieldChange) -> str:
    return f"The goal for {c.label} is changing from {c.old} {c.unit} to {c.new} {c.unit}."


def _wake_schedule(_c: FieldChange) -> str:
    # The cron expression itself is never rendered (Part 6: "raw field names
    # of any kind" never reach the operator) — only the fact that it moved.
    return "The days and times when this company checks in for new work are changing."


def _wake_trigger(c: FieldChange) -> str | None:
    sentences = _KNOWN_EVENT_TRIGGERS.get(c.trigger)
    if sentences is None:
        return None
    verb = "dropped" if c.field == "wake_trigger_dropped" else "added"
    return sentences[verb]


def _compliance_added(c: FieldChange) -> str:
    return f'Jarvis will start following this rule: "{c.new}".'


def _compliance_dropped(c: FieldChange) -> str:
    return f'Jarvis will stop following this rule: "{c.old}".'


SENTENCES: dict[str, Callable[[FieldChange], str | None]] = {
    "kpi_target_direction": _kpi_target_direction,
    "kpi_target_label": _kpi_target_label,
    "kpi_target_unit": _kpi_target_unit,
    "kpi_target_added": _kpi_target_added,
    "kpi_target_dropped": _kpi_target_dropped,
    "kpi_target_value": _kpi_target_value,
    "wake_schedule": _wake_schedule,
    "wake_trigger_added": _wake_trigger,
    "wake_trigger_dropped": _wake_trigger,
    "compliance_added": _compliance_added,
    "compliance_dropped": _compliance_dropped,
}
"""The platform-owned table of sentences keyed on the field (design Part 6).
Every value is deterministic string formatting over stored values — the same
shape `jarvis/approvals/rendering.py` uses for D-011, applied to a refresh
diff instead of an approval. A `field` absent from this table renders
nothing: Part 6 calls that "a feature, because it means a new Band B field
cannot reach an operator without someone writing the sentence"."""


def sentence_for(change: FieldChange) -> str | None:
    """Render one field change, or None if it has no approved sentence yet."""
    renderer = SENTENCES.get(change.field)
    return renderer(change) if renderer else None


@dataclass(frozen=True)
class PendingUpdateView:
    """What the operator surface shows for one company's pending update."""

    headline: str
    intro: str
    changes: tuple[str, ...] = field(default_factory=tuple)


def render_pending_update(
    *, company_name: str, type_display_name: str, changes: Sequence[FieldChange]
) -> PendingUpdateView | None:
    """Build the operator-facing view for a company's pending update.

    Args:
        company_name: The company's stored display name (D-007).
        type_display_name: The installed type's stored display name, e.g.
            "Affiliate publisher" — used exactly as Part 6's own worked
            example phrases it: "The {type} setup has changed since this
            company was created."
        changes: Every Band-B field the diff found different. Order is
            preserved in the rendered list.

    Returns:
        None if `changes` is empty or none of them has an approved sentence
        (Part 6: unrenderable is unrefreshable) — the caller's correct
        response to None is to show nothing, which is also today's status
        quo and therefore always safe.
    """
    rendered = [s for s in (sentence_for(c) for c in changes) if s is not None]
    if not rendered:
        return None
    return PendingUpdateView(
        headline=f"{company_name} — an update is ready for this company.",
        intro=f"The {type_display_name} setup has changed since this company was created.",
        changes=tuple(rendered),
    )


__all__ = [
    "SENTENCES",
    "FieldChange",
    "PendingUpdateView",
    "render_pending_update",
    "sentence_for",
]
