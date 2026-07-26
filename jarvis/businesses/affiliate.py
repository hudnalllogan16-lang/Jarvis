"""The Affiliate Business type (spec §13 Step 2).

The first full business type, and deliberately the proof of D-014: this module
contains **no logic** — no class, no function, no branch (asserted by
tests/test_affiliate_type.py against the AST). If the second type (M6) needs
more than a module shaped like this one, D-014 was wrong and the failure will be
visible rather than absorbed.

Per §13 Step 2 the Affiliate Business uses the Research, Content, and Compliance
capabilities, the standard contract, the autonomy ladder, and the Decision Log.
Everything below configures those; nothing below implements anything.
"""

from __future__ import annotations

from decimal import Decimal

from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.domain.contract import (
    AutonomyPolicy,
    CapabilityPermission,
    CapabilityType,
    KpiTarget,
)
from jarvis.events.types import APPROVAL_DECIDED

AFFILIATE = BusinessTypeDefinition(
    name="affiliate",
    # 1.0.0 -> 1.0.1 carries the M6-F10 wake-condition correction below into the
    # Registry. `ensure_builtin_types` reinstalls only when the version differs,
    # so a definition edited in place never reaches an installed platform: the
    # live registry still held `capability.result_returned` after the fix landed
    # in this file, and every company created from it inherited the loop (M6-F22).
    # Minor, deliberately: A-003 resets graduation counters on a *major* bump.
    version="1.0.1",
    display_name="Affiliate publisher",
    description=(
        "Researches topics people are searching for, writes posts with "
        "affiliate links, checks them against your rules, and asks you "
        "before publishing."
    ),
    prompt_templates={
        "affiliate.research": (
            "Find promising topics for an affiliate post. Intent: {intent}\n"
            "Return 2-3 topic ideas with, for each: what people are searching "
            "for, which products fit, and why now."
        ),
        "affiliate.content": (
            "Draft an affiliate post. Intent: {intent}\n"
            "Write a helpful, honest post of 400-700 words. Recommend only "
            "products the research supports. Mark every affiliate link "
            "clearly. Include a disclosure line at the top."
        ),
        "affiliate.compliance": (
            "Review this draft against the rules. Intent: {intent}\n"
            "Rules: affiliate relationships must be disclosed before the "
            "first link; no health, income, or guarantee claims; no "
            "fabricated reviews or experiences. Return PASS or a list of "
            "specific problems."
        ),
        "affiliate.operations": (
            "Prepare the approved post for publishing. Intent: {intent}\n"
            "Return the final title and body exactly as they should appear."
        ),
    },
    capability_permissions=(
        CapabilityPermission(
            capability=CapabilityType.RESEARCH,
            tool_scope=frozenset({"web_search"}),
            memory_read=True,
            max_invocation_budget_usd=Decimal("0.25"),
        ),
        CapabilityPermission(
            capability=CapabilityType.CONTENT,
            memory_read=True,
            memory_write=True,
            max_invocation_budget_usd=Decimal("0.40"),
        ),
        CapabilityPermission(
            capability=CapabilityType.COMPLIANCE,
            memory_read=True,
            max_invocation_budget_usd=Decimal("0.15"),
        ),
        CapabilityPermission(
            capability=CapabilityType.OPERATIONS,
            tool_scope=frozenset({"publish_post"}),
            credential_refs=frozenset({"affiliate_blog_webhook"}),
            max_invocation_budget_usd=Decimal("0.10"),
        ),
    ),
    autonomy_policies=(
        AutonomyPolicy(
            action_type="affiliate.publish_post",
            graduation_threshold=5,
            graduation_eligible=True,
        ),
    ),
    default_kpi_targets=(
        KpiTarget(
            key="posts_published",
            operator_label="Posts published",
            target_value=Decimal("20"),
            unit="posts/month",
        ),
    ),
    compliance_requirements=(
        "Every post discloses affiliate relationships before the first link.",
        "No health claims, income claims, or guarantees of results.",
        "No fabricated reviews, testimonials, or personal experiences.",
        "Publishing always requires owner approval until the owner has "
        "approved five consecutive posts unchanged.",
        "The owner reviews and signs off on these rules before this company type goes live.",
    ),
    suggested_budget_usd=Decimal("25.00"),
    suggested_wake_ceiling_usd=Decimal("1.00"),
    schedule_cron="0 9 * * *",
    # capability.result_returned deliberately excluded (M6-F10): under D-001
    # every capability result is awaited and consumed inside the cycle that
    # requested it, so subscribing here only let a cycle's own output re-wake
    # the business — a self-sustaining loop bounded only by max_cycles_per_day.
    event_triggers=frozenset({APPROVAL_DECIDED}),
    tool_registry={"publish_post": "webhook_publish"},
)
