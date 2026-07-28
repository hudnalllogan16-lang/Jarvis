"""The platform-wide Action Registry (design EXECUTIVE-GOVERNANCE.md rev 2, Parts 1.2-1.5, 9.2).

Authority is a property of an **action**, not of a component. A component may
hold several; an action holds exactly one. That inversion is deliberate:
components get refactored, split, and renamed, and an authority model keyed to
components silently re-authorises whatever moves. An `action_type` is already
the platform's unit of authorisation — A-003 makes it the key for graduation
counters, §8's four facts, and D-011's rendering — so keying authority to it
adds no new vocabulary and inherits every guard already built around the string.

Every entry is the owner's four-tuple, each field drawn from a **closed set**:

    Action -> Authority Level -> Approval Rule -> Audit Record

The closed sets are what make "you never need to invent governance again" true
rather than hopeful: a new capability does not design a governance story, it
picks four values, and `_validate` refuses an incoherent pick **at import
time**. Two cross-constraints carry the model's hardest guarantees:

* **L2-strategic admits exactly one approval rule** (`OWNER_APPROVAL`), so
  "never graduates" is a schema property rather than a configuration choice.
* **L3 admits only `OWNER_ONLY`**, so there is no combination of registry values
  that lets the platform *request* an L3 action.

Both are enforced here rather than in review, because a review outcome is not a
property of the code and this table is the only place authority exists (9.2).

## Why this module, and not a field on a contract

Under the owner's plugin trichotomy — *plugins may request authority; plugins
never possess authority; authority is granted by installation* (8.3) — authority
is **not contract data**. No path that reaches contract data can alter it: not a
refresh, not a migration, not a malformed type definition, not an operator edit.
A field would be per-instance, so N contracts would carry N answers and drift
would be invisible until two disagreed. This is one answer, in one place, that a
human can read end to end in a minute — and reading it end to end is the actual
governance act.

## What is deliberately *not* here

The design proposes seven further actions whose mechanisms do not exist yet —
`portfolio.compute_confidence` (Part 6), `reserve.state_transition` (5.4),
`operational.state_transition` (5.3), `confidence.state_transition` (Part 6), and
the three L2-strategic entries `platform.reallocate_capital`,
`platform.set_kpi_target`, `platform.propose_retirement` (8.1) — plus M10/M12's
unwritten `trading.*`. **None is registered.** Registering an action whose code
does not exist is the failure M8-4 named on the nav rail — *"a nav item is a
promise that a destination exists"* — applied to a constitution, and §14 forbids
it directly. They arrive with their mechanisms, each one a visible diff against
`AUTONOMY_PIN`.

L4 and L5 are reserved and hold **no entries**, asserted by test. A reserved
level that something quietly starts using is worse than no reserved level.

## The honest limit of the inheritance invariant

Three checking layers were designed (1.5); two are built. Layers 1 and 2 are
static and live in `tests/test_action_registry.py`. **Layer 3 — the runtime
assertion `context_level >= action_level` — cannot be built: the platform has no
execution-context authority level to compare against (M9-F134).** It is
scheduled with the registry's first consumer rather than assumed present.

Inheritance also governs what a component **may** do, never what it **can** do.
`jarvis/executive/` is L2-capable here and D-038 still forbids it `jarvis.llm`,
because *may* and *can* are different constraints and both are load-bearing
(M9-F132). A reader who concludes "the Executive is L2, therefore it may call a
model" has read the invariant correctly and the architecture wrongly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class AuthorityLevel(StrEnum):
    """What kind of decision an action embodies (design 1.1).

    Ordered by `rank`, because the downward-inheritance invariant is a
    comparison: a holder of a higher level may perform the actions of every
    lower level, never the reverse.
    """

    L0 = "L0"
    """Deterministic computation. Compute, report, notify — nothing else. No
    contract write, no model call, no uninjected clock, no external effect."""

    L1 = "L1"
    """Rule execution: the entire behaviour is a comparison of stored values
    against owner-set parameters. Fires, refuses, pauses and announces without
    asking. **Code may not determine a parameter's value; only policy can.**"""

    L2_TACTICAL = "L2-tactical"
    """Judgment *inside* a company's own contract — what to do with authority
    the company already has. Graduation-eligible under §8's ladder."""

    L2_STRATEGIC = "L2-strategic"
    """Judgment *about* a company's contract, or about the portfolio. **Never
    graduates, and has no counter to graduate with.** Each such judgment is
    about a portfolio state that no longer exists by the next one, so counting
    prior approvals is a category error — the same error D-030 caught when it
    kept refresh consent out of §8's queue."""

    L3 = "L3"
    """Owner only. Not a level the platform may reach at any autonomy setting.
    The platform may *render* an L3 change for an owner to make, and may
    *refuse* to operate without one. Proposal included in the prohibition."""

    L4 = "L4"
    """**Reserved** — candidate: delegated human authority (§3.2's District
    Managers, role-scoped operators). No entry may be registered here."""

    L5 = "L5"
    """**Reserved** — candidate: multi-party or institutional authority (M12
    live trading, a regulated deployment). No entry may be registered here."""

    @property
    def rank(self) -> int:
        """Position on the ladder, for the inheritance comparison."""
        return _RANK[self]


