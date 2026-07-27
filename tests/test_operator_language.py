"""Executable §12.5 compliance (spec §12.5, §1).

§12.5 says a technically correct implementation that fails it is "a spec
violation, not a 'polish later' item", and lists the concepts an operator must
never meet in the default UI. That is a testable property, so it is tested
rather than left to review discipline — review catches it once, a test catches
it on every commit.

The forbidden list is §12.5's own, verbatim: workflows, DAGs, agents, workers,
capabilities, prompts, tokens, wake cycles, Temporal, event bus, orchestration,
credential scopes, retries, dead-letter queues.
"""

from __future__ import annotations

import pytest

from jarvis.approvals.models import OPERATOR_LABELS as APPROVAL_LABELS
from jarvis.approvals.models import ApprovalRequest
from jarvis.approvals.rendering import (
    contains_technical_language,
    render_detail,
    render_failure,
    render_request,
)
from jarvis.domain.lifecycle import OPERATOR_LABELS as LIFECYCLE_LABELS
from jarvis.kernel.ids import BusinessId
from tests.surface_sources import (
    MARKUP,
    script_literals,
    surface_text,
    visible_text,
)

FORBIDDEN = [
    "workflow",
    "dag",
    "agent",
    "worker",
    "capability",
    "prompt",
    "token",
    "wake cycle",
    "woken",
    "temporal",
    "event bus",
    "orchestration",
    "credential scope",
    "retry",
    "dead-letter",
    "dead letter",
    "business",
]
"""§12.5's own list, plus two morphological gaps the runtime guard
(`contains_technical_language`) also had to close (M6 product re-review,
runtime term coverage): "woken" is a form of "wake cycle" a phrase check
never catches, and "business" is D-007's own Business -> Company term, never
previously listed at all."""


def test_dashboard_exists() -> None:
    assert MARKUP.exists(), "the operator dashboard is a §12.5 deliverable"


@pytest.mark.parametrize("term", FORBIDDEN)
def test_dashboard_markup_avoids_infrastructure_vocabulary(term: str) -> None:
    """Spec §12.5's default-view prohibition, applied to the shipped markup."""
    assert term not in visible_text().lower()


@pytest.mark.parametrize("term", FORBIDDEN)
def test_operator_facing_strings_in_the_dashboard_script(term: str) -> None:
    """The behaviour modules build most of the visible copy, so their string
    literals count. `surface_sources` resolves which files those are — after
    the M8-2 decomposition the copy lives in `static/app/*.js`, not in an
    inline `<script>`."""
    assert term not in script_literals().lower()


def test_doing_now_label_matches_past_tense_content() -> None:
    """M7 product re-review F3: the company card rendered past-tense Decision
    Log summaries (what a cycle already did) under the present-tense label
    "Doing now" -- a post-mortem sentence does not answer "what is happening
    right now". Renamed to a label the content can honestly satisfy."""
    html = surface_text()
    assert "Doing now" not in html
    assert "Latest update" in html


def test_doing_now_truncation_carries_a_details_affordance() -> None:
    """M7 product re-review F3: truncated text gave no signal that there was
    more to read. `render_doing_now` always ends truncated text with an
    ellipsis, so the card can detect that case and offer an explicit link
    into the same Details drill-down the button below already opens."""
    # Explicit UTF-8: the file's ellipsis character must round-trip exactly
    # for this assertion, and the platform's default text encoding is not
    # guaranteed to be UTF-8 (Windows locales commonly are not).
    # `surface_sources` reads every source as UTF-8 for the same reason.
    html = surface_text()
    assert "more in Details" in html
    assert "c.doing.endsWith('…')" in html


def test_goal_reading_does_not_stutter_measured_not_measured() -> None:
    """M7-5b item 3: an unmeasured KPI target rendered "measured not measured
    yet" — the same word twice in four words. Pinned so it cannot return."""
    html = surface_text()
    assert "measured not measured yet" not in html


def test_all_unmeasured_goals_collapse_to_one_sentence() -> None:
    """M7-5b item 3: when every goal is unmeasured — the whole drill-down for
    both affiliate companies live — one clean sentence replaces what would
    otherwise be a per-target list of "not measured yet" stutters."""
    html = surface_text()
    assert "goals.every(g => g.measured === null)" in html


def test_kind_and_kind_description_are_escaped_before_rendering() -> None:
    """M7-5b item 4: `c.kind`/`c.kind_description` interpolated straight into
    markup, unescaped, against the dashboard script's own stated invariant —
    "nothing on this card is trusted text... every value is escaped before it
    becomes markup." Pinned structurally so a future edit cannot quietly drop
    `esc()` from either again."""
    html = surface_text()
    assert "${esc(c.kind)}" in html
    assert "${esc(c.kind_description)}" in html
    assert "${c.kind}" not in html
    assert "${c.kind_description}" not in html


