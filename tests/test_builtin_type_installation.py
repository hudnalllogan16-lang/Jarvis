"""Startup installation of every built-in business type (M7-F1, packet M7-3).

M7-1 found that `ensure_builtin_types` named `affiliate` and only `affiliate`:
the Finance Tracking type was complete, passed its own D-014 gate, and could
still never reach a live registry, because the one place that installs types at
startup did not mention it. Nothing failed — the type was simply absent, which
is the failure mode a test has to catch because no error ever surfaces it.

These assert the *caller's* version gate, which is where the gate deliberately
lives (M6-F22, M7-F4: `install()` itself refuses a duplicate version rather
than absorbing it). Fresh database installs everything; a version bump
reinstalls; the same version is skipped without raising.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.kernel import container as container_module
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import BUILTIN_TYPES, PlatformKernel
from jarvis.kernel.errors import RegistryError
from jarvis.persistence.models import AuditLogRow, Base


class _NoProvider:
    """Installation calls no model; a provider that would prove it."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("installing a business type calls no model")

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def kernel() -> Any:
    """Yield a Kernel over a fresh in-memory database.

    `StaticPool` because `ensure_builtin_types` opens its own session through
    the Kernel's factory: without it every session gets its own empty
    `:memory:` database and the installed rows are invisible to the next read.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    built = PlatformKernel(settings, engine=engine, provider=_NoProvider())  # type: ignore[arg-type]
    try:
        yield built
    finally:
        await engine.dispose()


async def _installed(kernel: PlatformKernel) -> dict[str, str]:
    async with kernel.services() as svc:
        return {t.name: t.version for t in await svc.registry.installed_types()}


async def _install_records(kernel: PlatformKernel) -> int:
    """Return how many `business_type.installed` entries the audit log holds."""
    async with kernel.services() as svc:
        rows = await svc.session.scalars(
            select(AuditLogRow).where(AuditLogRow.event_type == "business_type.installed")
        )
        return len(rows.all())


def test_every_builtin_type_is_listed_once() -> None:
    """The tuple is the whole registration surface, so a name appearing twice
    would make the second install a guaranteed duplicate refusal."""
    names = [d.name for d in BUILTIN_TYPES]
    assert names == sorted(set(names), key=names.index)
    assert {d.name for d in BUILTIN_TYPES} == {AFFILIATE.name, FINANCE.name}


async def test_both_builtin_types_install_on_a_fresh_database(
    kernel: PlatformKernel,
) -> None:
    """M7-F1 exactly: before this fix a fresh database got `affiliate` and
    nothing else, and no error said so."""
    await kernel.ensure_builtin_types()
    installed = await _installed(kernel)
    assert installed == {AFFILIATE.name: AFFILIATE.version, FINANCE.name: FINANCE.version}


async def test_a_second_startup_installs_nothing_and_does_not_raise(
    kernel: PlatformKernel,
) -> None:
    """Same version is skipped by the caller's gate (M6-F22, M7-F4).

    Asserted on the audit trail rather than on the type rows: an upgrade path
    that overwrote a row with identical values would leave the rows looking
    right while installing on every restart.
    """
    await kernel.ensure_builtin_types()
    before = await _install_records(kernel)

    await kernel.ensure_builtin_types()
    after = await _install_records(kernel)

    assert before == after == 2


async def test_a_version_bump_reinstalls_that_type_only(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version gate is what makes the tuple safe to iterate at every
    startup: it upgrades what changed and leaves the rest alone."""
    await kernel.ensure_builtin_types()

    bumped = BusinessTypeDefinition.model_validate(
        FINANCE.model_dump(mode="json") | {"version": "1.1.0"}
    )
    monkeypatch.setattr(container_module, "BUILTIN_TYPES", (AFFILIATE, bumped))
    await kernel.ensure_builtin_types()

    installed = await _installed(kernel)
    assert installed[FINANCE.name] == "1.1.0"
    assert installed[AFFILIATE.name] == AFFILIATE.version


async def test_one_refused_builtin_does_not_strand_the_others(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first run where one definition is refused must still leave the
    operator with the templates that are fine — the alternative is an empty
    "New company" dialog and no way to tell which type was the problem."""
    from jarvis.businesses.provisioning import ProvisioningService

    real_install = ProvisioningService.install

    async def _install(self: ProvisioningService, definition: BusinessTypeDefinition) -> None:
        if definition.name == AFFILIATE.name:
            raise RegistryError("refused for this test")
        await real_install(self, definition)

    monkeypatch.setattr(ProvisioningService, "install", _install)
    await kernel.ensure_builtin_types()

    installed = await _installed(kernel)
    assert installed == {FINANCE.name: FINANCE.version}
