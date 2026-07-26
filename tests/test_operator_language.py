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

import pathlib
import re

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

DASHBOARD = pathlib.Path("jarvis/api/static/index.html")

FORBIDDEN = [
    "workflow",
    "dag",
    "agent",
    "worker",
    "capability",
    "prompt",
    "token",
    "wake cycle",
    "temporal",
    "event bus",
    "orchestration",
    "credential scope",
    "retry",
    "dead-letter",
    "dead letter",
]


def _visible_text(html: str) -> str:
    """Return only what an operator can actually read.

    Strips <style>, <script>, and tag internals. Comments explaining *why* a
    rule exists are developer-facing and legitimately name the concepts they
    are avoiding, so counting them would make the test unpassable for the right
    reasons.
    """
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return html


def test_dashboard_exists() -> None:
    assert DASHBOARD.exists(), "the operator dashboard is a §12.5 deliverable"


@pytest.mark.parametrize("term", FORBIDDEN)
def test_dashboard_markup_avoids_infrastructure_vocabulary(term: str) -> None:
    """Spec §12.5's default-view prohibition, applied to the shipped markup."""
    assert term not in _visible_text(DASHBOARD.read_text()).lower()


@pytest.mark.parametrize("term", FORBIDDEN)
def test_operator_facing_strings_in_the_dashboard_script(term: str) -> None:
    """The JS builds most of the visible copy, so its string literals count."""
    source = DASHBOARD.read_text()
    script = "".join(re.findall(r"<script.*?>(.*?)</script>", source, flags=re.S))
    script = re.sub(r"//.*", "", script)
    literals = " ".join(re.findall(r"['\"`]([^'\"`]{4,})['\"`]", script))
    # API paths are addresses, not copy; an operator never reads them.
    literals = re.sub(r"/api/\S*", " ", literals)
    assert term not in literals.lower()


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


def test_the_detector_actually_detects() -> None:
    """A guard that never fires is worse than none: it reads as coverage."""
    assert contains_technical_language("the workflow failed")
    assert contains_technical_language("retry 2/3")
    assert not contains_technical_language("Affiliate Co is publishing today's post")


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
