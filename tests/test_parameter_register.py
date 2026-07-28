"""The Parameter Register (packet M9-G1b, design EXECUTIVE-GOVERNANCE.md Part 3.3).

Two invariants the packet requires, plus the supporting checks that keep the
register from silently drifting from the code it describes:

- **No ENFORCING parameter may have an illegitimate origin** — except the
  three the platform is already, knowingly, in violation on (M9-F130),
  which are named exactly, not approximately, so a *new* violation cannot
  hide behind an old one and an *old* one cannot quietly disappear from the
  register without the code actually changing.
- **A parameter the design document already named as governing must be
  registered** — `DESIGN_NAMED_PARAMETERS` anchors this to
  EXECUTIVE-GOVERNANCE.md Part 1.8's own enumeration rather than to a
  fresh, unbounded claim about "every parameter that gates behaviour".
"""

from __future__ import annotations

import importlib
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from jarvis.domain.provenance import Origin, ProvenanceHead
from jarvis.registry.parameter_register import (
    DESIGN_NAMED_PARAMETERS,
    KNOWN_M130_EXCEPTIONS,
    PARAMETER_ENTRIES,
    PARAMETER_REGISTER,
    ParameterClass,
    is_legitimate_policy,
)


def _resolve(location: str) -> Any:
    """Return the live object a register row's ``location`` names.

    A pydantic field resolves to its `FieldInfo` (so a caller can inspect
    `is_required()` / `default`); a module-level constant resolves to its
    value. Raises `AssertionError` with the offending location rather than
    a bare `AttributeError`, so a failure names the row that is stale.
    """
    module_path, sep, attr_path = location.partition(":")
    assert sep, f"malformed location (missing ':'): {location!r}"
    module = importlib.import_module(module_path)
    obj: Any = module
    for part in attr_path.split("."):
        if isinstance(obj, type) and part in getattr(obj, "model_fields", {}):
            return obj.model_fields[part]
        assert hasattr(obj, part), f"{location!r} does not resolve: no {part!r} on {obj!r}"
        obj = getattr(obj, part)
    return obj


# ── register integrity ──────────────────────────────────────────────────────


def test_register_has_no_duplicate_names() -> None:
    """A dict keyed by name would silently drop a duplicate; this catches it."""
    assert len(PARAMETER_ENTRIES) == len(PARAMETER_REGISTER)


@pytest.mark.parametrize("entry", PARAMETER_ENTRIES, ids=lambda e: e.name)
def test_every_registered_parameter_resolves_to_real_code(entry: Any) -> None:
    """A register row that names deleted or renamed code is worse than none:
    it reports a governance guarantee nothing actually checks any more."""
    _resolve(entry.location)


@pytest.mark.parametrize("entry", PARAMETER_ENTRIES, ids=lambda e: e.name)
def test_current_source_matches_the_live_default(entry: Any) -> None:
    """Keeps `current_source`'s prose honest against the code it describes.

    A row claiming "code default" must resolve to a field that is not
    required; a row claiming "no default" must resolve to one that is.
    Module-level constants (the two alert-band tuples) always count as
    having a value, matching their own "code default (module constant)"
    wording.
    """
    resolved = _resolve(entry.location)
    claims_code_default = entry.current_source.startswith("code default")
    claims_no_default = "no default" in entry.current_source

    has_default = not resolved.is_required() if isinstance(resolved, FieldInfo) else True

    if claims_code_default:
        assert has_default, f"{entry.name}: register claims a code default; field is required"
    if claims_no_default:
        assert not has_default, f"{entry.name}: register claims no default; field has one"


# ── the origin-clause test (packet: "no ENFORCING parameter may have a code default") ──


def test_enforcing_violations_are_exactly_the_known_m130_exceptions() -> None:
    """Fails in both directions on purpose (design Part 9.5's ratchet discipline).

    A *new* ENFORCING parameter with an illegitimate origin must be added to
    `KNOWN_M130_EXCEPTIONS` deliberately, in the same diff that adds it to
    `docs/design/M9-F130-REMEDIATION.md` for the owner. And this set
    shrinking without the underlying code default actually disappearing
    would mean the exception list had gone stale, not that the platform had
    improved — both directions are real failures.
    """
    violations = {
        entry.name
        for entry in PARAMETER_ENTRIES
        if entry.param_class is ParameterClass.ENFORCING and not is_legitimate_policy(entry)
    }
    assert violations == KNOWN_M130_EXCEPTIONS


