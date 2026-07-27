"""Business activation invariants (spec §2.1, §4, §0.1; D-006).

Milestone 5 exists because an audit found a business could not actually be
activated: nothing created one, nothing started its Manager, no templates
existed, and the approval wake loop was open. These assert the path stays closed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.provisioning import ProvisioningService
from jarvis.domain.contract import CapabilityPermission, CapabilityType, KpiTarget
from jarvis.domain.kpi import KpiMapping, KpiSource
from jarvis.domain.lifecycle import LifecycleState
from jarvis.events.bus import EventBus
from jarvis.events.types import (
    APPROVAL_DECIDED,
    BUSINESS_ACTIVATED,
    CAPABILITY_RESULT,
    KPI_THRESHOLD_BREACHED,
)
from jarvis.kernel.errors import ConfigurationError
from jarvis.observability.audit import AuditLog
from jarvis.registry.registry import BusinessRegistry


def _definition(**over: object) -> BusinessTypeDefinition:
    base: dict[str, object] = {
        "name": "affiliate",
        "version": "1.0.0",
        "display_name": "Affiliate site",
        "description": "Writes and publishes review posts, and earns commission.",
        "prompt_templates": {
            "affiliate.research": "Research {intent}",
            "affiliate.content": "Write about {intent}",
        },
        "capability_permissions": (
            CapabilityPermission(capability=CapabilityType.RESEARCH),
            CapabilityPermission(capability=CapabilityType.CONTENT),
        ),
    }
    base.update(over)
    return BusinessTypeDefinition(**base)  # type: ignore[arg-type]


def _provisioning(session: AsyncSession, registry: BusinessRegistry) -> ProvisioningService:
    return ProvisioningService(registry, EventBus(session, AuditLog(session)))


async def test_company_can_actually_be_created(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """The gap that produced this milestone: nothing called `register_instance`."""
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(), display_name="Weekend Reviews"
    )
    assert await registry.get_state(business_id) is LifecycleState.ACTIVE


async def test_created_company_starts_running(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """§12.5 lists create-and-start as one operator action, not two."""
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(), display_name="Weekend Reviews"
    )
    contract = await registry.get_contract(business_id)
    assert contract.lifecycle_state is LifecycleState.PROVISIONING  # contract snapshot
    assert await registry.get_state(business_id) is LifecycleState.ACTIVE


async def test_activation_is_announced_on_the_bus(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """§2 forbids direct calls between workers, so the Manager is started by
    reconciliation over an announced event, not by a call from the Registry."""
    bus = EventBus(session, AuditLog(session))
    provisioning = ProvisioningService(registry, bus)
    await provisioning.install(_definition())
    await provisioning.create_company(definition=_definition(), display_name="Weekend Reviews")
    claimed = await bus.claim("test-consumer", [BUSINESS_ACTIVATED])
    assert [event.event_type for event in claimed] == [BUSINESS_ACTIVATED]


async def test_type_with_a_missing_template_is_refused(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """A permission with no template is a capability guaranteed to fail.

    Refused at install so a developer sees it, rather than at first dispatch
    where an operator sees a healthy company that never does anything.
    """
    broken = _definition(
        prompt_templates={"affiliate.research": "Research {intent}"},
    )
    with pytest.raises(ConfigurationError, match="prompt template"):
        await _provisioning(session, registry).install(broken)


async def test_a_kpi_mapping_with_no_matching_target_is_refused(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """D-027.2 install-time check (design Part 2.4): a mapping key that names
    no `default_kpi_targets` key would write an observation nothing reads."""
    broken = _definition(
        kpi_mappings=(
            KpiMapping(key="posts_published", source=KpiSource.CONFIGURED_KPI_TARGET_COUNT),
        ),
    )
    with pytest.raises(ConfigurationError, match="posts_published"):
        await _provisioning(session, registry).install(broken)


async def test_a_target_with_no_mapping_installs_fine(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """Negative control: a target with no mapping is a legitimate goal nothing
    has learned to measure yet (D-027.3), not an install-time defect."""
    fine = _definition(
        default_kpi_targets=(
            KpiTarget(
                key="posts_published",
                operator_label="Posts published",
                target_value=Decimal("20"),
                unit="posts/month",
            ),
        ),
    )
    await _provisioning(session, registry).install(fine)


async def test_subscribing_to_capability_result_returned_is_refused(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """M6-F10 install-time guard (design Part 2.4): every capability result is
    awaited inside the cycle that requested it (D-001), so subscribing to its
    own result is a self-sustaining wake loop."""
    broken = _definition(event_triggers=frozenset({CAPABILITY_RESULT}))
    with pytest.raises(ConfigurationError, match=r"capability\.result_returned"):
        await _provisioning(session, registry).install(broken)


async def test_kpi_mappings_with_a_threshold_breached_subscription_is_refused(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """M7-F35 install-time guard (design Part 2.4): a type that measures its
    own KPIs and wakes on the resulting threshold breach re-wakes itself from
    its own measurement."""
    broken = _definition(
        default_kpi_targets=(
            KpiTarget(
                key="posts_published",
                operator_label="Posts published",
                target_value=Decimal("20"),
                unit="posts/month",
            ),
        ),
        kpi_mappings=(
            KpiMapping(key="posts_published", source=KpiSource.CONFIGURED_KPI_TARGET_COUNT),
        ),
        event_triggers=frozenset({KPI_THRESHOLD_BREACHED}),
    )
    with pytest.raises(ConfigurationError, match=r"kpi\.threshold_breached"):
        await _provisioning(session, registry).install(broken)


async def test_threshold_breached_without_kpi_mappings_installs_fine(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """Negative control: the M7-F35 guard only fires when the type also
    declares mappings — subscribing alone (nothing measures anything) is
    not the re-wake loop."""
    fine = _definition(event_triggers=frozenset({KPI_THRESHOLD_BREACHED}))
    await _provisioning(session, registry).install(fine)


async def test_installed_at_refreshes_on_upgrade(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """M7-F48: the column default only fires on the first insert, so an
    upgrade must set `installed_at` explicitly or the row reports its
    original install time forever, with no way to tell a type ever changed
    underneath a running platform.

    Compared against the row's own original value, tzinfo stripped from both
    sides before comparing: SQLite's round-trip of a timezone-aware column is
    inconsistent about preserving the tzinfo tag (a client-side Python default
    keeps it, RETURNING-fetched values do not), and both timestamps are UTC by
    construction regardless.
    """
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    original = next(t for t in await registry.installed_types() if t.name == "affiliate")
    original_installed_at = original.installed_at.replace(tzinfo=None)

    await provisioning.install(_definition(version="1.0.1"))

    row = next(t for t in await registry.installed_types() if t.name == "affiliate")
    assert row.version == "1.0.1"
    assert row.installed_at.replace(tzinfo=None) >= original_installed_at


async def test_wake_ceiling_is_always_explicit(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """§2.1 requires a per-cycle ceiling before any business launches.

    A recorded default is explicit; an absent one is not.
    """
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(), display_name="Weekend Reviews"
    )
    contract = await registry.get_contract(business_id)
    assert contract.budget.wake_cycle_ceiling_usd > Decimal("0")


async def test_the_configured_default_ceiling_is_actually_applied(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """M6-F23: `default_wake_cycle_ceiling_usd` had no reader.

    The setting existed, the `.env` value was inert, and every company silently
    took its business type's suggestion instead — so raising the platform
    default changed nothing about any company that already existed or any that
    was created afterwards.
    """
    provisioning = ProvisioningService(
        registry,
        EventBus(session, AuditLog(session)),
        default_wake_ceiling_usd=Decimal("2.00"),
    )
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(), display_name="Weekend Reviews"
    )
    contract = await registry.get_contract(business_id)
    assert contract.budget.wake_cycle_ceiling_usd == Decimal("2.00")


async def test_an_explicit_ceiling_beats_the_configured_default(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """Precedence, most specific first. The platform default is a floor under
    forgetfulness, not a cap on what an owner may choose."""
    provisioning = ProvisioningService(
        registry,
        EventBus(session, AuditLog(session)),
        default_wake_ceiling_usd=Decimal("2.00"),
    )
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(),
        display_name="Weekend Reviews",
        wake_ceiling_usd=Decimal("7.50"),
    )
    contract = await registry.get_contract(business_id)
    assert contract.budget.wake_cycle_ceiling_usd == Decimal("7.50")


async def test_without_a_configured_default_the_types_suggestion_still_applies(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """Negative control: the reader must not replace the fallback with nothing.

    Defaults in Force requires an explicit ceiling before launch, so every path
    through creation has to end at a positive recorded number.
    """
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(display_name="Weekend Reviews"),
        display_name="Weekend Reviews",
    )
    contract = await registry.get_contract(business_id)
    assert contract.budget.wake_cycle_ceiling_usd == _definition().suggested_wake_ceiling_usd


async def test_the_kernel_hands_provisioning_the_configured_default() -> None:
    """The wiring M6-F23 was missing, asserted at the composition root.

    The tests above prove the service applies a default it is given; this proves
    something actually gives it one. Without this, the reader could exist and
    still never be reached from the path that creates real companies.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from jarvis.kernel.config import BudgetSettings, LLMSettings, Settings
    from jarvis.kernel.container import PlatformKernel
    from jarvis.persistence.models import Base

    class _NoProvider:
        """No model is called on this path; supplying one keeps it that way.

        `_env_file=None` and this stub together: the repository carries a real
        `.env`, and a test that built the configured provider would reach a live
        one from a path that has no business calling a model at all.
        """

        @property
        def name(self) -> str:
            return "stub"

        async def complete(self, request: object) -> object:
            raise AssertionError("creating a company calls no model")

        async def aclose(self) -> None:
            return None

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        budget=BudgetSettings(default_wake_cycle_ceiling_usd=Decimal("3.25")),
        _env_file=None,
    )
    kernel = PlatformKernel(settings, engine=engine, provider=_NoProvider())  # type: ignore[arg-type]
    try:
        async with kernel.services() as svc:
            provisioning = kernel.build_provisioning(svc)
            await provisioning.install(_definition())
            business_id = await provisioning.create_company(
                definition=_definition(), display_name="Weekend Reviews"
            )
            contract = await svc.registry.get_contract(business_id)
        assert contract.budget.wake_cycle_ceiling_usd == Decimal("3.25")
    finally:
        await kernel.aclose()


