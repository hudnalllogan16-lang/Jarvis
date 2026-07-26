"""Temporal activity boundary (spec §2, §11; D-004).

D-004 requires that *all* nondeterminism happen inside activities with recorded
results — model calls, tool calls, HTTP, clock reads, random draws, and UUID
generation. Workflow code is pure orchestration. Everything in this module is
therefore on the impure side of that line, and nothing here may be called from
workflow code.

This module also closes Milestone 1 finding M1-R1. `RuntimeIdentity.from_activity`
reads `activity.info().workflow_id`, which Temporal's server populates from the
*calling workflow*; activity code cannot forge it. Until this boundary existed,
D-002's derived identity was correct but had no production caller.
"""

from __future__ import annotations

from collections.abc import Callable

from temporalio import activity

from jarvis.capabilities.request import CapabilityResult, ScopedRequest
from jarvis.events.bus import Event
from jarvis.kernel.container import PlatformKernel
from jarvis.kernel.ids import DecisionId, new_decision_id, new_event_id
from jarvis.kernel.logging import get_logger
from jarvis.kernel.runtime import RuntimeIdentity

logger = get_logger(__name__)


class KernelActivities:
    """Activities bound to a Kernel instance.

    Class-based rather than free functions so the Kernel arrives by injection
    rather than a module global — the same reason the rest of the platform takes
    its collaborators as constructor arguments.
    """

    def __init__(self, kernel: PlatformKernel) -> None:
        """Args:
        kernel: The Platform Kernel supplying sessions and services.
        """
        self._kernel = kernel

    @activity.defn(name="dispatch_capability")
    async def dispatch_capability(self, request: ScopedRequest) -> CapabilityResult:
        """Dispatch one scoped capability request (spec §2.2).

        The invoking identity is derived here, from the Temporal runtime, not
        taken from the request — which is what makes spec §10 hold against a
        malformed or malicious request (D-002).

        Args:
            request: The scoped request, serialised by the calling workflow.

        Returns:
            A terminal `CapabilityResult` (D-001), returned to the workflow even
            when the invocation was dead-lettered.
        """
        identity = RuntimeIdentity.from_activity()
        async with self._kernel.services() as svc:
            # Load the invoking type's prompt templates from Registry metadata
            # so the executor can resolve prompt_ref (M5-F3): without this every
            # dispatch dead-letters with "unknown prompt reference".
            from jarvis.capabilities.executor import InMemoryTemplates

            contract = await svc.registry.get_contract(identity.business_id)
            definition = await self._kernel.type_definition(svc, contract.business_type)
            templates = InMemoryTemplates(definition.prompt_templates) if definition else None
            pool = self._kernel.build_pool(svc, templates=templates)
            return await pool.dispatch(identity=identity, request=request)

    @activity.defn(name="publish_event")
    async def publish_event(self, event_type: str, payload: dict[str, object]) -> str:
        """Publish an event to the bus (spec §2).

        The event id is minted here rather than in the workflow because UUID
        generation is nondeterministic and would break replay (D-004).
        """
        identity = RuntimeIdentity.from_activity()
        async with self._kernel.services() as svc:
            bus = self._kernel.build_bus(svc)
            return await bus.publish(
                Event(
                    event_id=new_event_id(),
                    event_type=event_type,
                    business_id=identity.business_id,
                    payload=payload,
                )
            )

    @activity.defn(name="claim_events")
    async def claim_events(self, event_types: list[str]) -> list[dict[str, object]]:
        """Claim unconsumed events for the calling business (A-002).

        Deduplication is keyed on the calling business, so a redelivered event
        cannot produce a second wake cycle for the same Manager.
        """
        identity = RuntimeIdentity.from_activity()
        async with self._kernel.services() as svc:
            bus = self._kernel.build_bus(svc)
            events = await bus.claim(identity.business_id, event_types)
            return [e.model_dump() for e in events]

    @activity.defn(name="record_decision")
    async def record_decision(
        self,
        summary: str,
        rationale: str,
        cycle_id: str | None = None,
        action_type: str | None = None,
    ) -> str:
        """Write a Decision Log entry (spec §11.5).

        Called at the moment a decision is made, not batched at cycle end:
        §11.5 requires the entry to exist when the decision does, and a cycle
        that crashes before flushing would otherwise leave an unexplained action.
        """
        identity = RuntimeIdentity.from_activity()
        decision_id: DecisionId = new_decision_id()
        async with self._kernel.services() as svc:
            await svc.decisions.record(
                decision_id=decision_id,
                business_id=identity.business_id,
                summary=summary,
                rationale=rationale,
                cycle_id=cycle_id,
                action_type=action_type,
            )
        return decision_id

    @activity.defn(name="platform_spend_24h")
    async def platform_spend_24h(self) -> str:
        """Return rolling 24h platform spend as a string (spec §9).

        Returned as a string because Decimal does not survive JSON round-trips
        intact, and float rounding in a spend ceiling is not acceptable.
        """
        async with self._kernel.services() as svc:
            ledger = self._kernel.build_ledger(svc)
            return str(await ledger.platform_spend_24h())


def all_activities(kernel: PlatformKernel) -> list[Callable[..., object]]:
    """Return every activity implementation for worker registration."""
    instance = KernelActivities(kernel)
    return [
        instance.dispatch_capability,
        instance.publish_event,
        instance.claim_events,
        instance.record_decision,
        instance.platform_spend_24h,
    ]


__all__ = ["KernelActivities", "all_activities"]
