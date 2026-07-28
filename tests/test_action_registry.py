"""The Action Registry's guards (design EXECUTIVE-GOVERNANCE.md rev 2, Parts 1.5, 9.2, 9.5).

Six guards, each in a shape this suite already proves elsewhere:

1. **Bidirectional completeness** — every registry entry names code that exists,
   and every action a business type declares is registered. The pattern
   `test_workflow_versioning.py` uses for its frozen inventory of the nine
   schedulable activities, and `test_design_system.py` for rail<->pane.
2. **Cross-constraint validity** — every entry's Approval Rule is admissible for
   its level. This is what makes "L2-strategic never graduates" and "L3 is never
   requestable" schema properties instead of review outcomes.
3. **The inheritance sweep** — design 1.5's layers 1 and 2: unique emit site,
   emitting module's level >= the action's level, no forward emission.
4. **Pinned by digest** — a level change fails, and the message names the
   sign-off requirement.
5. **L4 and L5 are empty.**
6. **Negative controls**, per M8-F120's discipline: a gate that has never failed
   is indistinguishable from a gate that cannot fail. Every detector below is
   run against a synthetic violation *and* against a synthetic legitimate case,
   the way `test_executive_import_boundary.py` proves its detector both fires
   and does not over-fire.

**What layer 3 would be, and why it is absent.** The runtime assertion
`context_level >= action_level` cannot be written: the platform has no
execution-context authority level to compare against (**M9-F134**). Only the two
static layers are buildable today, and they catch the failure at the only moment
it is cheap — before the code runs. Recorded here rather than assumed away.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.businesses.provisioning import ProvisioningService
from jarvis.domain.authority import (
    ACTION_REGISTRY,
    ADMISSIBLE_RULES,
    FORBIDDEN_OBLIGATIONS,
    MODULE_AUTHORITY,
    REQUIRED_OBLIGATIONS,
    RESERVED_LEVELS,
    ActionEntry,
    ApprovalRule,
    AuditObligation,
    AuthorityLevel,
    autonomy_inventory,
    namespace_error,
    platform_owned_namespaces,
    registry_digest,
)
from jarvis.domain.contract import AutonomyPolicy, CapabilityPermission, CapabilityType
from jarvis.kernel.errors import ConfigurationError

BUILTIN_TYPES = (AFFILIATE, FINANCE)
"""The injected built-in catalog (D-031). Every action any of these declares must
be registered, or the declaration carries an authority nobody granted."""


def _read(path: pathlib.Path) -> str:
    """Read a source file as UTF-8 explicitly.

    `Path.read_text()` uses the platform default, which on a Windows cp1252
    locale cannot decode every byte a UTF-8 source may contain —
    `tests/test_layering.py` records the curly quote that took gate 2 down for
    exactly this reason.
    """
    return path.read_text(encoding="utf-8")


# ── Guard 2: cross-constraint validity (design 1.2) ─────────────────────────


def test_the_registry_is_not_empty() -> None:
    """A registry with no entries would pass every sweep below vacuously."""
    assert ACTION_REGISTRY, "the Action Registry is empty"
    assert MODULE_AUTHORITY, "no module carries a declared authority level"


@pytest.mark.parametrize(
    "entry",
    sorted(ACTION_REGISTRY.values(), key=lambda e: e.action_type),
    ids=lambda e: e.action_type,
)
def test_every_entry_satisfies_the_cross_constraints(entry: ActionEntry) -> None:
    """Design 1.2's table, asserted independently of the module's own validator.

    `jarvis/domain/authority._validate` enforces this at import, which is the
    stronger placement — a schema enforced only by a test is a schema anyone can
    bypass by not running the test. Asserting it again here is not redundancy:
    it is what makes a silent failure of that validator detectable.
    """
    assert entry.approval_rule in ADMISSIBLE_RULES[entry.level]
    assert REQUIRED_OBLIGATIONS[entry.level] <= entry.audit_record
    assert not (FORBIDDEN_OBLIGATIONS[entry.level] & entry.audit_record)


def test_l2_strategic_admits_only_owner_approval() -> None:
    """ "Never graduates" is a schema property, not a configuration choice.

    An L2-strategic judgment is a *different* judgment about a *different*
    portfolio state each time, so the previous four approvals are evidence about
    four situations that no longer exist. D-030 caught the same category error
    one layer over when it kept refresh consent out of §8's queue.
    """
    assert ADMISSIBLE_RULES[AuthorityLevel.L2_STRATEGIC] == frozenset({ApprovalRule.OWNER_APPROVAL})
    assert ApprovalRule.GRADUATED not in ADMISSIBLE_RULES[AuthorityLevel.L2_STRATEGIC]


def test_l3_admits_only_owner_only() -> None:
    """There is no combination of registry values that lets the platform request an L3 act."""
    assert ADMISSIBLE_RULES[AuthorityLevel.L3] == frozenset({ApprovalRule.OWNER_ONLY})
    for entry in ACTION_REGISTRY.values():
        if entry.level is AuthorityLevel.L3:
            assert entry.approval_rule is ApprovalRule.OWNER_ONLY


def test_only_l2_tactical_may_be_graduated() -> None:
    """§8's ladder reaches exactly one level, and capital never graduates."""
    for entry in ACTION_REGISTRY.values():
        if entry.approval_rule is ApprovalRule.GRADUATED:
            assert entry.level is AuthorityLevel.L2_TACTICAL, (
                f"{entry.action_type} is GRADUATED at {entry.level}; the ladder is "
                f"L2-tactical only (spec §8, design 1.2)"
            )


