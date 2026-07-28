"""Contract refresh on type upgrade (D-029, D-030; design doc Part 4).

Audit finding F-A is the problem this exists for: a company's contract
snapshots `kpi_targets` at creation, so `KpiDirection` — added to the finance
type at 1.0.2 — applies only to companies created after it, and Portfolio
Watch's freshness metric still scores backwards (M7-F24, M7-F62). Trailhead
Gear Reviews is the sharper case: it snapshotted a wake condition the affiliate
type removed at 1.0.1 as the M6-F10 fix, so a live company can still re-wake
itself from its own output (M6-F22 predicted exactly this, in writing).

Two operations, and the split matters:

- `plan_refresh` reads and computes. **Both sides are stored values** — the
  contract on one, the installed definition on the other — so the plan an
  operator reads is D-011-shaped by construction: no model sits between the
  change and the human.
- `apply_refresh` writes, and only with consent that names the plan it is
  consenting to. It is not a workflow and not a Manager activity: D-004 keeps
  nondeterminism in activities, and this is neither a cycle step nor a model
  call. It is a Registry write (design 4.4).

Nothing here touches graduation state. A refresh is minor-version-scoped by
construction; A-003's major-version reset is keyed to the version change itself
and lives at install (`BusinessRegistry._reset_graduation_on_major_bump`).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from pydantic import ValidationError

from jarvis.businesses.definition import BusinessTypeDefinition, read_installed_definition
from jarvis.domain.contract import BusinessContract, KpiDirection, KpiTarget
from jarvis.domain.kpi import provisioned_kpi_targets
from jarvis.domain.refresh import (
    ContractRefreshPlan,
    FieldChange,
    RefreshBand,
    RefreshConsent,
    RefreshOutcome,
    RefreshResult,
    band_b_digest,
    band_b_values,
)
from jarvis.events.types import (
    APPROVAL_DECIDED,
    BUSINESS_ACTIVATED,
    CAPABILITY_RESULT,
    KPI_THRESHOLD_BREACHED,
)
from jarvis.kernel.errors import BusinessTypeNotFoundError, ConfigurationError, RegistryError
from jarvis.kernel.ids import BusinessId, BusinessTypeName, new_decision_id
from jarvis.kernel.logging import get_logger
from jarvis.observability.decision_log import DecisionLog
from jarvis.registry.registry import BusinessRegistry

logger = get_logger(__name__)

TRIGGER_SENTENCES: dict[str, tuple[str, str]] = {
    APPROVAL_DECIDED: (
        "It will start a new round of work as soon as you answer a request.",
        "It will no longer start a new round of work when you answer a request.",
    ),
    CAPABILITY_RESULT: (
        "It will start a new round of work when its own work comes back.",
        "It will stop starting a new round of work when its own work comes back.",
    ),
    KPI_THRESHOLD_BREACHED: (
        "It will start a new round of work when one of its numbers crosses a limit.",
        "It will no longer start a new round of work when one of its numbers crosses a limit.",
    ),
    BUSINESS_ACTIVATED: (
        "It will start a new round of work when the company is started up.",
        "It will no longer start a new round of work when the company is started up.",
    ),
}
"""One (added, removed) sentence pair per publishable signal, in operator
language (spec §12.5, design Part 6).

The table is keyed on the signal rather than assembled from its name because
the names themselves are exactly what an operator must never read: a diff
renderer printing `capability.result_returned` would emit two of §12.5's
seventeen forbidden terms verbatim and fail the gate, correctly.

