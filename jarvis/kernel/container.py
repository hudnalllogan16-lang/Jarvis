"""Platform Kernel container (spec §0).

The Kernel is infrastructure, not intelligence: this object holds resources and
hands out collaborators. It contains no reasoning, makes no decisions, and never
calls a model itself.

Nothing in Jarvis exists outside the Kernel (spec §0), which in practice means
every component is reached through this container rather than through module
globals. That is also what makes the platform testable: a test builds a Kernel
with its own session factory and provider and gets a complete, isolated system.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from jarvis.approvals.service import ApprovalService
from jarvis.budget.breaker import CircuitBreaker
from jarvis.budget.ledger import BudgetLedger
from jarvis.capabilities.contention import CapabilityGate
from jarvis.capabilities.executor import CapabilityExecutor, InMemoryTemplates, PromptTemplates
from jarvis.capabilities.idempotency import IdempotencyStore
from jarvis.capabilities.pool import CapabilityPool
from jarvis.capabilities.tools import ToolExecutor
from jarvis.events.bus import EventBus
from jarvis.kernel.config import Settings
from jarvis.kernel.logging import configure_logging, get_logger
from jarvis.kpi.engine import KpiEngine
from jarvis.llm.base import LLMProvider
from jarvis.llm.factory import build_provider
from jarvis.notifications.service import NotificationService
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.engine import build_engine, build_session_factory, session_scope
from jarvis.registry.registry import BusinessRegistry
from jarvis.security.credentials import CredentialManager

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KernelServices:
    """Session-scoped collaborators.

    Grouped rather than resolved individually so that a Registry, its Audit Log,
    and its Decision Log always share one transaction. D-008 I-6 requires a
    lifecycle transition and its two log entries to commit together; separate
    sessions would let a state change survive a failed log write, leaving a
    company whose history cannot explain how it got where it is.
    """

    session: AsyncSession
    audit: AuditLog
    decisions: DecisionLog
    registry: BusinessRegistry


class PlatformKernel:
    """Owns platform infrastructure and hands out session-scoped services."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: AsyncEngine | None = None,
        provider: LLMProvider | None = None,
        templates: PromptTemplates | None = None,
        secrets: dict[str, str] | None = None,
    ) -> None:
        """Args:
        settings: Root configuration.
        engine: Optional injected engine, for tests.
        provider: Optional injected LLM provider, for tests.
        templates: Prompt template source. Defaults to empty, which is correct
            until plugin loading lands: a capability with no templates fails
            permanently rather than inventing a prompt.
        secrets: Handle-to-secret mapping, overriding the configured one.
            Tests inject here; production leaves it None and the mapping comes
            from `settings.credentials` (spec §10).
        """
        configure_logging(settings.log_level)
        self._settings = settings
        self._engine = engine or build_engine(settings)
        self._session_factory: async_sessionmaker[AsyncSession] = build_session_factory(
            self._engine
        )
        self._provider = provider or build_provider(settings.llm)
        self._templates: PromptTemplates = templates or InMemoryTemplates({})
        # One gate for the whole process: fairness across businesses is only
        # meaningful if every dispatcher consults the same queue.
        self._gate = CapabilityGate()
        self._temporal_client: object | None = None
        # Secrets injected from the environment-backed settings source; the
        # mapping is handle -> value and values never leave CredentialManager
        # unwrapped (spec §10). Until M6-3 this read an argument no entrypoint
        # ever passed, so the comment was true of the design and false of the
        # running system: the manager was empty and every credentialled tool
        # would have been refused (M6-F28).
        self._credentials = CredentialManager(
            secrets
            if secrets is not None
            else {
                handle: value.get_secret_value()
                for handle, value in self._settings.credentials.items()
            }
        )
        logger.info(
            "kernel initialised",
            extra={"context": {"env": settings.env, "provider": self._provider.name}},
        )

    @property
    def settings(self) -> Settings:
        """Return the root configuration."""
        return self._settings

    @property
    def llm(self) -> LLMProvider:
        """Return the configured LLM provider.

        Callers depend on the protocol, never on the concrete class, so the
        vendor behind this is invisible to business logic (A-005).
        """
        return self._provider

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory, for components managing their own scope."""
        return self._session_factory

    @asynccontextmanager
    async def services(self) -> AsyncGenerator[KernelServices]:
        """Yield session-scoped services inside one transaction.

        Yields:
            A `KernelServices` bundle sharing a single session. Commits on clean
            exit, rolls back on exception.

        The Audit Log gets the session *factory* as well as the session, for the
        same reason the ledger does: a security denial is raised out of this
        scope, and "rolls back on exception" would take the record of the denial
        with it (M6-F38). `record_independently` commits on its own.
        """
        async with session_scope(self._session_factory) as session:
            audit = AuditLog(session, denial_sessions=self._session_factory)
            decisions = DecisionLog(session)
            yield KernelServices(
                session=session,
                audit=audit,
                decisions=decisions,
                registry=BusinessRegistry(session, audit, decisions),
            )

    # ── Milestone 2: execution spine factories ─────────────────────────────
    #
    # Built per session rather than held on the Kernel, because each takes a
    # session and must share the caller's transaction — an audit entry and the
    # lifecycle change it describes have to commit together, or a crash between
    # them leaves a state change with no explanation of how it happened.
    #
    # Budget reservations are the one deliberate exception (D-022): a hold that
    # commits when the caller's activity finishes cannot gate that activity's
    # spend, which is the M6-F12 race. The ledger therefore also gets the
    # session *factory*, and runs its reservations in their own short
    # transactions.

    def build_ledger(self, services: KernelServices) -> BudgetLedger:
        """Return a budget ledger bound to ``services``' session (D-003, D-022)."""
        return BudgetLedger(
            services.session,
            platform_ceiling_usd=self._settings.budget.platform_rolling_24h_usd,
            reservation_sessions=self._session_factory,
        )

    def build_breaker(self, services: KernelServices) -> CircuitBreaker:
        """Return a circuit breaker bound to ``services``' session (spec §9)."""
        return CircuitBreaker(
            self.build_ledger(services),
            services.decisions,
            ceiling_usd=self._settings.budget.platform_rolling_24h_usd,
        )

    def build_bus(self, services: KernelServices) -> EventBus:
        """Return an event bus bound to ``services``' session (spec §2)."""
        return EventBus(services.session, services.audit)

    def build_executor(self, templates: PromptTemplates | None = None) -> CapabilityExecutor:
        """Return a capability executor.

        Constructed fresh on every call. The executor is stateless by design
        (spec §6), so this costs nothing and removes any object in which context
        could accumulate across invocations (spec §2.2).

        Args:
            templates: Per-dispatch template source — normally the invoking
                business's type templates, loaded from Registry metadata by the
                dispatch activity (M5-F3). Falls back to the kernel-wide source.
        """
        return CapabilityExecutor(self._provider, templates or self._templates)

    def build_pool(
        self, services: KernelServices, *, templates: PromptTemplates | None = None
    ) -> CapabilityPool:
        """Return a capability pool bound to ``services``' session (spec §2.2)."""
        return CapabilityPool(
            session=services.session,
            registry=services.registry,
            ledger=self.build_ledger(services),
            breaker=self.build_breaker(services),
            executor=self.build_executor(templates),
            audit=services.audit,
            idempotency=IdempotencyStore(services.session),
            gate=self._gate,
            bus=self.build_bus(services),
        )

    def build_tools(self, services: KernelServices) -> ToolExecutor:
        """Return the tool execution boundary (D-015), session-scoped."""
        from jarvis.capabilities.idempotency import IdempotencyStore

        return ToolExecutor(
            credentials=self._credentials,
            idempotency=IdempotencyStore(services.session),
            audit=services.audit,
        )

    async def type_definition(self, services: KernelServices, name: str) -> Any:
        """Return the installed BusinessTypeDefinition for ``name``, or None.

        Read from Registry metadata, not from an in-process dict: definitions
        must survive a restart, or a company created yesterday wakes up today
        with no prompt templates and dead-letters every dispatch (M5-F3).
        """
        from jarvis.businesses.definition import BusinessTypeDefinition

        for row in await services.registry.installed_types():
            if row.name == name:
                raw = (row.plugin_metadata or {}).get("definition")
                return BusinessTypeDefinition.model_validate(raw) if raw else None
        return None

    def build_provisioning(self, services: KernelServices) -> Any:
        """Return the provisioning service (spec §4), session-scoped.

        Constructed here rather than imported by the API so the layering
        invariant holds: the API (M3) must not import the businesses package
        (M5), and the kernel is the composition root that may.

        This is also where the configured wake-cycle ceiling default acquires
        its reader (M6-F23): the setting existed and nothing consulted it, so a
        company created without an explicit ceiling silently took the business
        type's suggestion and the `.env` value was inert.
        """
        from jarvis.businesses.provisioning import ProvisioningService

        return ProvisioningService(
            services.registry,
            self.build_bus(services),
            default_wake_ceiling_usd=self._settings.budget.default_wake_cycle_ceiling_usd,
        )

    def build_approvals(self, services: KernelServices) -> ApprovalService:
        """Return the approval service bound to ``services``' session (spec §8)."""
        return ApprovalService(
            services.session,
            services.audit,
            services.decisions,
            bus=self.build_bus(services),
        )

    def build_kpis(self, services: KernelServices) -> KpiEngine:
        """Return the KPI engine bound to ``services``' session (spec §5)."""
        return KpiEngine(services.session, bus=self.build_bus(services))

    def build_notifications(self, services: KernelServices) -> NotificationService:
        """Return the notification service bound to ``services``' session."""
        return NotificationService(services.session)

    async def temporal_client(self) -> Any:
        """Return a connected Temporal client, or None if unavailable.

        Returns None rather than raising so the scheduler's timer sweep — which
        needs no Temporal at all — still runs when the workflow runtime is down.
        Approvals expiring on time matters more than event wakes.
        """
        if self._temporal_client is None:
            try:
                from temporalio.client import Client
                from temporalio.contrib.pydantic import pydantic_data_converter

                # Must match the worker's converter (jarvis/runtime/worker.py):
                # this client starts Managers with a pydantic `ManagerState`
                # argument, which Temporal's default converter cannot encode
                # (M6-F5).
                self._temporal_client = await Client.connect(
                    self._settings.temporal.host,
                    namespace=self._settings.temporal.namespace,
                    data_converter=pydantic_data_converter,
                )
            except Exception:
                logger.warning("temporal unavailable; event-based wakes are paused")
                return None
        return self._temporal_client

    async def ensure_builtin_types(self) -> None:
        """Install built-in business types if absent. Idempotent; call at startup.

        Installation is a Registry write, not an import side effect: a type that
        only existed in process memory would vanish on restart (M5-F3), and an
        import-time side effect is invisible in the audit log.
        """
        from jarvis.businesses.affiliate import AFFILIATE
        from jarvis.businesses.provisioning import ProvisioningService
        from jarvis.kernel.errors import RegistryError

        async with self.services() as svc:
            installed = {t.name: t.version for t in await svc.registry.installed_types()}
            if installed.get(AFFILIATE.name) == AFFILIATE.version:
                return
            try:
                await ProvisioningService(svc.registry, self.build_bus(svc)).install(AFFILIATE)
            except RegistryError:
                logger.warning("builtin type install skipped", extra={"context": {}})

    async def aclose(self) -> None:
        """Release the engine and provider transports."""
        await self._provider.aclose()
        await self._engine.dispose()
        logger.info("kernel closed")