_RANK: Final[Mapping[AuthorityLevel, int]] = {
    AuthorityLevel.L0: 0,
    AuthorityLevel.L1: 1,
    AuthorityLevel.L2_TACTICAL: 2,
    AuthorityLevel.L2_STRATEGIC: 3,
    AuthorityLevel.L3: 4,
    AuthorityLevel.L4: 5,
    AuthorityLevel.L5: 6,
}
"""L2-strategic outranks L2-tactical: it is judgment *about* a contract rather
than judgment *inside* one, and the never-autonomous list (1.3) puts every
strategic act above every tactical one."""

RESERVED_LEVELS: Final[frozenset[AuthorityLevel]] = frozenset(
    {AuthorityLevel.L4, AuthorityLevel.L5}
)


class ApprovalRule(StrEnum):
    """Who must answer before an action takes effect (design 1.2). Closed set."""

    NONE = "NONE"
    """Executes automatically; no human in the path."""

    GRADUATED = "GRADUATED"
    """Approval by default, may reduce to none via §8's ladder after a clean
    streak. The only rule that ever reduces."""

    OWNER_APPROVAL = "OWNER_APPROVAL"
    """A human must answer a specific §8 approval before any effect. Never
    reduces — there is no ladder attached to this rule."""

    OWNER_ONLY = "OWNER_ONLY"
    """Not requestable by the platform at all; only an owner performs it."""


class AuditObligation(StrEnum):
    """What a level owes the record (design 1.7). Closed set of five.

    Not "everything is audited" — a uniform rule produces uniform noise and is
    why nobody reads audit logs.
    """

    AUDIT = "AUDIT"
    DECISION_LOG = "DECISION_LOG"
    NOTIFY_ON_TRANSITION = "NOTIFY_ON_TRANSITION"
    NOTIFY_ON_PROPOSAL = "NOTIFY_ON_PROPOSAL"
    ACTOR_IDENTITY = "ACTOR_IDENTITY"
    """Required by all six L3 rows and **satisfiable by none**: every L3 path
    today passes `"platform"` or `"operator"` as its actor. Recorded honestly
    rather than quietly dropped — a governance model whose highest level has the
    weakest attribution is inverted, and naming it is what schedules the fix
    (design 1.7, escalation 13.4)."""


ADMISSIBLE_RULES: Final[Mapping[AuthorityLevel, frozenset[ApprovalRule]]] = {
    AuthorityLevel.L0: frozenset({ApprovalRule.NONE}),
    AuthorityLevel.L1: frozenset({ApprovalRule.NONE}),
    AuthorityLevel.L2_TACTICAL: frozenset({ApprovalRule.GRADUATED, ApprovalRule.OWNER_APPROVAL}),
    AuthorityLevel.L2_STRATEGIC: frozenset({ApprovalRule.OWNER_APPROVAL}),
    AuthorityLevel.L3: frozenset({ApprovalRule.OWNER_ONLY}),
    AuthorityLevel.L4: frozenset(),
    AuthorityLevel.L5: frozenset(),
}
"""Design 1.2's cross-constraint table. The two single-element rows are the
model's hardest guarantees; the two empty rows make the reserved levels
unusable even before the emptiness test runs."""