def test_an_incoherent_entry_is_refused_at_construction() -> None:
    """Negative control for the cross-constraint validator (M8-F120).

    Three synthetic entries, each violating one constraint, plus one legitimate
    entry proving the validator is not simply rejecting everything.
    """
    with pytest.raises(ValueError, match="not admissible"):
        ActionEntry(
            action_type="platform.sneak",
            level=AuthorityLevel.L2_STRATEGIC,
            approval_rule=ApprovalRule.GRADUATED,
            audit_record=frozenset(
                {
                    AuditObligation.AUDIT,
                    AuditObligation.DECISION_LOG,
                    AuditObligation.NOTIFY_ON_PROPOSAL,
                }
            ),
        )

    with pytest.raises(ValueError, match="not admissible"):
        ActionEntry(
            action_type="platform.sneak_l3",
            level=AuthorityLevel.L3,
            approval_rule=ApprovalRule.OWNER_APPROVAL,
            audit_record=frozenset(
                {
                    AuditObligation.AUDIT,
                    AuditObligation.DECISION_LOG,
                    AuditObligation.ACTOR_IDENTITY,
                }
            ),
        )

    with pytest.raises(ValueError, match="requires audit obligations"):
        ActionEntry(
            action_type="platform.quiet",
            level=AuthorityLevel.L1,
            approval_rule=ApprovalRule.NONE,
            audit_record=frozenset(),
        )

    with pytest.raises(ValueError, match="reserved"):
        ActionEntry(
            action_type="platform.reserved",
            level=AuthorityLevel.L4,
            approval_rule=ApprovalRule.NONE,
            audit_record=frozenset(),
        )

    # The other half of the control: a valid entry constructs cleanly.
    ok = ActionEntry(
        action_type="platform.fine",
        level=AuthorityLevel.L1,
        approval_rule=ApprovalRule.NONE,
        audit_record=frozenset({AuditObligation.AUDIT}),
    )
    assert ok.level is AuthorityLevel.L1


# ── Guard 5: reserved levels hold nothing (design 1.1) ──────────────────────


def test_reserved_levels_are_empty() -> None:
    """A reserved level that something quietly starts using is worse than none.

    The M8-4 discipline applied to a constitution: "a nav item is a promise that
    a destination exists", enforced bidirectionally.
    """
    occupied = sorted(e.action_type for e in ACTION_REGISTRY.values() if e.level in RESERVED_LEVELS)
    assert not occupied, (
        f"L4/L5 are reserved and hold no entries; found {occupied}. Assigning one needs "
        f"the candidate semantics in design 1.1 ratified first."
    )
    for level in RESERVED_LEVELS:
        assert ADMISSIBLE_RULES[level] == frozenset(), (
            f"{level} admits an approval rule, which makes it usable before it is defined"
        )


# ── Guard 1: bidirectional completeness ─────────────────────────────────────


def test_every_emitting_module_and_symbol_exists() -> None:
    """Registry -> code. An entry naming a deleted module is a lie about the platform.

    This is the direction that rots: a refactor renames a function, the registry
    keeps describing the old one, and the authority model quietly stops
    describing the running system.
    """
    missing_modules: list[str] = []
    missing_symbols: list[str] = []
    for entry in ACTION_REGISTRY.values():
        if entry.module is None:
            continue
        path = pathlib.Path(entry.module)
        if not path.exists():
            missing_modules.append(f"{entry.action_type} -> {entry.module}")
            continue
        if entry.symbol is None:
            continue
        if entry.symbol not in _defined_names(_read(path)):
            missing_symbols.append(f"{entry.action_type} -> {entry.module}::{entry.symbol}")

    assert not missing_modules, (
        f"registry entries naming modules that do not exist: {missing_modules}"
    )
    assert not missing_symbols, (
        f"registry entries naming symbols that do not exist: {missing_symbols}"
    )


def test_every_module_with_a_declared_level_exists() -> None:
    """An authority declaration for a deleted module silently widens nothing, but rots."""
    missing = [m for m in MODULE_AUTHORITY if not pathlib.Path(m).exists()]
    assert not missing, f"MODULE_AUTHORITY names modules that do not exist: {missing}"


def test_every_emitting_module_carries_a_declared_level() -> None:
    """Layer 1's precondition: an action cannot be checked against an absent level."""
    undeclared = sorted(
        {
            e.module
            for e in ACTION_REGISTRY.values()
            if e.module and e.module not in MODULE_AUTHORITY
        }
    )
    assert not undeclared, (
        f"these modules emit a registered action but carry no declared authority level: "
        f"{undeclared}. Add them to MODULE_AUTHORITY — an emit site with no level is a "
        f"hole in the inheritance invariant (design 1.5)."
    )