def test_known_exceptions_are_all_registered_and_enforcing() -> None:
    """Guards `KNOWN_M130_EXCEPTIONS` itself against naming a row that moved,
    was renamed, or was reclassified out of ENFORCING without the exception
    list being updated to match."""
    for name in KNOWN_M130_EXCEPTIONS:
        assert name in PARAMETER_REGISTER, f"{name} is not a registered parameter"
        assert PARAMETER_REGISTER[name].param_class is ParameterClass.ENFORCING


_M130_TABLE = "docs/design/M9-F130-REMEDIATION.md"


def test_m130_remediation_values_are_pinned() -> None:
    """F4 (M9-F188): the three known exceptions are presence-checked above
    (`test_enforcing_violations_are_exactly_the_known_m130_exceptions`), never
    value-checked — the audit's honest-limits note named this gap directly:
    "the remediation-table value-drift gap (presence-checked, not
    value-checked)". A silent change to any of the three live defaults would
    still satisfy that test, because it only compares *names*, while
    `docs/design/M9-F130-REMEDIATION.md`'s table — which the owner is
    ratifying against a specific value per row — quietly went stale
    underneath it. Pin each value the table states, so a drift fails loudly
    and the message points at the table to update.
    """
    max_cycles = _resolve(PARAMETER_REGISTER["wake_conditions.max_cycles_per_day"].location)
    assert max_cycles.default == 48, (
        f"WakeConditions.max_cycles_per_day drifted from the value "
        f"{_M130_TABLE}'s row 1 pins (48) — update the table before this pin"
    )

    max_budget = _resolve(
        PARAMETER_REGISTER["capability_permission.max_invocation_budget_usd"].location
    )
    assert max_budget.default == Decimal("0.50"), (
        f"CapabilityPermission.max_invocation_budget_usd drifted from the value "
        f"{_M130_TABLE}'s row 2 pins ($0.50) — update the table before this pin"
    )

    graduation = _resolve(PARAMETER_REGISTER["autonomy_policy.graduation_eligible"].location)
    assert graduation.default is False, (
        f"AutonomyPolicy.graduation_eligible's default drifted from the value "
        f"{_M130_TABLE}'s row 3 pins (False) — update the table before this pin"
    )


def test_announcing_entries_are_always_legitimate() -> None:
    """ANNOUNCING is not policy (Part 3.3); any recordable origin passes."""
    for entry in PARAMETER_ENTRIES:
        if entry.param_class is ParameterClass.ANNOUNCING:
            assert is_legitimate_policy(entry)


# ── the completeness test (packet: "a parameter absent from the register... fails") ──


def test_every_design_named_parameter_is_registered() -> None:
    """EXECUTIVE-GOVERNANCE.md Part 1.8 names these identifiers as governing
    the platform's behaviour. A parameter that document already flagged
    cannot be silently absent from the register — the completeness the
    M9-G1b packet asks for, anchored to a citable source rather than to an
    unbounded sweep (see the module's "Scope, stated honestly" docstring)."""
    haystack = " ".join(f"{e.name} {e.location} {e.note}" for e in PARAMETER_ENTRIES)
    missing = [p for p in DESIGN_NAMED_PARAMETERS if p not in haystack]
    assert not missing, f"design-named parameters missing from the register: {missing}"


# ── the provenance head (static half only, M9-F139) ─────────────────────────


def test_provenance_head_defaults_honestly_empty() -> None:
    """Part 3.5: an empty provenance head is the correct starting state for
    every value on the platform today — no approval has ever authorised a
    configuration change."""
    head = ProvenanceHead()
    assert head.origin is Origin.PLATFORM_DEFAULT
    assert head.modified_by is None
    assert head.approved_by is None


def test_provenance_head_is_frozen() -> None:
    head = ProvenanceHead()
    with pytest.raises(ValidationError):
        head.origin = Origin.OWNER  # type: ignore[misc]


def test_provenance_head_carries_no_executed_by_field() -> None:
    """M9-F139: Executed By is a property of each *use*, not of the value,
    and belongs to a Decision Lineage node. A regression that adds it here
    would silently reintroduce the "who used this most recently" bug Part
    3.2 named."""
    assert "executed_by" not in ProvenanceHead.model_fields
