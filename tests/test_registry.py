"""Business Registry tests (spec §0.1) and the D-002 authorization anchor (§10)."""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.domain.lifecycle import LifecycleState
from jarvis.kernel.errors import (
    BusinessNotFoundError,
    BusinessTypeNotFoundError,
    DuplicateBusinessError,
    InvalidLifecycleTransitionError,
    RegistryError,
    ScopeViolationError,
)
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import AuditLogRow
from jarvis.registry.registry import BusinessRegistry


async def _install(registry: BusinessRegistry) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"),
        version="1.0.0",
        display_name="Affiliate",
    )


async def test_register_and_read_back(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _install(registry)
    business_id = await registry.register_instance(contract)
    assert await registry.get_state(business_id) is LifecycleState.PROVISIONING
    assert (await registry.get_contract(business_id)).display_name == "Test Affiliate Co"


async def test_cannot_register_against_uninstalled_type(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    with pytest.raises(BusinessTypeNotFoundError):
        await registry.register_instance(contract)


async def test_identifiers_are_never_reused(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Spec §0.1: identifiers are unique and permanent."""
    await _install(registry)
    await registry.register_instance(contract)
    with pytest.raises(DuplicateBusinessError):
        await registry.register_instance(contract)


async def test_unknown_business_raises(registry: BusinessRegistry) -> None:
    with pytest.raises(BusinessNotFoundError):
        await registry.get_contract(BusinessId("biz_missing"))


async def test_set_type_enabled_on_uninstalled_type_raises_registry_error(
    registry: BusinessRegistry,
) -> None:
    """M6-F3: `set_type_enabled` on an uninstalled type must raise the
    documented `RegistryError`, not `NameError` — the name was referenced
    but never imported, so the real runtime behaviour was a crash rather
    than the documented error."""
    with pytest.raises(RegistryError):
        await registry.set_type_enabled(BusinessTypeName("nonexistent"), enabled=False)


async def test_type_removal_blocked_while_instances_exist(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Removing a type under live instances would strand their definitions."""
    await _install(registry)
    await registry.register_instance(contract)
    with pytest.raises(DuplicateBusinessError):
        await registry.remove_business_type(BusinessTypeName("affiliate"))


async def test_transition_writes_audit_and_decision_entries(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-008 I-6: every transition is explainable to the operator."""
    await _install(registry)
    business_id = await registry.register_instance(contract)
    await registry.transition(
        business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_1"),
        reason="Owner finished setup and started the company.",
    )
    assert await registry.get_state(business_id) is LifecycleState.ACTIVE


async def test_transition_decision_summary_uses_operator_labels(
    registry: BusinessRegistry, contract: BusinessContract, session: AsyncSession
) -> None:
    """M6-5a item 4: found live — a transition's Decision Log summary read
    "moved from provisioning to active", the raw enum values, in the exact
    feed an operator reads by default (spec §12.5, D-007). Regression."""
    await _install(registry)
    business_id = await registry.register_instance(contract)
    await registry.transition(
        business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_2"),
        reason="Owner finished setup and started the company.",
    )
    feed = await DecisionLog(session).activity_feed(business_id)
    summary = feed[0].summary
    assert summary == "Test Affiliate Co moved from Setting up to Running."


async def test_illegal_transition_rejected(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    await _install(registry)
    business_id = await registry.register_instance(contract)
    with pytest.raises(InvalidLifecycleTransitionError):
        await registry.transition(
            business_id,
            LifecycleState.RETIRED,
            decision_id=DecisionId("dec_2"),
            reason="skipping the drain phase",
        )


# ── D-002 / spec §10: the requester is never the authority on its own scope ──


async def _activate(registry: BusinessRegistry, contract: BusinessContract) -> BusinessId:
    await _install(registry)
    business_id = await registry.register_instance(contract)
    await registry.transition(
        business_id,
        LifecycleState.ACTIVE,
        decision_id=DecisionId("dec_activate"),
        reason="Started for testing.",
    )
    return business_id


async def test_valid_invocation_authorized(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    business_id = await _activate(registry, contract)
    await registry.authorize_invocation(
        identity=RuntimeIdentity.for_testing(business_id),
        declared_business_id=business_id,
        capability=CapabilityType.RESEARCH,
        requested_tools=frozenset({"web_search"}),
        requested_credentials=frozenset({"serp_key"}),
    )


async def test_declared_identity_cannot_override_workflow_identity(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The core §10 guarantee: a malformed request cannot assert another
    business's identity, because identity is derived, not declared."""
    business_id = await _activate(registry, contract)
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=BusinessId("biz_other"),
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset({"web_search"}),
            requested_credentials=frozenset(),
        )


async def test_tool_scope_escalation_rejected(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    business_id = await _activate(registry, contract)
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=business_id,
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset({"web_search", "wire_transfer"}),
            requested_credentials=frozenset(),
        )


async def test_credential_scope_escalation_rejected(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    business_id = await _activate(registry, contract)
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=business_id,
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset(),
            requested_credentials=frozenset({"brokerage_key"}),
        )


async def test_unpermitted_capability_rejected(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    business_id = await _activate(registry, contract)
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=business_id,
            capability=CapabilityType.FINANCE,
            requested_tools=frozenset(),
            requested_credentials=frozenset(),
        )


async def test_paused_business_accepts_no_dispatch(
    registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """D-008 I-4 enforced at the authorization boundary, not just in the UI."""
    business_id = await _activate(registry, contract)
    await registry.transition(
        business_id,
        LifecycleState.PAUSED,
        decision_id=DecisionId("dec_pause"),
        reason="Owner paused the company.",
    )
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=business_id,
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset({"web_search"}),
            requested_credentials=frozenset(),
        )


# ── Every security rejection must leave an audit record (spec §11) ───────────


async def _violations(session: AsyncSession) -> list[AuditLogRow]:
    stmt = select(AuditLogRow).where(AuditLogRow.event_type == "security.scope_violation")
    return list((await session.scalars(stmt)).all())


@pytest.mark.parametrize(
    ("capability", "tools", "credentials", "declared", "reason"),
    [
        (CapabilityType.RESEARCH, frozenset(), frozenset(), "other", "identity_mismatch"),
        (CapabilityType.FINANCE, frozenset(), frozenset(), None, "capability_not_permitted"),
        (CapabilityType.RESEARCH, frozenset({"wire"}), frozenset(), None, "tool_scope_escalation"),
        (
            CapabilityType.RESEARCH,
            frozenset(),
            frozenset({"brokerage_key"}),
            None,
            "credential_scope_escalation",
        ),
    ],
)
async def test_every_rejection_path_is_audited(
    registry: BusinessRegistry,
    contract: BusinessContract,
    session: AsyncSession,
    capability: CapabilityType,
    tools: frozenset[str],
    credentials: frozenset[str],
    declared: str | None,
    reason: str,
) -> None:
    """A silent denial stops the access but hides that something tried (§11)."""
    business_id = await _activate(registry, contract)
    assert await _violations(session) == []

    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=BusinessId(declared) if declared else business_id,
            capability=capability,
            requested_tools=tools,
            requested_credentials=credentials,
        )

    recorded = await _violations(session)
    assert len(recorded) == 1
    assert recorded[0].payload["reason"] == reason
    assert recorded[0].business_id == business_id
    assert recorded[0].payload["identity_source"] == "testing"


async def test_not_dispatchable_rejection_is_audited(
    registry: BusinessRegistry, contract: BusinessContract, session: AsyncSession
) -> None:
    """The fifth rejection path: a paused company (D-008 I-4)."""
    business_id = await _activate(registry, contract)
    await registry.transition(
        business_id,
        LifecycleState.PAUSED,
        decision_id=DecisionId("dec_pause_audit"),
        reason="Owner paused the company.",
    )
    with pytest.raises(ScopeViolationError):
        await registry.authorize_invocation(
            identity=RuntimeIdentity.for_testing(business_id),
            declared_business_id=business_id,
            capability=CapabilityType.RESEARCH,
            requested_tools=frozenset({"web_search"}),
            requested_credentials=frozenset(),
        )
    recorded = await _violations(session)
    assert [r.payload["reason"] for r in recorded] == ["not_dispatchable"]


def test_every_denial_in_authorize_goes_through_the_audited_helper() -> None:
    """Structural guard: a future check cannot reject without auditing.

    `authorize_invocation` must contain no bare `raise ScopeViolationError` —
    the only exit is `_deny`, which audits first. This is asserted against the
    source because it is a property of the code's shape, not of any one run.
    """
    source = inspect.getsource(BusinessRegistry.authorize_invocation)
    assert "raise ScopeViolationError" not in source
    assert source.count("await self._deny(") == 5


# ── Runtime identity cannot be forged from a request (D-002) ─────────────────


def test_identity_derives_from_server_supplied_workflow_id() -> None:
    business_id = BusinessId("biz_" + "a" * 32)
    identity = RuntimeIdentity.from_workflow_id(f"bm-{business_id}")
    assert identity.business_id == business_id


def test_non_business_workflow_id_is_refused() -> None:
    """An unidentifiable caller is refused, never defaulted (spec §10)."""
    for bad in ["", "bm-", "bm-biz_short", "executive-cfo", "bm-biz_" + "z" * 32]:
        with pytest.raises(ScopeViolationError):
            RuntimeIdentity.from_workflow_id(bad)


def test_identity_provenance_is_recorded() -> None:
    """Test-constructed identities are labelled so they are visible in audit."""
    assert RuntimeIdentity.for_testing(BusinessId("biz_" + "b" * 32))._source == "testing"
