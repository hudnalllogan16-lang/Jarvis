"""The cycle measures its KPIs (D-027; spec §5, §13 Step 3; M7-F21, M7-F22).

M7-F21 is the finding these tests exist to close: `KpiEngine.record` shipped in
M3 and no production caller ever reached it, so `kpi_values` had never held a
row. Every company's attainment was therefore structurally zero — not "not yet
measured" but permanently zero — and the health band, the dashboard's goals
component, and §13 Step 3's claim to exercise the KPI pattern were all reading
from an empty table.

Four properties are proven here, all offline:

1. A finished cycle writes observations for a type that declares mappings, and
   every number comes from a platform fact rather than from anything a model
   said (D-027.2).
2. A type that declares none writes nothing (D-027.3) — the negative control,
   without which "it wrote three rows" proves only that the code runs.
3. Attainment moves in both directions once observations exist.
4. The planning prompt carries the owner-approved compliance rules verbatim
   (D-027.5, M7-F22), read from the contract rather than from a copy of the
   text pasted into this file.

The freshness case dispatches through a real `CapabilityPool` against a real
ledger and audit log, so the completion it reads is the audit row an actual
invocation wrote. A hand-written row would prove the arithmetic and miss the
thing most likely to break: the event name the pool records under.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.businesses.provisioning import ProvisioningService
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates
from jarvis.capabilities.pool import CapabilityPool
from jarvis.capabilities.request import (
    CapabilityResult,
    InvocationStatus,
    ScopedRequest,
)
from jarvis.domain.contract import (
    BusinessContract,
    CapabilityPermission,
    CapabilityType,
)
from jarvis.domain.kpi import KpiSource
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.kpi.engine import KpiEngine
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager.activities import CAPABILITY_SUCCEEDED_EVENT, ManagerActivities
from jarvis.manager.types import CycleKpiRequest, PlanRequest
from jarvis.persistence.models import AuditLogRow, Base, KpiValueRow
from tests.conftest import as_business


class _StubProvider:
    """One canned reply. No live model is involved anywhere in this file."""

    def __init__(self, reply: str = "done") -> None:
        self._reply = reply
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: Any) -> CompletionResponse:
        self.prompts.append(" ".join(m.content for m in request.messages))
        return CompletionResponse(text=self._reply, usage=Usage(input_tokens=90, output_tokens=40))

    async def aclose(self) -> None:
        return None


class _PromptCapturingKernel:
    """A Kernel wrapper that records what the planner was actually asked."""

    def __init__(self, kernel: PlatformKernel, provider: _StubProvider) -> None:
        self._kernel = kernel
        self._provider = provider

    def __getattr__(self, name: str) -> Any:
        return getattr(self._kernel, name)

    @property
    def llm(self) -> Any:
        return self._provider


@pytest_asyncio.fixture
async def kernel() -> Any:
    """Yield a real Kernel over a fresh in-memory database.

    A real one, not a stand-in: `record_cycle_kpis` resolves the type
    definition through the Registry and builds the KPI engine through the
    composition root, and a stubbed Kernel would skip exactly the wiring M7-F1
    showed can silently be missing.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    built = PlatformKernel(settings, engine=engine, provider=_StubProvider())  # type: ignore[arg-type]
    try:
        yield built
    finally:
        await engine.dispose()


async def _company(
    kernel: PlatformKernel, definition: BusinessTypeDefinition, *, name: str = "Test Finance Co"
) -> BusinessContract:
    """Install ``definition`` and create an active company from it (§4).

    Through `ProvisioningService` rather than by hand-building a contract: the
    type's targets reach a running company only if `create_company` copies them
    across, and a hand-built contract would assume the thing under test.
    """
    async with kernel.services() as svc:
        provisioning = ProvisioningService(svc.registry, kernel.build_bus(svc))
        await provisioning.install(definition)
        business_id = await provisioning.create_company(definition=definition, display_name=name)
        return await svc.registry.get_contract(business_id)