REQUIRED_OBLIGATIONS: Final[Mapping[AuthorityLevel, frozenset[AuditObligation]]] = {
    AuthorityLevel.L0: frozenset(),
    AuthorityLevel.L1: frozenset({AuditObligation.AUDIT}),
    AuthorityLevel.L2_TACTICAL: frozenset(
        {
            AuditObligation.AUDIT,
            AuditObligation.DECISION_LOG,
            AuditObligation.NOTIFY_ON_PROPOSAL,
        }
    ),
    AuthorityLevel.L2_STRATEGIC: frozenset(
        {
            AuditObligation.AUDIT,
            AuditObligation.DECISION_LOG,
            AuditObligation.NOTIFY_ON_PROPOSAL,
        }
    ),
    AuthorityLevel.L3: frozenset(
        {
            AuditObligation.AUDIT,
            AuditObligation.DECISION_LOG,
            AuditObligation.ACTOR_IDENTITY,
        }
    ),
    AuthorityLevel.L4: frozenset(),
    AuthorityLevel.L5: frozenset(),
}
"""The *minimum* each level owes. An entry may record more, never less. L0 owes
nothing because a pure read that wrote nothing has nothing to record."""

FORBIDDEN_OBLIGATIONS: Final[Mapping[AuthorityLevel, frozenset[AuditObligation]]] = {
    AuthorityLevel.L0: frozenset({AuditObligation.NOTIFY_ON_PROPOSAL}),
    AuthorityLevel.L1: frozenset({AuditObligation.NOTIFY_ON_PROPOSAL}),
    AuthorityLevel.L2_TACTICAL: frozenset(),
    AuthorityLevel.L2_STRATEGIC: frozenset(),
    AuthorityLevel.L3: frozenset(),
    AuthorityLevel.L4: frozenset(),
    AuthorityLevel.L5: frozenset(),
}
"""L1 "notifies on transitions, never on conditions" (1.7), and neither L0 nor
L1 proposes anything — so `NOTIFY_ON_PROPOSAL` below L2 would describe a
notification about a proposal that cannot exist. Part 5.5 is the whole argument
for why this matters: a notification the operator learns to dismiss takes the
one that mattered with it."""

PLATFORM_NAMESPACE: Final[str] = "platform"
"""Reserved. A business type may never declare an action in this namespace
(A-003, M9-F116). Three live platform actions already use it, which made it a
de-facto reservation with nothing enforcing it."""


@dataclass(frozen=True, slots=True)
class ActionEntry:
    """One row of the four-tuple, plus the emit site inheritance is checked against.

    Frozen because the registry is read at import and never at runtime: an
    entry that could be mutated would make every static guard below a statement
    about start-up rather than about the code.
    """

    action_type: str
    """A-003's dotted identifier, namespaced to its owning business type or to
    `platform`."""

    level: AuthorityLevel
    approval_rule: ApprovalRule
    audit_record: frozenset[AuditObligation]

    module: str | None = None
    """Repository-relative path of the **one** module permitted to emit this
    action, or None where no platform path exists at all. `None` is not a gap:
    for four of the six L3 rows it is the strongest possible statement — an
    owner changes a ceiling, an autonomy grant, a credential scope, or a
    compliance requirement in configuration, and there is no code path that
    performs it."""

    symbol: str | None = None
    """The function or constant inside `module` that is the emit site. Named so
    the emit site is unique and checkable — the M1-R2 pattern, which has
    forbidden a bare `raise ScopeViolationError` outside `_deny` since M1."""

    note: str = ""

    def __post_init__(self) -> None:
        _validate(self)