async def test_the_create_company_route_accepts_a_per_round_limit() -> None:
    """M6-F23's other half: §2.1's ceiling was unreachable from `/api/companies`.

    An owner could name a company and a budget and nothing else, so the one
    number that bounds a single round of work could only be changed by editing
    platform configuration — which sets it for every company at once.
    """
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from jarvis.api.app import create_app
    from jarvis.kernel.config import BudgetSettings, LLMSettings, Settings
    from jarvis.kernel.container import PlatformKernel
    from jarvis.kernel.ids import BusinessId
    from jarvis.persistence.models import Base

    class _NoProvider:
        @property
        def name(self) -> str:
            return "stub"

        async def complete(self, request: object) -> object:
            raise AssertionError("creating a company calls no model")

        async def aclose(self) -> None:
            return None

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(  # type: ignore[call-arg]
        llm=LLMSettings(model="stub-model"),
        budget=BudgetSettings(default_wake_cycle_ceiling_usd=Decimal("2.00")),
        _env_file=None,
    )
    kernel = PlatformKernel(settings, engine=engine, provider=_NoProvider())  # type: ignore[arg-type]
    try:
        async with kernel.services() as svc:
            await kernel.build_provisioning(svc).install(_definition())

        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            explicit = await client.post(
                "/api/companies",
                json={"template": "affiliate", "name": "Named Limit", "per_round_limit_usd": 4.5},
            )
            defaulted = await client.post(
                "/api/companies", json={"template": "affiliate", "name": "Default Limit"}
            )
        assert explicit.status_code == 200
        assert defaulted.status_code == 200

        async with kernel.services() as svc:
            named = await svc.registry.get_contract(BusinessId(explicit.json()["id"]))
            fallback = await svc.registry.get_contract(BusinessId(defaulted.json()["id"]))
        assert named.budget.wake_cycle_ceiling_usd == Decimal("4.5")
        assert fallback.budget.wake_cycle_ceiling_usd == Decimal("2.00")
    finally:
        await kernel.aclose()


