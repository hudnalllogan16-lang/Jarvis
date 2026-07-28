"""Business type installation and company creation (spec §4, §0.1).

§4 distinguishes two things this module keeps separate: installing a *type* is a
development activity, and creating an *instance* of an installed type is
configuration the operator performs through a wizard. The wizard applies to
instantiating known types, never to building new ones.

Creation is also the point where §2.1's "exactly one Business Manager per
business" becomes real, so it publishes `business.activated` rather than
starting a workflow directly — §2 forbids direct calls between workers, and the
bus gives deduplication (A-002) so a replayed activation cannot start two
Managers for one business.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from jarvis.businesses.definition import (
    BusinessTypeDefinition,
    compute_digest,
    read_installed_definition,
)
from jarvis.businesses.refresh import refreshed_contract
from jarvis.domain.authority import AuthorityLevel, granted_entry, namespace_error
from jarvis.domain.contract import BudgetPolicy, BusinessContract, WakeConditions
from jarvis.domain.kpi import provisioned_kpi_targets
from jarvis.domain.lifecycle import LifecycleState
from jarvis.events.bus import Event, EventBus
from jarvis.events.types import BUSINESS_ACTIVATED, CAPABILITY_RESULT, KPI_THRESHOLD_BREACHED
from jarvis.kernel.errors import ConfigurationError
from jarvis.kernel.ids import (
    BusinessId,
    BusinessTypeName,
    EventId,
    new_business_id,
    new_decision_id,
    new_event_id,
)
from jarvis.kernel.logging import get_logger
from jarvis.registry.registry import BusinessRegistry

logger = get_logger(__name__)


class ProvisioningService:
    """Installs business types and creates companies from them (spec §4)."""

    def __init__(
        self,
        registry: BusinessRegistry,
        bus: EventBus,
        *,
        default_wake_ceiling_usd: Decimal | None = None,
    ) -> None:
        """Args:
        registry: Business Registry (spec §0.1).
        bus: Event bus, for activation signalling (spec §2).
        default_wake_ceiling_usd: The configured platform default for §2.1's
            per-cycle ceiling, applied when the operator names none. Injected
            rather than read from settings here, because this package holds no
            configuration handle; the Kernel is the composition root that does.
            None falls back to the type's suggestion — the shape a test or a
            caller with no settings gets, never an absent ceiling (M6-F23).
        """
        self._registry = registry
        self._bus = bus
        self._default_wake_ceiling_usd = default_wake_ceiling_usd

    async def install(self, definition: BusinessTypeDefinition) -> None:
        """Install a business type, refusing an internally inconsistent one.

        Raises:
            ConfigurationError: If any declared `action_type` lies outside the
                type's own namespace or is registered above L2-tactical
                (M9-F116 — see `_refuse_unauthorised_action_types`; checked
                first, because it is the only one of these whose bypass is a
                security event rather than a defect); if any permitted
                capability lacks a prompt
                template; if a `kpi_mappings` key names no
                `default_kpi_targets` key (D-027.2 — a mapping with no target
                writes an observation nothing reads); if `event_triggers`
                subscribes to `capability.result_returned` (M6-F10 — every
                result is awaited inside the cycle that requested it under
                D-001, so subscribing is a self-sustaining wake loop bounded
                only by `max_cycles_per_day`); if a type declaring
                `kpi_mappings` also subscribes to `KPI_THRESHOLD_BREACHED`
                (M7-F35 — the type would re-wake itself from its own
                measurement); or if this is an upgrade of an already-installed
                type and refreshing some existing company of that type
                against `definition` would produce an invalid contract
                (M8-F111 — see `_refuse_unrefreshable_upgrade`). Every one of
                these is refused here rather than at first dispatch, first
                cycle, or first refresh offer: the same defect surfaces either
                way, but here it reaches a developer instead of an operator.
        """
        self._refuse_unauthorised_action_types(definition)

        missing = definition.missing_templates()
        if missing:
            raise ConfigurationError(
                f"business type {definition.name} permits capabilities with no prompt "
                f"template: {list(missing)} (spec §4)"
            )

        target_keys = {target.key for target in definition.default_kpi_targets}
        unmatched_mappings = sorted(
            mapping.key for mapping in definition.kpi_mappings if mapping.key not in target_keys
        )
        if unmatched_mappings:
            raise ConfigurationError(
                f"business type {definition.name} declares kpi_mappings for "
                f"{unmatched_mappings}, which name no default_kpi_targets key: an "
                "observation with no target is unmeasurable (D-027.2)"
            )

        if CAPABILITY_RESULT in definition.event_triggers:
            raise ConfigurationError(
                f"business type {definition.name} subscribes to {CAPABILITY_RESULT!r}: "
                "every capability result is awaited inside the cycle that requested it "
                "(D-001), so this is a self-sustaining wake loop bounded only by "
                "max_cycles_per_day (M6-F10)"
            )

        if definition.kpi_mappings and KPI_THRESHOLD_BREACHED in definition.event_triggers:
            raise ConfigurationError(
                f"business type {definition.name} declares kpi_mappings and subscribes to "
                f"{KPI_THRESHOLD_BREACHED!r}: it would re-wake itself from its own "
                "measurement (M7-F35)"
            )

        existing = await self._registry.installed_type(BusinessTypeName(definition.name))
        if existing is not None and existing.version != definition.version:
            await self._refuse_unrefreshable_upgrade(definition)

        await self._registry.install_business_type(
            name=BusinessTypeName(definition.name),
            version=definition.version,
            display_name=definition.display_name,
            metadata={
                "description": definition.description,
                "prompt_templates": definition.prompt_templates,
                "definition": definition.model_dump(mode="json"),
                "definition_digest": compute_digest(definition),
            },
        )
        logger.info("business type installed", extra={"context": {"name": definition.name}})

    @staticmethod
    def _refuse_unauthorised_action_types(definition: BusinessTypeDefinition) -> None:
        """Refuse a type that declares an action it may not declare (M9-F116, D-050 draft).

        Two independent guards, in the order a bypass would have to defeat them.

        **A-003's namespace rule, now enforced.** A-003 has said since M1 that an
        action type is namespaced to the business *type*, and nothing checked it.
        `AutonomyPolicy.action_type`'s pattern admits any dotted identifier, so a
        business type could legally declare `platform.reallocate_capital` or
        `platform.circuit_breaker` — and both would validate, install, and enter
        `declared_action_types`.

        It is contained today only by what does not exist yet: `platform_feed()`
        filters on `business_id IS NULL`, so a company's rows cannot masquerade
        as platform ones, and there is no platform-scoped approval path to
        confuse. Design 8.1 builds exactly that path, and building it against an
        unreserved namespace is how a plugin acquires a platform authority.

        **Nothing above L2-tactical may be requested.** The second guard does not
        depend on the first: even were the namespace comparison wrong, an action
        the registry grants at L2-strategic or L3 is platform-owned, and a type
        requesting one is asking to create policy, which Part 2 forbids
        categorically. Defence in depth on the boundary that matters most —
        plugins may *request* authority, they never *possess* it, and only
        installation grants it (design 8.3).

        Refused here rather than at first approval, for the reason every other
        check in `install` is: the same defect surfaces either way, but here it
        reaches a developer instead of an operator, and before any row exists.

        Args:
            definition: The type definition about to be installed.

        Raises:
            ConfigurationError: If any declared `action_type` is outside the
                type's own namespace, is absent from the Action Registry
                entirely (M9-F185 — an unregistered action has no authority
                to install with; the trichotomy's default is nothing, not
                whatever the level comparison below happens to fall through
                to), or is registered above L2-tactical.
        """
        for policy in definition.autonomy_policies:
            reason = namespace_error(policy.action_type, type_name=definition.name)
            if reason is not None:
                raise ConfigurationError(reason)

            entry = granted_entry(policy.action_type)
            if entry is None:
                raise ConfigurationError(
                    f"business type {definition.name} declares {policy.action_type!r}, "
                    f"which the Action Registry does not grant: an unregistered action "
                    f"has no authority at all (design 8.3) and may not be installed. "
                    f"Register it in jarvis/domain/authority.py first."
                )
            if entry.level not in {
                AuthorityLevel.L0,
                AuthorityLevel.L1,
                AuthorityLevel.L2_TACTICAL,
            }:
                raise ConfigurationError(
                    f"business type {definition.name} declares {policy.action_type!r}, "
                    f"which the Action Registry grants at {entry.level}: a type may not "
                    f"request an authority above L2-tactical, because that is asking to "
                    f"create policy (design 8.3, Part 2)."
                )

    async def _refuse_unrefreshable_upgrade(self, definition: BusinessTypeDefinition) -> None:
        """Refuse ``definition`` if it would break an existing company's refresh (M8-F111).

        Reuses `businesses.refresh.refreshed_contract` — the exact validation
        `ContractRefreshService.plan_refresh` applies when it computes what
        accepting an update would write (design Part 4.4) — rather than a
        second, independently-drifting copy of "what does a refreshed
        contract look like" living here. `plan_refresh` itself cannot be
        called for this: it diffs against the *installed* row, and at this
        point in `install` the incoming `definition` is not installed yet.

        Every company of this type is checked, not only the first: an
        operator offered *no* update is different from one offered an update
        the platform silently could not have written, and this refuses the
        version bump itself rather than let that surface company by company
        as each one's refresh offer failed.

        Args:
            definition: The version about to be installed.

        Raises:
            ConfigurationError: If refreshing any existing company of this
                type against `definition` would produce an invalid contract.
                Reraised from `refreshed_contract` with the affected
                company named, so the refusal reaches a developer with
                enough context to act on it.
        """
        instances = [
            row
            for row in await self._registry.list_instances()
            if row.business_type == definition.name
        ]
        for row in instances:
            contract = await self._registry.get_contract(BusinessId(row.business_id))
            try:
                refreshed_contract(contract, definition)
            except ConfigurationError as exc:
                raise ConfigurationError(
                    f"installing {definition.name} {definition.version} would leave "
                    f"{contract.display_name} ({contract.business_id}) with no valid "
                    f"refresh available: {exc}"
                ) from exc

    async def create_company(
        self,
        *,
        definition: BusinessTypeDefinition,
        display_name: str,
        budget_usd: Decimal | None = None,
        wake_ceiling_usd: Decimal | None = None,
    ) -> BusinessId:
        """Create and activate one company from an installed type.

        Args:
            definition: The installed type.
            display_name: Operator-chosen company name.
            budget_usd: Spending cap. Defaults to the type's suggestion.
            wake_ceiling_usd: How much one round of work may spend (§2.1).
                Optional here, never optional in the contract: an unnamed
                ceiling resolves to the configured platform default and, failing
                that, to the type's suggestion. The spec's Defaults in Force
                require an explicit ceiling before a business launches, and a
                default that is applied and recorded is explicit — an absent one
                is not, which is what M6-F23 found.

        Returns:
            The permanent business identifier.

        Raises:
            ConfigurationError: If no ceiling can be resolved from any of the
                three sources. Refused rather than defaulted a fourth time: a
                business launched with a ceiling nobody chose is the failure
                Defaults in Force exists to prevent.
        """
        business_id = new_business_id()
        ceiling = self._resolved_wake_ceiling(wake_ceiling_usd, definition)
        contract = BusinessContract(
            business_id=business_id,
            business_type=BusinessTypeName(definition.name),
            display_name=display_name,
            budget=BudgetPolicy(
                business_cap_usd=budget_usd or definition.suggested_budget_usd,
                wake_cycle_ceiling_usd=ceiling,
            ),
            wake_conditions=WakeConditions(
                schedule_cron=definition.schedule_cron,
                event_triggers=definition.event_triggers,
            ),
            capability_permissions=definition.capability_permissions,
            autonomy_policies=definition.autonomy_policies,
            # M7-F49: `CONFIGURED_KPI_TARGET_COUNT`'s target is derived from
            # this type's own target count here, once, rather than trusting a
            # type author's hand-picked number to stay in sync with it — the
            # provisioning-time half of the D-027 amendment pass. A type that
            # maps no key to that source is unaffected (D-027.3's silence).
            kpi_targets=provisioned_kpi_targets(
                definition.default_kpi_targets, definition.kpi_mappings
            ),
            compliance_requirements=definition.compliance_requirements,
        )
        await self._registry.register_instance(contract)

        await self._registry.transition(
            business_id,
            LifecycleState.ACTIVE,
            decision_id=new_decision_id(),
            reason=f"You created {display_name} and started it.",
        )
        await self._bus.publish(
            Event(
                event_id=EventId(new_event_id()),
                event_type=BUSINESS_ACTIVATED,
                business_id=business_id,
                payload={"display_name": display_name, "business_type": definition.name},
            )
        )
        logger.info(
            "company created",
            extra={
                "context": {
                    "business_id": business_id,
                    "business_type": definition.name,
                    # Recorded because the ceiling is now applied from three
                    # possible sources; which one won is the fact an operator
                    # asking "why did it stop early" needs (D-021, M6-F23).
                    "wake_cycle_ceiling_usd": str(ceiling),
                    "ceiling_chosen_explicitly": wake_ceiling_usd is not None,
                }
            },
        )
        return business_id

    def _resolved_wake_ceiling(
        self, requested: Decimal | None, definition: BusinessTypeDefinition
    ) -> Decimal:
        """Return the per-cycle ceiling this company launches with (§2.1).

        Precedence, most specific first: what the operator asked for, then the
        platform's configured default, then the type's suggestion. The
        configured default sits above the type's suggestion deliberately —
        it is the one of the two an owner sets, and M6-F23 was precisely that
        it sat above nothing at all and was never read.

        Raises:
            ConfigurationError: If none of the three yields a positive amount.
        """
        for candidate in (requested, self._default_wake_ceiling_usd):
            if candidate is not None and candidate > 0:
                return candidate
        suggested = definition.suggested_wake_ceiling_usd
        if suggested > 0:
            return suggested
        raise ConfigurationError(
            f"business type {definition.name} has no spending limit for a single round of "
            "work and none was given (spec §2.1, Defaults in Force)"
        )

    async def available_types(self) -> Sequence[BusinessTypeDefinition]:
        """Return installed types, for the create-a-company flow (spec §4)."""
        out: list[BusinessTypeDefinition] = []
        for row in await self._registry.installed_types():
            if not getattr(row, "enabled", True):
                continue  # disabled types are invisible to creation (D-017)
            definition = read_installed_definition(row)
            if definition is not None:
                out.append(definition)
        return out
