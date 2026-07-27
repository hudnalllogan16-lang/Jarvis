"""What a Business Manager is started with (M8-F46, D-005).

§2.1 lists "active KPI targets" as durable Manager state, and until M8-3 that is
what `ManagerState.kpi_targets` was: seeded from the contract by
`ManagerLifecycle.reconcile` when the Manager started, then carried across every
cycle and every `continue_as_new` — up to a hundred of them. That made it a
second copy of a contract value that could only ever drift from it, and M8-F7
named the drift: the moment a refresh path shipped, every operator-facing number
would move while the planner went on working to the old figures.

M8-3 gave the targets a per-cycle route: they ride the post-wake context
snapshot, read from the contract, which is the authority. The keepsake copy is
what this pins closed.

The field itself stays on `ManagerState`, and the workflow still reads it, for
one reason only: a history captured before M8-3 recorded a context that carries
no targets, and those executions must go on planning against what they actually
planned against (spec §11, D-033). Removing it is a workflow-versioning change
gated on M8-F48 — no pre-M8-3 execution remaining queryable — and is not this
packet's to make.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.domain.contract import CapabilityPermission, CapabilityType, KpiTarget
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.manager.lifecycle import ManagerLifecycle
from jarvis.manager.state import ManagerState
from jarvis.persistence.models import Base

DEFINITION = BusinessTypeDefinition(
    name="affiliate",
    version="1.0.1",
    display_name="Affiliate publisher",
    description="Writes review posts and asks you before publishing.",
    prompt_templates={"affiliate.research": "Research {intent}"},
    capability_permissions=(CapabilityPermission(capability=CapabilityType.RESEARCH),),
    default_kpi_targets=(
        KpiTarget(
            key="posts_published",
            operator_label="Posts published",
            target_value=Decimal("20"),
            unit="posts/month",
        ),
    ),
)


class _NoProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("starting a Manager calls no model")

    async def aclose(self) -> None:
        return None


class _CapturingClient:
    """A Temporal client that records what it was asked to start."""

    def __init__(self) -> None:
        self.started: list[ManagerState] = []

    async def start_workflow(self, name: str, state: ManagerState, **kwargs: Any) -> None:
        self.started.append(state)


@pytest_asyncio.fixture
async def kernel() -> Any:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    built = PlatformKernel(  # type: ignore[arg-type]
        settings, engine=engine, provider=_NoProvider(), builtin_types=(DEFINITION,)
    )
    try:
        yield built
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_manager_starts_with_no_keepsake_copy_of_its_targets(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8-F46: the contract's targets are no longer copied into durable state.

    The company below has a target set, so a seeding `reconcile` would put it in
    the start argument. It must not: the cycle reads targets per cycle from the
    contract, and a second copy in workflow state is what made the planner
    stale in the first place (M8-F7).
    """
    await kernel.ensure_builtin_types()
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.create_company(definition=DEFINITION, display_name="Summit Trail Gear")

    client = _CapturingClient()

    async def _client() -> Any:
        return client

    monkeypatch.setattr(kernel, "temporal_client", _client)
    started = await ManagerLifecycle(kernel).reconcile()

    assert started == 1
    assert len(client.started) == 1
    assert client.started[0].kpi_targets == ()


def test_the_field_survives_for_replay_and_defaults_to_empty() -> None:
    """Spec §11, D-033: a pre-M8-3 history planned against carried targets and
    must go on doing so. `ManagerState` still accepts the field and defaults it
    to empty, so nothing started since carries one."""
    assert "kpi_targets" in ManagerState.model_fields
    assert ManagerState(business_id="biz_1").kpi_targets == ()  # type: ignore[arg-type]
