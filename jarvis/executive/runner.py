"""The Executive's own deterministic tick (design EXECUTIVE-LAYER.md Part 7, D-041) — packet D.

Everything else in this package computes or announces; nothing calls any of it.
`compute_portfolio_rollup`, `compute_portfolio_health`, `raise_spend_alerts`,
`raise_platform_ceiling_alerts` and `record_platform_halt` all exist, all pass
their own tests, and none of them runs unless something invokes them in order.
:func:`run_executive_tick` is that something — one pass, in the sequence design
Part 7 names: rollup, then census, then the two alert families, then the halt
narrative.

**Deliberately not a class holding a `PlatformKernel`.** Every sibling module in
this package takes its collaborators as plain arguments rather than reaching for
a container, and this function keeps that shape so it is testable against the
same lightweight `session`/`registry`/`contract` fixtures `test_executive_alerts.py`
already uses — no Temporal client, no LLM provider, no live database. The
kernel-aware part — opening a session, building a ledger/breaker/notifications
from `Settings`, and looping on a timer — belongs to `jarvis/runtime/worker.py`,
the composition root design Part 7 names, and stays there (D-016/D-017: no
supervisor mechanism changes, just one more part registered exactly like the
scheduler already is).

**M9-F78 resolved by construction, not by a new mechanism.** The rollup's
`platform_ceiling_usd` and the breaker's `ceiling_usd` must be the same number
or an operator could be told two different things about one ceiling in the same
breath. Nothing here enforces that — the composition root does, by reading
`Settings.budget.platform_rolling_24h_usd` exactly once and handing it to both
`compute_portfolio_rollup` and `PlatformKernel.build_breaker`, the same way
`PlatformKernel.build_ledger`/`build_breaker` already source it for every other
caller (`jarvis/kernel/container.py`). This module's own tests hold that
sourcing to account for by taking `platform_ceiling_usd` as a single argument
and never a second one.

**M9-F79: no new 24h window constant.** Nothing here measures a window itself —
`platform_spend_24h` (via `ledger`), `_halt_already_explained` (via `record_
platform_halt`, `jarvis.budget.ledger.PLATFORM_SPEND_WINDOW`), and the platform
ceiling's own dedup (via `NotificationService.has_unread`, which is state-based
rather than time-based) are the only three places a "still within 24h" question
is ever asked, and all three already read the ledger's one constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.executive.alerts import (
    PlatformAlert,
    SpendAlert,
    raise_platform_ceiling_alerts,
    raise_spend_alerts,
    record_platform_halt,
)
from jarvis.executive.health import PortfolioHealth, compute_portfolio_health
from jarvis.executive.liveness import RuntimeLivenessAlert, raise_runtime_liveness_alerts
from jarvis.executive.rollup import PortfolioRollup, compute_portfolio_rollup
from jarvis.kernel.logging import get_logger
from jarvis.kpi.engine import KpiEngine
from jarvis.notifications.service import NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.observability.heartbeat import HeartbeatStore
from jarvis.observability.poller import PollerReading
from jarvis.registry.registry import BusinessRegistry

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutiveTickReport:
    """What one Executive tick did, for the caller to log or assert on.

    Every field is a read-out of what the four steps below already returned —
    this dataclass adds no arithmetic of its own, the same discipline
    `PortfolioRollup` and `PortfolioHealth` hold for their own inputs.
    """

    rollup: PortfolioRollup
    census: PortfolioHealth
    liveness: RuntimeLivenessAlert
    spend_alerts: tuple[SpendAlert, ...]
    platform_alerts: tuple[PlatformAlert, ...]
    halted: bool


async def run_executive_tick(
    *,
    registry: BusinessRegistry,
    ledger: BudgetLedger,
    kpi: KpiEngine,
    notifications: NotificationService,
    breaker: CircuitBreaker,
    decisions: DecisionLog,
    heartbeat: HeartbeatStore,
    audit: AuditLog,
    poller: PollerReading,
    platform_ceiling_usd: Decimal,
    heartbeat_stale_after_seconds: float,
    poller_stale_after_seconds: float,
    part_failing_after_crashes: int,
    now: datetime | None = None,
) -> ExecutiveTickReport:
    """Run one deterministic Executive pass: rollup -> census -> liveness ->
    alerts -> halt.

    The order is design Part 7's and is load-bearing, not incidental: the two
    alert families read `rollup`'s own fields rather than recomputing anything
    (design Part 12's sequencing note), so the rollup must exist first; the
    halt narrative asks the breaker rather than a second comparison of
    `rollup`'s figures (2.4), so it can run anywhere after the rollup but is
    kept last because it is the one step that writes a Decision Log entry
    rather than only a notification. Census has no dependency on either alert
    family and no writer of its own yet (packet E, design Part 8) — it is
    computed here, every tick, so the day its first reader lands nothing has
    to change on this side. The liveness verdict runs immediately after the
    census (packet P0-C's own placement) — it depends on neither the rollup
    nor either alert family, and belongs beside census as the tick's other
    "compute and report on every pass regardless of who reads it yet" step.

    **Idempotent-on-repeat by construction, not by anything this function
    adds.** Every step it calls already carries its own deduplication —
    `raise_spend_alerts`/`raise_platform_ceiling_alerts` against `Notification
    Service.has_unread`, `record_platform_halt` against the platform Decision
    Log, `raise_runtime_liveness_alerts` against the platform Audit Log — so
    calling this twice against an unchanged database announces nothing
    twice. That is what makes a scripted two-tick run a meaningful proof
    rather than a formality: see `tests/test_executive_runner.py`.

    Args:
        registry: Read-only source of company existence and contracts.
        ledger: Read-only source of spend, for the rollup.
        kpi: Read-only source of health scores and recorded cycle counts.
        notifications: Writer for the operator's queue (every alert family).
        breaker: The enforcing circuit breaker — asked, not second-guessed,
            for whether the platform is actually halted (2.4).
        decisions: Platform Decision Log, read and written through the halt
            narrative only.
        heartbeat: Read for the liveness verdict's self-report signal
            (design 3.2 Signal 1, packet P0-B's store).
        audit: Read and written through the liveness verdict only — the
            transition record D-046 requires and the read half of its own
            transition detector (`AuditLog.latest_platform_entry`).
        poller: The liveness verdict's external signal (design 3.2 Signal 2),
            already read by the composition root (design 3.3: "the Executive
            receives a reading, not a dependency") — never fetched here.
        platform_ceiling_usd: The platform's rolling 24h ceiling, sourced by
            the caller from the same place the breaker's own ceiling comes
            from (M9-F78) — see the module docstring.
        heartbeat_stale_after_seconds: `settings.heartbeat.
            heartbeat_stale_after_seconds`, threaded to the liveness verdict.
        poller_stale_after_seconds: `settings.heartbeat.
            poller_stale_after_seconds`, threaded to the liveness verdict.
        part_failing_after_crashes: `settings.heartbeat.
            part_failing_after_crashes` (design 5.4), threaded to the
            liveness verdict.
        now: Injectable clock (D-004, D-038 — no uninjected clock). Threaded
            through to `record_platform_halt` and the liveness verdict, both
            of which read the same instant; the rollup and census take no
            clock of their own.

    Returns:
        A report naming everything this pass computed and announced.
    """
    moment = now or datetime.now(UTC)

    rollup = await compute_portfolio_rollup(
        registry, ledger, kpi, platform_ceiling_usd=platform_ceiling_usd
    )
    census = await compute_portfolio_health(registry, ledger, kpi)
    liveness = await raise_runtime_liveness_alerts(
        heartbeat,
        poller,
        notifications,
        audit,
        now=moment,
        heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
        poller_stale_after_seconds=poller_stale_after_seconds,
        part_failing_after_crashes=part_failing_after_crashes,
    )
    spend_alerts = await raise_spend_alerts(rollup, notifications)
    platform_alerts = await raise_platform_ceiling_alerts(rollup, notifications)
    halted = await record_platform_halt(rollup, breaker, decisions, now=moment)

    if spend_alerts or platform_alerts or halted:
        logger.info(
            "executive tick complete",
            extra={
                "context": {
                    "spend_alerts": len(spend_alerts),
                    "platform_alerts": len(platform_alerts),
                    "halted": halted,
                }
            },
        )
    return ExecutiveTickReport(
        rollup=rollup,
        census=census,
        liveness=liveness,
        spend_alerts=spend_alerts,
        platform_alerts=platform_alerts,
        halted=halted,
    )
