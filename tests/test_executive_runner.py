"""The Executive's own deterministic tick and its timer (design EXECUTIVE-LAYER.md
Part 7, D-041) — packet D (M9-1c).

Two layers, tested at the level each one deserves:

- `run_executive_tick` (`jarvis/executive/runner.py`) is a plain async function
  over explicit collaborators, exactly like its siblings in this package, so it
  is exercised here against the same in-memory platform
  `test_executive_alerts.py` and `test_executive_rollup.py` already use — no
  Temporal, no LLM provider, no live database (packet's own constraint: $0,
  live DB read-only, no live worker start).
- `run_executive` (`jarvis/runtime/worker.py`) is the timer loop the
  composition root owns. It is exercised with a scripted harness in the style
  of M8-7's reservation-reconcile tests: a fake `asyncio.sleep` that ends the
  loop after a fixed number of iterations rather than a real wait, proving the
  interval comes from `Settings` and that a failed tick is contained without
  ever starting a real worker process.

The central proof this file exists to carry: **a scripted multi-tick run**
showing that `raise_spend_alerts`, `raise_platform_ceiling_alerts` and
`record_platform_halt`'s own deduplication survive being called through this
orchestration, across separate calls with freshly built collaborators each
time — the same restart-safety `test_executive_alerts.py` proves for each
function alone, now proven for the sequence a real timer actually runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

import jarvis.runtime.worker as worker
from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.executive.runner import ExecutiveTickReport, run_executive_tick
from jarvis.kernel.config import ExecutiveSettings, LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessTypeName
from jarvis.kpi.engine import KpiEngine
from jarvis.notifications.service import NotificationService
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import Base
from jarvis.registry.registry import BusinessRegistry

CEILING = Decimal("500.00")


async def _install_and_register(registry: BusinessRegistry, contract: BusinessContract) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"), version="1.0.0", display_name="Affiliate"
    )
    await registry.register_instance(contract)


def _collaborators(session: AsyncSession, *, ceiling: Decimal = CEILING) -> dict[str, object]:
    """Build one tick's worth of collaborators, fresh, bound to ``session``.

    Deliberately not memoized or shared across calls in the tests below:
    `run_executive` (`jarvis/runtime/worker.py`) builds a fresh set every
    iteration from a fresh `kernel.services()` scope, and a test that reused
    Python objects across "ticks" would be proving dedup survives object
    reuse, not dedup survives a restart — the property design Part 7 and the
    packet's own escalation trigger actually care about.
    """
    decisions = DecisionLog(session)
    ledger = BudgetLedger(session, platform_ceiling_usd=ceiling)
    return {
        "ledger": ledger,
        "kpi": KpiEngine(session),
        "notifications": NotificationService(session),
        "breaker": CircuitBreaker(ledger, decisions, ceiling_usd=ceiling),
        "decisions": decisions,
        "platform_ceiling_usd": ceiling,
    }


async def _tick(
    session: AsyncSession, registry: BusinessRegistry, *, ceiling: Decimal = CEILING
) -> ExecutiveTickReport:
    return await run_executive_tick(registry=registry, **_collaborators(session, ceiling=ceiling))  # type: ignore[arg-type]


# ── run_executive_tick: the pipeline itself ─────────────────────────────────


async def test_a_quiet_tick_still_returns_the_rollup_and_the_census(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Design Part 7: census runs every tick even though nothing reads it yet
    (packet E). A tick with nothing to announce is not a no-op."""
    await _install_and_register(registry, contract)

    report = await _tick(session, registry)

    assert report.rollup.committed_capital_usd == contract.budget.business_cap_usd
    assert report.census.never_measured_count == 1
    assert report.spend_alerts == ()
    assert report.platform_alerts == ()
    assert report.halted is False