def test_every_declared_business_action_is_registered() -> None:
    """Code -> registry, for the partition where actions are declared as data.

    **This is the completeness ratchet that actually bites.** A business type
    declaring an action the registry does not grant is precisely the plugin
    bypass design 9.6 names: authority acquired by declaring data the platform
    trusts. Under the owner's trichotomy a plugin possesses nothing installation
    did not grant, so an unregistered declaration must fail the build.
    """
    unregistered: list[str] = []
    for definition in BUILTIN_TYPES:
        for policy in definition.autonomy_policies:
            if policy.action_type not in ACTION_REGISTRY:
                unregistered.append(f"{definition.name} declares {policy.action_type}")
    assert not unregistered, (
        f"business types declare actions absent from the Action Registry: {unregistered}. "
        f"Authority is granted by installation and lives in the registry, never in "
        f"contract data (design 8.3) — an unregistered action has no authority at all."
    )


def test_registered_business_actions_match_a_declaring_type() -> None:
    """The other direction: an L2-tactical entry naming no live declaration.

    Kept separate from the sweep above because the failure means something
    different — not a bypass, but a registry describing a capability the catalog
    no longer ships, which is how an entry outlives the code that justified it.
    """
    declared = {p.action_type for d in BUILTIN_TYPES for p in d.autonomy_policies}
    orphaned = sorted(
        e.action_type
        for e in ACTION_REGISTRY.values()
        if e.level is AuthorityLevel.L2_TACTICAL and e.action_type not in declared
    )
    assert not orphaned, (
        f"L2-tactical entries no built-in type declares: {orphaned}. Either the type was "
        f"removed and the grant should be too, or the entry is speculative (§14)."
    )


def _defined_names(source: str) -> set[str]:
    """Return every function, class, and module-level assignment name in `source`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


# ── Guard 3: the inheritance sweep, layers 1 and 2 (design 1.5) ─────────────


def test_each_action_has_a_unique_emit_site() -> None:
    """Layer 1(a). One action, one place that emits it.

    The M1-R2 pattern: `authorize_invocation` may contain no bare
    `raise ScopeViolationError` because the only exit is `_deny`, which audits
    first. Applied to authority, a shared emit site would mean two actions'
    levels are enforced at one place and the stricter one is decorative.
    """
    sites: dict[tuple[str, str], list[str]] = {}
    for entry in ACTION_REGISTRY.values():
        if entry.module is None or entry.symbol is None:
            continue
        sites.setdefault((entry.module, entry.symbol), []).append(entry.action_type)
    shared = {site: actions for site, actions in sites.items() if len(actions) > 1}
    assert not shared, f"one emit site serving several actions: {shared}"


SHARED_EMIT_SITES: dict[str, str] = {
    "autonomy.reset": (
        "Two writers, both lowering autonomy: ApprovalService._reset_counter (a denial or "
        "correction, actor 'operator') and BusinessRegistry._reset_graduation_on_major_bump "
        "(A-003's major-version rule, actor 'platform'). Design 1.5's unique-emit-site rule "
        "exists to stop a privilege being granted from two places; both of these REVOKE one, "
        "and a refusal reachable by more paths is a safer platform, not a less safe one. "
        "The grant itself has exactly one writer and "
        "test_the_privilege_grant_has_exactly_one_writer asserts it. Recorded as M9-F161."
    ),
}
"""Actions emitted from more than one place, each with the reason it is permitted.

