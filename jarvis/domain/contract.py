"""Standard Business Contract (spec §5).

Every business MUST implement these fields. The Executive Layer interacts with
businesses only through this contract and MUST NOT contain business-specific
logic (spec §5), so nothing in this module may reference a concrete business
type.

Per spec §5, "Workers" is *not* a contract field: it is replaced by
`capability_permissions` — which capabilities a business may call, and with what
scopes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.domain.lifecycle import LifecycleState
from jarvis.domain.provenance import ProvenanceHead
from jarvis.kernel.ids import BusinessId, BusinessTypeName


class CapabilityType(StrEnum):
    """The standard capability set (spec §2.2).

    Additional capabilities MAY be added; the set MUST NOT be duplicated per
    business. These are pool-wide generic capabilities, never per-business
    specialists.
    """

    RESEARCH = "research"
    FINANCE = "finance"
    DEVELOPMENT = "development"
    CONTENT = "content"
    DESIGN = "design"
    COMPLIANCE = "compliance"
    OPERATIONS = "operations"


class _Contract(BaseModel):
    """Base for contract models: immutable, strict, no extra fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class CapabilityPermission(_Contract):
    """One capability a business is permitted to invoke, and its scope ceiling.

    This is the authorization record consulted at the capability-pool boundary
    (D-002). A scoped request is admissible only if every scope it asks for is a
    subset of the permission recorded here. The request itself is never the
    authority on its own scope (spec §10).
    """

    capability: CapabilityType
    tool_scope: frozenset[str] = Field(default_factory=frozenset)
    """Tool identifiers this business may reach through this capability."""

    memory_read: bool = True
    memory_write: bool = False
    """Memory access is business-local only (spec §7); there is no field here to
    grant another business's memory, by construction."""

    credential_refs: frozenset[str] = Field(default_factory=frozenset)
    """Handles resolved by the secrets manager at the tool-execution boundary.
    Never secret material — secrets MUST NOT appear in prompts (spec §10)."""

    max_invocation_budget_usd: Decimal = Field(default=Decimal("0.50"), ge=0)
    """Per-invocation ceiling (spec §2.2), the innermost debit scope in D-003.

    Governance note (**M9-F117** -> **M9-F130**): this field's own code
    default is the platform's ENFORCING policy example — see
    ``jarvis.registry.parameter_register``. The default is unchanged here
    because fixing it would rewrite what every live capability permission
    resolves to with no owner sign-off; the M9-G1b packet records it in the
    REMEDIATION table for ratification rather than changing it."""

    provenance: ProvenanceHead = Field(default_factory=ProvenanceHead)
    """Static provenance head for :attr:`max_invocation_budget_usd`
    (Origin/Modified By/Approved By only — ``jarvis.domain.provenance``).
    Additive with a default: a permission stored before this field existed
    deserializes unchanged, honestly empty (Part 3.5)."""


class AutonomyPolicy(_Contract):
    """Per-action-type autonomy configuration (spec §5, §8; identity per A-003).

    Approval is required by default for every money-moving, trade-executing, or
    external-commitment action, with no exception at launch (spec §8).
    """

    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    """Namespaced to the business *type*, e.g. ``affiliate.publish_post`` (A-003)."""

    requires_approval: bool = True
    graduation_threshold: int = Field(ge=1)
    """Consecutive clean approvals required before friction is reduced (spec §8).
    Explicit configuration, set at business creation — never defaulted silently."""

    graduation_eligible: bool = False
    """Whether this action may ever reduce to no-approval via §8's ladder.

    **Opt-in, and the default is the whole point (M9-F115 → M9-F130).** It
    defaulted to `True` until M9-G1a, so a type author who omitted the field got
    a graduation-eligible action — while §8 requires approval by default with no
    exception at launch, which is the opposite. That is design 9.5's "accidental
    autonomy ratchet" in its subtlest form: not a bypass, a default nobody chose.

    Flipping it costs one character of intent and fails safe in both directions:
    a declaration that omits the field is now non-eligible, and a stored contract
    that omits it deserializes as non-eligible rather than silently carrying a
    privilege. Autonomy cannot increase by omission — every increase is now a
    diff a human approved, which is exactly what the pinned inventory in
    `tests/test_action_registry.py` asserts.

    Still `False` for trade execution and any direct movement of real capital:
    those MUST NOT be eligible for graduation in v1 (spec §8, hard constraint),
    and `ApprovalService._advance_counter` guards that a second time on the
    action's own amount so a misconfigured policy still cannot graduate money.

    **Divided between two packets, deliberately.** M9-G1b enumerated this as an
    ENFORCING policy violation and left it in its REMEDIATION table under
    "implement nothing, change no live contract"; M9-G1a's mandate was the
    ratchet itself and carried the flip. Both are correct and the split is the
    reason the record reads oddly: the register still lists the finding because
    the *live stored contracts* are unchanged — both affiliate companies store
    `graduation_eligible: true` explicitly (verified read-only), so this default
    governs only future declarations that omit it. The remediation owed to the
    owner is the stored values, not this line.
    """

    provenance: ProvenanceHead = Field(default_factory=ProvenanceHead)
    """Static provenance head for this policy's ENFORCING fields
    (``graduation_eligible``, ``graduation_threshold``). Additive with a
    default; see :class:`jarvis.domain.provenance.ProvenanceHead`."""

    @field_validator("graduation_threshold")
    @classmethod
    def _threshold_must_be_meaningful(cls, v: int) -> int:
        if v < 3:
            msg = "graduation_threshold below 3 defeats the purpose of the ladder (spec §8)"
            raise ValueError(msg)
        return v


