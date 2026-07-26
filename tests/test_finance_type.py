"""Finance Tracking type and D-014 tests (spec §13 Step 3; packet M7-1).

Mirrors `tests/test_affiliate_type.py` in shape. The difference this file
exists to prove: Finance Tracking is read-only (no execution capability, no
`declared_action_types`), so its shape of test replaces "publishing requires
approval" with "there is no action here to require approval for" — and adds
an installation/version-registration test showing the type installs through
the exact same generic mechanism `affiliate` does (`ProvisioningService`),
with no change to that mechanism.
"""

from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.businesses.provisioning import ProvisioningService
from jarvis.domain.contract import (
    BudgetPolicy,
    BusinessContract,
    CapabilityType,
    WakeConditions,
)
from jarvis.events.bus import EventBus
from jarvis.events.types import APPROVAL_DECIDED
from jarvis.kernel.errors import DuplicateBusinessError
from jarvis.kernel.ids import BusinessId
from jarvis.observability.audit import AuditLog
from jarvis.registry.registry import BusinessRegistry

BIZ = BusinessId("biz_" + "fedcba9876543210" * 2)


def test_a_type_is_data_not_code() -> None:
    """D-014's proof obligation, asserted on the module's AST.

    If the finance module ever grows a function or class, a type has started
    to be code, and §4's "configuration only" instantiation is quietly dead —
    exactly what this packet exists to test with a *second* type.
    """
    tree = ast.parse(pathlib.Path("jarvis/businesses/finance.py").read_text())
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert definitions == [], "a business type must contain no logic (D-014)"


def test_definition_carries_everything_an_instance_needs() -> None:
    """Spec §4: instance creation is values over an installed definition."""
    assert FINANCE.capability_permissions
    assert FINANCE.schedule_cron or FINANCE.event_triggers
    assert FINANCE.suggested_wake_ceiling_usd > 0
    assert FINANCE.suggested_budget_usd > 0


def test_definition_survives_registry_metadata_round_trip() -> None:
    """Definitions persist as Registry metadata (M5 reconciliation)."""
    raw = FINANCE.model_dump(mode="json")
    assert BusinessTypeDefinition.model_validate(raw) == FINANCE


def test_every_permitted_capability_has_a_prompt() -> None:
    """Install-time check that would otherwise be a first-cycle dead letter."""
    for permission in FINANCE.capability_permissions:
        assert f"finance_tracking.{permission.capability.value}" in FINANCE.prompt_templates


def test_missing_prompt_is_reported_before_install() -> None:
    """Install-time check (ProvisioningService.install refuses on this)."""
    payload = FINANCE.model_dump()
    payload["prompt_templates"] = {"finance_tracking.research": "only this one"}
    partial = BusinessTypeDefinition.model_validate(payload)
    missing = partial.missing_templates()
    assert "finance_tracking.finance" in missing


def test_capability_permissions_are_limited_to_research_and_finance() -> None:
    """Owner-approved M7 scope: read-only via Research and Finance only — no
    Content/Compliance/Operations, and therefore no path to an effect."""
    assert {p.capability for p in FINANCE.capability_permissions} == {
        CapabilityType.RESEARCH,
        CapabilityType.FINANCE,
    }


def test_no_tool_scope_performs_an_effect() -> None:
    """Nothing here reaches the approved-action path (D-015): no tool_registry
    entry exists for any tool granted through any capability permission."""
    assert FINANCE.tool_registry == {}


def test_declared_action_types_is_empty_because_read_only() -> None:
    """Nothing is proposable, so nothing is approvable, so nothing executes.

    Asserted directly against `autonomy_policies` (the only source
    `BusinessContract.declared_action_types` reads from) and again on an
    actual contract built from this definition's fields, so the empty set is
    proven at the boundary the platform actually checks, not just locally.
    """
    assert FINANCE.autonomy_policies == ()
    contract = BusinessContract(
        business_id=BIZ,
        business_type="finance_tracking",  # type: ignore[arg-type]
        display_name="Test Finance Co",
        budget=BudgetPolicy(
            business_cap_usd=FINANCE.suggested_budget_usd,
            wake_cycle_ceiling_usd=FINANCE.suggested_wake_ceiling_usd,
        ),
        wake_conditions=WakeConditions(
            schedule_cron=FINANCE.schedule_cron, event_triggers=FINANCE.event_triggers
        ),
        capability_permissions=FINANCE.capability_permissions,
        autonomy_policies=FINANCE.autonomy_policies,
        kpi_targets=FINANCE.default_kpi_targets,
        compliance_requirements=FINANCE.compliance_requirements,
    )
    assert contract.declared_action_types == frozenset()
    assert contract.requires_approval("finance_tracking.anything") is True


def test_wake_cycle_ceiling_is_explicit() -> None:
    """Defaults in Force: the ceiling MUST be explicit before launch."""
    assert FINANCE.suggested_wake_ceiling_usd is not None