An exemption list in the shape `test_layering.py` uses for `COMPOSITION_ROOTS`:
short, justified per entry, and reviewable — rather than a weakened assertion
that would hide the next one.
"""


def test_each_action_has_a_single_emit_site_in_the_source() -> None:
    """Layer 1(a), asserted against the code rather than against the registry's own bookkeeping.

    `test_each_action_has_a_unique_emit_site` checks the table is internally
    consistent; this checks the table is *true*. They fail for different reasons
    and the second is the one that catches reality drifting from the model — an
    action quietly acquiring a second emitter is how one place's guards become
    optional.
    """
    emitters: dict[str, set[str]] = {}
    for path in sorted(pathlib.Path("jarvis").rglob("*.py")):
        module = path.as_posix()
        if module == "jarvis/domain/authority.py":
            continue  # the registry names every action by construction
        for action in _referenced_actions(_read(path)):
            emitters.setdefault(action, set()).add(module)

    unexpected: list[str] = []
    for action, modules in sorted(emitters.items()):
        if len(modules) <= 1:
            continue
        if action in SHARED_EMIT_SITES:
            continue
        unexpected.append(f"{action} emitted from {sorted(modules)}")
    assert not unexpected, (
        f"actions with more than one emit site and no recorded justification: {unexpected}. "
        f"Add it to SHARED_EMIT_SITES with the reason, or route the second site through the "
        f"first (the M1-R2 pattern)."
    )


def test_the_shared_emit_site_exemptions_are_still_real() -> None:
    """An exemption for an action that no longer has two emitters silently widens the rule."""
    for action, reason in SHARED_EMIT_SITES.items():
        assert action in ACTION_REGISTRY, f"{action} is exempted but not registered"
        assert reason.strip(), f"{action} is exempted with no justification"
        modules = {
            path.as_posix()
            for path in pathlib.Path("jarvis").rglob("*.py")
            if path.as_posix() != "jarvis/domain/authority.py"
            and action in _referenced_actions(_read(path))
        }
        assert len(modules) > 1, (
            f"{action} is exempted from the unique-emit-site rule but has {len(modules)} "
            f"emitter(s); drop the exemption"
        )


def test_no_module_emits_an_action_above_its_declared_level() -> None:
    """Layer 1(b). The emitting module's level must be >= the action's level.

    This is the check that catches the ratchet's quietest form — not a component
    reaching *up*, which review would notice, but a component promoted
    *sideways*: a module that gains one high-authority responsibility and
    carries that authority into every low-authority path it already had.
    """
    violations: list[str] = []
    for entry in ACTION_REGISTRY.values():
        if entry.module is None:
            continue
        declared = MODULE_AUTHORITY.get(entry.module)
        if declared is None:
            continue
        if declared.rank < entry.level.rank:
            violations.append(
                f"{entry.module} is declared {declared} but emits {entry.action_type} "
                f"at {entry.level}"
            )
    assert not violations, f"emission above declared authority: {violations}"


def test_no_module_references_an_action_registered_above_its_level() -> None:
    """Layer 2. No forward emission, swept over string literals.

    The same machinery as `test_executive_import_boundary.py`, which walks per
    file and proves its own detector both fires and does not over-fire. A module
    that merely *names* a higher-authority action is the reviewable event: the
    string is how every downstream mechanism keys off the action (A-003), so
    holding it is the first half of emitting it.
    """
    violations: list[str] = []
    undeclared: list[str] = []
    for path in sorted(pathlib.Path("jarvis").rglob("*.py")):
        module = path.as_posix()
        referenced = _referenced_actions(_read(path))
        if not referenced:
            continue
        declared = MODULE_AUTHORITY.get(module)
        if declared is None:
            undeclared.append(f"{module} references {sorted(referenced)}")
            continue
        for action in referenced:
            entry = ACTION_REGISTRY[action]
            if entry.level.rank > declared.rank:
                violations.append(
                    f"{module} (declared {declared}) references {action} at {entry.level}"
                )

    assert not undeclared, (
        f"modules naming a registered action but carrying no declared authority level: "
        f"{undeclared}. **This is the platform-side completeness ratchet**: a new component "
        f"that starts emitting a governed action must declare the authority it emits at, or "
        f"the inheritance invariant has a hole exactly the size of that module."
    )
    assert not violations, (
        f"forward emission — a module naming an action above its own authority: {violations}"
    )


def _referenced_actions(source: str) -> set[str]:
    """Return every registered action type appearing as a string literal in `source`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in ACTION_REGISTRY
        ):
            found.add(node.value)
    return found


def test_the_inheritance_detectors_detect() -> None:
    """Negative control for both static layers (M8-F120).

    Synthetic source naming a registered L3 action, read by a detector that has
    no idea which file it came from — proving the sweep above would fire if a
    real L0 module started holding that string.
    """
    synthetic = """
CEILING_ACTION = "platform.change_spending_ceiling"
def raise_it():
    return CEILING_ACTION
"""
    found = _referenced_actions(synthetic)
    assert "platform.change_spending_ceiling" in found, (
        "the literal sweep missed a synthetic forward reference; layer 2 would be vacuous"
    )
    assert ACTION_REGISTRY["platform.change_spending_ceiling"].level.rank > (AuthorityLevel.L0.rank)


def test_the_inheritance_detector_is_not_trigger_happy() -> None:
    """The other half: an unrelated string is not mistaken for an action type."""
    synthetic = """
LABEL = "portfolio.compute_rollup_v2"
OTHER = "some.unrelated.string"
NOT_AN_ACTION = "publish_post"
"""
    assert _referenced_actions(synthetic) == set()


# ── Guard 4: the pin, and the ratchet (design 9.2 guard 4, 9.5) ─────────────

REGISTRY_DIGEST_PIN = "1cf445eeeef8a3bcc265dda54df1b9266dad43f3e9b101e628c6f157e379a109"
"""SHA-256 over every governance-relevant field of the registry and the module
authority table. Updating this line is the visible, reviewable, single-line diff
that cannot be mistaken for anything else."""

AUTONOMY_PIN: dict[str, tuple[str, str, int | None, bool | None]] = {
    # action_type: (level, approval_rule, graduation_threshold, graduation_eligible)
    "affiliate.publish_post": ("L2-tactical", "GRADUATED", 5, True),
    "autonomy.reset": ("L1", "NONE", None, None),
    "budget.read_aggregates": ("L0", "NONE", None, None),
    "budget.refuse_reservation": ("L1", "NONE", None, None),
    "business.dropped_wake_notice": ("L1", "NONE", None, None),
    # New surface, not a loosened rule: P0-D's skipped-round notice, ratified
    # with the Phase 0 design (DECISIONS, "Phase 0 design merged" — two new L1
    # actions, D-055..D-061). A newly registered action is not an autonomy
    # increase by `_increases_autonomy`'s own definition, so the pin moves
    # without a sign-off row and this comment is the reviewable statement of why.
    "business.late_wake_notice": ("L1", "NONE", None, None),
    "business.park_degraded": ("L1", "NONE", None, None),
    "business.wake_cycle": ("L1", "NONE", None, None),
    "capability.deny": ("L1", "NONE", None, None),
    "capability.dispatch": ("L1", "NONE", None, None),
    "kpi.compute_health": ("L0", "NONE", None, None),
    "platform.approval_expired": ("L1", "NONE", None, None),
    "platform.change_authority_level": ("L3", "OWNER_ONLY", None, None),
    "platform.change_compliance_requirement": ("L3", "OWNER_ONLY", None, None),
    "platform.change_spending_ceiling": ("L3", "OWNER_ONLY", None, None),
    "platform.circuit_breaker": ("L1", "NONE", None, None),
    "platform.grant_autonomy": ("L3", "OWNER_ONLY", None, None),
    "platform.grant_credential_scope": ("L3", "OWNER_ONLY", None, None),
    "platform.install_business_type": ("L3", "OWNER_ONLY", None, None),
    "platform.lifecycle_transition": ("L1", "NONE", None, None),
    "portfolio.compute_census": ("L0", "NONE", None, None),
    "portfolio.compute_rollup": ("L0", "NONE", None, None),
    "reservation.reconcile": ("L1", "NONE", None, None),
    "spending.company_band_notice": ("L1", "NONE", None, None),
    "spending.platform_band_notice": ("L1", "NONE", None, None),
}
"""The frozen inventory of every `(action_type -> level, approval_rule,
threshold, eligibility)` across the platform registry and the built-in catalog.

**Failing in both directions is deliberate.** A ratchet guard that fires only on
dangerous changes lets the pin rot on safe ones, and a rotted pin catches
nothing. The asymmetry belongs in the *message*, not the trigger — see
`test_the_autonomy_inventory_matches_its_pin`.
"""

