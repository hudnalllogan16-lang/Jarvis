"""Business Registry (spec §0.1).

The Platform Kernel's authoritative record of what business types are installed
and what business instances exist. Bookkeeping infrastructure, not a reasoning
component — nothing in this module makes a judgement or calls a model.

It is also the trust anchor for D-002: the capability pool resolves an invoking
workflow's business identity through `resolve_identity` rather than trusting the
identity declared on an inbound request, which is what makes spec §10's "under
any circumstance, including bugs or malformed requests" satisfiable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.domain.lifecycle import (
    OPERATOR_LABELS,
    LifecycleState,
    TransitionEffects,
    accepts_dispatch,
    validate_transition,
)
from jarvis.kernel.errors import (
    BusinessNotFoundError,
    BusinessTypeNotFoundError,
    DuplicateBusinessError,
    RegistryError,
    ScopeViolationError,
)
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import BusinessInstanceRow, BusinessTypeRow

logger = get_logger(__name__)


class BusinessRegistry:
    """Discovery, registration, and lifecycle bookkeeping for businesses (§0.1)."""

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditLog,
        decisions: DecisionLog,
    ) -> None:
        """Args:
        session: Active session.
        audit: Audit log writer (spec §11).
        decisions: Decision log writer (spec §11.5). Required, not optional:
            D-008 I-6 makes a Decision Log entry mandatory on every
            lifecycle transition, so the dependency is not injectable as None.
        """
        self._session = session
        self._audit = audit
        self._decisions = decisions

    # ── Business types (plugins, spec §4) ──────────────────────────────────

    async def install_business_type(
        self,
        *,
        name: BusinessTypeName,
        version: str,
        display_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Install or upgrade a business type.

        Args:
            name: Stable type name, e.g. ``affiliate``.
            version: Semantic version. A major bump resets autonomy graduation
                counters for instances of this type (A-003).
            display_name: Operator-facing "company template" name (D-007).
            metadata: Plugin metadata.

        An upgrade (an existing row under a new version) also refreshes
        `installed_at` to now — the column default only fires on the first
        insert, so without this an upgraded row would report its original
        install time forever (M7-F48).

        Raises:
            DuplicateBusinessError: If the same name and version is already
                installed. Reinstalling an identical version is a caller bug,
                not an idempotent no-op — silently absorbing it would hide a
                double-install during plugin loading.
        """
        existing = await self._session.get(BusinessTypeRow, name)
        if existing is not None and existing.version == version:
            raise DuplicateBusinessError(
                f"business type {name} version {version} already installed"
            )
        if existing is None:
            self._session.add(
                BusinessTypeRow(
                    name=name,
                    version=version,
                    display_name=display_name,
                    plugin_metadata=metadata or {},
                )
            )
        else:
            existing.version = version
            existing.display_name = display_name
            existing.plugin_metadata = metadata or {}
            # `installed_at`'s column default only fires on INSERT, so an
            # upgrade left it reading the original install time forever —
            # an operator (or a developer reading the row) had no way to tell
            # a type had ever changed underneath a running platform (M7-F48).
            existing.installed_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.record(
            event_type="business_type.installed",
            actor="platform",
            payload={"name": name, "version": version},
        )

    async def remove_business_type(self, name: BusinessTypeName) -> None:
        """Remove an installed business type.

        Raises:
            BusinessTypeNotFoundError: If the type is not installed.
            DuplicateBusinessError: If instances of the type still exist.
                Removing a type out from under live instances would strand
                workflows with no definition to replay against (D-004).
        """
        row = await self._session.get(BusinessTypeRow, name)
        if row is None:
            raise BusinessTypeNotFoundError(f"business type {name} is not installed")

        stmt = select(BusinessInstanceRow).where(BusinessInstanceRow.business_type == name).limit(1)
        if (await self._session.scalars(stmt)).first() is not None:
            raise DuplicateBusinessError(
                f"cannot remove business type {name}: instances still registered",
                operator_message="Close the companies using this template first.",
            )
        await self._session.delete(row)
        await self._audit.record(
            event_type="business_type.removed", actor="platform", payload={"name": name}
        )

    async def set_type_enabled(self, name: BusinessTypeName, *, enabled: bool) -> None:
        """Enable or disable a business type (D-017).

        Disabling hides the type from the create-a-company flow. It never
        touches existing instances: whether a company runs is its own lifecycle
        state, and conflating the two would make one switch silently pause
        someone's businesses.

        Raises:
            RegistryError: If the type is not installed.
        """
        row = await self._session.get(BusinessTypeRow, name)
        if row is None:
            raise RegistryError(f"business type {name} is not installed")
        row.enabled = enabled
        await self._session.flush()
        await self._audit.record(
            event_type="business_type.toggled",
            actor="operator",
            payload={"name": name, "enabled": enabled},
        )

    async def installed_types(self) -> Sequence[BusinessTypeRow]:
        """Return every installed business type."""
        return (await self._session.scalars(select(BusinessTypeRow))).all()

    # ── Business instances (spec §0.1) ─────────────────────────────────────

    async def register_instance(self, contract: BusinessContract) -> BusinessId:
        """Register a new business instance in PROVISIONING.

        The Executive Layer owns company creation (spec §3.1) but interacts with
        businesses only through the Standard Business Contract (spec §5); this
        method is the seam. A business that does not yet exist has no contract to
        interact through, so creation necessarily runs through the Registry.

        Args:
            contract: The full Standard Business Contract (spec §5).

        Returns:
            The permanent business identifier (spec §0.1).

        Raises:
            BusinessTypeNotFoundError: If the contract names an uninstalled type.
            DuplicateBusinessError: If the identifier or display name is taken.
        """
        if await self._session.get(BusinessTypeRow, contract.business_type) is None:
            raise BusinessTypeNotFoundError(
                f"business type {contract.business_type} is not installed"
            )
        if await self._session.get(BusinessInstanceRow, contract.business_id) is not None:
            raise DuplicateBusinessError(
                f"business {contract.business_id} already registered; "
                "identifiers are permanent and never reused (spec §0.1)"
            )

        self._session.add(
            BusinessInstanceRow(
                business_id=contract.business_id,
                business_type=contract.business_type,
                display_name=contract.display_name,
                lifecycle_state=LifecycleState.PROVISIONING.value,
                contract=contract.model_dump(mode="json"),
            )
        )
        await self._session.flush()
        await self._audit.record(
            event_type="business.registered",
            actor="platform",
            business_id=contract.business_id,
            payload={"business_type": contract.business_type},
        )
        logger.info("business registered", extra={"context": {"id": contract.business_id}})
        return contract.business_id

    async def get_contract(self, business_id: BusinessId) -> BusinessContract:
        """Return the Standard Business Contract for ``business_id``.

        Raises:
            BusinessNotFoundError: If no such instance exists.
        """
        row = await self._require_row(business_id)
        return BusinessContract.model_validate(row.contract)

    async def get_state(self, business_id: BusinessId) -> LifecycleState:
        """Return the current lifecycle state of ``business_id``."""
        row = await self._require_row(business_id)
        return LifecycleState(row.lifecycle_state)

    async def list_instances(
        self, *, state: LifecycleState | None = None
    ) -> Sequence[BusinessInstanceRow]:
        """Return registered instances, optionally filtered by lifecycle state.

        This is the discovery API the Executive Layer, dashboard, and event bus
        use to enumerate businesses (spec §0.1).
        """
        stmt = select(BusinessInstanceRow)
        if state is not None:
            stmt = stmt.where(BusinessInstanceRow.lifecycle_state == state.value)
        return (await self._session.scalars(stmt.order_by(BusinessInstanceRow.created_at))).all()

    async def transition(
        self,
        business_id: BusinessId,
        target: LifecycleState,
        *,
        decision_id: DecisionId,
        reason: str,
        actor: str = "operator",
    ) -> TransitionEffects:
        """Move a business to a new lifecycle state (spec §0.1, D-008).

        Args:
            business_id: The business to transition.
            target: Requested next state.
            decision_id: Identifier minted in an activity (D-004).
            reason: Plain-language why, written to the Decision Log (I-6).
            actor: Who initiated it — ``operator`` or ``executive.*``.

        Returns:
            The effects the caller must apply: timer cancellation, draining,
            dispatch blocking, credential revocation (D-008 invariants I-1..I-5).
            Returned rather than performed, so the Registry stays bookkeeping and
            the caller owns the infrastructure actions.

        Raises:
            BusinessNotFoundError: If no such instance exists.
            InvalidLifecycleTransitionError: If the transition is not permitted.
        """
        row = await self._require_row(business_id)
        current = LifecycleState(row.lifecycle_state)
        effects = validate_transition(current, target)

        row.lifecycle_state = target.value
        await self._session.flush()

        audit_ref = await self._audit.record(
            event_type="business.state_changed",
            actor=actor,
            business_id=business_id,
            payload={
                "from": current.value,
                "to": target.value,
                "effects": effects._asdict(),
            },
        )
        await self._decisions.record(
            decision_id=decision_id,
            business_id=business_id,
            # Operator-facing labels (D-007), not the raw lifecycle values: this
            # entry lands in the activity feed an operator reads directly, and
            # spec §12.5 never permits "provisioning"/"active" there (found
            # live in M6-5a: "Trailhead Gear Reviews moved from provisioning
            # to active.").
            summary=(
                f"{row.display_name} moved from {OPERATOR_LABELS[current]} "
                f"to {OPERATOR_LABELS[target]}."
            ),
            rationale=reason,
            action_type="platform.lifecycle_transition",
            audit_ref=audit_ref,
        )
        return effects

    # ── Authorization anchor (D-002) ───────────────────────────────────────

    async def resolve_identity(self, workflow_business_id: BusinessId) -> BusinessContract:
        """Resolve a workflow's registered business identity to its contract.

        This is the derivation step in D-002. The caller passes the identifier
        the *workflow* was registered under, never one read from a request
        payload, so a malformed or malicious scoped request cannot assert a
        different identity.

        Raises:
            BusinessNotFoundError: If the identity is unknown.
        """
        return await self.get_contract(workflow_business_id)

    async def authorize_invocation(
        self,
        *,
        identity: RuntimeIdentity,
        declared_business_id: BusinessId,
        capability: CapabilityType,
        requested_tools: frozenset[str],
        requested_credentials: frozenset[str],
    ) -> None:
        """Validate a scoped capability request at the pool boundary (D-002).

        Spec §10 requires that an invocation scoped to Business A cannot reach
        Business B's credentials, memory, or budget "under any circumstance,
        including bugs or malformed requests". That is only achievable if the
        requester is not the authority on its own scope, so `identity` is a
        `RuntimeIdentity` derived from the Temporal runtime rather than a plain
        identifier the caller could supply. The request's own claims are treated
        as untrusted input throughout.

        Every rejection is audited before it is raised. A silent denial is worse
        than no denial: it stops the immediate access but leaves no trace that
        something tried, which is the signal an operator most needs.

        Args:
            identity: Identity derived from the running workflow.
            declared_business_id: Identity claimed by the request. Advisory only.
            capability: Capability being invoked.
            requested_tools: Tool scope asked for.
            requested_credentials: Credential handles asked for.

        Raises:
            ScopeViolationError: On any mismatch. Never narrowed, never silently
                corrected — a mismatch means something is wrong, and quietly
                trimming the scope would hide the defect that caused it.
            BusinessNotFoundError: If the derived identity is unknown.
        """
        business_id = identity.business_id

        if declared_business_id != business_id:
            await self._deny(
                identity,
                capability,
                reason="identity_mismatch",
                detail=(
                    f"request declared business {declared_business_id} but workflow identity "
                    f"is {business_id} (spec §10, D-002)"
                ),
                extra={"declared": declared_business_id},
            )

        contract = await self.resolve_identity(business_id)

        # Lifecycle state is read live, never from the contract snapshot. That
        # snapshot is written once at `register_instance` and `transition()`
        # moves only the instance row, so a contract-derived state would report
        # every business as PROVISIONING and gate dispatch on registration-time
        # facts. A dispatch check that cannot see the current state is not a
        # check — D-008 I-4 is a statement about now, not about registration.
        state = await self.get_state(business_id)

        if not accepts_dispatch(state):
            await self._deny(
                identity,
                capability,
                reason="not_dispatchable",
                detail=f"business {business_id} is {state.value} and accepts no dispatch (I-4)",
                operator_message="This company isn't running right now.",
            )

        permission = contract.permission_for(capability)
        if permission is None:
            await self._deny(
                identity,
                capability,
                reason="capability_not_permitted",
                detail=f"business {business_id} may not invoke {capability.value} (spec §5)",
            )
            return

        excess_tools = requested_tools - permission.tool_scope
        if excess_tools:
            await self._deny(
                identity,
                capability,
                reason="tool_scope_escalation",
                detail=f"tool scope exceeds permission for {capability.value} (spec §2.2)",
                extra={"excess": sorted(excess_tools)},
            )

        excess_credentials = requested_credentials - permission.credential_refs
        if excess_credentials:
            await self._deny(
                identity,
                capability,
                reason="credential_scope_escalation",
                detail=f"credential scope exceeds permission for {capability.value} (spec §10)",
                extra={"excess": sorted(excess_credentials)},
            )

    async def _deny(
        self,
        identity: RuntimeIdentity,
        capability: CapabilityType,
        *,
        reason: str,
        detail: str,
        operator_message: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Audit a security rejection, then raise it.

        Single exit point for every denial in `authorize_invocation`, so a new
        check cannot be added without an audit record: the only way to reject is
        to call this.

        The record is written **independently of the caller's transaction**
        (M6-F38). This method is called from `authorize_invocation`, which runs
        inside `kernel.services()`, and the `ScopeViolationError` below travels
        all the way out — `pool.dispatch` re-raises it deliberately, because a
        scope violation is a security event rather than a task outcome. So the
        enclosing scope rolls back, and until now it rolled back this entry with
        it: a probe showed one refused dispatch and zero persisted rows. Every
        §10 denial the platform has ever made was invisible afterwards, which is
        the opposite of what "always audited" promised.

        Raises:
            ScopeViolationError: Always. The return type is `None` only so that
                call sites read as statements.
        """
        await self._audit.record_independently(
            event_type="security.scope_violation",
            actor="platform",
            business_id=identity.business_id,
            payload={
                "reason": reason,
                "capability": capability.value,
                "workflow_id": identity.workflow_id,
                "identity_source": identity.audit_source,
                **(extra or {}),
            },
        )
        logger.warning(
            "scope violation denied",
            extra={"context": {"reason": reason, "business_id": identity.business_id}},
        )
        raise ScopeViolationError(detail, operator_message=operator_message)

    # ── internals ──────────────────────────────────────────────────────────

    async def _require_row(self, business_id: BusinessId) -> BusinessInstanceRow:
        row = await self._session.get(BusinessInstanceRow, business_id)
        if row is None:
            raise BusinessNotFoundError(f"no business registered with id {business_id}")
        return row