def test_wake_conditions_are_schedule_based_only() -> None:
    """Owner-approved M7 scope: schedule only. No `approval.decided` (nothing
    is ever approvable) and no other event trigger — D-006 still holds
    platform-wide; this type simply never raises a wake event of its own."""
    assert FINANCE.schedule_cron is not None
    assert FINANCE.event_triggers == frozenset()
    assert APPROVAL_DECIDED not in FINANCE.event_triggers


def test_compliance_requirements_carry_the_owner_approval() -> None:
    """Defaults in Force: the owner reviews and approves per type before launch.

    Approved 2026-07-26 with revisions (DECISIONS.md "M7 owner decision"); the
    text in `finance.py` is the owner's, verbatim. Asserted on the load-bearing
    clauses rather than on the whole strings, so re-wrapping a line does not
    fail the build but dropping a rule does.
    """
    rules = FINANCE.compliance_requirements
    assert len(rules) == 7
    assert rules[-1] == "The owner approves these compliance requirements for the M7 launch."
    joined = " ".join(rules).lower()
    assert "observation-only mode" in joined
    assert "must not place orders" in joined
    assert "brokerage write operations" in joined
    assert "do not constitute financial, investment, legal, or tax advice" in joined


def test_restrictions_are_scoped_to_m7_rather_than_stated_as_permanent() -> None:
    """The owner's revision, made mechanical.

    The M7-1 draft framed the restrictions as permanent properties of the type.
    The owner rejected that: the long-term roadmap includes trade
    recommendation, brokerage management, and execution, so the restrictions
    are scoped to M7 and rule 3 keeps the evolution path open — conditioned on
    the architecture explicitly enabling it, which is a §12 amendment the owner
    makes, not something a later packet may infer from this approval.
    """
    rules = FINANCE.compliance_requirements
    restrictive = [r for r in rules if "must not" in r.lower() or "observation-only" in r.lower()]
    assert restrictive, "the M7 restrictions must still be stated"
    assert all(r.startswith("During M7,") for r in restrictive)

    evolution = [r for r in rules if "may evolve" in r.lower()]
    assert len(evolution) == 1
    assert "once the architecture explicitly enables those capabilities" in evolution[0]


def test_nothing_this_type_publishes_promises_it_will_never_recommend() -> None:
    """The same direction, applied to every string this type actually ships.

    The draft's "never a recommendation to buy, sell, or trade any asset"
    framing had reached three places — the compliance rules, the operator-facing
    description on the "New company" card, and the prompts the model is given —
    and Part 0 of packet M7-3 rewrote only the first. A promise an operator
    reads is as binding in practice as one in the rules, so all three are
    checked here: what this type does during M7 is stated in the present tense,
    never as a permanent guarantee about what it will never do.
    """
    published = {
        "description": FINANCE.description,
        **{f"rule {i}": r for i, r in enumerate(FINANCE.compliance_requirements, 1)},
        **{f"prompt {k}": v for k, v in FINANCE.prompt_templates.items()},
    }
    for where, text in published.items():
        assert "never" not in text.lower(), (
            f"{where} makes a permanent promise the owner explicitly rejected "
            '(DECISIONS.md "M7 owner decision")'
        )


async def test_finance_installs_through_the_same_generic_mechanism_as_affiliate(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """D-014's real claim: a second type is pure configuration over
    `ProvisioningService.install` — no change to that mechanism was needed."""
    provisioning = ProvisioningService(registry, EventBus(session, AuditLog(session)))
    await provisioning.install(FINANCE)
    installed = {t.name: t.version for t in await registry.installed_types()}
    assert installed["finance_tracking"] == FINANCE.version


async def test_reinstalling_the_same_version_is_refused_not_silently_absorbed(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """`install()` itself is not idempotent on a duplicate version (by design —
    see `BusinessRegistry.install_business_type`); the version gate that makes
    re-installation safe lives in the *caller* (`ensure_builtin_types` checks
    the installed version before calling install at all, exactly the M6-F22
    lesson). This proves the gate finance would need behaves the same way
    affiliate's already does, so version-gated registration for this type is
    the existing mechanism, not a new one.
    """
    provisioning = ProvisioningService(registry, EventBus(session, AuditLog(session)))
    await provisioning.install(FINANCE)
    with pytest.raises(DuplicateBusinessError):
        await provisioning.install(FINANCE)


def test_suggested_budget_is_lower_than_a_full_capability_chain_type() -> None:
    """Sanity check on the authored numbers: a two-capability, read-only type
    should not suggest a richer budget than the four-capability Affiliate type
    it is modeled after."""
    from jarvis.businesses.affiliate import AFFILIATE

    assert FINANCE.suggested_budget_usd < AFFILIATE.suggested_budget_usd
    assert FINANCE.suggested_wake_ceiling_usd <= AFFILIATE.suggested_wake_ceiling_usd
    per_cycle_capability_spend = sum(
        (p.max_invocation_budget_usd for p in FINANCE.capability_permissions), Decimal("0")
    )
    assert per_cycle_capability_spend <= FINANCE.suggested_wake_ceiling_usd