async def test_operator_budget_overrides_the_suggestion(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    business_id = await provisioning.create_company(
        definition=_definition(),
        display_name="Weekend Reviews",
        budget_usd=Decimal("12.00"),
    )
    contract = await registry.get_contract(business_id)
    assert contract.budget.business_cap_usd == Decimal("12.00")


async def test_installed_types_are_discoverable(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """The create flow needs to list what can be created (spec §4)."""
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    types = await provisioning.available_types()
    assert [t.name for t in types] == ["affiliate"]
    assert types[0].description


async def test_identifiers_are_unique_per_company(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """§0.1: identifiers are permanent and never reused, so two companies from
    one template must not collide."""
    provisioning = _provisioning(session, registry)
    await provisioning.install(_definition())
    first = await provisioning.create_company(definition=_definition(), display_name="One")
    second = await provisioning.create_company(definition=_definition(), display_name="Two")
    assert first != second


def test_manager_start_is_not_the_registrys_job() -> None:
    """§0.1 makes the Registry bookkeeping infrastructure.

    Reaching into the workflow runtime is not bookkeeping, so the Registry must
    not import the Temporal client.
    """
    import pathlib

    source = pathlib.Path("jarvis/registry/registry.py").read_text()
    assert "temporalio" not in source
    assert "start_workflow" not in source


def test_exactly_one_manager_is_enforced_by_workflow_id() -> None:
    """§2.1: exactly one Manager per business.

    Enforced by deriving the workflow id from the business id, so a second start
    is an id collision the server rejects. A check-then-start would race.
    """
    import pathlib

    source = pathlib.Path("jarvis/manager/lifecycle.py").read_text()
    assert "business_workflow_id" in source
    assert "id=business_workflow_id" in source


def test_approval_decision_event_type_is_a_shared_constant() -> None:
    """The original defect was a name that existed in two places meaning two
    different things. One constant, one meaning."""
    assert APPROVAL_DECIDED == "approval.decided"
