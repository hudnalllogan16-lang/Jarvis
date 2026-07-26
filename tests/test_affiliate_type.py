"""Affiliate type and D-014 tests (spec §4, §13 Step 2)."""

from __future__ import annotations

import ast
import pathlib

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.domain.contract import CapabilityType
from jarvis.kernel.ids import BusinessId

BIZ = BusinessId("biz_" + "0123456789abcdef" * 2)


def test_a_type_is_data_not_code() -> None:
    """D-014's proof obligation, asserted on the module's AST.

    If the affiliate module ever grows a function or class, a type has started
    to be code, and §4's "configuration only" instantiation is quietly dead.
    """
    tree = ast.parse(pathlib.Path("jarvis/businesses/affiliate.py").read_text())
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert definitions == [], "a business type must contain no logic (D-014)"


def test_definition_carries_everything_an_instance_needs() -> None:
    """Spec §4: instance creation is values over an installed definition.

    ProvisioningService.create_company takes the definition plus display name
    and optional budget numbers — nothing else. The definition must therefore
    carry the rest, and this asserts it does.
    """
    assert AFFILIATE.capability_permissions
    assert AFFILIATE.schedule_cron or AFFILIATE.event_triggers
    assert AFFILIATE.suggested_wake_ceiling_usd > 0
    assert AFFILIATE.suggested_budget_usd > 0


def test_definition_survives_registry_metadata_round_trip() -> None:
    """Definitions persist as Registry metadata (M5 reconciliation).

    A definition that cannot round-trip through JSON dies on restart, which is
    exactly the defect the in-process-dict design had (M5-F3).
    """
    raw = AFFILIATE.model_dump(mode="json")
    assert BusinessTypeDefinition.model_validate(raw) == AFFILIATE


def test_every_permitted_capability_has_a_prompt() -> None:
    """Install-time check that would otherwise be a first-cycle dead letter."""
    for permission in AFFILIATE.capability_permissions:
        assert f"affiliate.{permission.capability.value}" in AFFILIATE.prompt_templates


def test_missing_prompt_is_reported_before_install() -> None:
    """Install-time check (ProvisioningService.install refuses on this)."""
    payload = AFFILIATE.model_dump()
    payload["prompt_templates"] = {"affiliate.research": "only this one"}
    partial = BusinessTypeDefinition.model_validate(payload)
    missing = partial.missing_templates()
    assert "affiliate.content" in missing
    assert "affiliate.compliance" in missing


def test_publish_requires_approval_from_day_one() -> None:
    """Spec §8: approval by default, no exception at launch."""
    policy = next(
        p for p in AFFILIATE.autonomy_policies if p.action_type == "affiliate.publish_post"
    )
    assert policy.requires_approval


def test_wake_cycle_ceiling_is_explicit() -> None:
    """Defaults in Force: the ceiling MUST be explicit before launch."""
    assert AFFILIATE.suggested_wake_ceiling_usd is not None


def test_compliance_requirements_exist_for_owner_signoff() -> None:
    """Defaults in Force: owner reviews and signs off per type before launch."""
    assert len(AFFILIATE.compliance_requirements) >= 3
    assert any("disclos" in rule.lower() for rule in AFFILIATE.compliance_requirements)


def test_publish_tool_is_scoped_to_operations_only() -> None:
    """The effect-performing tool is not reachable from content generation."""
    for permission in AFFILIATE.capability_permissions:
        if permission.capability is not CapabilityType.OPERATIONS:
            assert "publish_post" not in permission.tool_scope