SIGNOFF_PATH = pathlib.Path("docs/AUTHORITY-SIGNOFF.md")


def _live_inventory() -> dict[str, tuple[str, str, int | None, bool | None]]:
    """Assemble the current inventory from the registry plus the built-in catalog."""
    policies = {p.action_type: p for d in BUILTIN_TYPES for p in d.autonomy_policies}
    out: dict[str, tuple[str, str, int | None, bool | None]] = {}
    for action, (level, rule) in autonomy_inventory().items():
        policy = policies.get(action)
        out[action] = (
            level,
            rule,
            policy.graduation_threshold if policy else None,
            policy.graduation_eligible if policy else None,
        )
    return out


def _increases_autonomy(
    before: tuple[str, str, int | None, bool | None] | None,
    after: tuple[str, str, int | None, bool | None] | None,
) -> bool:
    """Return whether the change from `before` to `after` reduces required authority.

    Four shapes count as an increase: a level dropping (less judgment claimed for
    the same act), an approval rule moving toward less human involvement, a
    graduation threshold falling (a shorter streak buys autonomy sooner), and
    eligibility switching on. A newly registered action is not itself an
    increase — it is new surface, caught by the pin's exact-match trigger.
    """
    if before is None or after is None:
        return False
    rank = {"L0": 0, "L1": 1, "L2-tactical": 2, "L2-strategic": 3, "L3": 4}
    friction = {"OWNER_ONLY": 3, "OWNER_APPROVAL": 2, "GRADUATED": 1, "NONE": 0}
    if rank.get(after[0], 0) < rank.get(before[0], 0):
        return True
    if friction.get(after[1], 0) < friction.get(before[1], 0):
        return True
    if before[2] is not None and after[2] is not None and after[2] < before[2]:
        return True
    return bool(after[3]) and not bool(before[3])


def _signed_off_actions() -> set[str]:
    """Return every action type an owner has signed an authority change for.

    Parses `docs/AUTHORITY-SIGNOFF.md`'s table. Absent file means nothing is
    signed off, which is the correct default — the marker must be *added* to
    permit a change, never removed to forbid one.
    """
    if not SIGNOFF_PATH.exists():
        return set()
    actions: set[str] = set()
    for line in _read(SIGNOFF_PATH).splitlines():
        match = re.match(r"^\|\s*`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`\s*\|", line.strip())
        if match:
            actions.add(match.group(1))
    return actions


def test_the_registry_digest_matches_its_pin() -> None:
    """Design 9.2 guard 4. Any governance-relevant change fails here first.

    This is also M9-F133's fix: a type upgrade that would re-grant authority
    changes the digest and therefore cannot ride a refresh consent — Band C
    freezes `autonomy_policies` on the *instance*, and the registry is
    platform-side where Band C does not reach.
    """
    assert registry_digest() == REGISTRY_DIGEST_PIN, (
        "the Action Registry changed.\n"
        "If this change lowers a required authority, enables graduation, or lowers a "
        "threshold, it INCREASES AUTONOMY and needs owner sign-off (§15, D-043) recorded "
        f"in {SIGNOFF_PATH} before the pin is updated.\n"
        "If it is a safe-direction change or a new action, update REGISTRY_DIGEST_PIN in "
        "this file — deliberately, as its own reviewable line."
    )