def _ruleless(name: str = "ruleless_tracking") -> BusinessTypeDefinition:
    """Return a minimal type whose owner approved no compliance rules."""
    return BusinessTypeDefinition(
        name=name,
        version="1.0.0",
        display_name="Ruleless tracker",
        description="A company template with no rules attached.",
        prompt_templates={f"{name}.research": "Gather {intent}"},
        capability_permissions=(
            CapabilityPermission(
                capability=CapabilityType.RESEARCH,
                tool_scope=frozenset({"web_search"}),
                max_invocation_budget_usd=Decimal("0.20"),
            ),
        ),
        compliance_requirements=(),
    )


async def _kpi_rows(kernel: PlatformKernel) -> dict[str, Decimal]:
    """Return the KPI observations written so far, key to value."""
    async with kernel.services() as svc:
        rows = list((await svc.session.scalars(select(KpiValueRow))).all())
    return {row.key: Decimal(str(row.value)) for row in rows}


def _result(n: int, status: InvocationStatus, business_id: BusinessId) -> CapabilityResult:
    return CapabilityResult(
        invocation_id=InvocationId(f"inv_{n}"),
        business_id=business_id,
        capability=CapabilityType.RESEARCH,
        status=status,
        output="a figure and its source",
    )


async def _measure(
    kernel: PlatformKernel,
    business_id: BusinessId,
    *,
    cycle_id: str,
    results: tuple[CapabilityResult, ...] = (),
) -> dict[str, str]:
    """Run the measurement activity as that company's Manager would."""
    activities = ManagerActivities(kernel)
    recorded = await as_business(
        business_id,
        activities.record_cycle_kpis,
        CycleKpiRequest(business_id=business_id, cycle_id=cycle_id, results=results),
    )
    assert isinstance(recorded, dict)
    return recorded


# ── 1. a completed cycle measures itself ───────────────────────────────────


async def test_a_completed_cycle_writes_kpi_values_for_finance(kernel: PlatformKernel) -> None:
    """D-027.1: the row `kpi_values` has never held (M7-F21).

    Two results that succeeded and one that did not finish, so the count is a
    real count rather than "however many were dispatched".
    """
    contract = await _company(kernel, FINANCE)
    biz = contract.business_id

    recorded = await _measure(
        kernel,
        biz,
        cycle_id="cyc_measured",
        results=(
            _result(1, InvocationStatus.SUCCEEDED, biz),
            _result(2, InvocationStatus.SUCCEEDED, biz),
            _result(3, InvocationStatus.DEAD_LETTERED, biz),
        ),
    )

    assert recorded["reports_delivered"] == "2"
    assert recorded["metrics_tracked"] == str(len(contract.kpi_targets))
    rows = await _kpi_rows(kernel)
    assert rows["reports_delivered"] == Decimal("2")
    assert rows["metrics_tracked"] == Decimal("3")


async def test_results_belonging_to_another_company_are_not_counted(
    kernel: PlatformKernel,
) -> None:
    """D-002 at the measurement boundary.

    The results arrive in a payload, and a payload's account of whose work it
    was is the malformed-request case §10 says must not be load-bearing — a
    mis-assembled cycle would otherwise inflate one company's numbers with
    another's output.
    """
    biz = (await _company(kernel, FINANCE)).business_id
    other = BusinessId("biz_" + "0f0f0f0f0f0f0f0f" * 2)

    recorded = await _measure(
        kernel,
        biz,
        cycle_id="cyc_mixed",
        results=(
            _result(1, InvocationStatus.SUCCEEDED, biz),
            _result(2, InvocationStatus.SUCCEEDED, other),
        ),
    )
    assert recorded["reports_delivered"] == "1"


