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
from jarvis.domain.refresh import frozen_field_differences
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
from jarvis.persistence.models import (
    AutonomyCounterRow,
    BusinessInstanceRow,
    BusinessTypeRow,
    ContractRefreshDeclineRow,
)

logger = get_logger(__name__)


def _major(version: str) -> int:
    """Return the major component of a semantic version string (A-003)."""
    return int(version.split(".")[0])


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

        An upgrade that changes the **major** version additionally resets every
        graduation counter belonging to this type's companies, per A-003. See
        `_reset_graduation_on_major_bump` for why that happens here.

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
        previous_version = existing.version if existing is not None else None
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
        if previous_version is not None:
            await self._reset_graduation_on_major_bump(name, previous_version, version)

    async def _reset_graduation_on_major_bump(
        self, name: BusinessTypeName, previous_version: str, version: str
    ) -> int:
        """Reset this type's graduation counters when its major version moves.

        A-003: "Changing a business type's plugin **major** version resets its
        counters; minor versions do not." The action's behaviour may have
        changed, so the operator's prior approvals no longer vouch for it.

        The rule was asserted in four docstrings, backed by a column, and had
        zero readers and zero writers — the `KpiEngine.record` shape again
        (M7-F21), and again absent from the deferred-completion ledger
        (**M8-F8**). This is its reader and its writer.

        **It runs at install, not at refresh acceptance**, which was the open
        question in the design's Part 7.2. A-003 keys the rule to the version
        change itself, and a reset that waited for consent would leave a
        graduated action running unattended under changed behaviour for as long
        as an operator ignored the offer — the opposite of what the rule is
        for. A refresh is a change an operator agrees to; this is a safety
        property they do not get to defer. It is deliberately *not* a Band C
        exception: a graduation counter is not a contract field at all (design
        Part 4.2), so nothing here touches `autonomy_policies`.

        Args:
            name: The type whose version changed.
            previous_version: The version that was installed before this call.
            version: The version now installed.

        Returns:
            How many counters were reset. Zero for a minor bump, and zero for a
            major bump with nothing graduated — which is every case live today
            (design 4.5: one counter row exists in the entire system, at zero,
            ungraduated).
        """
        target_major = _major(version)
        if _major(previous_version) == target_major:
            return 0

        instances = select(BusinessInstanceRow.business_id).where(
            BusinessInstanceRow.business_type == name
        )
        stmt = select(AutonomyCounterRow).where(AutonomyCounterRow.business_id.in_(instances))
        counters = (await self._session.scalars(stmt)).all()

        reset = 0
        for counter in counters:
            if (
                counter.plugin_major_version == target_major
                and counter.consecutive_approvals == 0
                and not counter.graduated
            ):
                # Already at this major and holding nothing: rewriting it would
                # produce an audit entry describing a reset that reset nothing.
                continue
            counter.consecutive_approvals = 0
            counter.graduated = False
            counter.plugin_major_version = target_major
            reset += 1
            await self._audit.record(
                event_type="autonomy.reset",
                actor="platform",
                business_id=BusinessId(counter.business_id),
                payload={
                    "action_type": counter.action_type,
                    "reason": "plugin_major_version",
                    "major_version": target_major,
                },
            )
        await self._session.flush()
        await self._audit.record(
            event_type="business_type.graduation_reset",
            actor="platform",
            payload={
                "name": name,
                "from_major": _major(previous_version),
                "to_major": target_major,
                "counters_reset": reset,
            },
        )
        logger.info(
            "graduation counters reset on a major version bump",
            extra={"context": {"name": name, "counters_reset": reset}},
        )
        return reset

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

    async def installed_type(self, name: BusinessTypeName) -> BusinessTypeRow | None:
        """Return one installed business type row, or None if not installed."""
        return await self._session.get(BusinessTypeRow, name)

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

    async def refresh_contract(
        self,
        business_id: BusinessId,
        contract: BusinessContract,
        *,
        audit_ref_payload: dict[str, Any],
    ) -> int:
        """Replace a company's stored contract, refusing to touch Band C (D-029).

        The only contract writer besides `register_instance`, and deliberately
        narrow: it re-reads the stored contract, compares every Band C field
        against the proposal, and refuses the whole write if any of them moved.
        The guard lives here rather than in the planner because a guard at the
        write boundary holds for every future caller, including ones that do
        not exist yet — and the fields it protects are identity, the operator's
        money, and the two authorization records `authorize_invocation` reads.

        The new contract is validated by `BusinessContract` before it arrives
        (the caller constructs it through the model), so a refresh that would
        produce an invalid contract — a type that dropped every wake condition,
        say — never reaches this method.

        Args:
            business_id: The company whose contract is being replaced.
            contract: The full replacement contract.
            audit_ref_payload: Before/after detail for the audit record. Passed
                in rather than derived here so the Registry stays bookkeeping
                and the caller — which knows what it changed and why — owns the
                description.

        Returns:
            The audit row id, usable as a Decision Log `audit_ref`.

        Raises:
            BusinessNotFoundError: If no such instance exists.
            RegistryError: If the proposal differs from the stored contract in
                any Band C field, or names a different company.
        """
        row = await self._require_row(business_id)
        stored = BusinessContract.model_validate(row.contract)

        if contract.business_id != business_id:
            raise RegistryError(
                f"refresh for {business_id} carries a contract for {contract.business_id}"
            )
        moved = frozen_field_differences(stored, contract)
        if moved:
            raise RegistryError(
                f"refusing to refresh {business_id}: it would change never-refreshed "
                f"fields {list(moved)} (D-029 Band C)",
                operator_message="Jarvis stopped an update that would have changed "
                "settings you chose.",
            )

        row.contract = contract.model_dump(mode="json")
        await self._session.flush()
        audit_ref = await self._audit.record(
            event_type="business.contract_refreshed",
            actor="operator",
            business_id=business_id,
            payload=audit_ref_payload,
        )
        logger.info("contract refreshed", extra={"context": {"id": business_id}})
        return audit_ref

    async def record_refresh_decline(
        self,
        business_id: BusinessId,
        *,
        declined_version: str,
        source_digest: str,
        target_digest: str,
    ) -> None:
        """Persist that the operator declined a contract-refresh plan (D-030
        Part 4.3; M8-F102/M9-4).

        Upserted, not appended: one row per company answers "is the version
        installed right now the one this company's operator already said no
        to" — the only question `plan_refresh` asks of it — and the Decision
        Log already holds the append-only record of every decline an operator
        can read (`ContractRefreshService.decline_refresh`'s own write, spec
        §11.5). A second decline before the version moves again replaces the
        row rather than growing a history nothing reads.

        Args:
            business_id: The company whose operator declined.
            declined_version: The installed type version the declined plan was
                computed against — the suppression key (see
                `declined_refresh_version`).
            source_digest: Band B digest of the contract at decline time.
            target_digest: Band B digest the declined plan would have written.
                Both digests are audit context, not the suppression key.
        """
        row = await self._session.get(ContractRefreshDeclineRow, business_id)
        if row is None:
            self._session.add(
                ContractRefreshDeclineRow(
                    business_id=business_id,
                    declined_version=declined_version,
                    source_digest=source_digest,
                    target_digest=target_digest,
                )
            )
        else:
            row.declined_version = declined_version
            row.source_digest = source_digest
            row.target_digest = target_digest
            row.declined_at = datetime.now(UTC)
        await self._session.flush()

    async def declined_refresh_version(self, business_id: BusinessId) -> str | None:
        """Return the installed type version this company's operator most
        recently declined, or None if no decline is on file.

        `plan_refresh` suppresses its offer exactly while the version it is
        currently planning against equals this — deliberately a version
        string comparison, not a digest match. See
        `ContractRefreshDeclineRow`'s docstring (M8-F3) for why a content
        digest cannot make that distinction safely.
        """
        row = await self._session.get(ContractRefreshDeclineRow, business_id)
        return row.declined_version if row is not None else None

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