def test_create_dialog_error_uses_the_error_style_not_the_timestamp_style() -> None:
    """M7 product re-review F4: "Give it a name first." rendered in `.waited`
    -- an 11px grey mono class built for a card's "waiting 3h ago" timestamp,
    not an error. The stylesheet's `.formErr` (risk colour) existed unused for
    exactly this; the create-dialog error now uses it, positioned before the
    action buttons rather than trailing after them."""
    html = surface_text()
    assert 'class="formErr" id="newErr"' in html
    assert 'class="waited" id="newErr"' not in html


def test_lifecycle_labels_are_plain_language() -> None:
    """Spec §12.5, D-007: every state has an operator-facing term."""
    for label in LIFECYCLE_LABELS.values():
        assert not contains_technical_language(label)
        assert label[0].isupper()


def test_approval_labels_are_plain_language() -> None:
    for label in APPROVAL_LABELS.values():
        assert not contains_technical_language(label)


def _request(**over: object) -> ApprovalRequest:
    base: dict[str, object] = {
        "approval_id": "apr_1",
        "business_id": BusinessId("biz_" + "0123456789abcdef" * 2),
        "action_type": "affiliate.publish_post",
        "action_summary": "publish today's post",
        "triggering_condition": "Today's post is ready.",
        "downside": "A weak post could lose a few readers.",
    }
    base.update(over)
    return ApprovalRequest(**base)  # type: ignore[arg-type]


def test_approval_reads_as_a_sentence_about_a_company() -> None:
    """§12.5's example shape: "Trading Fund wants to buy 50 shares (~$X)."."""
    rendered = render_request(_request(), "Affiliate Co")
    assert rendered == "Affiliate Co wants to publish today's post."
    assert not contains_technical_language(rendered)


def test_amount_is_rendered_from_the_stored_value() -> None:
    """§8 requires the exact amount. It is formatted, never regenerated."""
    from decimal import Decimal

    rendered = render_request(_request(amount_usd=Decimal("1250.5")), "Trading Fund")
    assert "$1,250.50" in rendered


def test_approval_detail_covers_all_four_facts_section_8_requires() -> None:
    from decimal import Decimal

    detail = render_detail(_request(amount_usd=Decimal("50")), "Affiliate Co")
    assert set(detail) == {"What happens", "How much", "Why now", "What could go wrong"}
    for value in detail.values():
        assert not contains_technical_language(value)


def test_approval_detail_omits_amount_for_non_capital_actions() -> None:
    """Showing "$0.00" on an action that moves no money is a lie of format."""
    assert "How much" not in render_detail(_request(), "Affiliate Co")


def test_failures_read_as_consequences_not_error_codes() -> None:
    """§12.5's own example, inverted: never "Job failed: retry 2/3"."""
    rendered = render_failure("Affiliate Co", "publish today's post")
    assert rendered == "Affiliate Co couldn't publish today's post — Jarvis is trying again."
    assert not contains_technical_language(rendered)


@pytest.mark.parametrize(
    "template",
    [
        "CEILING_STOP_SUMMARY",
        "CEILING_STOP_RATIONALE",
        "CYCLE_FAILED_SUMMARY",
        "CYCLE_FAILED_RATIONALE",
        "DEPENDENCY_SKIP_REASON",
    ],
)
def test_manager_cycle_outcomes_are_written_for_the_operator(template: str) -> None:
    """§12.5 applies to the Decision Log, not only to the dashboard.

    A cycle that fails or stops on budget writes one of these into the activity
    feed, which is the operator's first answer to "what is this company doing" —
    so it must never arrive as "the workflow failed" or "retries exhausted".
    """
    from jarvis.manager import workflow as manager_workflow

    text = str(getattr(manager_workflow, template)).format(name="Affiliate Co")
    assert not contains_technical_language(text)
    assert text.endswith(".")


@pytest.mark.parametrize(
    "template",
    [
        "MANAGER_PARKED_SUMMARY",
        "MANAGER_PARKED_RATIONALE",
        "MANAGER_PARKED_TITLE",
        "MANAGER_PARKED_BODY",
    ],
)
def test_the_park_records_are_written_for_the_operator(template: str) -> None:
    """§12.5 for D-034.1's records, which live in the activity, not the workflow.

    A Manager that cannot read its own context writes a Decision Log entry and
    raises a notification, and both reach the operator's default view. They are
    authored in `jarvis/manager/activities.py` rather than beside the branch that
    chooses them, because the sentence names the company and the display name is
    exactly what the failed read could not deliver — so they need the same guard
    the workflow's own templates get above, applied where they actually are.
    """
    from jarvis.manager import activities as manager_activities

    text = str(getattr(manager_activities, template)).format(name="Affiliate Co")
    assert not contains_technical_language(text)
    assert text[0].isupper()


