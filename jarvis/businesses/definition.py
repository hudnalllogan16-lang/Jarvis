"""Business type definition (spec §4).

§4 says a new business type is a development task producing a Business Manager
workflow definition, a compliance_requirements definition, and domain-specific
prompt/tool configurations. It does not say what shape that artifact takes, so
this is that shape.

The Manager *workflow* is not part of a definition: there is one generic
Business Manager workflow (§2.1) and a type supplies the configuration it runs
under. That is what makes §4's "a new instance is addable via configuration only
— no orchestrator code changes" true rather than aspirational.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.domain.contract import (
    AutonomyPolicy,
    CapabilityPermission,
    CapabilityType,
    KpiTarget,
)
from jarvis.domain.kpi import KpiMapping


class BusinessTypeDefinition(BaseModel):
    """Everything needed to instantiate a business of one type (spec §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    display_name: str = Field(min_length=1)
    """Operator-facing "company template" name (D-007)."""

    description: str = Field(min_length=1)
    """Shown in the create-a-company flow. Plain language (spec §12.5)."""

    prompt_templates: dict[str, str] = Field(min_length=1)
    """Keyed ``{type}.{capability}`` to match `ScopedRequest.prompt_ref`.

    Required, not optional: a type with no templates produces a business whose
    every dispatch fails permanently as a missing task definition — a company
    that looks healthy and can never do anything."""

    capability_permissions: tuple[CapabilityPermission, ...] = Field(min_length=1)
    autonomy_policies: tuple[AutonomyPolicy, ...] = ()
    default_kpi_targets: tuple[KpiTarget, ...] = ()

    kpi_mappings: tuple[KpiMapping, ...] = ()
    """Which of this type's metrics the cycle measures, and from which platform
    fact (D-027.2). Data, like everything else here — the type declares what a
    metric *is*, and `record_cycle_kpis` reads it.

    Empty by default and empty is meaningful: a type with no mappings records no
    observations (D-027.3). Targets without mappings are still legitimate — they
    are goals nothing has learned to measure yet — so this defaulting to `()`
    leaves an existing type exactly as it was rather than silently starting to
    write numbers for it."""

    compliance_requirements: tuple[str, ...] = ()
    """Drafted for the owner, signed off per type before launch (Defaults in Force)."""

    suggested_budget_usd: Decimal = Field(default=Decimal("50.00"), gt=0)
    suggested_wake_ceiling_usd: Decimal = Field(default=Decimal("1.00"), gt=0)
    """No platform default exists for the wake-cycle ceiling and §2.1 requires it
    be explicit before launch, so a type suggests one and creation records it."""

    schedule_cron: str | None = "0 9 * * *"
    event_triggers: frozenset[str] = Field(default_factory=frozenset)

    tool_registry: dict[str, str] = Field(default_factory=dict)
    """Tool name -> implementation key, consumed by the approved-action path
    (D-015). Which tools *exist* for this type. Whether an instance may use one
    remains its CapabilityPermission.tool_scope — existence is not permission."""

    @property
    def major_version(self) -> int:
        """Return the major version. A bump resets graduation counters (A-003)."""
        return int(self.version.split(".")[0])

    def template_key(self, capability: CapabilityType) -> str:
        """Return the prompt reference the Manager will use for ``capability``."""
        return f"{self.name}.{capability.value}"

    def missing_templates(self) -> tuple[str, ...]:
        """Return permitted capabilities that have no template.

        A permission without a template is a capability the business is allowed
        to invoke and guaranteed to fail at. Checked at install time rather than
        first dispatch, so the failure surfaces to a developer instead of to an
        operator watching a company do nothing.
        """
        return tuple(
            self.template_key(p.capability)
            for p in self.capability_permissions
            if self.template_key(p.capability) not in self.prompt_templates
        )


def compute_digest(definition: BusinessTypeDefinition) -> str:
    """Return a stable content digest of ``definition``'s JSON form.

    The staleness detector's comparison key (design doc Part 2.5): stored
    alongside an installed row at install time and recomputed from the source
    definition on every startup sweep. `sort_keys` makes the digest depend only
    on content, never on field order, so two definitions that would serialize
    identically always hash identically.

    This is what lets `ensure_builtin_types` notice a definition edited in
    place without a version bump — the case `install()`'s duplicate-version
    gate (M6-F22, M7-F4) deliberately does not reinstall, and the live
    `affiliate` v1.0.1 row that predates this mechanism entirely (M8-F3) has
    no stored digest to match, so it compares unequal too.
    """
    canonical = json.dumps(definition.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