def test_the_autonomy_inventory_matches_its_pin() -> None:
    """Design 9.5 assertion 4. Autonomy cannot increase accidentally.

    **The honest limit of this guard, stated because a security control whose
    reach is overstated is worse than one whose reach is known:** it makes an
    autonomy increase *impossible to make invisibly*, not impossible to make.
    Anyone able to edit the registry can also edit the pin and write the
    sign-off row. What the mechanism guarantees is that doing so requires
    stating, in an owner-facing file that exists for no other purpose, exactly
    which action's authority was reduced and by whom — so the increase is a
    named, reviewable act rather than a line inside an unrelated diff. That is
    the same protection D-011 gives an approval: it defends the human's
    attention, which is the thing actually being attacked.
    """
    live = _live_inventory()
    changed = sorted(set(live) | set(AUTONOMY_PIN))
    diffs = [a for a in changed if live.get(a) != AUTONOMY_PIN.get(a)]
    if not diffs:
        return

    increases = [a for a in diffs if _increases_autonomy(AUTONOMY_PIN.get(a), live.get(a))]
    unsigned = sorted(set(increases) - _signed_off_actions())

    detail = "\n".join(f"  {a}: {AUTONOMY_PIN.get(a)} -> {live.get(a)}" for a in diffs)
    if unsigned:
        pytest.fail(
            "THIS INCREASES AUTONOMY — owner sign-off required (§15, D-043).\n"
            f"{detail}\n"
            f"Unsigned: {unsigned}\n"
            f"Record the change in {SIGNOFF_PATH} with the owner, date, and reason, "
            "then update AUTONOMY_PIN."
        )
    if increases:
        pytest.fail(
            "signed-off autonomy increase — update AUTONOMY_PIN to accept it.\n"
            f"{detail}\n"
            f"Signed off in {SIGNOFF_PATH}: {sorted(increases)}"
        )
    pytest.fail(
        f"the autonomy inventory changed in a safe direction — update AUTONOMY_PIN.\n{detail}"
    )


def test_the_ratchet_detector_classifies_direction_correctly() -> None:
    """Negative control for the asymmetry (M8-F120).

    A guard whose *message* carries the asymmetry is only as good as its
    direction test, and nothing else exercises `_increases_autonomy`.
    """
    base = ("L2-tactical", "OWNER_APPROVAL", 5, False)

    # Increases.
    assert _increases_autonomy(base, ("L1", "NONE", 5, False)), "level drop missed"
    assert _increases_autonomy(base, ("L2-tactical", "GRADUATED", 5, False)), "rule relax missed"
    assert _increases_autonomy(base, ("L2-tactical", "OWNER_APPROVAL", 3, False)), (
        "threshold drop missed"
    )
    assert _increases_autonomy(base, ("L2-tactical", "OWNER_APPROVAL", 5, True)), (
        "eligibility switch-on missed"
    )

    # Safe direction — must NOT be reported as an increase, or every safe edit
    # would demand a sign-off and the sign-off file would become noise.
    assert not _increases_autonomy(base, ("L3", "OWNER_ONLY", 5, False))
    assert not _increases_autonomy(base, ("L2-tactical", "OWNER_APPROVAL", 9, False))
    assert not _increases_autonomy(("L2-tactical", "GRADUATED", 5, True), base)
    assert not _increases_autonomy(base, base)


# ── The privilege grant itself (design 9.5 assertions 1 and 2, M9-F127) ────

GRANT_MODULE = pathlib.Path("jarvis/approvals/service.py")
GRANT_FUNCTION = "_advance_counter"


def _graduated_true_sites() -> list[tuple[str, int]]:
    """Return every place in `jarvis/` that assigns a truthy value to `.graduated`."""
    sites: list[tuple[str, int]] = []
    for path in sorted(pathlib.Path("jarvis").rglob("*.py")):
        for node in ast.walk(ast.parse(_read(path))):
            if isinstance(node, ast.Assign):
                if not (isinstance(node.value, ast.Constant) and node.value.value is True):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "graduated":
                        sites.append((path.as_posix(), node.lineno))
            elif isinstance(node, ast.keyword) and node.arg == "graduated":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    sites.append((path.as_posix(), node.lineno))
    return sites


def test_the_privilege_grant_has_exactly_one_writer() -> None:
    """M9-F127, closed. Design 9.5 assertion 1.

    `_advance_counter`'s two guards are correct, and until now **nothing
    asserted they are the only path to `graduated = True`.** The refusal path
    has had exactly this guard since M1-R2 — `authorize_invocation` may contain
    no bare `raise ScopeViolationError` because the only exit is `_deny`, which
    audits first. The privilege *grant* had none, which is the wrong way round:
    a second refusal path is harmless, and a second grant path is an autonomy
    ratchet with no guards on it.
    """
    sites = _graduated_true_sites()
    assert len(sites) == 1, (
        f"`graduated = True` is assigned in {len(sites)} places: {sites}. Exactly one is "
        f"permitted — `{GRANT_MODULE}::{GRANT_FUNCTION}` — because that is the only "
        f"function carrying §8's two guards (design 9.5 assertion 1)."
    )
    module, _ = sites[0]
    assert module == GRANT_MODULE.as_posix()