def _validate(entry: ActionEntry) -> None:
    """Refuse an incoherent entry at import time.

    Import time rather than test time because these are schema properties, and
    a schema enforced only by a test is a schema anyone can bypass by not
    running the test. The suite asserts the same properties independently
    (`tests/test_action_registry.py`) so that this function's own failure to
    fire is detectable.

    Raises:
        ValueError: If the level is reserved, the approval rule is inadmissible
            for the level, a required audit obligation is missing, or a
            forbidden one is present.
    """
    if entry.level in RESERVED_LEVELS:
        msg = (
            f"{entry.action_type}: {entry.level} is reserved and holds no entries "
            f"(design 1.1). Assign a live level or leave the action unregistered."
        )
        raise ValueError(msg)

    admissible = ADMISSIBLE_RULES[entry.level]
    if entry.approval_rule not in admissible:
        msg = (
            f"{entry.action_type}: approval rule {entry.approval_rule} is not admissible "
            f"at {entry.level}; permitted: {sorted(admissible)} (design 1.2). "
            f"This is the cross-constraint that makes 'L2-strategic never graduates' and "
            f"'L3 is never requestable' schema properties."
        )
        raise ValueError(msg)

    missing = REQUIRED_OBLIGATIONS[entry.level] - entry.audit_record
    if missing:
        msg = (
            f"{entry.action_type}: {entry.level} requires audit obligations "
            f"{sorted(missing)} and the entry omits them (design 1.7)."
        )
        raise ValueError(msg)

    forbidden = FORBIDDEN_OBLIGATIONS[entry.level] & entry.audit_record
    if forbidden:
        msg = (
            f"{entry.action_type}: {entry.level} may not carry {sorted(forbidden)} — "
            f"nothing below L2 proposes anything (design 1.7)."
        )
        raise ValueError(msg)

    if entry.symbol is not None and entry.module is None:
        msg = f"{entry.action_type}: names a symbol with no module to find it in."
        raise ValueError(msg)


def _entry(
    action_type: str,
    level: AuthorityLevel,
    approval_rule: ApprovalRule,
    audit: set[AuditObligation],
    *,
    module: str | None = None,
    symbol: str | None = None,
    note: str = "",
) -> ActionEntry:
    return ActionEntry(
        action_type=action_type,
        level=level,
        approval_rule=approval_rule,
        audit_record=frozenset(audit),
        module=module,
        symbol=symbol,
        note=note,
    )


_A = AuditObligation
_L = AuthorityLevel
_R = ApprovalRule

