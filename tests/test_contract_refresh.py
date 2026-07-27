"""The contract-refresh mechanism (D-029, D-030; design doc Part 4).

The three live companies of design Part 5 are the fixtures here, reconstructed
from the shapes read out of the live database read-only on 2026-07-27, because
each proves a different half of the mechanism:

- **Summit Trail Gear** is the negative control. Created after affiliate 1.0.1
  installed, its snapshot is already current, so its plan must be *empty*. A
  blanket overwrite would look identical on the other two and be
  indistinguishable from a correct diff; Summit is what makes the diff-driven
  nature falsifiable. Summit also carries the whole of Band C's guard case: its
  per-round limit is $2.00 against its template's $1.00 suggestion, an explicit
  operator choice (M6-F23/M6-F25), and a refresh that moved it would be the
  platform overriding a person about money.
- **Trailhead Gear Reviews** is the defect case. Its stored wake conditions
  still carry the signal affiliate 1.0.1 removed as the M6-F10 fix, so a
  refresh clears a live loop rather than cosmetic staleness (M6-F22).
- **Portfolio Watch** is audit finding F-A. Its stored targets carry no
  direction, so its freshness figure scores backwards; the correction's own
  test is the attainment arithmetic against real recorded rows, 45 -> 78.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.rendering import contains_technical_language
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.provisioning import ProvisioningService
from jarvis.businesses.refresh import TRIGGER_SENTENCES, ContractRefreshService
from jarvis.domain.contract import (
    AutonomyPolicy,
    BudgetPolicy,
    BusinessContract,
    CapabilityPermission,
    CapabilityType,
    KpiDirection,
    KpiTarget,
    WakeConditions,
)
from jarvis.domain.kpi import KpiMapping, KpiSource
from jarvis.domain.refresh import (
    BAND_B_FIELDS,
    FROZEN_FIELDS,
    ContractRefreshPlan,
    RefreshBand,
    RefreshConsent,
    RefreshOutcome,
    frozen_field_differences,
)
from jarvis.events.bus import EventBus
from jarvis.events.types import ALL_EVENT_TYPES, APPROVAL_DECIDED, CAPABILITY_RESULT
from jarvis.kernel.errors import ConfigurationError, RegistryError
from jarvis.kernel.ids import BusinessId, BusinessTypeName, new_business_id
from jarvis.kpi.engine import KpiEngine
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import ApprovalRow, AuditLogRow, DecisionLogRow, KpiValueRow
from jarvis.registry.registry import BusinessRegistry

# ── the two live type definitions, at the versions that matter ──────────────


def _affiliate(version: str = "1.0.1", **over: Any) -> BusinessTypeDefinition:
    """The affiliate type. 1.0.0 carried the wake signal 1.0.1 removed (M6-F10)."""
    base: dict[str, Any] = {
        "name": "affiliate",
        "version": version,
        "display_name": "Affiliate publisher",
        "description": "Writes review posts and asks you before publishing.",
        "prompt_templates": {
            "affiliate.research": "Research {intent}",
            "affiliate.content": "Write about {intent}",
        },
        "capability_permissions": (
            CapabilityPermission(
                capability=CapabilityType.RESEARCH, tool_scope=frozenset({"web_search"})
            ),
            CapabilityPermission(capability=CapabilityType.CONTENT),
        ),
        "autonomy_policies": (
            AutonomyPolicy(action_type="affiliate.publish_post", graduation_threshold=5),
        ),
        "default_kpi_targets": (
            KpiTarget(
                key="posts_published",
                operator_label="Posts published",
                target_value=Decimal("20"),
                unit="posts/month",
            ),
        ),
        "compliance_requirements": ("Every post discloses its affiliate links.",),
        "suggested_budget_usd": Decimal("25.00"),
        "suggested_wake_ceiling_usd": Decimal("1.00"),
        "schedule_cron": "0 9 * * *",
        "event_triggers": frozenset({APPROVAL_DECIDED}),
    }
    if version == "1.0.0":
        base["event_triggers"] = frozenset({APPROVAL_DECIDED, CAPABILITY_RESULT})
    base.update(over)
    return BusinessTypeDefinition(**base)


def _finance(version: str = "1.0.2", **over: Any) -> BusinessTypeDefinition:
    """The finance type. 1.0.2 added `direction`; 1.0.1 is what F-A snapshotted."""
    freshness: dict[str, Any] = {
        "key": "data_freshness_hours",
        "operator_label": "Data freshness",
        "target_value": Decimal("24"),
        "unit": "hours since last check",
    }
    if version != "1.0.1":
        freshness["direction"] = KpiDirection.BELOW
    base: dict[str, Any] = {
        "name": "finance_tracking",
        "version": version,
        "display_name": "Finance tracker",
        "description": "Tracks the numbers you care about and reports on them.",
        "prompt_templates": {"finance_tracking.finance": "Track {intent}"},
        "capability_permissions": (CapabilityPermission(capability=CapabilityType.FINANCE),),
        "autonomy_policies": (),
        "default_kpi_targets": (
            KpiTarget(
                key="metrics_tracked",
                operator_label="Metrics tracked",
                target_value=Decimal("5"),
                unit="metrics",
            ),
            KpiTarget(**freshness),
            KpiTarget(
                key="reports_delivered",
                operator_label="Reports delivered",
                target_value=Decimal("4"),
                unit="reports/month",
            ),
        ),
        "kpi_mappings": (
            KpiMapping(key="metrics_tracked", source=KpiSource.CONFIGURED_KPI_TARGET_COUNT),
            KpiMapping(
                key="data_freshness_hours",
                source=KpiSource.HOURS_SINCE_NEWEST_SUCCEEDED_RESULT,
            ),
            KpiMapping(key="reports_delivered", source=KpiSource.SUCCEEDED_RESULTS_IN_CYCLE),
        ),
        "compliance_requirements": ("Every figure cites the record it came from.",),
        "suggested_budget_usd": Decimal("20.00"),
        "suggested_wake_ceiling_usd": Decimal("2.00"),
        "schedule_cron": "0 9 * * *",
        "event_triggers": frozenset({APPROVAL_DECIDED}),
    }
    base.update(over)
    return BusinessTypeDefinition(**base)


# ── harness ─────────────────────────────────────────────────────────────────


def _refresh(session: AsyncSession, registry: BusinessRegistry) -> ContractRefreshService:
    return ContractRefreshService(registry, DecisionLog(session))


def _provisioning(session: AsyncSession, registry: BusinessRegistry) -> ProvisioningService:
    return ProvisioningService(registry, EventBus(session, AuditLog(session)))


async def _company(
    registry: BusinessRegistry,
    definition: BusinessTypeDefinition,
    display_name: str,
    *,
    ceiling: Decimal | None = None,
    budget: Decimal | None = None,
) -> BusinessId:
    """Register a company whose snapshot came from ``definition``.

    Built through `register_instance` rather than `create_company` because two
    of the three subjects were created from a *superseded* version of their
    type — which is the whole point of them — and `install()` rightly refuses
    to install one of those definitions at all (M6-F10's validation).
    """
    business_id = new_business_id()
    await registry.register_instance(
        BusinessContract(
            business_id=business_id,
            business_type=BusinessTypeName(definition.name),
            display_name=display_name,
            budget=BudgetPolicy(
                business_cap_usd=budget or definition.suggested_budget_usd,
                wake_cycle_ceiling_usd=ceiling or definition.suggested_wake_ceiling_usd,
            ),
            wake_conditions=WakeConditions(
                schedule_cron=definition.schedule_cron,
                event_triggers=definition.event_triggers,
            ),
            capability_permissions=definition.capability_permissions,
            autonomy_policies=definition.autonomy_policies,
            kpi_targets=definition.default_kpi_targets,
            compliance_requirements=definition.compliance_requirements,
        )
    )
    return business_id


def _consent(plan: ContractRefreshPlan, *, granted: bool = True) -> RefreshConsent:
    return RefreshConsent(plan_key=plan.plan_key, granted=granted)


@pytest.fixture
def refresh(session: AsyncSession, registry: BusinessRegistry) -> ContractRefreshService:
    return _refresh(session, registry)


# ── Subject 3: Summit Trail Gear, the negative control ──────────────────────


async def test_a_company_already_current_produces_an_empty_plan(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design Part 5 subject 3: the diff must be empty, not merely harmless.

    Summit was created after affiliate 1.0.1 installed. If a refresh were a
    blanket overwrite it would look identical here and on the two companies
    that need one, and nothing in the suite could tell a correct diff from a
    rewrite of everything.
    """
    definition = _affiliate()
    await _provisioning(session, registry).install(definition)
    summit = await _company(registry, definition, "Summit Trail Gear", ceiling=Decimal("2.00"))

    plan = await refresh.plan_refresh(summit)

    assert plan.is_empty
    assert plan.changes == ()
    assert plan.source_digest == plan.target_digest


async def test_applying_an_empty_plan_writes_nothing(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    definition = _affiliate()
    await _provisioning(session, registry).install(definition)
    summit = await _company(registry, definition, "Summit Trail Gear", ceiling=Decimal("2.00"))
    before = await registry.get_contract(summit)

    plan = await refresh.plan_refresh(summit)
    result = await refresh.apply_refresh(summit, plan, consent=_consent(plan))

    assert result.outcome is RefreshOutcome.NOTHING_TO_APPLY
    assert await registry.get_contract(summit) == before
    assert await _audit_count(session, "business.contract_refreshed") == 0


async def test_summit_s_operator_chosen_limit_is_reported_and_never_applied(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """The Band C guard case (design Part 5 subject 3, M6-F23/M6-F25).

    $2.00 against the template's $1.00 suggestion was an explicit operator
    choice. It shows up in `withheld` — Band C is reported so it can be seen to
    be holding — and never in `changes`, which is the half that gets written.
    """
    definition = _affiliate()
    await _provisioning(session, registry).install(definition)
    summit = await _company(registry, definition, "Summit Trail Gear", ceiling=Decimal("2.00"))

    plan = await refresh.plan_refresh(summit)

    withheld = {change.field: change for change in plan.withheld}
    assert "budget.wake_cycle_ceiling_usd" in withheld
    assert withheld["budget.wake_cycle_ceiling_usd"].band is RefreshBand.FROZEN
    assert withheld["budget.wake_cycle_ceiling_usd"].before == "2"
    assert all(change.band is RefreshBand.CONSENTED for change in plan.changes)
    assert not any(change.field.startswith("budget") for change in plan.changes)


async def test_the_operator_s_money_survives_a_refresh_that_changes_other_things(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """The cheapest possible guard on the whole of Band C, applied end to end.

    Summit's ceiling shape on a company that *does* have Band B work to do: the
    refresh writes, and both money figures come out the other side untouched.
    """
    await _provisioning(session, registry).install(_affiliate())
    company = await _company(
        registry,
        _affiliate("1.0.0"),
        "Summit Trail Gear",
        ceiling=Decimal("2.00"),
        budget=Decimal("25.00"),
    )

    plan = await refresh.plan_refresh(company)
    assert plan.changes, "this company must actually need a refresh for the guard to mean anything"
    await refresh.apply_refresh(company, plan, consent=_consent(plan))

    after = await registry.get_contract(company)
    assert after.budget.wake_cycle_ceiling_usd == Decimal("2.00")
    assert after.budget.business_cap_usd == Decimal("25.00")


# ── Subject 2: Trailhead Gear Reviews, the defect case ──────────────────────


async def test_a_stale_wake_signal_is_the_change_a_refresh_offers(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design Part 5 subject 2: M6-F10's fix reaching a company that predates it."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")

    plan = await refresh.plan_refresh(trailhead)

    assert [change.field for change in plan.changes] == ["wake_conditions.event_triggers"]
    change = plan.changes[0]
    assert change.before == CAPABILITY_RESULT
    assert change.after == ""
    assert change.description == (
        "It will stop starting a new round of work when its own work comes back."
    )


async def test_applying_it_closes_the_loop_and_leaves_the_other_signal(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Safe: Trailhead keeps two wake paths, the daily one and the answer one."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")

    plan = await refresh.plan_refresh(trailhead)
    result = await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))

    assert result.outcome is RefreshOutcome.APPLIED
    after = await registry.get_contract(trailhead)
    assert CAPABILITY_RESULT not in after.wake_conditions.event_triggers
    assert APPROVAL_DECIDED in after.wake_conditions.event_triggers
    assert after.wake_conditions.schedule_cron == "0 9 * * *"


# ── Subject 1: Portfolio Watch, audit finding F-A ───────────────────────────


async def test_a_missing_direction_is_the_change_and_the_arithmetic_moves(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """F-A reproduced against recorded observations: 45 -> 78 (design Part 5.1).

    The correction's own test. The three figures are the live ones — three
    metrics against a target of five, a freshness reading of 0.0005 hours
    against a 24-hour target, three reports against four — and the freshness
    term is the whole of the difference: scored the wrong way round it
    contributes 0.00002 and scored correctly it contributes 1.
    """
    await _provisioning(session, registry).install(_finance("1.0.2"))
    watch = await _company(registry, _finance("1.0.1"), "Portfolio Watch", budget=Decimal("15.00"))
    for key, value in (
        ("metrics_tracked", "3"),
        ("data_freshness_hours", "0.0005"),
        ("reports_delivered", "3"),
    ):
        session.add(KpiValueRow(business_id=watch, key=key, value=Decimal(value)))
    await session.flush()

    engine = KpiEngine(session)
    before = await registry.get_contract(watch)
    assert await engine.attainment(before) == 45

    plan = await refresh.plan_refresh(watch)
    assert [change.field for change in plan.changes] == [
        "kpi_targets.data_freshness_hours.direction"
    ]
    assert plan.changes[0].description == "Data freshness now counts lower numbers as better."

    await refresh.apply_refresh(watch, plan, consent=_consent(plan))

    after = await registry.get_contract(watch)
    assert await engine.attainment(after) == 78


# ── Band C: the guard at the write boundary ─────────────────────────────────


@pytest.mark.parametrize(
    "field",
    [
        "budget",
        "capability_permissions",
        "autonomy_policies",
        "display_name",
        "goals",
        "wake_conditions.max_cycles_per_day",
    ],
)
def test_every_frozen_field_is_detected_when_it_moves(
    contract: BusinessContract, field: str
) -> None:
    """`frozen_field_differences` is the guard; a guard that never fires is none.

    Each of these is moved in turn and must be named. `wake_conditions` is the
    interesting one: `max_cycles_per_day` is frozen while two of its siblings
    are Band B, so the guard has to reach inside the model rather than compare
    it whole.
    """
    mutations: dict[str, dict[str, Any]] = {
        "budget": {
            "budget": contract.budget.model_copy(update={"wake_cycle_ceiling_usd": Decimal("9.00")})
        },
        "capability_permissions": {
            "capability_permissions": (
                *contract.capability_permissions,
                CapabilityPermission(capability=CapabilityType.OPERATIONS),
            )
        },
        "autonomy_policies": {
            "autonomy_policies": (
                AutonomyPolicy(action_type="affiliate.spend_money", graduation_threshold=5),
            )
        },
        "display_name": {"display_name": "Renamed Co"},
        "goals": {"goals": ("grow",)},
        "wake_conditions.max_cycles_per_day": {
            "wake_conditions": contract.wake_conditions.model_copy(update={"max_cycles_per_day": 4})
        },
    }
    moved = contract.model_copy(update=mutations[field])
    assert frozen_field_differences(contract, moved) == (field,)


def test_a_band_b_only_change_names_no_frozen_field(contract: BusinessContract) -> None:
    """The other half: the guard must not fire on the changes it exists to allow."""
    moved = contract.model_copy(
        update={
            "kpi_targets": (
                KpiTarget(
                    key="posts_published",
                    operator_label="Posts published",
                    target_value=Decimal("30"),
                    unit="posts/month",
                ),
            ),
            "compliance_requirements": ("A new rule.",),
            "wake_conditions": contract.wake_conditions.model_copy(
                update={"event_triggers": frozenset({APPROVAL_DECIDED})}
            ),
        }
    )
    assert frozen_field_differences(contract, moved) == ()


async def test_the_registry_refuses_a_write_that_would_widen_permissions(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 7.1, enforced rather than documented.

    `capability_permissions` is the authorization record `authorize_invocation`
    reads. A refresh that widened it would grant an existing company new tool
    or credential reach with no human in the loop — a §10 boundary widening,
    frozen in v1. The guard sits at the write boundary, so it holds for a
    caller that has not been written yet, and it refuses the *whole* write
    rather than trimming the offending field.
    """
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.1", display_name="Affiliate publisher"
    )
    await registry.register_instance(contract)
    widened = contract.model_copy(
        update={
            "capability_permissions": (
                CapabilityPermission(
                    capability=CapabilityType.RESEARCH,
                    tool_scope=frozenset({"web_search", "wire_transfer"}),
                    credential_refs=frozenset({"serp_key", "bank_key"}),
                ),
            ),
            "compliance_requirements": ("A rule that would have been written.",),
        }
    )

    with pytest.raises(RegistryError, match="never-refreshed"):
        await registry.refresh_contract(
            contract.business_id, widened, audit_ref_payload={"fields": []}
        )

    stored = await registry.get_contract(contract.business_id)
    assert stored.capability_permissions == contract.capability_permissions
    assert stored.compliance_requirements == contract.compliance_requirements


# ── consent (D-030) ─────────────────────────────────────────────────────────


def test_consent_has_no_default_and_therefore_cannot_be_implied() -> None:
    """A caller cannot get a write by omitting the answer."""
    with pytest.raises(ValueError, match="granted"):
        RefreshConsent(plan_key="abc")  # type: ignore[call-arg]


def test_consent_carries_no_action_type(contract: BusinessContract) -> None:
    """D-030 made structural: the absence of the field is the guarantee.

    An `action_type` would key the graduation counters (D-010, A-003) on a
    configuration change, so after five clean acceptances company updates would
    begin applying unattended.
    """
    assert "action_type" not in RefreshConsent.model_fields
    assert "action_type" not in ContractRefreshPlan.model_fields


async def test_a_refusal_to_consent_writes_nothing(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    with pytest.raises(RegistryError, match="granted consent"):
        await refresh.apply_refresh(trailhead, plan, consent=_consent(plan, granted=False))

    after = await registry.get_contract(trailhead)
    assert CAPABILITY_RESULT in after.wake_conditions.event_triggers


async def test_consent_to_one_plan_is_not_consent_to_another(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    with pytest.raises(RegistryError, match="different set of changes"):
        await refresh.apply_refresh(
            trailhead, plan, consent=RefreshConsent(plan_key="some-other-plan", granted=True)
        )


async def test_declining_is_recorded_as_an_outcome(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design 4.3: a decline is a real outcome, recorded, not a deferral loop."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    result = await refresh.decline_refresh(trailhead, plan, consent=_consent(plan, granted=False))

    assert result.outcome is RefreshOutcome.DECLINED
    entry = await _decision(session, trailhead)
    assert entry is not None
    assert entry.action_type is None
    assert not contains_technical_language(entry.summary)
    assert not contains_technical_language(entry.rationale)
    assert await _audit_count(session, "business.contract_refreshed") == 0


# ── idempotency (D-024.3) and staleness ─────────────────────────────────────


async def test_applying_the_same_plan_twice_writes_once(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """One plan, at most one effect — D-024.3's discipline, keyed on a derived
    value rather than a minted one so a resent plan is recognisably the same."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    first = await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))
    second = await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))

    assert first.outcome is RefreshOutcome.APPLIED
    assert second.outcome is RefreshOutcome.ALREADY_APPLIED
    assert await _audit_count(session, "business.contract_refreshed") == 1
    assert await _decision_count(session, trailhead) == 1


async def test_the_plan_key_is_derived_not_minted(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Two plans for the same transition are the same plan, so a re-rendered
    offer does not become a second thing the operator has to consent to."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")

    first = await refresh.plan_refresh(trailhead)
    second = await refresh.plan_refresh(trailhead)

    assert first.plan_key == second.plan_key


async def test_a_plan_computed_against_a_type_that_has_since_moved_is_refused(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """The operator consented to a set of changes, not to whatever is current."""
    provisioning = _provisioning(session, registry)
    await provisioning.install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    await provisioning.install(_affiliate("1.1.0", compliance_requirements=("A newer rule.",)))

    with pytest.raises(RegistryError, match="changed since this refresh was planned"):
        await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))
    assert await _audit_count(session, "business.contract_refreshed") == 0


# ── §8 relationship, records, and language ──────────────────────────────────


async def test_a_refresh_never_enters_the_approvals_queue(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """D-030 stated as the observable property (design 4.3, Part 6)."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))

    approvals = await session.scalar(select(func.count()).select_from(ApprovalRow))
    assert int(approvals or 0) == 0
    entry = await _decision(session, trailhead)
    assert entry is not None
    assert entry.action_type is None


async def test_the_audit_record_carries_the_before_and_the_after(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design 4.4: the record has to answer what changed, from stored values."""
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))

    row = await session.scalar(
        select(AuditLogRow).where(AuditLogRow.event_type == "business.contract_refreshed")
    )
    assert row is not None
    assert row.business_id == trailhead
    assert CAPABILITY_RESULT in row.payload["before"]["wake_conditions.event_triggers"]
    assert CAPABILITY_RESULT not in row.payload["after"]["wake_conditions.event_triggers"]
    assert row.payload["fields"] == ["wake_conditions.event_triggers"]


async def test_every_sentence_a_plan_produces_is_operator_language(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """§12.5 is a gate, not a style (design Part 6).

    Four of the seventeen forbidden terms sit directly in this feature's path.
    A diff renderer that printed field names would emit `capability.
    result_returned` and `capability_permissions` verbatim, so the descriptions
    are built from a platform-owned table keyed on the field and never from the
    field itself.
    """
    provisioning = _provisioning(session, registry)
    await provisioning.install(_affiliate())
    await provisioning.install(_finance("1.0.2"))
    subjects = [
        await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews"),
        await _company(registry, _finance("1.0.1"), "Portfolio Watch"),
        await _company(registry, _affiliate(), "Summit Trail Gear", ceiling=Decimal("2.00")),
    ]

    for business_id in subjects:
        plan = await refresh.plan_refresh(business_id)
        for change in (*plan.changes, *plan.withheld):
            assert change.description
            assert change.description.endswith(".")
            assert not contains_technical_language(change.description), change.description


async def test_the_decision_log_entry_reads_as_a_sentence_about_a_company(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    await _provisioning(session, registry).install(_affiliate())
    trailhead = await _company(registry, _affiliate("1.0.0"), "Trailhead Gear Reviews")
    plan = await refresh.plan_refresh(trailhead)

    await refresh.apply_refresh(trailhead, plan, consent=_consent(plan))

    entry = await _decision(session, trailhead)
    assert entry is not None
    assert entry.summary.startswith("Trailhead Gear Reviews")
    assert not contains_technical_language(entry.summary)
    assert not contains_technical_language(entry.rationale)
    assert plan.changes[0].description in entry.rationale


def test_every_publishable_wake_signal_has_its_two_sentences() -> None:
    """Design Part 6: a field with no sentence is not renderable and therefore
    not refreshable. That is a feature, so it is asserted rather than assumed —
    a new signal added to `ALL_EVENT_TYPES` fails here until someone writes the
    two lines an operator would read."""
    assert set(TRIGGER_SENTENCES) == set(ALL_EVENT_TYPES)
    for added, removed in TRIGGER_SENTENCES.values():
        for sentence in (added, removed):
            assert sentence.endswith(".")
            assert not contains_technical_language(sentence)


# ── the band classification itself ──────────────────────────────────────────


def test_the_two_bands_partition_the_contract() -> None:
    """D-029 classifies every contract field, or it classifies nothing.

    A field added to `BusinessContract` and to neither list would be silently
    unclassified — and an unclassified field is one a future refresh could move
    without anyone having decided it should.
    """
    named = set()
    for field in (*BAND_B_FIELDS, *FROZEN_FIELDS):
        named.add(field.split(".")[0])
    assert named == set(BusinessContract.model_fields)


def test_max_cycles_per_day_is_not_band_b(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design Part 4.2's first load-bearing constraint, as a list membership."""
    assert "wake_conditions.max_cycles_per_day" in FROZEN_FIELDS
    assert not any(field.startswith("wake_conditions.max") for field in BAND_B_FIELDS)


async def test_a_refresh_leaves_the_wake_rate_bound_alone(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """The same constraint, end to end: the type has no field for this, so a
    type upgrade may not move it."""
    await _provisioning(session, registry).install(_affiliate())
    business_id = new_business_id()
    stale = _affiliate("1.0.0")
    await registry.register_instance(
        BusinessContract(
            business_id=business_id,
            business_type=BusinessTypeName("affiliate"),
            display_name="Trailhead Gear Reviews",
            budget=BudgetPolicy(
                business_cap_usd=Decimal("25.00"), wake_cycle_ceiling_usd=Decimal("1.00")
            ),
            wake_conditions=WakeConditions(
                schedule_cron=stale.schedule_cron,
                event_triggers=stale.event_triggers,
                max_cycles_per_day=6,
            ),
            capability_permissions=stale.capability_permissions,
            kpi_targets=stale.default_kpi_targets,
        )
    )

    plan = await refresh.plan_refresh(business_id)
    await refresh.apply_refresh(business_id, plan, consent=_consent(plan))

    assert (await registry.get_contract(business_id)).wake_conditions.max_cycles_per_day == 6


async def test_a_refresh_that_would_produce_an_invalid_contract_is_refused(
    session: AsyncSession, registry: BusinessRegistry, refresh: ContractRefreshService
) -> None:
    """Design 4.4: a type that dropped every wake condition is refused, not
    written — and refused at planning, so an operator is never offered a change
    the platform could not carry out."""
    await _provisioning(session, registry).install(
        _affiliate("1.1.0", schedule_cron=None, event_triggers=frozenset())
    )
    company = await _company(registry, _affiliate(), "Trailhead Gear Reviews")

    with pytest.raises(ConfigurationError, match="invalid contract"):
        await refresh.plan_refresh(company)


# ── helpers ─────────────────────────────────────────────────────────────────


async def _audit_count(session: AsyncSession, event_type: str) -> int:
    total = await session.scalar(
        select(func.count()).select_from(AuditLogRow).where(AuditLogRow.event_type == event_type)
    )
    return int(total or 0)


async def _decision_count(session: AsyncSession, business_id: BusinessId) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(DecisionLogRow)
        .where(DecisionLogRow.business_id == business_id)
        .where(DecisionLogRow.action_type.is_(None))
    )
    return int(total or 0)


async def _decision(session: AsyncSession, business_id: BusinessId) -> DecisionLogRow | None:
    return await session.scalar(
        select(DecisionLogRow)
        .where(DecisionLogRow.business_id == business_id)
        .where(DecisionLogRow.action_type.is_(None))
    )