async def test_freshness_is_read_from_the_audit_row_a_real_dispatch_wrote(
    kernel: PlatformKernel,
) -> None:
    """D-027.2: an observation comes from something the platform recorded.

    The invocation goes through a real `CapabilityPool`, so the completion this
    reads is the one the pool actually wrote, under the event name it chose.
    Reading a hand-written row instead would leave that name free to drift and
    the metric free to go quietly empty.
    """
    contract = await _company(kernel, FINANCE)
    biz = contract.business_id

    async with kernel.services() as svc:
        pool = CapabilityPool(
            session=svc.session,
            registry=svc.registry,
            ledger=kernel.build_ledger(svc),
            breaker=kernel.build_breaker(svc),
            executor=CapabilityExecutor(
                _StubProvider("a figure and its source"),  # type: ignore[arg-type]
                InMemoryTemplates({"finance_tracking.research": "Gather {intent}"}),
            ),
            audit=svc.audit,
        )
        result = await pool.dispatch(
            identity=RuntimeIdentity.for_testing(biz),
            request=ScopedRequest(
                invocation_id=InvocationId("inv_live"),
                declared_business_id=biz,
                capability=CapabilityType.RESEARCH,
                prompt_ref="finance_tracking.research",
                prompt_inputs={"intent": "the configured metrics"},
                tool_scope=frozenset({"web_search"}),
                budget_allocation_usd=Decimal("0.20"),
                cycle_id="cyc_live",
            ),
        )
        assert result.status is InvocationStatus.SUCCEEDED
        names = [row.event_type for row in await svc.audit.for_business(biz)]
    assert CAPABILITY_SUCCEEDED_EVENT in names, "the pool no longer records what this reads"

    recorded = await _measure(kernel, biz, cycle_id="cyc_live", results=(result,))
    assert Decimal(recorded["data_freshness_hours"]) < Decimal("0.1"), (
        "work that just finished cannot be hours stale"
    )
    assert recorded["reports_delivered"] == "1"


async def test_freshness_is_unmeasured_rather_than_zero_before_any_work(
    kernel: PlatformKernel,
) -> None:
    """No fact, no observation (D-027.2).

    A company that has never completed anything has no completion to measure
    from. Writing zero would say its data is perfectly fresh, which is the
    opposite of true and a number nobody observed.
    """
    biz = (await _company(kernel, FINANCE)).business_id
    recorded = await _measure(kernel, biz, cycle_id="cyc_first")

    assert "data_freshness_hours" not in recorded
    assert "data_freshness_hours" not in await _kpi_rows(kernel)
    assert recorded["reports_delivered"] == "0", "a cycle that delivered nothing still says so"


async def test_a_stale_company_reports_the_hours_since_it_last_finished(
    kernel: PlatformKernel,
) -> None:
    """The metric's whole purpose: staleness that grows across failed cycles.

    Measured from the audit log rather than from the current cycle, so a cycle
    in which everything failed reports how old the data now is instead of the
    near-zero a within-cycle reading would give by construction.
    """
    biz = (await _company(kernel, FINANCE)).business_id
    async with kernel.services() as svc:
        svc.session.add(
            AuditLogRow(
                event_type=CAPABILITY_SUCCEEDED_EVENT,
                actor=biz,
                business_id=biz,
                payload={"invocation_id": "inv_old"},
                recorded_at=datetime.now(UTC) - timedelta(hours=30),
            )
        )
        await svc.session.flush()

    recorded = await _measure(
        kernel,
        biz,
        cycle_id="cyc_stale",
        results=(_result(1, InvocationStatus.DEAD_LETTERED, biz),),
    )
    assert Decimal("29.9") < Decimal(recorded["data_freshness_hours"]) < Decimal("30.1")
    assert recorded["reports_delivered"] == "0"


# ── 2. the negative control: a type that declares nothing records nothing ──


