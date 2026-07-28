"""The Parameter Register (design EXECUTIVE-GOVERNANCE.md Part 3.3, G1b).

Deliverable of packet M9-G1b. Every governing value the platform reads today
— ENFORCING (gates what the platform may do) or ANNOUNCING (paces or warns,
never gates) — registered by name, class, origin, and current source, so
"where did this number come from" is a lookup rather than a source-reading
exercise (Part 9.4's argument, applied to the register itself).

**What this module is not.** It is not the platform-wide Action Registry
(packet M9-G1a, `Action -> Authority Level -> Approval Rule -> Audit
Record`) and does not enumerate actions. It is not the Goal Register (Part
3.3's third section, KPI targets and compliance requirements) beyond the one
row the M9-G1b packet names explicitly (`KpiTarget`'s provenance head, see
`jarvis/domain/contract.py`) — extending it to goals in general is future
work, not claimed here. And it carries no `Executed By` field anywhere: that
is Decision Lineage's territory (M9-F139, `jarvis/domain/provenance.py`).

**Scope, stated honestly.** The register below is a curated enumeration of
the parameters design EXECUTIVE-GOVERNANCE.md Part 1.8, Part 5.1, and
M9-F123 already named as governing — not a claim that every `Field(...)` in
`jarvis/` has been reviewed. `tests/test_parameter_register.py` checks this
list two ways: every entry resolves to a real attribute in the live code
(so the register cannot silently describe something that moved or was
deleted), and every parameter the design document names by identifier
appears here (so a parameter the document already flagged as governing
cannot be silently dropped). Extending *which* parameters are governing is a
design question for a future packet, not something this module's tests can
discover on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.domain.provenance import PERMITTED_POLICY_ORIGINS, Origin


class ParameterClass(StrEnum):
    """The owner's classification (design Part 2.1), carried into the register.

    Revision 1's effect test survives as this field: the question it answers
    is "could changing this value cause the platform to permit something it
    previously refused, or refuse something it previously permitted?" — the
    classification step, prior to and separate from the origin-clause
    admission test (:data:`jarvis.domain.provenance.PERMITTED_POLICY_ORIGINS`).
    """

    ENFORCING = "enforcing"
    """Governs what the platform may do. A policy under the owner's
    definition (Part 2.1) — its Origin MUST be one of
    :data:`~jarvis.domain.provenance.PERMITTED_POLICY_ORIGINS` or it is not a
    legitimate policy, however long the platform has enforced it."""

    ANNOUNCING = "announcing"
    """Describes, paces, or warns — never gates a permission decision. Not
    policy (Part 3.3's Parameter Register section); any recordable Origin is
    admissible."""


@dataclass(frozen=True, slots=True)
class ParameterEntry:
    """One row of the Parameter Register.

    The four things the M9-G1b packet requires recorded, plus a resolvable
    location and a one-line rationale so a reader never has to go read the
    design document to understand why a row says what it says.
    """

    name: str
    """Stable identifier for this parameter. Not a code path — a register
    key, so a future rename of the underlying attribute does not silently
    rename the parameter it governs."""

    param_class: ParameterClass
    origin: Origin

    current_source: str
    """Plain description of where the value actually comes from today —
    "code default", "approved config (Settings/.env)", "specification
    default", or "contract field, no default (caller must supply)". This is
    the fourth thing the packet asks for, kept as prose rather than a second
    enum because the distinction that matters is legitimacy (`origin`), not
    a closed vocabulary of source shapes."""

    location: str
    """``"<dotted.module.path>:<Attribute>[.<field>]"``, resolved by
    `tests/test_parameter_register.py` against the live code."""

    note: str
    """One sentence of rationale, generally citing the finding (M9-F###)
    that established this row."""


PARAMETER_ENTRIES: tuple[ParameterEntry, ...] = (
    # ── ENFORCING — the three M9-F130 violations ────────────────────────
    ParameterEntry(
        name="wake_conditions.max_cycles_per_day",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (Field(default=48))",
        location="jarvis.domain.contract:WakeConditions.max_cycles_per_day",
        note=(
            "Stored, unchanged, in all three live contracts. The platform's "
            "most serious ENFORCING violation. M9-F117 -> M9-F130."
        ),
    ),
    ParameterEntry(
        name="capability_permission.max_invocation_budget_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (Field(default=Decimal('0.50')))",
        location=("jarvis.domain.contract:CapabilityPermission.max_invocation_budget_usd"),
        note="D-003's innermost debit scope carries a code default. M9-F117 -> M9-F130.",
    ),
    ParameterEntry(
        name="autonomy_policy.graduation_eligible",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (bool = False)",
        location="jarvis.domain.contract:AutonomyPolicy.graduation_eligible",
        note=(
            "Defaulted to permission, the opposite of spec §8. M9-G1a flipped it to "
            "False, so the ratchet no longer arms by omission — but the origin "
            "violation STANDS and this row stays: nobody authorised False either, and "
            "PLATFORM_DEFAULT is not a permitted policy origin. The flip made the "
            "default safe; only an owner can make it legitimate. Live stored contracts "
            "are untouched — both affiliate companies store true explicitly (verified "
            "read-only) — so the remediation owed to the owner is the stored values, "
            "not this line. M9-F115 -> M9-F130."
        ),
    ),
    # ── ENFORCING — conforming today ────────────────────────────────────
    ParameterEntry(
        name="budget_policy.business_cap_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.APPROVED_CONFIG,
        current_source="contract field, no default (Field(gt=0))",
        location="jarvis.domain.contract:BudgetPolicy.business_cap_usd",
        note="MUST be explicit before launch; no path silently supplies it. Conforms.",
    ),
    ParameterEntry(
        name="budget_policy.wake_cycle_ceiling_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.APPROVED_CONFIG,
        current_source="contract field, no default (Field(gt=0))",
        location="jarvis.domain.contract:BudgetPolicy.wake_cycle_ceiling_usd",
        note="MUST be explicit before launch. Conforms (design Part 1.8).",
    ),
    ParameterEntry(
        name="autonomy_policy.graduation_threshold",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.APPROVED_CONFIG,
        current_source="contract field, no default (Field(ge=1))",
        location="jarvis.domain.contract:AutonomyPolicy.graduation_threshold",
        note="Explicit configuration set at business creation, never defaulted. Conforms.",
    ),
    ParameterEntry(
        name="settings.budget.platform_rolling_24h_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.APPROVED_CONFIG,
        current_source="approved config (Settings; JARVIS_BUDGET__PLATFORM_ROLLING_24H_USD)",
        location="jarvis.kernel.config:BudgetSettings.platform_rolling_24h_usd",
        note=(
            "A Settings fallback is deployment configuration's own default, not a "
            "silent per-instance one. Conforms (design Part 1.8)."
        ),
    ),
    ParameterEntry(
        name="settings.budget.default_wake_cycle_ceiling_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.SPECIFICATION,
        current_source="specification default (Defaults in Force)",
        location="jarvis.kernel.config:BudgetSettings.default_wake_cycle_ceiling_usd",
        note="A safety net, not a substitute — the spec requires the per-business value.",
    ),
    ParameterEntry(
        name="settings.budget.reasoning_token_price_per_million_usd",
        param_class=ParameterClass.ENFORCING,
        origin=Origin.SPECIFICATION,
        current_source="specification default (D-022 point 2's upper bound)",
        location=("jarvis.kernel.config:BudgetSettings.reasoning_token_price_per_million_usd"),
        note="An upper bound D-022 itself specifies, not a developer's guess. Conforms.",
    ),
    # ── ANNOUNCING ───────────────────────────────────────────────────────
    ParameterEntry(
        name="settings.executive.tick_interval_seconds",
        param_class=ParameterClass.ANNOUNCING,
        origin=Origin.APPROVED_CONFIG,
        current_source="approved config (Settings; owner-adjustable)",
        location="jarvis.kernel.config:ExecutiveSettings.tick_interval_seconds",
        note="A cadence, not a gate. Parameter Register row (Part 3.3).",
    ),
    ParameterEntry(
        name="budget_policy.max_cycles_before_continuation",
        param_class=ParameterClass.ANNOUNCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (Field(default=100))",
        location="jarvis.domain.contract:BudgetPolicy.max_cycles_before_continuation",
        note="Paces D-005's continue-as-new; gates no permission. A code default is fine here.",
    ),
    ParameterEntry(
        name="executive.alerts.spend_bands",
        param_class=ParameterClass.ANNOUNCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (module constant)",
        location="jarvis.executive.alerts:SPEND_BANDS",
        note="Module constant, not config (M9-F123). ANNOUNCING, so recordable is enough.",
    ),
    ParameterEntry(
        name="executive.alerts.platform_bands",
        param_class=ParameterClass.ANNOUNCING,
        origin=Origin.PLATFORM_DEFAULT,
        current_source="code default (module constant)",
        location="jarvis.executive.alerts:PLATFORM_BANDS",
        note="Module constant, not config (M9-F123). Same as SPEND_BANDS.",
    ),
)
"""Every row, in registration order. The source of truth; :data:`PARAMETER_REGISTER`
is a lookup view over it."""


PARAMETER_REGISTER: dict[str, ParameterEntry] = {entry.name: entry for entry in PARAMETER_ENTRIES}
"""The register, keyed by :attr:`ParameterEntry.name`.

Built from :data:`PARAMETER_ENTRIES` rather than written directly as a dict
literal so a duplicated `name` is a fact `tests/test_parameter_register.py`
can catch by comparing lengths — a dict literal would have silently kept
only the last of two entries sharing a key."""


KNOWN_M130_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "wake_conditions.max_cycles_per_day",
        "capability_permission.max_invocation_budget_usd",
        "autonomy_policy.graduation_eligible",
    }
)
"""The three ENFORCING parameters currently violating the origin clause —
**owner-flagged, not fixed** (the M9-G1b packet: "implement nothing, change
no live contract"). See ``docs/design/M9-F130-REMEDIATION.md`` for the
ratification ask.

`tests/test_parameter_register.py` asserts the set of actual violations
equals exactly this frozenset — failing in both directions on purpose
(design Part 9.5's ratchet discipline): a *new* violation must be added here
deliberately, in the same diff that adds it to the REMEDIATION table, and
this set shrinking without the corresponding code default disappearing
would mean the register had gone stale rather than the platform having
improved."""


def is_legitimate_policy(entry: ParameterEntry) -> bool:
    """Return whether ``entry`` satisfies the owner's origin clause.

    Only meaningful for :attr:`ParameterClass.ENFORCING` rows — an
    ANNOUNCING parameter is not policy at all (Part 3.3) and any recordable
    origin is fine for it, so this returns True unconditionally for those.

    Args:
        entry: A row from :data:`PARAMETER_REGISTER`.

    Returns:
        True if ``entry`` is ANNOUNCING, or is ENFORCING with an origin in
        :data:`~jarvis.domain.provenance.PERMITTED_POLICY_ORIGINS`.
    """
    if entry.param_class is not ParameterClass.ENFORCING:
        return True
    return entry.origin in PERMITTED_POLICY_ORIGINS


DESIGN_NAMED_PARAMETERS: tuple[str, ...] = (
    "max_cycles_per_day",
    "max_invocation_budget_usd",
    "graduation_eligible",
    "business_cap_usd",
    "wake_cycle_ceiling_usd",
    "platform_rolling_24h_usd",
    "tick_interval_seconds",
)
"""Identifiers design EXECUTIVE-GOVERNANCE.md Part 1.8 names, verbatim, in
its "Where today's platform lands" table — the closed, citable source this
module's completeness test anchors on (see the module docstring's "Scope,
stated honestly" paragraph). Not exhaustive over every `Field(...)` in
`jarvis/`; exhaustive over what the design document itself already flagged
as governing, which is the claim `tests/test_parameter_register.py` actually
makes and the only one it is entitled to make without a broader design
decision about what else counts."""