def test_the_park_notification_body_adds_to_its_title() -> None:
    """A notification whose body restates its title tells an operator nothing
    they have not already read. The title names the company; the body says what
    it means and that nobody has to do anything about it."""
    from jarvis.manager.activities import MANAGER_PARKED_BODY, MANAGER_PARKED_TITLE

    assert MANAGER_PARKED_TITLE.format(name="Affiliate Co") not in MANAGER_PARKED_BODY
    assert MANAGER_PARKED_BODY.endswith(".")


def test_the_detector_actually_detects() -> None:
    """A guard that never fires is worse than none: it reads as coverage."""
    assert contains_technical_language("the workflow failed")
    assert contains_technical_language("retry 2/3")
    assert not contains_technical_language("Affiliate Co is publishing today's post")


def test_detector_catches_morphological_variants_missed_live() -> None:
    """Runtime term coverage (M6 product re-review, carried into M7-2):
    "woken" and "business" passed the guard live because a plain phrase/word
    check for "wake cycle" and a missing "business" entry both left a gap a
    model's own prose walked straight through."""
    assert contains_technical_language("Acme Co was woken by a new order.")
    assert contains_technical_language("The business is waiting on your OK.")
    # Plurals/inflections that a bare word-boundary match on the singular
    # form would silently stop catching (word boundaries need a non-word
    # character on both sides, so "worker" alone does not match "workers").
    assert contains_technical_language("Two workers picked up the task.")
    assert contains_technical_language("Both capabilities are unavailable.")


def test_detector_catches_milestone_codenames_and_kpi() -> None:
    """M7-F50 (packet M7-5a item 4): live Manager prose reached the operator
    feed echoing internal framing ("the M7 targets"), and D-027.2 makes `KPI`
    a name this codebase uses for itself, never one an owner was taught."""
    assert contains_technical_language("Acme Co hit the M7 targets early.")
    assert contains_technical_language("Tracked against M6 milestones.")
    assert contains_technical_language("Scoped for M8, not this quarter.")
    assert contains_technical_language("The KPI moved up this week.")
    assert contains_technical_language("Both KPIs improved.")


def test_milestone_codename_guard_does_not_false_positive_on_similar_tokens() -> None:
    """A word-boundary match, the same shape as `wake cycle`/`woken`: a real
    boundary requires a non-word character on both sides, so a milestone
    codename embedded in a longer alphanumeric token is not itself the
    codename."""
    assert not contains_technical_language("Acme Co reviewed model M7Zephyr today.")
    assert not contains_technical_language("The company processed item m70 today.")


def test_compliance_requirements_would_trip_the_guard_and_must_stay_off_its_path() -> None:
    """D-027.5 stores the owner's rules verbatim, four beginning "During M7"
    by design (DECISIONS.md correction F-C) — quoting them is D-011's
    direction, not against it. This pins that fact so a future change
    routing `compliance_requirements` through `contains_technical_language`/
    `render_operator_text` (the M7-F50 guard, packet M7-5a item 4) fails
    loudly instead of quietly laundering the owner's own rules.

    `render_operator_text`'s only callers today are the Decision Log feed and
    notifications (`jarvis/api/app.py`, `jarvis/api/render.py`);
    `compliance_requirements` reaches only the planning prompt
    (`jarvis/manager/activities.py`) and is never rendered through either.
    """
    from jarvis.businesses.finance import FINANCE

    assert any(contains_technical_language(rule) for rule in FINANCE.compliance_requirements)


def test_detector_does_not_false_positive_on_related_english_words() -> None:
    """The boundary this guard has to hold, chosen deliberately rather than
    copied: a word-boundary match must not flag a real word that merely
    contains a forbidden one as a substring, or every sentence using ordinary
    English becomes a false alarm.

    "awoken" is the sharpest case here, not a softball one: it is a genuine
    morphological sibling of "woken" (both inflect "wake"), and a naive
    substring check would have flagged it for free since "woken" sits inside
    it literally. A word-boundary match does not, because there is no
    boundary between the "a" and "woken" in "awoken" -- which is exactly the
    property this fix relies on elsewhere to avoid banning "businesslike" for
    containing "business". Both stand or fall on the same mechanism, so both
    are asserted here rather than assumed.
    """
    assert not contains_technical_language("Acme Co finally awoken from its slow start.")
    assert not contains_technical_language("A businesslike tone suits this reply.")
    assert not contains_technical_language("The team stayed busy all week.")
    assert not contains_technical_language("Affiliate Co is publishing today's post.")


def test_no_duplicate_request_models() -> None:
    """No two Pydantic request models in the API share a name (regression: M5-F7).

    A duplicate class definition silently shadows the earlier one, so a route can
    validate against a different model than its body reads — which is exactly how
    the create-company contract broke after the M5 reconciliation. This asserts on
    the module's AST so a re-duplication fails the build instead of the UI.
    """
    import ast
    import pathlib as _pl

    tree = ast.parse(_pl.Path("jarvis/api/app.py").read_text())
    class_names = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    duplicates = {n for n in class_names if class_names.count(n) > 1}
    assert not duplicates, f"duplicate class definitions in api/app.py: {duplicates}"
