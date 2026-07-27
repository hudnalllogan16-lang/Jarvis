"""Contract refresh: the band classification and the diff model (D-029, D-030).

A business type's data reaches a company through three bands (D-029, design doc
Part 4.2), and the line between them is **authority**, not convenience:

- **Band A — live.** `prompt_templates`, `kpi_mappings`, `tool_registry`, and the
  type's `display_name`/`description` are read from the Registry on every use.
  They are not contract fields at all, so nothing here describes them: a version
  bump propagates them with no diff and no consent.
- **Band B — refreshed with operator consent.** Type-owned values the operator
  was shown and that carry no authorization: `kpi_targets`,
  `wake_conditions.schedule_cron`, `wake_conditions.event_triggers`, and
  `compliance_requirements`. This module's diff model describes exactly these.
- **Band C — never refreshed.** Identity, the operator's money, the lifecycle
  state, and the two authorization records. `frozen_field_differences` is the
  enforcement, not the documentation.

The two lists partition `BusinessContract` completely, which is checked by
`tests/test_contract_refresh.py` — a field added to the contract and to neither
band would otherwise be silently unclassified, and an unclassified field is one
a future refresh could move without anyone deciding it should.

Everything here is pure data and pure functions over stored values. Both sides
of a diff are read from storage — the contract on one side, the installed
definition on the other — so a rendered plan is D-011-shaped by construction:
no model sits between a change and the human who accepts it.

It lives in `domain` for the reason `domain/kpi.py` does: the plan is produced
in `businesses` (M5) and read by the operator surface in `api` (M3), and a model
defined beside its producer would be unreadable by its consumer under the
layering invariant.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from jarvis.domain.contract import BusinessContract
from jarvis.kernel.ids import BusinessId, BusinessTypeName


class RefreshBand(StrEnum):
    """Which band a contract field belongs to (D-029)."""

    LIVE = "live"
    """Band A: read live from the Registry, never snapshotted, never consented."""

    CONSENTED = "consented"
    """Band B: snapshotted, refreshed only with the operator's explicit consent."""

    FROZEN = "frozen"
    """Band C: instance-owned or a security surface. Never refreshed, ever."""


BAND_B_FIELDS: Final[tuple[str, ...]] = (
    "kpi_targets",
    "wake_conditions.schedule_cron",
    "wake_conditions.event_triggers",
    "compliance_requirements",
)
"""The complete set of contract values a refresh may write (design Part 4.2).

`wake_conditions.max_cycles_per_day` is deliberately absent: it has no field on
`BusinessTypeDefinition` at all — it is a contract default (48) — so the type
does not own it and a type upgrade may not move it."""


FROZEN_FIELDS: Final[tuple[str, ...]] = (
    "business_id",
    "business_type",
    "display_name",
    "created_at",
    "lifecycle_state",
    "budget",
    "capability_permissions",
    "autonomy_policies",
    "goals",
    "wake_conditions.max_cycles_per_day",
)
"""Band C, enumerated so it can be enforced rather than remembered.

`budget` is the operator's money and the live data is the argument: Summit Trail
Gear's per-round limit is an explicit operator choice against its template's
suggestion (M6-F23/M6-F25). `capability_permissions` and `autonomy_policies` are
the authorization records `authorize_invocation` reads — refreshing them would
let a version bump widen an existing company's reach with no human in the loop
(design Part 7.1, frozen in v1). `goals` has no counterpart on a type at all."""


class FieldChange(BaseModel):
    """One difference between a stored contract and its installed type.

    `before` and `after` are rendered from the stored values on both sides and
    are never the input to the write: `apply_refresh` recomposes the new
    contract from the definition itself, so a change is *described* here and
    *effected* there. That separation is what stops a rendering bug from
    becoming a write.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(min_length=1)
    """Dotted path into the contract, e.g. ``kpi_targets.data_freshness_hours``.
    Engineer-facing: it is a key for the audit record and for the sentence
    table, and it is never shown to an operator (spec §12.5, design Part 6)."""

    band: RefreshBand
    before: str
    after: str
    description: str = Field(min_length=1)
    """One plain sentence, in operator language, from a platform-owned table
    keyed on the kind of field (design Part 6). Required, not optional: a field
    with no sentence is not renderable and therefore not refreshable, which is
    what stops a new Band B field from reaching an operator before someone has
    written the sentence for it."""


class ContractRefreshPlan(BaseModel):
    """What a refresh would change for one company, and what it would not.

    Produced by `plan_refresh`, which writes nothing. An empty `changes` is the
    ordinary answer for a company created after the current version installed
    (Summit Trail Gear, design Part 5 subject 3) and is what makes the mechanism
    falsifiable: a blanket overwrite would look identical on a company that
    needs one and produce a plan here on a company that does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    business_id: BusinessId
    business_type: BusinessTypeName
    installed_version: str
    """The version the plan diffs against. Recorded so an audit entry says what
    the company was brought up to; never rendered (design Part 6 forbids
    showing an operator a version string)."""

    changes: tuple[FieldChange, ...] = ()
    """Band B differences, in the order a renderer should show them."""

    withheld: tuple[FieldChange, ...] = ()
    """Band C differences, reported and never applied.

    Reported rather than dropped because Band C is the half of this design most
    worth being able to see: Summit's per-round limit differs from its
    template's suggestion, and a plan that showed nothing there would be
    indistinguishable from one where the guard had quietly stopped working."""

    source_digest: str
    """Digest of the Band B values this plan was computed against."""

    target_digest: str
    """Digest of the Band B values applying it would produce."""

    @property
    def plan_key(self) -> str:
        """Return the stable identifier for this exact transition (D-024.3).

        Derived from the company and both stored digests rather than minted, so
        it is identical across a retried or re-rendered plan and different for
        any other transition. That is what lets `apply_refresh` tell "this is
        the plan the operator consented to" from "the type moved underneath
        them", without storing a pending record anywhere.
        """
        return _digest(
            {
                "business_id": self.business_id,
                "source": self.source_digest,
                "target": self.target_digest,
            }
        )

    @property
    def is_empty(self) -> bool:
        """Return whether this company is already up to date."""
        return not self.changes


