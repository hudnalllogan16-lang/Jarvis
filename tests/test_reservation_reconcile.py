"""Orphaned budget reservations are found, released, and audited (D-034.3).

Spec §9, §11; D-003, D-022 point 3; resolves M6-F18.

D-022 made terminality the thing that resolves a hold, and refused a TTL on
purpose: D-001 guarantees every invocation terminates, so a timer would only be
guessing at something the platform already knows. That reasoning holds for every
invocation the platform *finishes*. It does not hold for one whose worker died
between `reserve` and `settle`, because the settle and the release both lived in
the process that stopped — and the reservation, which D-022 deliberately commits
in its own transaction so it can gate the work, survives the worker that took it.

A RESERVED row counts toward the cycle, the business, and the platform ceiling
(`_COUNTING_STATES`). An orphan therefore costs a company headroom permanently,
for spend that never happened, and nothing in the platform ever looked for one.

D-034.3's answer is a scheduler-owned sweep: terminality first, an age bound as
the backstop, and every release audited. The two ways this could go wrong are
both tested below and are opposites — releasing a hold that is still live
(which hands a running invocation's headroom to a concurrent one and reopens
M6-F12 from the other side), and never releasing anything at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.budget.ledger import RELEASED, RESERVED, SETTLED
from jarvis.businesses.affiliate import AFFILIATE
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates
from jarvis.capabilities.pool import CapabilityPool
from jarvis.capabilities.request import ScopedRequest
from jarvis.domain.contract import CapabilityType
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.kernel.runtime import RuntimeIdentity
from jarvis.llm.base import CompletionResponse, Usage
from jarvis.manager.workflow import ACTIVITY_TIMEOUT, DISPATCH_TIMEOUT
from jarvis.persistence.models import AuditLogRow, Base, BudgetLedgerRow, DeadLetterRow
from jarvis.scheduler.service import (
    MAX_RECONCILED_PER_SWEEP,
    ORPHANED_RESERVATION_AGE,
    Scheduler,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CYCLE = "cyc_orphan"
RECONCILED = "budget.reservation_reconciled"


class _StubProvider:
    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> CompletionResponse:
        return CompletionResponse(text="{}", usage=Usage(input_tokens=1, output_tokens=1))

    async def aclose(self) -> None:
        return None


class _CapturingTemporalClient:
    """A Temporal client that records `start_workflow` calls instead of
    making them (M8-13 leak fix).

    `Scheduler.sweep()` unconditionally calls `ManagerLifecycle.reconcile()`
    (this module calls `sweep()` at every call site below), and `reconcile()`
    calls `kernel.temporal_client()` for real unless told otherwise. This
    file's `kernel` fixture never overrode it, so every `sweep()` call here
    was opening a real connection to `localhost:7233` and issuing real
    `start_workflow`s against whatever `settings.temporal.namespace` resolved
    to — `"default"` in any environment with no lane env vars set, since
    `_env_file=None` disables reading the repo's `.env` file but pydantic-
    settings still reads the process environment, which is empty here.

    This is the leaking test path M8-F162's audit missed (it checked
    `test_manager_start_state.py`, `test_approval_roundtrip.py`, and others,
    but not this file): found live 2026-07-27 by diffing the `default`
    namespace's workflow count before/after a full `scripts/gates.sh` run —
    11 new `RUNNING` executions, one per `sweep()` call site here. None of
    this file's assertions depend on a real workflow having started, so the
    fix is the same monkeypatch every other Kernel-integration test in this
    suite already uses for the same reason
    (`tests/test_manager_start_state.py`'s `_CapturingClient`) — a pure
    test-file change, not a production code change.
    """

    def __init__(self) -> None:
        self.started: list[object] = []

    async def start_workflow(self, name: str, state: object, **kwargs: object) -> None:
        self.started.append(state)


@pytest_asyncio.fixture
async def kernel(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[PlatformKernel]:
    """A real Kernel over one shared in-memory connection.

    `_env_file=None`: the repository holds a real `.env`, and a test that read it
    would reach a live provider and a real database.
    """
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

    client = _CapturingTemporalClient()

    async def _fake_temporal_client() -> _CapturingTemporalClient:
        return client

    monkeypatch.setattr(built, "temporal_client", _fake_temporal_client)

    yield built
    await built.aclose()


@pytest_asyncio.fixture
async def company(kernel: PlatformKernel) -> BusinessId:
    async with kernel.services() as svc:
        provisioning = kernel.build_provisioning(svc)
        await provisioning.install(AFFILIATE)
        return await provisioning.create_company(
            definition=AFFILIATE, display_name="Summit Trail Gear"
        )


async def _hold(
    kernel: PlatformKernel,
    company: BusinessId,
    *,
    invocation_id: str | None = None,
    age: timedelta = timedelta(minutes=1),
    amount: Decimal = Decimal("0.50"),
    state: str = RESERVED,
) -> int:
    """Record one ledger row of a given age, and return its id.

    Written directly rather than through `reserve`, because what is under test
    is what happens to a row nobody came back for — and `recorded_at` is the
    fact the age bound reads, which a real reservation would set to now.
    """
    async with kernel.services() as svc:
        row = BudgetLedgerRow(
            business_id=company,
            invocation_id=invocation_id,
            cycle_id=CYCLE,
            amount_usd=amount,
            state=state,
            recorded_at=NOW - age,
        )
        svc.session.add(row)
        await svc.session.flush()
        return row.id


async def _dead_letter(kernel: PlatformKernel, company: BusinessId, invocation_id: str) -> None:
    """Record the invocation as having reached a terminal state (spec §9)."""
    async with kernel.services() as svc:
        svc.session.add(
            DeadLetterRow(
                invocation_id=invocation_id,
                business_id=company,
                capability="research",
                attempts=3,
                operator_summary="Summit Trail Gear couldn't finish a task.",
                technical_detail="the worker went away",
            )
        )


async def _states(kernel: PlatformKernel) -> list[str]:
    async with kernel.services() as svc:
        rows = (await svc.session.scalars(select(BudgetLedgerRow))).all()
        return [row.state for row in rows]


async def _audited(kernel: PlatformKernel) -> list[AuditLogRow]:
    async with kernel.services() as svc:
        return list(
            (
                await svc.session.scalars(
                    select(AuditLogRow).where(AuditLogRow.event_type == RECONCILED)
                )
            ).all()
        )


# ── terminality first ──────────────────────────────────────────────────────


async def test_a_hold_whose_invocation_is_dead_lettered_is_released(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-034.3's first ground, and the one D-022 already believed was covered.

    `CapabilityPool._execute_with_retry` releases the hold *before* it writes the
    dead-letter row, so a row still RESERVED beside a dead letter is a release
    that did not land — a failure between two writes that D-022's terminality
    principle has no answer for, because the thing that was supposed to act on
    terminality is what failed.
    """
    await _hold(kernel, company, invocation_id="inv_dead")
    await _dead_letter(kernel, company, "inv_dead")

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 1
    assert await _states(kernel) == [RELEASED]


async def test_the_release_says_why_it_happened(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """§11: headroom that comes back must say where it came back from.

    A ceiling that quietly gains a dollar is indistinguishable, afterwards, from
    a ceiling that was never enforced. D-034.3 requires every release audited,
    and "every" is why this asserts on the payload rather than on the count.
    """
    await _hold(kernel, company, invocation_id="inv_dead", amount=Decimal("0.25"))
    await _dead_letter(kernel, company, "inv_dead")

    await Scheduler(kernel).sweep(now=NOW)

    rows = await _audited(kernel)
    assert len(rows) == 1
    assert rows[0].business_id == company
    assert rows[0].payload["invocation_id"] == "inv_dead"
    assert rows[0].payload["cycle_id"] == CYCLE
    assert rows[0].payload["amount_usd"] == "0.250000"
    assert rows[0].payload["reason"] == "invocation reached a terminal state"


async def test_the_headroom_actually_comes_back(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The point of the whole sweep, stated as the number a ceiling reads.

    RESERVED counts toward every ceiling and RELEASED counts toward none, so
    this is the difference between a company that has lost that budget forever
    and one that has it again.
    """
    await _hold(kernel, company, invocation_id="inv_dead", amount=Decimal("0.40"))
    await _dead_letter(kernel, company, "inv_dead")

    async with kernel.services() as svc:
        before = await kernel.build_ledger(svc).cycle_spend(CYCLE)
    await Scheduler(kernel).sweep(now=NOW)
    async with kernel.services() as svc:
        after = await kernel.build_ledger(svc).cycle_spend(CYCLE)

    assert before == Decimal("0.40")
    assert after == Decimal("0")


# ── the age bound, and what it must never touch ────────────────────────────


async def test_an_old_hold_with_no_evidence_at_all_is_released_by_age(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The backstop, for the case that leaves nothing to read.

    A worker that dies mid-invocation commits neither the dead-letter row nor
    the audit entry — its transaction never closed. There is no terminality to
    find, which is exactly why terminality alone cannot be the whole mechanism
    and why D-022's "no TTL heuristics" needed the amendment D-034.3 makes.
    """
    await _hold(kernel, company, invocation_id="inv_lost", age=ORPHANED_RESERVATION_AGE)

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 1
    assert await _states(kernel) == [RELEASED]
    assert (await _audited(kernel))[0].payload["reason"] == (
        "held past the age bound with no terminal result"
    )


async def test_a_live_hold_is_left_alone(kernel: PlatformKernel, company: BusinessId) -> None:
    """The negative control that matters most.

    A young hold with no terminal result is an invocation in flight, and its
    hold is the only thing stopping a sibling dispatch from spending the same
    headroom (D-022 point 1). A sweep that guessed here would reintroduce
    M6-F12 from the inside — and would do it silently, because the released row
    looks exactly like a legitimate one.
    """
    await _hold(kernel, company, invocation_id="inv_running", age=timedelta(minutes=5))

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 0
    assert await _states(kernel) == [RESERVED]
    assert await _audited(kernel) == []


async def test_a_settled_hold_is_never_reopened(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Only RESERVED rows are candidates. A SETTLED row is spend that happened,
    and releasing it would erase money the platform really paid — the one
    direction D-003 rule 1 must never be wrong in."""
    await _hold(kernel, company, invocation_id="inv_done", age=timedelta(days=3), state=SETTLED)

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 0
    assert await _states(kernel) == [SETTLED]


async def test_a_reasoning_hold_with_no_invocation_is_still_reconciled(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """`plan_cycle` and `synthesize_results` reserve with no invocation id at all
    (D-022 point 2, M6-F14), so a rule keyed only on invocations would leave the
    Manager's own reasoning holds orphaned forever — and those are most of a
    cycle's cost."""
    await _hold(kernel, company, invocation_id=None, age=ORPHANED_RESERVATION_AGE * 2)

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 1
    assert (await _audited(kernel))[0].payload["invocation_id"] is None


# ── the bounds themselves ──────────────────────────────────────────────────


def test_the_age_bound_clears_the_longest_legitimate_hold() -> None:
    """Structural, so a future timeout change cannot make the backstop unsafe.

    A reservation lives inside one activity, so the longest one can legitimately
    be held is that activity's `start_to_close_timeout`. The age bound has to sit
    clear of it by a margin, and the margin has to be checked against the
    constants rather than against a number somebody remembered — raising
    `DISPATCH_TIMEOUT` past this bound would silently turn this sweep into a
    releaser of live holds.
    """
    longest = max(ACTIVITY_TIMEOUT, DISPATCH_TIMEOUT)
    assert longest * 2 <= ORPHANED_RESERVATION_AGE


async def test_one_sweep_does_a_bounded_amount_of_work(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The sweep runs beside the §9 approval timers, so a backlog must not turn
    one pass into an unbounded one. Oldest-first means a bounded pass is the
    right kind of incomplete: the holds that have cost headroom longest go
    first, and the rest wait exactly one sweep."""
    for minutes in range(MAX_RECONCILED_PER_SWEEP + 3):
        await _hold(kernel, company, age=ORPHANED_RESERVATION_AGE + timedelta(minutes=minutes))

    first = await Scheduler(kernel).sweep(now=NOW)
    second = await Scheduler(kernel).sweep(now=NOW)

    assert first.reservations_released == MAX_RECONCILED_PER_SWEEP
    assert second.reservations_released == 3


async def test_the_release_and_its_record_commit_together(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """D-034.3's "every release audited", made true rather than nearly true.

    Both writes go into the reconciling transaction, so neither is visible
    unless both are. Rolling that transaction back is the only way to observe
    it: if the release used its own short transaction the way `reserve` and
    `release` do — correctly, for a hold whose owner is still running — a crash
    between the two would leave headroom back on a ceiling with nothing
    explaining where it came from.
    """
    await _hold(kernel, company, invocation_id="inv_dead")
    await _dead_letter(kernel, company, "inv_dead")

    async with kernel.services() as svc:
        released = await Scheduler(kernel)._reconcile_reservations(svc, NOW)
        assert released == 1
        await svc.session.rollback()

    assert await _states(kernel) == [RESERVED], "the release went back"
    assert await _audited(kernel) == [], "and so did the record of it"


# ── M8-F88: one orphan the backstop no longer has to catch ────────────────
#
# M8-F92 recorded that in practice the age bound, not terminality, was doing
# this sweep's work — D-022's expectation inverted. A cancelled dispatch is one
# of the reasons why: it left a RESERVED row with no dead letter beside it and
# no audit entry, so there was nothing terminal to read and the backstop was the
# only thing that would ever release it. M8-F88 gives that path the handler
# `_ask_model` has had since D-022, which narrows what the backstop is carrying.


class _CancellingProvider:
    """Provider whose call is cancelled — the worker is going away."""

    @property
    def name(self) -> str:
        return "cancelling"

    async def complete(self, request: object) -> CompletionResponse:
        raise asyncio.CancelledError

    async def aclose(self) -> None:
        return None


async def _dispatch_cancelled(kernel: PlatformKernel, company: BusinessId) -> None:
    """Dispatch one invocation through a real pool and have it cancelled.

    A real `CapabilityPool` against the real ledger, because what is under test
    is which ledger row the pool leaves behind — a hand-written row would be a
    test about this file's idea of the pool.
    """
    async with kernel.services() as svc:
        pool = CapabilityPool(
            session=svc.session,
            registry=svc.registry,
            ledger=kernel.build_ledger(svc),
            breaker=kernel.build_breaker(svc),
            executor=CapabilityExecutor(
                _CancellingProvider(),  # type: ignore[arg-type]
                InMemoryTemplates({"affiliate.research": "Research {topic}"}),
            ),
            audit=svc.audit,
        )
        with pytest.raises(asyncio.CancelledError):
            await pool.dispatch(
                identity=RuntimeIdentity.for_testing(company),
                request=ScopedRequest(
                    invocation_id=InvocationId("inv_cancelled"),
                    declared_business_id=company,
                    capability=CapabilityType.RESEARCH,
                    prompt_ref="affiliate.research",
                    prompt_inputs={"topic": "trail shoes"},
                    budget_allocation_usd=Decimal("0.50"),
                    cycle_id=CYCLE,
                ),
            )


async def test_a_cancelled_dispatch_leaves_the_sweep_nothing_to_find(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """M8-F88, stated as what the reconcile no longer has to do.

    The hold comes back at the moment the invocation ends, which is what D-022
    point 3 says should happen and what this path was not doing. The sweep then
    finds nothing — not "finds it and releases it", which would be the same
    headroom returning up to half an hour later and one more thing the backstop
    was quietly load-bearing for.
    """
    await _dispatch_cancelled(kernel, company)
    assert await _states(kernel) == [RELEASED], "released by the pool, not by a timer"

    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 0
    assert await _audited(kernel) == []


async def test_before_that_the_headroom_waited_out_the_age_bound(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """The defect, kept executable: what a cancelled dispatch used to leave.

    A RESERVED row with no terminal evidence anywhere — the worker was cancelled
    before it could write one. The sweep is *right* not to touch it while it is
    young (that is `test_a_live_hold_is_left_alone`, and guessing there would
    reopen M6-F12 from the inside), so the company's headroom stayed gone until
    `ORPHANED_RESERVATION_AGE` — twice the longest activity timeout — had passed.

    That window is the cost M8-F88 removes, and it is why "the backstop catches
    it eventually" was never a sufficient answer.
    """
    await _hold(kernel, company, invocation_id="inv_cancelled", age=timedelta(minutes=5))

    young = await Scheduler(kernel).sweep(now=NOW)
    assert young.reservations_released == 0
    assert await _states(kernel) == [RESERVED], "the headroom is still gone"

    old = await Scheduler(kernel).sweep(now=NOW + ORPHANED_RESERVATION_AGE)
    assert old.reservations_released == 1
    assert (await _audited(kernel))[0].payload["reason"] == (
        "held past the age bound with no terminal result"
    )


async def test_a_platform_with_nothing_held_does_nothing(
    kernel: PlatformKernel, company: BusinessId
) -> None:
    """Negative control on the sweep itself: no holds, no writes, no audit noise
    on every timer tick."""
    report = await Scheduler(kernel).sweep(now=NOW)

    assert report.reservations_released == 0
    assert await _audited(kernel) == []