class BudgetPolicy(_Contract):
    """Business-scoped budget ceilings (spec §5, §2.1; hierarchy per D-003)."""

    business_cap_usd: Decimal = Field(gt=0)
    """Halts dispatch for this business alone when breached (D-003 rule 2), so a
    single business cannot trip the platform breaker for everyone (spec §10)."""

    wake_cycle_ceiling_usd: Decimal = Field(gt=0)
    """Maximum reasoning budget for one Manager wake cycle (spec §2.1). MUST be
    explicit before a business launches — there is no platform default."""

    max_cycles_before_continuation: int = Field(default=100, ge=1)
    """Wake cycles before the Manager workflow continues-as-new (D-005), which
    is what keeps durable workflow state bounded. ANNOUNCING, not ENFORCING
    (Part 2.1 classification, ``jarvis.registry.parameter_register``): it
    paces a workflow mechanism and gates no permission, so a code default is
    legitimate here in a way it is not for :attr:`business_cap_usd`."""

    provenance: ProvenanceHead = Field(default_factory=ProvenanceHead)
    """Static provenance head for this policy's ENFORCING fields
    (``business_cap_usd``, ``wake_cycle_ceiling_usd``). Additive with a
    default; see :class:`jarvis.domain.provenance.ProvenanceHead`."""


class WakeConditions(_Contract):
    """When a Business Manager wakes (spec §2.1).

    MUST be explicitly configured per business, never left implicit. A business
    with no wake condition at all can never act, so at least one is required.
    """

    schedule_cron: str | None = None
    """Cron expression for schedule-based waking, e.g. a daily planning cycle."""

    event_triggers: frozenset[str] = Field(default_factory=frozenset)
    """Event types that wake this Manager, e.g. ``approval.decided`` — which is
    what makes the continuation approval model work (D-006)."""

    max_cycles_per_day: int = Field(default=48, ge=1)
    """Bounds wake *frequency*. The spec's cost ceiling bounds a single cycle but
    nothing bounds how often cycles start; without this a Manager woken by its
    own capability results can oscillate indefinitely within budget.

    Governance note (**M9-F117** -> **M9-F130**): this field's code default
    is stored, unchanged, in all three live contracts today — the platform's
    most serious ENFORCING policy violation (design EXECUTIVE-GOVERNANCE.md
    Part 1.8, Part 5.2, Part 9.4). Not fixed here: removing the default or
    rewriting the live contracts is exactly the change the M9-G1b packet
    withholds pending the owner's retroactive blessing at ratification. See
    the REMEDIATION table, ``docs/design/M9-F130-REMEDIATION.md``."""

    provenance: ProvenanceHead = Field(default_factory=ProvenanceHead)
    """Static provenance head for :attr:`max_cycles_per_day`. Additive with a
    default; see :class:`jarvis.domain.provenance.ProvenanceHead`."""


class KpiDirection(StrEnum):
    """Which way a metric's value must move to count as attainment (M7-F30).

    Most metrics are "more is better" (revenue, reports delivered); some are
    "less is better" (hours since the data was last refreshed, error counts).
    `KpiEngine.attainment` reads this to choose which ratio it computes — the
    type declares which kind of metric this is, as data, so the comparison
    stays generic (D-014's discipline, applied to the comparison and not just
    the value)."""

    ABOVE = "above"
    """Higher is better: ``actual / target``, capped at 1."""

    BELOW = "below"
    """Lower is better: ``target / actual``, capped at 1, with a zero actual
    (the best possible reading) scored as full attainment rather than a
    division by zero."""