def test_the_grant_is_dominated_by_both_guards() -> None:
    """Design 9.5 assertion 2. Both guards, not just the policy flag.

    Two independent guards, because they fail differently: the policy flag can
    be misconfigured, and the action's own amount cannot lie about whether money
    moved. Guarding twice is what makes "capital never graduates" (spec §8) hold
    even under a bad policy — the security-engineer boundary this packet is
    least willing to leave to review.

    Resolved through local variables, because the live code computes
    `capital_action` and `eligible` before branching on them; asserting against
    the literal `if` test alone would pass a refactor that dropped a guard into
    an unused variable.
    """
    tree = ast.parse(_read(GRANT_MODULE))
    func = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == GRANT_FUNCTION
        ),
        None,
    )
    assert func is not None, f"{GRANT_FUNCTION} is gone from {GRANT_MODULE}"

    assigned: dict[str, str] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assigned[target.id] = ast.unparse(node.value)

    guarding: list[str] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        grants = any(
            isinstance(inner, ast.Assign)
            and isinstance(inner.value, ast.Constant)
            and inner.value.value is True
            and any(isinstance(t, ast.Attribute) and t.attr == "graduated" for t in inner.targets)
            for inner in ast.walk(node)
        )
        if grants:
            guarding.append(_expanded(ast.unparse(node.test), assigned))

    assert guarding, "no `if` dominates the graduation assignment — it is unconditional"
    for test in guarding:
        assert "graduation_eligible" in test, (
            f"the policy-flag guard is missing from the condition dominating the grant: {test}"
        )
        assert "amount_usd" in test, (
            f"the capital guard is missing from the condition dominating the grant: {test}. "
            f"Capital actions MUST NOT graduate (spec §8), guarded on the action's own "
            f"amount so a misconfigured policy still cannot graduate money."
        )


def _expanded(expression: str, assigned: dict[str, str], *, depth: int = 4) -> str:
    """Substitute locally-assigned names into `expression`, transitively."""
    for _ in range(depth):
        grown = expression
        for name, value in assigned.items():
            if re.search(rf"\b{re.escape(name)}\b", grown):
                grown = re.sub(rf"\b{re.escape(name)}\b", f"({value})", grown)
        if grown == expression:
            break
        expression = grown
    return expression


def test_the_grant_detectors_detect() -> None:
    """Negative control for both grant guards (M8-F120).

    A synthetic `_advance_counter` missing the capital guard must be caught by
    the same expansion the real one passes — otherwise the assertion above only
    proves the current code parses.
    """
    synthetic = """
class S:
    async def _advance_counter(self, row, contract):
        policy = contract.autonomy_for(row.action_type)
        eligible = policy.graduation_eligible
        if eligible and counter.consecutive_approvals >= policy.graduation_threshold:
            counter.graduated = True
"""
    tree = ast.parse(synthetic)
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "_advance_counter"
    )
    assigned = {
        t.id: ast.unparse(n.value)
        for n in ast.walk(func)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        for t in [n.targets[0]]
        if isinstance(t, ast.Name)
    }
    condition = next(
        _expanded(ast.unparse(n.test), assigned) for n in ast.walk(func) if isinstance(n, ast.If)
    )
    assert "graduation_eligible" in condition, "the expansion lost the flag it should keep"
    assert "amount_usd" not in condition, (
        "the detector would not notice a missing capital guard — the assertion above is vacuous"
    )


def test_graduation_eligibility_defaults_to_refusal() -> None:
    """M9-F115. The ratchet-safe default, asserted where a change would be noticed.

    §8 requires approval by default with no exception at launch. This field
    defaulted the other way until M9-G1a, so a type author who omitted it got a
    graduation-eligible action — an autonomy increase nobody chose.
    """
    policy = AutonomyPolicy(action_type="affiliate.publish_post", graduation_threshold=5)
    assert policy.graduation_eligible is False, (
        "graduation_eligible must default to False: eligibility is opt-in per "
        "declaration, so autonomy cannot arrive by omission (M9-F115, design 9.5)"
    )


# ── A-003 namespace enforcement (M9-F116, design 8.3 check 4, 9.6) ──────────


def test_platform_namespace_is_reserved_against_every_type() -> None:
    """The live bypass, closed. A type may never declare a platform action.

    Both actions named here are real registry entries — `platform.circuit_breaker`
    halts platform spending and `platform.change_spending_ceiling` is L3 — and
    both would have validated, installed, and entered `declared_action_types`
    before this check existed.
    """
    for action in (
        "platform.circuit_breaker",
        "platform.change_spending_ceiling",
        "platform.reallocate_capital",
    ):
        reason = namespace_error(action, type_name="affiliate")
        assert reason is not None, f"{action} was accepted from a business type"
        assert "reserved" in reason or "platform-owned" in reason


def test_a_type_may_not_borrow_another_types_namespace() -> None:
    """A-003 namespaces an action to its *own* type, and only its own."""
    assert namespace_error("finance.read_ledger", type_name="affiliate") is not None
    assert namespace_error("affiliate.publish_post", type_name="finance") is not None


def test_every_platform_owned_prefix_is_reserved() -> None:
    """The reservation is derived from the registry, so it cannot drift.

    A hand-maintained list would drift the moment the two diverged, and the
    direction it drifts in — a platform prefix that is no longer reserved — is
    precisely the bypass this closes.
    """
    reserved = platform_owned_namespaces()
    for entry in ACTION_REGISTRY.values():
        prefix = entry.action_type.split(".", 1)[0]
        if entry.level in {AuthorityLevel.L2_TACTICAL, AuthorityLevel.L2_STRATEGIC}:
            continue
        assert prefix in reserved, f"{prefix} is used by {entry.action_type} but not reserved"
    assert "platform" in reserved


def test_a_types_own_namespace_is_still_permitted() -> None:
    """The detector is not trigger-happy: the legitimate declaration passes.

    Proving the refusals above fire is only meaningful alongside proof that the
    one live L2 declaration — `affiliate.publish_post`, shipped and graduating —
    is not caught by them.
    """
    assert namespace_error("affiliate.publish_post", type_name="affiliate") is None
    assert namespace_error("finance.read_ledger", type_name="finance") is None


