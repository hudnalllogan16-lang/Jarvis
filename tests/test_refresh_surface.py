"""The operator API surface for a company's pending template update: the
Details-route seam, its consent routes, and `not_ready_count` wired to a real
caller (M8-F61) — originally packet M8-9.

**M8-11 update (M8-F115 closes).** `_pending_update`/`apply_pending_update`/
`dismiss_pending_update` in `jarvis/api/app.py` now call the real
`plan_refresh`/`apply_refresh`/`decline_refresh` (design PLUGIN-FRAMEWORK.md
Part 4.4, packet M8-8), through `kernel.build_refresh` — the M6-F20 pattern:
`jarvis/businesses` is milestone 5 and this route lives in milestone 3, so the
Kernel composition root builds the session-scoped service and this module
never imports the businesses package directly. The tests below through
"`── not_ready_count`" that pin a 409/404/None outcome still describe a real
outcome, not a stub: every fixture in that group is a freshly-created company,
genuinely current against the type it was just created from, so a real
`plan_refresh` legitimately answers "nothing pending" for it — the same
answer the old honest stub gave, for a different and now real reason. The
"pending update, for real" group below is what exercises the mechanism with
something to find.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE
from jarvis.domain.contract import BudgetPolicy, BusinessContract, WakeConditions
from jarvis.events.types import CAPABILITY_RESULT
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessTypeName, new_business_id
from jarvis.persistence.models import Base


class _NoProvider:
    """No test here calls a model; this makes that an assertion."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("this surface never calls a model")

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]


async def _make_kernel(builtin_types: Any = None) -> PlatformKernel:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PlatformKernel(  # type: ignore[arg-type,call-arg]
        _settings(), engine=engine, provider=_NoProvider(), builtin_types=builtin_types
    )


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    built = await _make_kernel()
    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def api(kernel: PlatformKernel) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _create(kernel: PlatformKernel, definition: BusinessTypeDefinition, name: str) -> str:
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(definition)
        business_id = await provisioning.create_company(definition=definition, display_name=name)
        return str(business_id)


async def _stale_affiliate_company(kernel: PlatformKernel, name: str) -> str:
    """Install the real, current `AFFILIATE` (1.0.1), then register a company
    whose snapshot still carries the wake signal 1.0.1 removed as the M6-F10
    fix — the same "Trailhead Gear Reviews" shape `test_contract_refresh.py`
    uses, reconstructed here rather than imported because it is this file's
    own fixture for a company with a genuine, non-empty Band-B diff to offer.
    Registered directly (`register_instance`), not `create_company`, which
    would build a contract from the *current* definition and so never be
    stale by construction.
    """
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        business_id = new_business_id()
        await svc.registry.register_instance(
            BusinessContract(
                business_id=business_id,
                business_type=BusinessTypeName(AFFILIATE.name),
                display_name=name,
                budget=BudgetPolicy(
                    business_cap_usd=AFFILIATE.suggested_budget_usd,
                    wake_cycle_ceiling_usd=AFFILIATE.suggested_wake_ceiling_usd,
                ),
                wake_conditions=WakeConditions(
                    schedule_cron=AFFILIATE.schedule_cron,
                    event_triggers=frozenset({*AFFILIATE.event_triggers, CAPABILITY_RESULT}),
                ),
                capability_permissions=AFFILIATE.capability_permissions,
                autonomy_policies=AFFILIATE.autonomy_policies,
                kpi_targets=AFFILIATE.default_kpi_targets,
                compliance_requirements=AFFILIATE.compliance_requirements,
            )
        )
        return str(business_id)


# ── the pending-update seam: real plan_refresh, nothing to find ────────────