async def test_a_type_without_mappings_records_no_observations(
    kernel: PlatformKernel,
) -> None:
    """D-027.3, and the control that makes the tests above mean something.

    Affiliate has KPI targets and no mappings, so it must write nothing at
    all — silence, not zeros. A company scored zero on a metric nobody defined
    reads as failing rather than as unmeasured, and Affiliate's mappings are
    D-027's recorded follow-up rather than this packet's silent scope.
    """
    assert AFFILIATE.default_kpi_targets, "the control is only meaningful with targets set"
    biz = (await _company(kernel, AFFILIATE, name="Test Affiliate Co")).business_id

    recorded = await _measure(
        kernel,
        biz,
        cycle_id="cyc_affiliate",
        results=(_result(1, InvocationStatus.SUCCEEDED, biz),),
    )
    assert recorded == {}
    assert await _kpi_rows(kernel) == {}


async def test_the_cycle_context_tells_the_workflow_which_types_measure(
    kernel: PlatformKernel,
) -> None:
    """The gate the workflow reads (D-027.3, spec §11).

    `measures_kpis` is how "this type declares no mappings" reaches workflow
    code without a Registry read there, and it is what keeps a captured history
    replayable when a new activity joins the cycle path. Asserted for both
    shipped types through the real activity, so the flag tracks the definitions
    rather than a constant.
    """
    activities = ManagerActivities(kernel)
    affiliate = (await _company(kernel, AFFILIATE, name="Test Affiliate Co")).business_id
    finance = (await _company(kernel, FINANCE)).business_id

    quiet = await as_business(affiliate, activities.load_cycle_context, str(affiliate))
    measured = await as_business(finance, activities.load_cycle_context, str(finance))

    assert quiet["measures_kpis"] is False
    assert measured["measures_kpis"] is True


# ── 3. attainment, in both directions ──────────────────────────────────────


async def test_attainment_is_zero_until_something_is_measured(
    kernel: PlatformKernel,
) -> None:
    """M7-F21 stated as arithmetic: targets with no observations score zero.

    This is what every company in the platform's history has scored, and the
    reason the goals component of the health card has never moved.
    """
    contract = await _company(kernel, FINANCE)
    async with kernel.services() as svc:
        assert await KpiEngine(svc.session).attainment(contract) == 0


async def test_attainment_moves_once_the_cycle_measures(kernel: PlatformKernel) -> None:
    """The other direction: observations meeting targets produce attainment.

    Checked against hand-computed ratios rather than "> 0", so a future change
    to a mapping or to the averaging has to be looked at rather than absorbed.
    """
    contract = await _company(kernel, FINANCE)
    biz = contract.business_id
    await _measure(
        kernel,
        biz,
        cycle_id="cyc_one",
        results=tuple(_result(n, InvocationStatus.SUCCEEDED, biz) for n in range(4)),
    )
    async with kernel.services() as svc:
        attainment = await KpiEngine(svc.session).attainment(contract)

    # reports_delivered 4/4 -> 1.0, metrics_tracked 3/5 -> 0.6, and freshness
    # unmeasured (this company has completed nothing through the pool), so it
    # is left out of the average rather than counted as a miss.
    assert attainment == int((Decimal("1.0") + Decimal("0.6")) / 2 * 100)


async def test_an_observation_that_misses_its_target_scores_below_it(
    kernel: PlatformKernel,
) -> None:
    """Negative control on attainment: it must go down as well as up."""
    contract = await _company(kernel, FINANCE)
    biz = contract.business_id
    await _measure(
        kernel,
        biz,
        cycle_id="cyc_thin",
        results=(_result(1, InvocationStatus.SUCCEEDED, biz),),
    )
    async with kernel.services() as svc:
        attainment = await KpiEngine(svc.session).attainment(contract)
    # reports_delivered 1/4 -> 0.25, metrics_tracked 3/5 -> 0.6.
    assert attainment == int((Decimal("0.25") + Decimal("0.6")) / 2 * 100)