A signal with no pair here is **not renderable and therefore not refreshable**
— `_trigger_change` refuses rather than inventing a sentence, so a new wake
signal cannot reach an operator before someone has written its two lines. The
keys are `events.types.ALL_EVENT_TYPES`, checked by test."""

DIRECTION_SENTENCES: dict[KpiDirection, str] = {
    KpiDirection.ABOVE: "counts higher numbers as better",
    KpiDirection.BELOW: "counts lower numbers as better",
}
"""How each direction reads in a sentence. Portfolio Watch's live case is the
`BELOW` one: its freshness figure was being scored as though more hours since
the last check were an achievement (F-A, M7-F30)."""


class ContractRefreshService:
    """Plans and applies Band B contract refreshes for one company (D-029)."""

    def __init__(self, registry: BusinessRegistry, decisions: DecisionLog) -> None:
        """Args:
        registry: Business Registry — the contract's only writer (§0.1).
        decisions: Decision Log writer. Required, not optional: every
            resolution of a refresh owes the operator a "why" in the feed
            they actually read (spec §11.5), and an injectable-as-None
            dependency is one a caller can forget.
        """
        self._registry = registry
        self._decisions = decisions

    # ── planning (no writes) ───────────────────────────────────────────────

    async def plan_refresh(self, business_id: BusinessId) -> ContractRefreshPlan:
        """Return what refreshing ``business_id`` would change, writing nothing.

        Diffs the stored contract against the installed definition row. The
        result is per-band: `changes` are the Band B differences a refresh may
        write, `withheld` are the Band C differences it never will.

        Args:
            business_id: The company to plan for.

        Returns:
            A plan whose `is_empty` is True when the company is already
            current — the ordinary answer for one created since the installed
            version, and the case that makes this mechanism falsifiable. Also
            True when the operator already declined this exact installed
            version (D-030 Part 4.3, M8-F102/M9-4): `changes` collapses to
            `()` the same way, so nothing downstream needs to tell "current"
            from "suppressed" apart to do the right thing — both mean there is
            nothing here to show or act on right now. `withheld` (Band C) is
            unaffected either way; it is never gated by consent state.

        Raises:
            BusinessNotFoundError: If no such company exists.
            BusinessTypeNotFoundError: If its type is not installed, or its
                installed row carries no definition.
            ConfigurationError: If refreshing would produce a contract that is
                not valid — a type that dropped every wake condition, say. A
                plan an operator could accept and the platform could not write
                is worse than a refusal, so it is refused here where it
                reaches a developer.
        """
        contract = await self._registry.get_contract(business_id)
        definition = await self._installed_definition(contract.business_type)
        target = refreshed_contract(contract, definition)

        changes = tuple(_band_b_changes(contract, definition))
        if changes and await self._is_declined(business_id, definition.version):
            # Suppressed, not merely hidden: collapse to the same shape a
            # genuinely-current plan has (empty changes, source == target) so
            # apply/dismiss's existing `plan.is_empty` checks (jarvis/api/
            # app.py) and the operator surface (render_plan) need no changes
            # of their own to do the honest thing. A new version changes
            # `definition.version`, which changes what `_is_declined` compares
            # against, which naturally stops matching — no separate clearing
            # step required.
            changes = ()
            target = contract

        return ContractRefreshPlan(
            business_id=business_id,
            business_type=contract.business_type,
            installed_version=definition.version,
            changes=changes,
            withheld=tuple(_withheld_changes(contract, definition)),
            source_digest=band_b_digest(contract),
            target_digest=band_b_digest(target),
        )

    async def _is_declined(self, business_id: BusinessId, installed_version: str) -> bool:
        """Return whether the operator already declined ``installed_version``.

        Version-keyed, not digest-keyed (see `ContractRefreshDeclineRow` and
        `BusinessRegistry.declined_refresh_version` for why: a content digest
        cannot distinguish a real version change from the same-version drift
        M8-F3 found live).
        """
        declined = await self._registry.declined_refresh_version(business_id)
        return declined == installed_version

    # ── applying (the write path) ──────────────────────────────────────────

    async def apply_refresh(
        self,
        business_id: BusinessId,
        plan: ContractRefreshPlan,
        *,
        consent: RefreshConsent,
    ) -> RefreshResult:
        """Write ``plan``'s Band B changes, with the operator's consent (D-030).

        Atomic per company: the whole Band B set is one contract value written
        in one statement inside the caller's transaction, so a company is never
        left half-refreshed. No schema change was needed for that — the
        contract is a single stored value and always was.

        Idempotent per D-024.3's discipline. The key is *derived* from the
        company and the two stored digests rather than minted, so a re-sent
        plan is recognisably the same plan: applying one that has already been
        written returns `ALREADY_APPLIED` and writes nothing a second time,
        and applying one computed against a definition that has since moved is
        refused rather than silently retargeted — the operator consented to a
        set of changes, not to whatever is current now.

        Args:
            business_id: The company to refresh.
            plan: The plan the operator was shown.
            consent: Their answer. Required and never implied; `granted` has
                no default, and it names the plan it answers.

        Returns:
            What was done, including the Decision Log entry's identifier when
            one was written.

        Raises:
            RegistryError: If consent was not granted, if it names a different
                plan, or if the definition moved since the plan was computed.
            BusinessNotFoundError: If no such company exists.
        """
        if consent.plan_key != plan.plan_key:
            raise RegistryError(
                "consent names a different set of changes than the plan supplied",
                operator_message="This update changed while you were reading it. "
                "Take another look.",
            )
        if not consent.granted:
            raise RegistryError(
                "apply_refresh requires granted consent; use decline_refresh to record a no",
                operator_message="Nothing was changed.",
            )
        if plan.is_empty:
            return RefreshResult(business_id=business_id, outcome=RefreshOutcome.NOTHING_TO_APPLY)

        contract = await self._registry.get_contract(business_id)
        current = band_b_digest(contract)
        if current == plan.target_digest:
            # Already written — a resend, or a second click. Not an error and
            # not a second audit record: one plan, at most one effect (D-024.3).
            return RefreshResult(business_id=business_id, outcome=RefreshOutcome.ALREADY_APPLIED)
        if current != plan.source_digest:
            raise RegistryError(
                f"refresh plan for {business_id} was computed against a contract that has "
                "since changed",
                operator_message="This update is out of date. Take another look.",
            )

        definition = await self._installed_definition(contract.business_type)
        refreshed = refreshed_contract(contract, definition)
        if band_b_digest(refreshed) != plan.target_digest:
            raise RegistryError(
                f"the company template for {contract.business_type} changed since this "
                "refresh was planned",
                operator_message="This update changed while you were reading it. "
                "Take another look.",
            )

        audit_ref = await self._registry.refresh_contract(
            business_id,
            refreshed,
            audit_ref_payload={
                "business_type": contract.business_type,
                "installed_version": plan.installed_version,
                "plan_key": plan.plan_key,
                "fields": [change.field for change in plan.changes],
                "before": band_b_values(contract),
                "after": band_b_values(refreshed),
                "consented_by": consent.actor,
            },
        )
        decision_id = new_decision_id()
        await self._decisions.record(
            decision_id=decision_id,
            business_id=business_id,
            summary=f"{contract.display_name} was updated to match its company template.",
            rationale=_rationale(plan),
            # No action_type, deliberately and structurally (D-030). Three
            # mechanisms key on that string — the graduation counters (D-010,
            # A-003), the effect binding (D-024), and approval rendering
            # (D-011) — and the first would mean that after five clean
            # acceptances, company updates began applying unattended. Its
            # absence is what makes "this can never graduate" true rather than
            # promised.
            action_type=None,
            inputs_considered={"changes": [change.field for change in plan.changes]},
            audit_ref=audit_ref,
        )
        logger.info(
            "contract refresh applied",
            extra={
                "context": {
                    "business_id": business_id,
                    "fields": [change.field for change in plan.changes],
                }
            },
        )
        return RefreshResult(
            business_id=business_id,
            outcome=RefreshOutcome.APPLIED,
            applied_fields=tuple(change.field for change in plan.changes),
            decision_id=decision_id,
        )

    async def decline_refresh(
        self,
        business_id: BusinessId,
        plan: ContractRefreshPlan,
        *,
        consent: RefreshConsent,
    ) -> RefreshResult:
        """Record that the operator declined ``plan``. Writes no contract.

        Declining is a real outcome, recorded, not a deferral loop (design
        4.3). The company keeps its snapshot, which is the status quo — so an
        operator who says no changes nothing, and one who says nothing at all
        changes nothing either.

        Args:
            business_id: The company the plan was for.
            plan: The plan being declined.
            consent: The answer, whose `granted` must be False.

        Raises:
            RegistryError: If the consent names a different plan, or grants.
        """
        if consent.plan_key != plan.plan_key:
            raise RegistryError("consent names a different set of changes than the plan supplied")
        if consent.granted:
            raise RegistryError("decline_refresh recorded against a granted consent")

        contract = await self._registry.get_contract(business_id)
        decision_id = new_decision_id()
        await self._decisions.record(
            decision_id=decision_id,
            business_id=business_id,
            summary=f"You chose not to update {contract.display_name} yet.",
            rationale=(
                "Nothing changed. This company keeps the settings it has, and Jarvis "
                "will offer the update again the next time its company template changes."
            ),
            action_type=None,
            inputs_considered={"changes": [change.field for change in plan.changes]},
        )
        # D-030 Part 4.3 / M8-F102: the Decision Log entry above is the
        # operator-readable record that this happened; this is the mechanism
        # that makes it *do* something — the next `plan_refresh` for this
        # company suppresses the same offer until `plan.installed_version`
        # moves (M9-4).
        await self._registry.record_refresh_decline(
            business_id,
            declined_version=plan.installed_version,
            source_digest=plan.source_digest,
            target_digest=plan.target_digest,
        )
        return RefreshResult(
            business_id=business_id,
            outcome=RefreshOutcome.DECLINED,
            decision_id=decision_id,
        )

    # ── internals ──────────────────────────────────────────────────────────

    async def _installed_definition(self, name: BusinessTypeName) -> BusinessTypeDefinition:
        """Return the installed definition for ``name``.

        Read from the Registry row rather than from the in-process catalog: the
        contract is diffed against what is *installed*, which is the only thing
        every other runtime reader consumes (M5-F3), and a company must never
        be offered a change from a definition the platform has not installed.
        """
        row = await self._registry.installed_type(name)
        definition = read_installed_definition(row)
        if definition is None:
            raise BusinessTypeNotFoundError(
                f"business type {name} is not installed, or carries no definition"
            )
        return definition


def refreshed_contract(
    contract: BusinessContract, definition: BusinessTypeDefinition
) -> BusinessContract:
    """Return ``contract`` with its Band B values taken from ``definition``.

    The whole write, in one place. Everything not named here is left exactly as
    stored, which is what makes the Band C guard at the write boundary a
    double-check rather than the only check.

    `kpi_targets` come from `provisioned_kpi_targets`, the same function
    `ProvisioningService.create_company` calls, rather than from
    `definition.default_kpi_targets` directly (M8-F153). A key mapped to
    `CONFIGURED_KPI_TARGET_COUNT` has its target derived from the type's own
    target count (M7-F49), and a company that arrived at the installed version
    by refresh must land on the same contract as one created at it — two
    derivations of one number are a drift waiting to happen, and the drifting
    half would be the one no test creates a company through.

    `max_cycles_per_day` is carried through untouched: the type has no field
    for it, so a type upgrade may not move it (design Part 4.2).

    Public (M8-F111) so `ProvisioningService.install` can reuse this exact
    validation to refuse an upgrade whose Band B projection would break an
    existing company, rather than a second copy of "what does a refreshed
    contract look like" living in `businesses/provisioning.py` and drifting
    from this one.

    Raises:
        ConfigurationError: If the result is not a valid contract.
    """
    payload = contract.model_dump(mode="json")
    payload["kpi_targets"] = [
        target.model_dump(mode="json")
        for target in provisioned_kpi_targets(
            definition.default_kpi_targets, definition.kpi_mappings
        )
    ]
    payload["wake_conditions"] = {
        **payload["wake_conditions"],
        "schedule_cron": definition.schedule_cron,
        "event_triggers": sorted(definition.event_triggers),
    }
    payload["compliance_requirements"] = list(definition.compliance_requirements)
    try:
        return BusinessContract.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationError(
            f"refreshing {contract.business_id} against {definition.name} "
            f"{definition.version} would produce an invalid contract: {exc}"
        ) from exc


def _band_b_changes(
    contract: BusinessContract, definition: BusinessTypeDefinition
) -> Iterable[FieldChange]:
    """Yield every Band B difference, in the order a renderer should show them.

    The declared side is the *derived* target set, not `default_kpi_targets`
    raw (M8-F153): `refreshed_contract` writes the derived one, and a plan that
    diffed against the underived one would describe a change the write does not
    make — or stay silent about one it does. One derivation, read by both.
    """
    yield from _kpi_target_changes(
        contract.kpi_targets,
        provisioned_kpi_targets(definition.default_kpi_targets, definition.kpi_mappings),
    )
    yield from _wake_changes(contract, definition)
    yield from _compliance_changes(contract, definition)


def _kpi_target_changes(
    stored: tuple[KpiTarget, ...], declared: tuple[KpiTarget, ...]
) -> Iterable[FieldChange]:
    """Yield membership and per-field differences between two target sets.

    Membership moves because a target with no mapping is unmeasurable and a
    mapping with no target writes nothing readable (design Part 4.2).

    `target_value` moves because the type default is today the *only* source of
    one: M7-F24 confirmed no per-instance override path exists, so refreshing it
    is lossless by construction. That argument expires the day a per-instance
    target edit surface lands, when this rule must narrow to the descriptive
    fields and refresh needs per-field provenance (**M8-F6**).
    """
    by_key = {target.key: target for target in stored}
    declared_by_key = {target.key: target for target in declared}

    for key, target in declared_by_key.items():
        if key not in by_key:
            yield _change(
                f"kpi_targets.{key}",
                before="",
                after=f"{target.target_value} {target.unit}",
                description=(
                    f"Starts tracking {target.operator_label}, "
                    f"aiming for {_plain(target.target_value)} {target.unit}."
                ),
            )

    for key, target in by_key.items():
        if key not in declared_by_key:
            yield _change(
                f"kpi_targets.{key}",
                before=f"{target.target_value} {target.unit}",
                after="",
                description=f"Stops tracking {target.operator_label}.",
            )
            continue

        current = declared_by_key[key]
        if target.operator_label != current.operator_label:
            yield _change(
                f"kpi_targets.{key}.operator_label",
                before=target.operator_label,
                after=current.operator_label,
                description=(f"Renames '{target.operator_label}' to '{current.operator_label}'."),
            )
        if target.direction is not current.direction:
            yield _change(
                f"kpi_targets.{key}.direction",
                before=target.direction.value,
                after=current.direction.value,
                description=(
                    f"{current.operator_label} now {DIRECTION_SENTENCES[current.direction]}."
                ),
            )
        if target.unit != current.unit:
            yield _change(
                f"kpi_targets.{key}.unit",
                before=target.unit,
                after=current.unit,
                description=(
                    f"Measures {current.operator_label} in {current.unit} instead of {target.unit}."
                ),
            )
        if target.target_value != current.target_value:
            yield _change(
                f"kpi_targets.{key}.target_value",
                before=_plain(target.target_value),
                after=_plain(current.target_value),
                description=(
                    f"Changes the goal for {current.operator_label} from "
                    f"{_plain(target.target_value)} to {_plain(current.target_value)} "
                    f"{current.unit}."
                ),
            )


def _wake_changes(
    contract: BusinessContract, definition: BusinessTypeDefinition
) -> Iterable[FieldChange]:
    """Yield differences in the two type-owned wake conditions.

    Trailhead Gear Reviews is the live subject: its stored signals still carry
    the one the affiliate type removed at 1.0.1 (M6-F10), so this is the first
    refresh that clears a defect rather than a cosmetic staleness.
    """
    stored_cron = contract.wake_conditions.schedule_cron
    if stored_cron != definition.schedule_cron:
        if definition.schedule_cron is None:
            description = "It will stop starting a round of work on a timetable."
        elif stored_cron is None:
            description = "It will start a regular round of work on a timetable."
        else:
            description = "It will start its regular round of work at a different time."
        yield _change(
            "wake_conditions.schedule_cron",
            before=stored_cron or "",
            after=definition.schedule_cron or "",
            description=description,
        )

    stored_triggers = set(contract.wake_conditions.event_triggers)
    declared_triggers = set(definition.event_triggers)
    for trigger in sorted(declared_triggers - stored_triggers):
        yield _trigger_change(trigger, added=True)
    for trigger in sorted(stored_triggers - declared_triggers):
        yield _trigger_change(trigger, added=False)


def _trigger_change(trigger: str, *, added: bool) -> FieldChange:
    """Return the change for one added or removed wake signal.

    Raises:
        ConfigurationError: If the signal has no sentence pair. A Band B
            difference the platform cannot describe is one an operator cannot
            consent to, so it is refused rather than rendered as a raw name
            (design Part 6).
    """
    sentences = TRIGGER_SENTENCES.get(trigger)
    if sentences is None:
        raise ConfigurationError(
            f"no operator sentence for the wake signal {trigger!r}: a change that cannot "
            "be described in plain language cannot be offered (spec §12.5)"
        )
    return _change(
        "wake_conditions.event_triggers",
        before="" if added else trigger,
        after=trigger if added else "",
        description=sentences[0] if added else sentences[1],
    )


def _compliance_changes(
    contract: BusinessContract, definition: BusinessTypeDefinition
) -> Iterable[FieldChange]:
    """Yield the compliance-rule difference, if there is one.

    One change for the whole list rather than one per line: the rules are
    owner-approved text injected verbatim into planning (D-027.5), and a
    line-by-line diff would put that text through a renderer that has no
    business paraphrasing it.
    """
    if contract.compliance_requirements == definition.compliance_requirements:
        return
    yield _change(
        "compliance_requirements",
        before=f"{len(contract.compliance_requirements)} rules",
        after=f"{len(definition.compliance_requirements)} rules",
        description="The rules this company works to have been updated.",
    )


def _withheld_changes(
    contract: BusinessContract, definition: BusinessTypeDefinition
) -> Iterable[FieldChange]:
    """Yield Band C differences — reported, never applied (D-029).

    Only the comparable ones: identity and `created_at` have no counterpart on
    a type, so there is nothing to report about them. What is here is the half
    of Band C a version bump could plausibly be expected to move, which is
    exactly the half worth being able to see it has not.
    """
    if contract.budget.business_cap_usd != definition.suggested_budget_usd:
        yield _change(
            "budget.business_cap_usd",
            before=_plain(contract.budget.business_cap_usd),
            after=_plain(definition.suggested_budget_usd),
            band=RefreshBand.FROZEN,
            description=(
                f"Keeps your spending limit of ${_plain(contract.budget.business_cap_usd)}. "
                "Jarvis never changes a limit you set."
            ),
        )
    if contract.budget.wake_cycle_ceiling_usd != definition.suggested_wake_ceiling_usd:
        yield _change(
            "budget.wake_cycle_ceiling_usd",
            before=_plain(contract.budget.wake_cycle_ceiling_usd),
            after=_plain(definition.suggested_wake_ceiling_usd),
            band=RefreshBand.FROZEN,
            description=(
                "Keeps your limit of "
                f"${_plain(contract.budget.wake_cycle_ceiling_usd)} for one round of work. "
                "Jarvis never changes a limit you set."
            ),
        )
    if contract.capability_permissions != definition.capability_permissions:
        yield _change(
            "capability_permissions",
            before=f"{len(contract.capability_permissions)} kinds of work",
            after=f"{len(definition.capability_permissions)} kinds of work",
            band=RefreshBand.FROZEN,
            description="Keeps what this company is allowed to do exactly as it is.",
        )
    if contract.autonomy_policies != definition.autonomy_policies:
        yield _change(
            "autonomy_policies",
            before=f"{len(contract.autonomy_policies)} actions",
            after=f"{len(definition.autonomy_policies)} actions",
            band=RefreshBand.FROZEN,
            description="Keeps what this company must ask you about exactly as it is.",
        )


def _change(
    field: str,
    *,
    before: str,
    after: str,
    description: str,
    band: RefreshBand = RefreshBand.CONSENTED,
) -> FieldChange:
    """Return one field change. Band B unless said otherwise."""
    return FieldChange(field=field, band=band, before=before, after=after, description=description)


def _rationale(plan: ContractRefreshPlan) -> str:
    """Return the Decision Log rationale: the sentences the operator accepted.

    Assembled from the plan's own descriptions rather than re-derived, so the
    feed records what the operator was shown rather than a second account of
    it (D-011's principle, applied to the record instead of the request).
    """
    return "You reviewed and accepted these changes. " + " ".join(
        change.description for change in plan.changes
    )


def _plain(value: Decimal) -> str:
    """Return a decimal without trailing zeros, for a sentence."""
    normalized = value.normalize()
    return f"{normalized:f}"
