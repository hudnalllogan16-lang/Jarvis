"""The pending-update field-to-sentence table (design PLUGIN-FRAMEWORK.md Part
6, packet M8-9). `jarvis/api/pending_update.py` is the operator-language half
of a contract refresh — D-011-shaped, deterministic string formatting over
stored values, never a generic serializer and never model prose.

The diff computation itself (`plan_refresh`, packet M8-8) is not exercised
here: these tests build `FieldChange` sequences directly, the same shape a
real diff would hand this module, and check what an operator would read.
Three of the fixtures below reconstruct design Part 5's real scenarios
(Portfolio Watch, Trailhead Gear Reviews, Summit Trail Gear) so the rendered
sentences can be checked against the document's own worked examples.
"""

from __future__ import annotations

import pytest

from jarvis.api.pending_update import (
    SENTENCES,
    FieldChange,
    render_pending_update,
    sentence_for,
)
from jarvis.approvals.rendering import contains_technical_language

# ── Part 6's own worked examples ────────────────────────────────────────────


def test_direction_below_matches_the_design_docs_own_example() -> None:
    """design Part 6's table, verbatim: 'Data freshness — lower is better;
    this company was measuring it the wrong way round.'"""
    change = FieldChange(field="kpi_target_direction", label="Data freshness", direction="below")
    assert sentence_for(change) == (
        "Data freshness — lower is better; this company was measuring it the wrong way round."
    )


def test_capability_result_returned_dropped_matches_the_design_docs_own_example() -> None:
    """design Part 6's worked example (Trailhead Gear Reviews): 'It will stop
    starting a new round of work when its own work comes back.' The raw event
    name never appears in the rendered sentence."""
    change = FieldChange(field="wake_trigger_dropped", trigger="capability.result_returned")
    sentence = sentence_for(change)
    assert sentence == "It will stop starting a new round of work when its own work comes back."
    assert "capability" not in sentence.lower()
    assert "result_returned" not in sentence.lower()


# ── Part 5's three real companies, reconstructed ────────────────────────────


def test_portfolio_watch_diff_renders_one_sentence() -> None:
    """Part 5, Subject 1: `data_freshness_hours` gains `direction: below`;
    nothing else moves."""
    view = render_pending_update(
        company_name="Portfolio Watch",
        type_display_name="Finance tracker",
        changes=[
            FieldChange(field="kpi_target_direction", label="Data freshness", direction="below"),
        ],
    )
    assert view is not None
    assert view.headline == "Portfolio Watch — an update is ready for this company."
    assert view.intro == "The Finance tracker setup has changed since this company was created."
    assert view.changes == (
        "Data freshness — lower is better; this company was measuring it the wrong way round.",
    )


def test_trailhead_diff_renders_the_dropped_trigger_only() -> None:
    """Part 5, Subject 2: `event_triggers` drops `capability.result_returned`;
    `kpi_targets` and `compliance_requirements` are identical, so a real
    `plan_refresh` would not include them as changes at all."""
    view = render_pending_update(
        company_name="Trailhead Gear Reviews",
        type_display_name="Affiliate publisher",
        changes=[
            FieldChange(field="wake_trigger_dropped", trigger="capability.result_returned"),
        ],
    )
    assert view is not None
    assert view.headline == "Trailhead Gear Reviews — an update is ready for this company."
    assert view.changes == (
        "It will stop starting a new round of work when its own work comes back.",
    )


def test_summit_empty_diff_renders_nothing() -> None:
    """Part 5, Subject 3, the negative control: an empty diff must produce
    "already up to date" (nothing to render), not a blanket sentence that
    would look identical to a real change."""
    assert (
        render_pending_update(
            company_name="Summit Trail Gear", type_display_name="Affiliate publisher", changes=[]
        )
        is None
    )


# ── every mapped field renders something, and it stays clean ───────────────


@pytest.mark.parametrize(
    "change",
    [
        FieldChange(field="kpi_target_direction", label="Reports delivered", direction="above"),
        FieldChange(field="kpi_target_label", old="Monthly Revenue", new="Revenue (MTD)"),
        FieldChange(field="kpi_target_unit", label="Data freshness", old="hours", new="minutes"),
        FieldChange(field="kpi_target_added", label="Reports delivered"),
        FieldChange(field="kpi_target_dropped", label="Legacy metric"),
        FieldChange(
            field="kpi_target_value",
            label="Posts published",
            old="20",
            new="30",
            unit="posts/month",
        ),
        FieldChange(field="wake_schedule"),
        FieldChange(field="wake_trigger_added", trigger="approval.decided"),
        FieldChange(field="wake_trigger_dropped", trigger="approval.decided"),
        FieldChange(field="compliance_added", new="No trades over $500 without sign-off."),
        FieldChange(field="compliance_dropped", old="Reviewed weekly."),
    ],
)
def test_every_known_field_renders_a_clean_operator_sentence(change: FieldChange) -> None:
    sentence = sentence_for(change)
    assert sentence, f"{change.field} has no sentence"
    assert not contains_technical_language(sentence), sentence


def test_every_mapped_field_has_a_wake_trigger_or_a_direct_sentence() -> None:
    """`SENTENCES` and `_KNOWN_EVENT_TRIGGERS` together are the whole table
    (design Part 6): this is a completeness check against Part 4.2's list so
    the table cannot silently lose a field without a test noticing."""
    assert set(SENTENCES) == {
        "kpi_target_direction",
        "kpi_target_label",
        "kpi_target_unit",
        "kpi_target_added",
        "kpi_target_dropped",
        "kpi_target_value",
        "wake_schedule",
        "wake_trigger_added",
        "wake_trigger_dropped",
        "compliance_added",
        "compliance_dropped",
    }


# ── unrenderable is unrefreshable (design Part 6) ───────────────────────────


def test_an_unknown_field_renders_nothing() -> None:
    """A field with no sentence in the table must not render — Part 6: 'not
    renderable and therefore not refreshable' is a feature, not a gap."""
    assert sentence_for(FieldChange(field="something_new_and_unmapped")) is None


def test_an_unknown_event_trigger_renders_nothing() -> None:
    """Only the two triggers this platform actually uses have approved
    sentences; a future trigger must not leak its raw event name."""
    change = FieldChange(field="wake_trigger_dropped", trigger="kpi.threshold_breached")
    assert sentence_for(change) is None


def test_a_plan_of_only_unrenderable_changes_is_no_update_at_all() -> None:
    """If every change in a diff is unrenderable, the whole thing must read
    as no pending update — never a card with an empty change list."""
    assert (
        render_pending_update(
            company_name="Portfolio Watch",
            type_display_name="Finance tracker",
            changes=[FieldChange(field="something_new_and_unmapped")],
        )
        is None
    )


def test_unrenderable_changes_are_dropped_but_renderable_ones_still_show() -> None:
    view = render_pending_update(
        company_name="Portfolio Watch",
        type_display_name="Finance tracker",
        changes=[
            FieldChange(field="something_new_and_unmapped"),
            FieldChange(field="kpi_target_direction", label="Data freshness", direction="below"),
        ],
    )
    assert view is not None
    assert len(view.changes) == 1
