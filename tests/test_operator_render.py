"""Decision Log render-boundary tests (spec §12.5, §11.5; M6-5a item 4).

`jarvis/api/render.py` is the one place live Manager prose is laundered for
the operator surface, because the Decision Log itself is append-only (A-006)
and cannot be edited after the fact. These tests exercise the boundary
directly rather than through the live database, so the runtime guard is
proven regardless of what today's data happens to contain.
"""

from __future__ import annotations

from jarvis.api.render import (
    DOING_NOW_LIMIT,
    NEUTRAL_FALLBACK,
    render_doing_now,
    render_operator_text,
)


def test_platform_ids_are_stripped_from_live_prose() -> None:
    """Found live (M6-5a): a Manager's own rationale read "An approval request
    (apr_1a161be0303c4cf5910e51e50c7d6775) is pending review" — an internal
    reference no operator asked to see."""
    raw = "An approval request (apr_1a161be0303c4cf5910e51e50c7d6775) is pending review."
    rendered = render_operator_text(raw)
    assert "apr_" not in rendered
    assert "1a161be0303c4cf5910e51e50c7d6775" not in rendered


def test_id_only_parenthetical_is_dropped_whole() -> None:
    """M6 product re-review F2: id-stripping used to leave the parenthetical
    behind — "An approval request (something) is pending review." — which
    reads as a bug, not a redaction. The live-observed sentence now collapses
    to plain prose with the vestigial parens gone entirely."""
    raw = "An approval request (apr_1a161be0303c4cf5910e51e50c7d6775) is pending review."
    assert render_operator_text(raw) == "An approval request is pending review."
    assert "(something)" not in render_operator_text(raw)


def test_id_only_parenthetical_with_multiple_ids_is_dropped_whole() -> None:
    """The same vestigial-parens shape with more than one id inside."""
    raw = "Linked to the pending request (apr_1a2b3c4d5e6f, biz_1a2b3c4d5e6f) already."
    assert render_operator_text(raw) == "Linked to the pending request already."


def test_parenthetical_mixing_an_id_with_other_words_keeps_its_parens() -> None:
    """Only a parenthetical that is *nothing but* ids is vestigial. One that
    also carries real words is left with its parens intact — id-stripped, not
    id-and-parens-stripped, or real content would be silently deleted."""
    raw = "The report (see apr_1a2b3c4d5e6f for detail) is ready."
    rendered = render_operator_text(raw)
    assert rendered == "The report (see something for detail) is ready."


def test_business_and_cycle_ids_are_also_stripped() -> None:
    raw = "biz_5908873296374587aa15121f0a369ec1 finished cyc_23f8c78a79e24105ad11a97079cb568d."
    rendered = render_operator_text(raw)
    assert "biz_" not in rendered
    assert "cyc_" not in rendered


def test_raw_lifecycle_words_translate_per_d007() -> None:
    """Found live (M6-5a): a transition wrote "moved from provisioning to
    active" straight into the activity feed. The write path is fixed at its
    source (registry.py); this is the render-time backstop."""
    rendered = render_operator_text("Acme Co moved from provisioning to active.")
    assert rendered == "Acme Co moved from Setting up to Running."


def test_technical_prose_falls_back_to_a_neutral_line() -> None:
    """The runtime guard: text that still reads as technical after cleanup is
    replaced outright, never shown with just the flagged word missing."""
    rendered = render_operator_text("Retrying the capability invocation after a worker crash.")
    assert rendered == NEUTRAL_FALLBACK


def test_clean_prose_passes_through_unchanged() -> None:
    raw = "Drafted a new blog post and researched topics for next week."
    assert render_operator_text(raw) == raw


def test_doing_now_is_capped_with_an_ellipsis() -> None:
    raw = "x" * 200
    rendered = render_doing_now(raw)
    assert len(rendered) == DOING_NOW_LIMIT + 1  # + the ellipsis character
    assert rendered.endswith("…")


def test_doing_now_leaves_short_text_untouched() -> None:
    raw = "Published today's post."
    assert render_doing_now(raw) == raw


def test_doing_now_still_applies_the_technical_language_guard() -> None:
    raw = "Retrying " + "a" * 200
    assert render_doing_now(raw) == NEUTRAL_FALLBACK