def test_an_unnamespaced_action_is_refused() -> None:
    """A-003 requires the dotted form; a bare verb names no owning type."""
    reason = namespace_error("publish_post", type_name="affiliate")
    assert reason is not None
    assert "not namespaced" in reason


def _definition(*action_types: str, name: str = "rogue") -> BusinessTypeDefinition:
    """Build a minimal, otherwise-valid type declaring `action_types`.

    Otherwise-valid on purpose: if the definition failed one of `install`'s
    older checks the refusal below would prove nothing about the new one.
    """
    return BusinessTypeDefinition(
        name=name,
        version="1.0.0",
        display_name="Rogue Co",
        description="A type used to prove the installer refuses what it should.",
        prompt_templates={f"{name}.operations": "do the thing"},
        capability_permissions=(
            CapabilityPermission(
                capability=CapabilityType.OPERATIONS,
                tool_scope=frozenset({"publish_post"}),
            ),
        ),
        autonomy_policies=tuple(
            AutonomyPolicy(action_type=a, graduation_threshold=5) for a in action_types
        ),
    )


def test_install_refuses_a_type_declaring_a_platform_action() -> None:
    """M9-F116, closed at the install boundary.

    Before this check, `platform.reallocate_capital` on a business type
    validated, installed, and entered `declared_action_types`. It was contained
    only by what did not exist yet — `platform_feed()` filters on
    `business_id IS NULL` and there is no platform-scoped approval path to
    confuse — and design 8.1 builds exactly that path. The namespace is reserved
    *before* the path exists, which is the only ordering that is not a race.

    Checked against `ProvisioningService`'s own static helper rather than a
    live install, so the refusal is proven without a database: the property is
    a property of the definition, not of any one run.
    """
    for action in ("platform.reallocate_capital", "platform.circuit_breaker"):
        with pytest.raises(ConfigurationError, match=r"reserved|platform-owned"):
            ProvisioningService._refuse_unauthorised_action_types(_definition(action))


def test_install_refuses_a_type_borrowing_another_types_namespace() -> None:
    """A-003: the prefix must equal the declaring type's own name."""
    with pytest.raises(ConfigurationError, match=r"A-003"):
        ProvisioningService._refuse_unauthorised_action_types(
            _definition("affiliate.publish_post", name="rogue")
        )


def test_install_refuses_a_type_requesting_authority_above_l2_tactical() -> None:
    """The second, independent guard (design 8.3 check 2).

    It does not depend on the namespace comparison being right: even if that
    check were wrong, an action the registry grants at L3 is platform-owned, and
    a type requesting one is asking to create policy — which Part 2 forbids
    categorically. Proven by pointing the namespace check away from the failure:
    a type actually *named* `platform` clears the prefix comparison and is still
    refused.
    """
    with pytest.raises(ConfigurationError, match=r"reserved|above L2-tactical"):
        ProvisioningService._refuse_unauthorised_action_types(
            _definition("platform.change_spending_ceiling", name="platform")
        )


def test_install_refuses_a_type_declaring_an_unregistered_action() -> None:
    """F1 (M9-F185, governance violation): an unregistered action has no authority.

    Before this fix, `granted_entry(...) is None` fell straight through the
    level comparison (`entry is not None and entry.level not in {...}`), so a
    business type declaring an action the registry had never heard of
    installed exactly as if L0/L1/L2-tactical had been granted. Namespaced
    correctly on purpose — `finance` owns the `finance.` prefix (proven by
    `test_a_types_own_namespace_is_still_permitted` above) — so the namespace
    guard cannot be what is catching this; only the registry-membership guard
    can.
    """
    action = "finance.read_ledger"
    assert action not in ACTION_REGISTRY, (
        "fixture must exercise a genuinely unregistered action for this test to mean anything"
    )
    with pytest.raises(ConfigurationError, match=r"does not grant|unregistered"):
        ProvisioningService._refuse_unauthorised_action_types(_definition(action, name="finance"))


def test_install_still_accepts_a_registered_action_negative_control() -> None:
    """Negative control for F1 (M8-F120 discipline): a registered action is unaffected.

    Proves the new registry-membership guard is not a blanket refusal that
    happens to also catch the unregistered case above — it lets a genuinely
    granted action through untouched.
    """
    ProvisioningService._refuse_unauthorised_action_types(
        _definition("affiliate.publish_post", name="affiliate")
    )


def test_install_accepts_the_live_affiliate_type() -> None:
    """The detector is not trigger-happy: the shipped catalog still installs.

    A guard the production catalog fails is a guard that gets weakened rather
    than obeyed.
    """
    for definition in BUILTIN_TYPES:
        ProvisioningService._refuse_unauthorised_action_types(definition)


def test_the_live_catalog_passes_its_own_namespace_check() -> None:
    """The shipped types must satisfy the rule the installer now enforces.

    A guard that the production catalog fails is a guard that gets weakened
    rather than obeyed, so this is asserted before the installer test relies on
    it.
    """
    for definition in BUILTIN_TYPES:
        for policy in definition.autonomy_policies:
            assert namespace_error(policy.action_type, type_name=definition.name) is None