_ENTRIES: Final[tuple[ActionEntry, ...]] = (
    # ── L0 · deterministic computation ──────────────────────────────────────
    _entry(
        "portfolio.compute_rollup",
        _L.L0,
        _R.NONE,
        set(),
        module="jarvis/executive/rollup.py",
        symbol="compute_portfolio_rollup",
    ),
    _entry(
        "portfolio.compute_census",
        _L.L0,
        _R.NONE,
        set(),
        module="jarvis/executive/health.py",
        symbol="compute_portfolio_health",
    ),
    _entry(
        "kpi.compute_health",
        _L.L0,
        _R.NONE,
        set(),
        module="jarvis/kpi/engine.py",
        symbol="health",
    ),
    _entry(
        "budget.read_aggregates",
        _L.L0,
        _R.NONE,
        set(),
        module="jarvis/budget/ledger.py",
        symbol="platform_spend_24h",
        note="Reads only. The ledger's refusing half is budget.refuse_reservation at L1.",
    ),
    # ── L1 · rule execution ─────────────────────────────────────────────────
    _entry(
        "platform.circuit_breaker",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.DECISION_LOG},
        module="jarvis/budget/breaker.py",
        symbol="trip",
        note=(
            "The component that enforces the rule is the component that announces it "
            "(design 1.6): the halt narrative asks assert_closed rather than comparing "
            "the rollup's own arithmetic."
        ),
    ),
    _entry(
        "budget.refuse_reservation",
        _L.L1,
        _R.NONE,
        {_A.AUDIT},
        module="jarvis/budget/ledger.py",
        symbol="reserve",
        note="Ceilings come from the contract, never from this module (L1's parameter rule).",
    ),
    _entry(
        "spending.company_band_notice",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.NOTIFY_ON_TRANSITION},
        module="jarvis/executive/alerts.py",
        symbol="raise_spend_alerts",
        note="Bands are module constants today, not config — M9-F123, owned by the register.",
    ),
    _entry(
        "spending.platform_band_notice",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.NOTIFY_ON_TRANSITION},
        module="jarvis/executive/alerts.py",
        symbol="raise_platform_ceiling_alerts",
        note="M9-F123 as above.",
    ),
    _entry(
        "platform.approval_expired",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.DECISION_LOG, _A.NOTIFY_ON_TRANSITION},
        module="jarvis/approvals/service.py",
        symbol="expire_stale",
        note="Silence is refusal (spec §9): expiry pauses and never auto-approves.",
    ),
    _entry(
        "platform.lifecycle_transition",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.DECISION_LOG},
        module="jarvis/registry/registry.py",
        symbol="transition",
        note="D-008's matrix; all 25 pairs tested since M1-R3.",
    ),
    _entry(
        "business.wake_cycle",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.DECISION_LOG},
        module="jarvis/manager/activities.py",
        symbol="record_cycle_decision",
    ),
    _entry(
        "business.park_degraded",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.DECISION_LOG, _A.NOTIFY_ON_TRANSITION},
        module="jarvis/manager/activities.py",
        symbol="record_manager_park",
        note="D-034.1.",
    ),
    _entry(
        "business.dropped_wake_notice",
        _L.L1,
        _R.NONE,
        {_A.AUDIT, _A.NOTIFY_ON_TRANSITION},
        module="jarvis/manager/activities.py",
        symbol="record_dropped_wake",
        note="D-035.",
    ),
    _entry(
        "capability.dispatch",
        _L.L1,
        _R.NONE,
        {_A.AUDIT},
        module="jarvis/capabilities/pool.py",
        symbol="dispatch",
    ),
    _entry(
        "capability.deny",
        _L.L1,
        _R.NONE,
        {_A.AUDIT},
        module="jarvis/registry/registry.py",
        symbol="_deny",
        note=(
            "M1-R2: all five security rejections route here, which audits and then raises. "
            "The precedent this registry's unique-emit-site check generalises."
        ),
    ),
    _entry(
        "reservation.reconcile",
        _L.L1,
        _R.NONE,
        {_A.AUDIT},
        module="jarvis/scheduler/service.py",
        symbol="_reconcile_reservations",
        note="D-034.3.",
    ),
    _entry(
        "autonomy.reset",
        _L.L1,
        _R.NONE,
        {_A.AUDIT},
        module="jarvis/approvals/service.py",
        symbol="_reset_counter",
        note=(
            "Resetting a streak lowers autonomy, so it is safe at L1. Advancing one raises "
            "autonomy and is not a separate action: it is the graduated outcome of the "
            "L2-tactical action itself, guarded by _advance_counter's two guards. "
            "**Two emitters, deliberately (M9-F161):** this one, and "
            "BusinessRegistry._reset_graduation_on_major_bump for A-003's major-version "
            "rule. Both revoke; neither grants. A refusal reachable by more paths is a "
            "safer platform, and the grant's single writer is asserted separately."
        ),
    ),
    # ── L2-tactical · judgment inside a company's own contract ──────────────
    _entry(
        "affiliate.publish_post",
        _L.L2_TACTICAL,
        _R.GRADUATED,
        {_A.AUDIT, _A.DECISION_LOG, _A.NOTIFY_ON_PROPOSAL},
        module="jarvis/businesses/affiliate.py",
        symbol="AFFILIATE",
        note=(
            "The one live L2 action. Threshold 5, counter at 0. Whether it should remain "
            "graduation-eligible is an open owner question (design 13.5) and is not "
            "answered here — this records that GRADUATED is coherent, not that it is desired."
        ),
    ),
    # ── L3 · owner only ─────────────────────────────────────────────────────
    # Every row requires ACTOR_IDENTITY and nothing can supply it (design 1.7).
    _entry(
        "platform.change_spending_ceiling",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        note=(
            "Config; no code path exists, and that absence is the guarantee. "
            "Never-autonomous item 1: a platform that may edit its own ceilings has "
            "every authority, one config write later."
        ),
    ),
    _entry(
        "platform.grant_autonomy",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        note="Contract, at creation. Never-autonomous item 2. Band C freezes it on the instance.",
    ),
    _entry(
        "platform.change_authority_level",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        module="jarvis/domain/authority.py",
        symbol="_ENTRIES",
        note=(
            "This table. Never-autonomous item 9, and the reason the ratchet guard exists: "
            "editing a level here is the act that requires owner sign-off."
        ),
    ),
    _entry(
        "platform.install_business_type",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        module="jarvis/businesses/provisioning.py",
        symbol="install",
        note=(
            "Authority is granted by installation (8.3), so installing is an L3 act. "
            "An upgrade is also an installation — a level change discovered there fails "
            "the install and never rides a refresh consent (M9-F133, T6)."
        ),
    ),
    _entry(
        "platform.grant_credential_scope",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        note="Contract, at creation. Never-autonomous item 6; D-015 keeps material out of code.",
    ),
    _entry(
        "platform.change_compliance_requirement",
        _L.L3,
        _R.OWNER_ONLY,
        {_A.AUDIT, _A.DECISION_LOG, _A.ACTOR_IDENTITY},
        note=(
            "Type definition, owner-signed, injected verbatim (D-027.5). Never-autonomous "
            "item 8, and per tension T5 this is where a rule binding even the owner belongs "
            "— not a reserved authority level."
        ),
    ),
)