class RefreshConsent(BaseModel):
    """The operator's answer to one specific plan (D-030).

    A required input to `apply_refresh`, never implied and never defaulted:
    `granted` has no default, so a caller cannot omit it and get a write.

    It carries no `action_type`, which is the whole of D-030 made structural.
    An `ApprovalRequest` would key three mechanisms on that string — the
    graduation counters (D-010, A-003), the effect binding (D-024), and the
    approval rendering (D-011) — and the first of those means that after five
    clean acceptances, company updates would begin applying unattended. §8
    governs what a company proposes to do; this governs what the platform
    proposes to change about a company.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_key: str = Field(min_length=1)
    """The plan this answer is about. Consent to one set of changes is never
    consent to a different set."""

    granted: bool
    actor: str = "operator"


class RefreshOutcome(StrEnum):
    """How `apply_refresh` resolved."""

    APPLIED = "applied"
    NOTHING_TO_APPLY = "nothing_to_apply"
    """The plan was empty — the company was already current."""

    ALREADY_APPLIED = "already_applied"
    """This exact plan had already been written. The idempotent case (D-024.3):
    a repeated call writes nothing and records nothing a second time."""

    DECLINED = "declined"
    """The operator said no. A real outcome, recorded, not a deferral."""


class RefreshResult(BaseModel):
    """What `apply_refresh` did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    business_id: BusinessId
    outcome: RefreshOutcome
    applied_fields: tuple[str, ...] = ()
    decision_id: str | None = None


def band_b_values(contract: BusinessContract) -> dict[str, Any]:
    """Return the contract's Band B values as plain JSON-safe data.

    The projection both digests are taken over, and the payload the audit
    record carries as its before/after. One function so the two can never
    describe different sets of fields.
    """
    return {
        "kpi_targets": [target.model_dump(mode="json") for target in contract.kpi_targets],
        "wake_conditions.schedule_cron": contract.wake_conditions.schedule_cron,
        "wake_conditions.event_triggers": sorted(contract.wake_conditions.event_triggers),
        "compliance_requirements": list(contract.compliance_requirements),
    }


def band_b_digest(contract: BusinessContract) -> str:
    """Return a stable digest of ``contract``'s Band B values."""
    return _digest(band_b_values(contract))


def frozen_field_differences(before: BusinessContract, after: BusinessContract) -> tuple[str, ...]:
    """Return the Band C fields that differ between two contracts.

    The enforcement point for D-029's third band. `BusinessRegistry.
    refresh_contract` calls it and refuses to write anything it names, so a
    refresh cannot move identity, money, the lifecycle state, or either
    authorization record even if the planner that produced the new contract is
    wrong. A guard at the write boundary holds for callers that do not exist
    yet; a guard in the planner holds only for the planner.

    Args:
        before: The stored contract.
        after: The contract a refresh proposes to store.

    Returns:
        The names of the frozen fields that differ, in `FROZEN_FIELDS` order.
        Empty means the proposal touches Band C not at all.
    """
    differing: list[str] = []
    for field in FROZEN_FIELDS:
        if _read(before, field) != _read(after, field):
            differing.append(field)
    return tuple(differing)


def _read(contract: BusinessContract, path: str) -> Any:
    """Return the value at a dotted ``path``, normalised for comparison.

    Normalised because the two contracts being compared arrive by different
    routes — one deserialized from the instance row, one recomposed in memory —
    and a difference in representation must never read as a Band C violation.
    A refusal that fires on a `frozenset` versus a `list` would make the guard
    untrustworthy, and an untrustworthy guard gets weakened rather than fixed.
    """
    value: Any = contract
    for part in path.split("."):
        value = getattr(value, part)
    return _normalize(value)


def _normalize(value: Any) -> Any:
    """Return a comparable form of one contract value, recursively.

    Collections of scalars are sorted, which is what makes the comparison
    immune to `frozenset` iteration order — `tool_scope` and `credential_refs`
    are frozensets inside `capability_permissions`, and their dumped order is a
    property of the set object rather than of its contents. Collections of
    structures keep their order, because the order of `capability_permissions`
    or `autonomy_policies` is contract content and a reordering is a change.
    """
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json"))
    if isinstance(value, dict):
        mapping: dict[str, Any] = {str(key): _normalize(item) for key, item in value.items()}  # type: ignore[misc]
        return mapping
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)  # type: ignore[misc]
    if isinstance(value, tuple | list):
        items: list[Any] = [_normalize(item) for item in value]  # type: ignore[misc]
        if all(item is None or isinstance(item, bool | int | float | str) for item in items):
            return sorted(items, key=repr)
        return items
    return value if value is None or isinstance(value, bool | int | str) else str(value)


def _digest(payload: Any) -> str:
    """Return a sha256 over ``payload``'s canonical JSON form.

    `sort_keys` makes the digest depend only on content, never on field order,
    the same discipline `businesses.definition.compute_digest` uses for the
    staleness detector.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