async def test_freshness_attainment_reads_a_good_reading_as_a_near_full_score(
    kernel: PlatformKernel,
) -> None:
    """M7-F30, fixed: attainment now learns direction.

    `data_freshness_hours` is lower-is-better and declares
    `direction=KpiDirection.BELOW` on Finance's target (`jarvis/businesses/
    finance.py`, version 1.0.2). `KpiEngine.attainment` now computes
    `target / actual` (capped at 1) for a BELOW metric instead of `actual /
    target`, so data refreshed an hour ago against a 24-hour target reads as
    essentially full attainment rather than the 4% miss this test used to pin
    as a recorded defect. Combined with the other two targets, which are
    genuinely at target, every metric now scores 1.0.
    """
    contract = await _company(kernel, FINANCE)
    biz = contract.business_id
    async with kernel.services() as svc:
        engine = KpiEngine(svc.session)
        await engine.record(business_id=biz, key="data_freshness_hours", value=Decimal("1"))
        await engine.record(business_id=biz, key="reports_delivered", value=Decimal("4"))
        await engine.record(business_id=biz, key="metrics_tracked", value=Decimal("5"))
        attainment = await engine.attainment(contract)
    # freshness: min(24/1, 1) -> 1.0; reports_delivered 4/4 -> 1.0;
    # metrics_tracked 5/5 -> 1.0.
    assert attainment == 100


# ── 4. the planning prompt carries the owner's rules verbatim ──────────────


async def test_the_planning_prompt_carries_the_stored_compliance_rules(
    kernel: PlatformKernel,
) -> None:
    """D-027.5, closing M7-F22: the rules were stored and read by nothing.

    Asserted rule by rule against `contract.compliance_requirements` — the
    stored values — rather than against a copy of the text in this file. A test
    written the other way would pass while the platform sent the model a
    paraphrase, which is the failure D-011 exists to prevent one layer up.
    """
    contract = await _company(kernel, FINANCE)
    assert contract.compliance_requirements, "the owner-approved rules must be stored"

    provider = _StubProvider(json.dumps({"rationale": "Check the metrics.", "items": []}))
    activities = ManagerActivities(_PromptCapturingKernel(kernel, provider))  # type: ignore[arg-type]
    await as_business(
        contract.business_id,
        activities.plan_cycle,
        PlanRequest(business_id=contract.business_id),
    )

    prompt = provider.prompts[-1]
    for rule in contract.compliance_requirements:
        assert rule in prompt, f"the planner was never told: {rule}"


async def test_a_type_with_no_rules_adds_no_empty_section(kernel: PlatformKernel) -> None:
    """Negative control: the section appears because there is something in it."""
    contract = await _company(kernel, _ruleless(), name="Test Ruleless Co")
    assert contract.compliance_requirements == ()

    provider = _StubProvider(json.dumps({"rationale": "x", "items": []}))
    activities = ManagerActivities(_PromptCapturingKernel(kernel, provider))  # type: ignore[arg-type]
    await as_business(
        contract.business_id,
        activities.plan_cycle,
        PlanRequest(business_id=contract.business_id),
    )
    assert "Rules it must follow" not in provider.prompts[-1]


# ── the mappings themselves ────────────────────────────────────────────────


def test_every_finance_mapping_names_a_target_it_can_be_compared_against() -> None:
    """A mapping whose key matches no target records a trend with no goal.

    Legal, and not what this type means: each of Finance's three targets is
    mapped, so attainment has an observation for every goal the owner set.
    """
    targets = {target.key for target in FINANCE.default_kpi_targets}
    mapped = {mapping.key for mapping in FINANCE.kpi_mappings}
    assert mapped == targets


def test_every_finance_mapping_names_a_source_the_platform_implements() -> None:
    """A definition ahead of its runtime writes nothing and logs why; this keeps
    the shipped type from being in that state."""
    for mapping in FINANCE.kpi_mappings:
        assert mapping.source in set(KpiSource)