async def test_a_freshly_created_company_has_no_pending_update(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """A company created from the currently-installed type has an empty
    `plan_refresh` by construction (design Part 4.3's status quo) — the real
    mechanism's answer, not a stand-in for one."""
    business_id = await _create(kernel, AFFILIATE, "Weekend Reviews")
    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert "pending_update" in detail
    assert detail["pending_update"] is None
    # M9-3 item 6: genuinely current stays exactly as silent as it always
    # was — the new note exists for the OTHER silent case (below), not this
    # one.
    assert detail["pending_update_note"] is None


async def test_an_uncomputable_plan_gets_the_one_honest_line_not_silence(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """M9-3 surface backlog item 6: 'up-to-date vs uncomputable both silent'.

    `register_instance` itself refuses an uninstalled type, so the only way
    to reach `_pending_update`'s documented edge case — "a row installed
    before [the M8-F111] guard existed could still be in this state" — is a
    company that was legitimately registered against an installed type whose
    row is then gone by the time `plan_refresh` looks for it. Deleting the
    `BusinessTypeRow` after registration reproduces exactly that: the
    company is real and untouched, only its type's installed row is missing,
    which is what `_installed_definition` (`jarvis/businesses/refresh.py`)
    raises `BusinessTypeNotFoundError` for. Before this fix that produced the
    exact same `pending_update: null` a genuinely current company gets; now
    it also carries a note distinguishing the two.
    """
    business_id = await _create(kernel, AFFILIATE, "Orphaned Template Co")
    async with kernel.services() as svc:
        row = await svc.registry.installed_type(BusinessTypeName(AFFILIATE.name))
        assert row is not None
        await svc.session.delete(row)
        # `kernel.services()` commits on clean exit (see its own docstring) —
        # no explicit commit needed, and none of the other direct-registry
        # fixtures in this file take one either.

    detail = (await api.get(f"/api/companies/{business_id}")).json()

    assert detail["pending_update"] is None
    assert detail["pending_update_note"] == (
        "Jarvis couldn't check whether an update is ready for this company just now — "
        "it will try again on its own."
    )


async def test_pending_update_is_not_on_the_default_card(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """§12.5: drill-down loads only when the operator opens it — the card
    list must not carry it, the same rule `goals` already follows."""
    await _create(kernel, AFFILIATE, "Weekend Reviews")
    companies = (await api.get("/api/companies")).json()

    assert "pending_update" not in companies[0]


# ── consent routes: a current company genuinely has nothing to consent to ──


async def test_applying_a_pending_update_says_its_not_ready_yet(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """`plan_refresh` for a freshly-created company is genuinely empty, so the
    real apply route refuses it the same way the old stub always did — the
    409 is now `plan.is_empty`, not an unconditional refusal."""
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    res = await api.post(f"/api/companies/{business_id}/pending-update/apply")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert isinstance(detail, str) and detail
    assert "ready" in detail.lower()


async def test_dismissing_a_pending_update_says_its_not_ready_yet(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    business_id = await _create(kernel, FINANCE, "Portfolio Watch")
    res = await api.post(f"/api/companies/{business_id}/pending-update/dismiss")

    assert res.status_code == 409
    assert isinstance(res.json()["detail"], str)


async def test_applying_a_pending_update_for_an_unknown_company_is_404(
    api: httpx.AsyncClient,
) -> None:
    """Never a 409 for a company that doesn't exist — that would say "not
    ready yet" about something that was never there at all. `plan_refresh`
    raises `BusinessNotFoundError` for it, mapped to 404 ahead of the generic
    `JarvisError` -> 409 mapping."""
    res = await api.post("/api/companies/biz_nonexistent/pending-update/apply")
    assert res.status_code == 404


async def test_dismissing_a_pending_update_for_an_unknown_company_is_404(
    api: httpx.AsyncClient,
) -> None:
    res = await api.post("/api/companies/biz_nonexistent/pending-update/dismiss")
    assert res.status_code == 404


# ── pending update, for real: a genuine Band-B diff, end to end ────────────


async def test_a_stale_company_shows_a_real_pending_update_on_its_detail_route(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """M8-F115 closes: the Details route now carries a real, non-empty diff
    for a company whose snapshot predates the installed type — the exact
    Trailhead Gear Reviews shape design Part 5 and `test_contract_refresh.py`
    both use, reached this time through the live HTTP route."""
    business_id = await _stale_affiliate_company(kernel, "Trailhead Gear Reviews")

    detail = (await api.get(f"/api/companies/{business_id}")).json()

    update = detail["pending_update"]
    assert update is not None
    assert update["headline"] == "Trailhead Gear Reviews — an update is ready for this company."
    assert update["intro"] == (
        "The Affiliate publisher setup has changed since this company was created."
    )
    assert update["changes"] == [
        "It will stop starting a new round of work when its own work comes back."
    ]


async def test_applying_a_real_pending_update_writes_it_and_reports_updated(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """The write path, end to end through the HTTP route: apply, then confirm
    the company's own contract moved. `apply_refresh`'s own idempotency
    (D-024.3, `RefreshOutcome.ALREADY_APPLIED`) is exercised directly at the
    service level in `test_contract_refresh.py`; the route recomputes the
    plan fresh on every call rather than trusting a client-held plan_key
    (see `apply_pending_update`'s docstring), so a repeat click here lands on
    the same "nothing pending" 409 a company that was never stale gets — the
    honest outcome, since by then there genuinely is nothing left to apply.
    """
    business_id = await _stale_affiliate_company(kernel, "Trailhead Gear Reviews")

    first = await api.post(f"/api/companies/{business_id}/pending-update/apply")
    assert first.status_code == 200
    assert first.json() == {"status": "Updated."}

    detail = (await api.get(f"/api/companies/{business_id}")).json()
    assert detail["pending_update"] is None, "a company just brought current has nothing pending"

    second = await api.post(f"/api/companies/{business_id}/pending-update/apply")
    assert second.status_code == 409
    assert "ready" in second.json()["detail"].lower()


async def test_dismissing_a_real_pending_update_writes_nothing_and_still_offers_it(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    """Design 4.3: a decline is recorded but changes no contract, and M8-F102
    (decline persistence) stays deferred — nothing suppresses the offer, so
    the same real diff is still there on the next look. Honest, not a bug."""
    business_id = await _stale_affiliate_company(kernel, "Trailhead Gear Reviews")

    res = await api.post(f"/api/companies/{business_id}/pending-update/dismiss")
    assert res.status_code == 200
    assert res.json() == {"status": "Not now."}

    detail = (await api.get(f"/api/companies/{business_id}")).json()
    assert detail["pending_update"] is not None, "a decline must not apply anything"
    assert detail["pending_update"]["changes"] == [
        "It will stop starting a new round of work when its own work comes back."
    ]


# ── not_ready_count wired to a real caller (M8-F61) ─────────────────────────


async def test_install_builtin_reports_a_contained_failure_by_count() -> None:
    """M8-F61: `not_ready_count` had no UI consumer. `newco.js`'s
    `install-templates` action now reads it (see the M8-9 report); this pins
    the JSON shape that consumer depends on, at the HTTP boundary rather than
    only at the container level `test_builtin_type_installation.py` already
    covers.
    """
    poisoned_templates = dict(AFFILIATE.prompt_templates)
    del poisoned_templates["affiliate.operations"]
    poisoned = BusinessTypeDefinition.model_validate(
        AFFILIATE.model_dump(mode="json") | {"prompt_templates": poisoned_templates}
    )
    kernel = await _make_kernel(builtin_types=(poisoned, FINANCE))
    try:
        transport = httpx.ASGITransport(app=create_app(kernel))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api:
            res = await api.post("/api/company-templates/install-builtin")
            body = res.json()
            assert body["not_ready_count"] == 1
            assert body["status"] == "Some templates aren't ready."
            assert body["installed"] == [FINANCE.name]
    finally:
        await kernel.aclose()


async def test_install_builtin_reports_zero_when_everything_installs(
    kernel: PlatformKernel, api: httpx.AsyncClient
) -> None:
    res = await api.post("/api/company-templates/install-builtin")
    body = res.json()

    assert body["not_ready_count"] == 0
    assert body["status"] == "Templates ready."
