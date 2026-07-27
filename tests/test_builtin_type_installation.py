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

M8-1b moved `BUILTIN_TYPES` to `jarvis.businesses.catalog` and made it an
*injected* sequence (design Part 2.1-2.2): `PlatformKernel(builtin_types=...)`
is now the way a test swaps the installed set, replacing the previous
monkeypatch of the container module global — `ensure_builtin_types` reads
`self._builtin_types`, captured once at construction, so a later monkeypatch of
the module attribute would no longer reach it.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.catalog import BUILTIN_TYPES
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
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
async def engine() -> Any:
    """Yield a fresh in-memory database engine.

    `StaticPool` because `ensure_builtin_types` opens its own session through
    the Kernel's factory: without it every session gets its own empty
    `:memory:` database and the installed rows are invisible to the next read.
    Exposed on its own (rather than baked into the `kernel` fixture) so a test
    can build a *second* Kernel over the same database with a different
    injected `builtin_types` sequence (design Part 2.2).
    """
    built = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with built.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield built
    finally:
        await built.dispose()


def _kernel(engine: Any, *, builtin_types: Any = None) -> PlatformKernel:
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    return PlatformKernel(  # type: ignore[arg-type]
        settings, engine=engine, provider=_NoProvider(), builtin_types=builtin_types
    )


@pytest_asyncio.fixture
async def kernel(engine: Any) -> Any:
    """Yield a Kernel over `engine`, installing the default catalog."""
    yield _kernel(engine)


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
    kernel: PlatformKernel, engine: Any
) -> None:
    """The version gate is what makes the tuple safe to iterate at every
    startup: it upgrades what changed and leaves the rest alone.

    The bumped sequence is injected via `PlatformKernel(builtin_types=...)`
    (design Part 2.2) rather than monkeypatched onto the container module —
    `ensure_builtin_types` reads `self._builtin_types`, captured once at
    construction, so a second Kernel over the same database is how a test
    swaps it.
    """
    await kernel.ensure_builtin_types()

    bumped = BusinessTypeDefinition.model_validate(
        FINANCE.model_dump(mode="json") | {"version": "1.1.0"}
    )
    upgraded = _kernel(engine, builtin_types=(AFFILIATE, bumped))
    await upgraded.ensure_builtin_types()

    installed = await _installed(upgraded)
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


async def _audit_payloads(kernel: PlatformKernel, event_type: str) -> list[dict[str, Any]]:
    async with kernel.services() as svc:
        rows = await svc.session.scalars(
            select(AuditLogRow).where(AuditLogRow.event_type == event_type)
        )
        return [row.payload for row in rows.all()]


async def test_a_poisoned_type_is_contained_by_jarviserror_not_registryerror(
    engine: Any,
) -> None:
    """M8-F1: `install()`'s own validation raises `ConfigurationError`, a
    `JarvisError` sibling of `RegistryError` rather than a subclass — the
    exact real-world defect a built-in can have (a permitted capability with
    no prompt template). The old `except RegistryError` let this abort every
    install after it in the tuple; `except JarvisError` contains it.
    """
    poisoned_templates = dict(AFFILIATE.prompt_templates)
    del poisoned_templates["affiliate.operations"]
    poisoned = BusinessTypeDefinition.model_validate(
        AFFILIATE.model_dump(mode="json") | {"prompt_templates": poisoned_templates}
    )
    poisoned_kernel = _kernel(engine, builtin_types=(poisoned, FINANCE))

    report = await poisoned_kernel.ensure_builtin_types()

    installed = await _installed(poisoned_kernel)
    assert installed == {FINANCE.name: FINANCE.version}
    assert report.installed == (FINANCE.name,)
    assert report.skipped == (AFFILIATE.name,)


async def test_a_poisoned_type_writes_an_audited_skip_with_no_exception_text(
    engine: Any,
) -> None:
    """M8-F2: a skip must be audited, not just logged, and the record is
    operator-safe — the type name and failure class, never
    `technical_detail` (engineer-facing, spec §12.5)."""
    poisoned_templates = dict(AFFILIATE.prompt_templates)
    del poisoned_templates["affiliate.operations"]
    poisoned = BusinessTypeDefinition.model_validate(
        AFFILIATE.model_dump(mode="json") | {"prompt_templates": poisoned_templates}
    )
    poisoned_kernel = _kernel(engine, builtin_types=(poisoned, FINANCE))

    await poisoned_kernel.ensure_builtin_types()

    skips = await _audit_payloads(poisoned_kernel, "business_type.install_skipped")
    assert skips == [{"name": AFFILIATE.name, "failure_class": "ConfigurationError"}]
    assert all("template" not in str(v).lower() for v in skips[0].values())


async def test_a_clean_type_at_an_unchanged_version_stays_silent(
    kernel: PlatformKernel,
) -> None:
    """Design Part 2.5, negative control: a definition that has not changed
    since it was installed must never be flagged as drifted."""
    await kernel.ensure_builtin_types()
    await kernel.ensure_builtin_types()

    assert await _audit_payloads(kernel, "business_type.definition_drifted") == []


async def test_a_definition_edited_in_place_is_flagged_not_reinstalled(
    kernel: PlatformKernel, engine: Any
) -> None:
    """Design Part 2.5 / M8-F3: same-version drift is detected, never
    auto-installed. M6-F22's exact scenario — a definition edited in the
    source file without a version bump — must not silently vanish, and the
    stored row must not change underneath the (unbumped) version gate."""
    await kernel.ensure_builtin_types()

    edited = BusinessTypeDefinition.model_validate(
        FINANCE.model_dump(mode="json") | {"description": "edited without a version bump"}
    )
    drifted_kernel = _kernel(engine, builtin_types=(AFFILIATE, edited))
    report = await drifted_kernel.ensure_builtin_types()

    # Detection only: nothing installed or skipped-as-a-failure this sweep,
    # and the stored definition is untouched.
    assert report.installed == ()
    assert report.skipped == ()
    async with drifted_kernel.services() as svc:
        stored = await svc.registry.installed_types()
    finance_row = next(row for row in stored if row.name == FINANCE.name)
    assert (finance_row.plugin_metadata or {})["definition"]["description"] == FINANCE.description

    drift = await _audit_payloads(drifted_kernel, "business_type.definition_drifted")
    assert drift == [{"name": FINANCE.name, "version": FINANCE.version}]