ACTION_REGISTRY: Final[Mapping[str, ActionEntry]] = {e.action_type: e for e in _ENTRIES}
"""The platform-wide matrix. Twenty-four actions: 4 L0, 13 L1, 1 L2-tactical, 6 L3.

Sixteen of the twenty-four are rule execution or deterministic computation
against one live judgment action — the platform is overwhelmingly a
rule-executing system, which is the right shape and worth knowing (design 1.4).
"""

if len(ACTION_REGISTRY) != len(_ENTRIES):  # pragma: no cover - import-time guard
    _dupes = sorted({e.action_type for e in _ENTRIES if list(_ENTRIES).count(e) > 1})
    msg = f"duplicate action_type in the Action Registry: {_dupes}"
    raise ValueError(msg)


MODULE_AUTHORITY: Final[Mapping[str, AuthorityLevel]] = {
    # L0 — computes and reports; D-038's import rule keeps the first two honest.
    "jarvis/executive/rollup.py": AuthorityLevel.L0,
    "jarvis/executive/health.py": AuthorityLevel.L0,
    "jarvis/kpi/engine.py": AuthorityLevel.L0,
    # L1 — fires, refuses, pauses, announces.
    "jarvis/budget/ledger.py": AuthorityLevel.L1,
    "jarvis/budget/breaker.py": AuthorityLevel.L1,
    "jarvis/executive/alerts.py": AuthorityLevel.L1,
    "jarvis/approvals/service.py": AuthorityLevel.L1,
    "jarvis/registry/registry.py": AuthorityLevel.L1,
    "jarvis/manager/activities.py": AuthorityLevel.L1,
    "jarvis/capabilities/pool.py": AuthorityLevel.L1,
    "jarvis/scheduler/service.py": AuthorityLevel.L1,
    # L2-tactical — the one type that declares a judgment action.
    "jarvis/businesses/affiliate.py": AuthorityLevel.L2_TACTICAL,
    # L3 — where an owner's own acts land.
    "jarvis/domain/authority.py": AuthorityLevel.L3,
    "jarvis/businesses/provisioning.py": AuthorityLevel.L3,
}
"""The level each emitting module carries — design 1.5's layers 1 and 2 compare
against this.

Declared **here** rather than as a constant in each module, for the same reason
authority is not contract data: one table a human reads end to end, versus N
declarations that drift until two disagree. It also keeps the annotation out of
fourteen source files, so a level change is a diff in the governance module
where the ratchet guard can see it.

A module's level is a **ceiling**, not a claim that it emits at that level:
`provisioning.py` is L3 because installing a type grants authority (8.3), and
`authority.py` is L3 because this table is where an authority level is changed.
Both are owner acts performed through code, which is exactly what L3's
"the platform may *render* an L3 change for an owner to make" describes.
"""


def registry_digest() -> str:
    """Return a stable digest over every governance-relevant field.

    Design 9.2 guard 4. The pin makes "any level change requires owner sign-off"
    mechanical: changing a level changes this value, the ratchet test fails, and
    updating the pin is a visible single-line diff that cannot be mistaken for
    anything else. It is also M9-F133's fix — an upgrade that would re-grant
    authority changes the digest and therefore cannot ride a refresh consent.

    `note` is excluded deliberately: prose is not governance, and a digest that
    changed when a comment was reworded would be updated so routinely that the
    update would stop being a reviewable event.
    """
    payload = [
        {
            "action_type": e.action_type,
            "level": str(e.level),
            "approval_rule": str(e.approval_rule),
            "audit_record": sorted(str(o) for o in e.audit_record),
            "module": e.module,
            "symbol": e.symbol,
        }
        for e in sorted(_ENTRIES, key=lambda e: e.action_type)
    ]
    payload.append({str(m): str(level) for m, level in sorted(MODULE_AUTHORITY.items())})  # type: ignore[arg-type]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── A-003 namespace enforcement (M9-F116, design 8.3 check 4) ───────────────