class KpiTarget(_Contract):
    """A KPI target set by the Executive Layer (spec §3.1) for a Manager to
    execute against tactically (spec §2.1).

    The Manager may not change these — that is the strategy/execution split.
    """

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operator_label: str
    """Plain metric name shown in the UI, e.g. "Monthly Revenue" — never
    ``KPI: revenue_mtd`` (spec §12.5)."""

    target_value: Decimal
    unit: str

    direction: KpiDirection = KpiDirection.ABOVE
    """Which way attainment runs for this metric (M7-F30). Defaults to
    ``ABOVE`` so a target stored before this field existed — the three live
    companies' contract JSON among them — deserializes unchanged: additive
    with a default, not a migration (proven against a pre-field contract
    snapshot in ``tests/test_contract.py``)."""

    provenance: ProvenanceHead = Field(default_factory=ProvenanceHead)
    """Static provenance head for this target (Part 3.3's Goal Register
    row: Origin ``OWNER`` once the Executive sets a target, or
    ``TYPE_DEFINITION`` for a type's suggested one — Part 3.3's collision
    between the two is what M8-F6's deadlock becomes *detectable* rather
    than merely scheduled). Additive with the same precedent as
    :attr:`direction` above; see
    :class:`jarvis.domain.provenance.ProvenanceHead`."""


class BusinessContract(_Contract):
    """The full Standard Business Contract for one business instance (spec §5).

    This is the only surface through which the Executive Layer may interact with
    a business (spec §5). It carries no reference to Temporal, to the capability
    pool's internals, or to any business-specific type.
    """

    business_id: BusinessId
    business_type: BusinessTypeName
    display_name: str = Field(min_length=1, max_length=120)
    """Operator-facing company name (spec §12.5: Business -> Company)."""

    lifecycle_state: LifecycleState = LifecycleState.PROVISIONING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    budget: BudgetPolicy
    wake_conditions: WakeConditions
    capability_permissions: tuple[CapabilityPermission, ...] = ()
    autonomy_policies: tuple[AutonomyPolicy, ...] = ()
    kpi_targets: tuple[KpiTarget, ...] = ()
    goals: tuple[str, ...] = ()
    compliance_requirements: tuple[str, ...] = ()
    """Drafted for the owner, signed off per business type before launch
    (spec, Defaults in Force)."""

    @field_validator("wake_conditions")
    @classmethod
    def _must_have_a_wake_condition(cls, v: WakeConditions) -> WakeConditions:
        if v.schedule_cron is None and not v.event_triggers:
            msg = (
                "wake conditions MUST be explicitly configured, not left implicit "
                "(spec §2.1): set schedule_cron, event_triggers, or both"
            )
            raise ValueError(msg)
        return v

    @field_validator("autonomy_policies")
    @classmethod
    def _action_types_unique(cls, v: tuple[AutonomyPolicy, ...]) -> tuple[AutonomyPolicy, ...]:
        seen = [p.action_type for p in v]
        if len(seen) != len(set(seen)):
            msg = "duplicate action_type in autonomy_policies; identity must be unique (A-003)"
            raise ValueError(msg)
        return v

    def permission_for(self, capability: CapabilityType) -> CapabilityPermission | None:
        """Return this business's permission record for ``capability``.

        Args:
            capability: The capability type being requested.

        Returns:
            The permission record, or None if this business may not invoke it.
        """
        return next((p for p in self.capability_permissions if p.capability is capability), None)

    @property
    def declared_action_types(self) -> frozenset[str]:
        """Return the actions this business is configured to be able to take.

        The set is snapshotted from the business type's definition at creation
        (spec §4, D-014), and every member matches A-003's identifier pattern
        because `AutonomyPolicy.action_type` enforces it.

        This is the authority on what an action *is*. §8's four facts, the
        graduation counters (D-010, A-003), and the approval rendering (D-011)
        all key on the action type string, so a string outside this set names no
        action: it can never graduate, no tool implements it, and an operator
        approving it would authorise nothing. A proposal carrying one is
        therefore an invalid proposal rather than an action needing approval —
        which is the difference between §8's "unknown actions require approval"
        and D-013's "the model proposes, the platform validates".
        """
        return frozenset(p.action_type for p in self.autonomy_policies)

    def declares_action(self, action_type: str) -> bool:
        """Return whether ``action_type`` is an action this business can take."""
        return action_type in self.declared_action_types

    def autonomy_for(self, action_type: str) -> AutonomyPolicy | None:
        """Return the autonomy policy for ``action_type``, if configured.

        A missing policy means approval is required: absence of configuration is
        never permission (spec §8).
        """
        return next((p for p in self.autonomy_policies if p.action_type == action_type), None)

    def requires_approval(self, action_type: str) -> bool:
        """Return whether ``action_type`` requires human approval right now.

        Defaults to True for unknown action types (spec §8: approval by default,
        no exception at launch).
        """
        policy = self.autonomy_for(action_type)
        return True if policy is None else policy.requires_approval