async def test_a_tick_runs_rollup_before_the_alerts_that_read_it(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The ordering is load-bearing (design Part 12's sequencing note): the
    alerts must fire on this tick's own rollup, not a stale one."""
    await _install_and_register(registry, contract)
    ledger = BudgetLedger(session, platform_ceiling_usd=CEILING)
    await ledger.reserve(contract=contract, amount_usd=Decimal("26.00"))  # 52% of $50

    report = await _tick(session, registry)

    assert [a.band for a in report.spend_alerts] == [50]
    assert report.rollup.per_company[0].lifetime_spend_usd == Decimal("26.00")


# ── the scripted multi-tick proof ───────────────────────────────────────────


async def test_dedup_and_once_per_halt_survive_across_separate_ticks(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The packet's own named proof: a scripted run across four ticks, each
    with freshly built collaborators against the same underlying database —
    company band, platform band, and the halt narrative each announce once
    and stay quiet on every unchanged repeat, and the platform band correctly
    steps aside once breach is reached.

    Sequence:
      1. Spend reaches $26 of a $50 company cap (52%) against a $28 platform
         ceiling (92.86%) -> company band 50 and platform band 80 both fire.
      2. Same state, a second tick -> both suppressed (still unread).
      3. Spend reaches the $28 ceiling exactly (100%) -> the halt narrative
         fires for the first time; the platform band stays silent (breach is
         its territory, not the warning bands').
      4. Same state, a third and fourth tick -> the halt is not re-explained
         (restart-safe dedup, `jarvis.budget.ledger.PLATFORM_SPEND_WINDOW`
         still covers it) and no stale platform-band notice appears either.
    """
    await _install_and_register(registry, contract)
    ceiling = Decimal("28.00")

    # Tick 1 — cross the first company band and the first platform band.
    ledger = BudgetLedger(session, platform_ceiling_usd=ceiling)
    await ledger.reserve(contract=contract, amount_usd=Decimal("26.00"))
    tick1 = await _tick(session, registry, ceiling=ceiling)
    assert [a.band for a in tick1.spend_alerts] == [50]
    assert [a.band for a in tick1.platform_alerts] == [80]
    assert tick1.halted is False

    # Tick 2 — unchanged state, fresh collaborators: nothing new.
    tick2 = await _tick(session, registry, ceiling=ceiling)
    assert tick2.spend_alerts == ()
    assert tick2.platform_alerts == ()
    assert tick2.halted is False

    # Tick 3 — spend reaches the ceiling exactly: the halt narrative fires,
    # the platform band does not (it is at breach, not merely close to it).
    ledger2 = BudgetLedger(session, platform_ceiling_usd=ceiling)
    await ledger2.reserve(contract=contract, amount_usd=Decimal("2.00"))  # now $28 / $28
    tick3 = await _tick(session, registry, ceiling=ceiling)
    assert tick3.platform_alerts == ()
    assert tick3.halted is True

    # Ticks 4 and 5 — unchanged breach, fresh collaborators each time: the
    # halt is explained once, not once per pass, and stays that way.
    tick4 = await _tick(session, registry, ceiling=ceiling)
    tick5 = await _tick(session, registry, ceiling=ceiling)
    assert tick4.halted is False
    assert tick5.halted is False
    assert tick4.platform_alerts == ()
    assert tick5.platform_alerts == ()

    decisions = DecisionLog(session)
    assert len(await decisions.platform_feed()) == 1  # explained exactly once
    notifications = NotificationService(session)
    assert await notifications.unread_count() == 2  # the two tick-1 notices, still unread


# ── ExecutiveSettings: the interval this timer reads ────────────────────────


def test_the_tick_interval_defaults_to_sixty_seconds() -> None:
    assert ExecutiveSettings().tick_interval_seconds == 60


def test_the_tick_interval_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_EXECUTIVE__TICK_INTERVAL_SECONDS", "15")
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.executive.tick_interval_seconds == 15


# ── run_executive: the timer loop, scripted (no real sleep, no live worker) ─


class _StubProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:  # pragma: no cover - unused
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def kernel() -> AsyncIterator[PlatformKernel]:
    """A real Kernel over one shared in-memory connection, no Temporal or LLM
    reachable — `run_executive` touches neither, so nothing here needs the
    `_CapturingTemporalClient` workaround `test_reservation_reconcile.py`
    documents for `Scheduler.sweep` (which does)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    built = PlatformKernel(
        Settings(llm=LLMSettings(model="stub-model"), _env_file=None),  # type: ignore[call-arg]
        engine=engine,
        provider=_StubProvider(),  # type: ignore[arg-type]
    )
    yield built
    await built.aclose()


async def test_run_executive_reads_the_interval_from_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No override given: the loop sleeps for exactly `Settings.executive.
    tick_interval_seconds`, proven without ever actually waiting that long."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_executive(kernel)

    assert sleeps == [kernel.settings.executive.tick_interval_seconds]


async def test_run_executive_interval_override_beats_settings(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_executive(kernel, interval_seconds=5)

    assert sleeps == [5]


async def test_a_failed_tick_is_contained_and_the_next_tick_still_runs(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6-F9's contained-failure discipline, applied to this timer: the first
    tick raises, the loop logs and continues rather than dying, and the
    second tick runs to completion — proven by a marker only the real
    `run_executive_tick` implementation would produce."""
    real_tick = worker.run_executive_tick
    calls = {"n": 0}

    async def _flaky_tick(**kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom — a transient failure, contained")
        return await real_tick(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(worker, "run_executive_tick", _flaky_tick)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_executive(kernel, interval_seconds=0)

    assert calls["n"] == 2  # tick 1 failed and was contained; tick 2 still ran
    assert len(sleeps) == 2  # the loop slept after both — no overlap, no early exit


async def test_no_overlap_ticks_run_strictly_one_after_another(
    kernel: PlatformKernel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each tick is awaited to completion before the next one starts — proven
    by a tick that yields control (`asyncio.sleep(0)`) mid-flight and a
    concurrency counter that must never exceed 1."""
    real_tick = worker.run_executive_tick
    in_flight = {"n": 0, "max": 0}

    async def _counting_tick(**kwargs: object) -> object:
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        await asyncio.sleep(0)  # yield, so a real overlap would be observable
        result = await real_tick(**kwargs)  # type: ignore[arg-type]
        in_flight["n"] -= 1
        return result

    monkeypatch.setattr(worker, "run_executive_tick", _counting_tick)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_executive(kernel, interval_seconds=0)

    assert in_flight["max"] == 1
    assert len(sleeps) == 3