def platform_owned_namespaces() -> frozenset[str]:
    """Return every prefix the platform itself uses, plus the reserved one.

    Derived from the registry rather than listed, so adding a platform action
    reserves its namespace in the same edit. A hand-maintained list would drift
    the moment the two diverged, and the direction it drifts in — a platform
    prefix that is no longer reserved — is precisely the bypass.
    """
    business_prefixes = {
        e.action_type.split(".", 1)[0]
        for e in _ENTRIES
        if e.level in {AuthorityLevel.L2_TACTICAL, AuthorityLevel.L2_STRATEGIC}
    }
    platform_prefixes = {e.action_type.split(".", 1)[0] for e in _ENTRIES} - business_prefixes
    return frozenset(platform_prefixes | {PLATFORM_NAMESPACE})


def namespace_error(action_type: str, *, type_name: str) -> str | None:
    """Return why `action_type` may not be declared by `type_name`, or None.

    A-003 says an action type is namespaced to the business *type*. **Nothing
    enforced it** (M9-F116): `AutonomyPolicy.action_type`'s pattern admits any
    dotted identifier, so a business type could legally declare
    `platform.reallocate_capital` or `platform.circuit_breaker`, and both would
    validate, install, and enter `declared_action_types`.

    Contained today only by accident of what does not exist yet —
    `platform_feed()` filters on `business_id IS NULL`, so a company's rows
    cannot masquerade as platform ones, and no platform approval path exists to
    confuse. Design 8.1 builds exactly that path. **Reserve the namespace before
    the path exists**, because a plugin acquiring a platform authority is the
    one failure this registry exists to make impossible.

    Returned rather than raised so the caller decides the error class: install
    refuses with `ConfigurationError`, and a test can assert the reason text.

    Args:
        action_type: The dotted identifier a type declares.
        type_name: The declaring business type's own name.

    Returns:
        A reason string if the declaration is refused, otherwise None.
    """
    prefix, _, remainder = action_type.partition(".")
    if not remainder:
        return (
            f"action type {action_type!r} is not namespaced: A-003 requires '{type_name}.<action>'"
        )
    if prefix == PLATFORM_NAMESPACE:
        return (
            f"business type {type_name!r} declares {action_type!r}: the "
            f"{PLATFORM_NAMESPACE!r} namespace is reserved for platform-owned actions "
            f"and a type may never declare one (A-003, M9-F116). Plugins may request "
            f"authority; they never possess it."
        )
    if prefix in platform_owned_namespaces():
        return (
            f"business type {type_name!r} declares {action_type!r}, but {prefix!r} is a "
            f"platform-owned namespace in the Action Registry (A-003, M9-F116)."
        )
    if prefix != type_name:
        return (
            f"business type {type_name!r} declares {action_type!r}: A-003 namespaces an "
            f"action type to its own type, so the prefix must be {type_name!r}, not "
            f"{prefix!r}."
        )
    return None


def granted_entry(action_type: str) -> ActionEntry | None:
    """Return the registry entry for `action_type`, or None if unregistered.

    An unregistered action has **no authority**, which is the default the
    trichotomy requires: a plugin possesses nothing the registry did not grant.
    """
    return ACTION_REGISTRY.get(action_type)


def autonomy_inventory() -> Mapping[str, tuple[str, str]]:
    """Return `{action_type: (level, approval_rule)}` for the pinned ratchet test.

    The registry half of design 9.5's assertion 4. The catalog half — each live
    type's `graduation_threshold` and `graduation_eligible` — is assembled by the
    test, because this module may not import `jarvis.businesses` (M1 may not
    reach M5, `tests/test_layering.py`).
    """
    return {e.action_type: (str(e.level), str(e.approval_rule)) for e in _ENTRIES}


__all__ = [
    "ACTION_REGISTRY",
    "ADMISSIBLE_RULES",
    "FORBIDDEN_OBLIGATIONS",
    "MODULE_AUTHORITY",
    "PLATFORM_NAMESPACE",
    "REQUIRED_OBLIGATIONS",
    "RESERVED_LEVELS",
    "ActionEntry",
    "ApprovalRule",
    "AuditObligation",
    "AuthorityLevel",
    "autonomy_inventory",
    "granted_entry",
    "namespace_error",
    "platform_owned_namespaces",
    "registry_digest",
]
