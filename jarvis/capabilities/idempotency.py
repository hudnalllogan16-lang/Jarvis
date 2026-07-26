"""Idempotency for external-facing actions (spec §6, key per A-001).

Spec §6 requires any capability performing a publish, send, spend, or execute to
be idempotent, but never says what the key is derived from — and idempotency
without a defined key is not a testable requirement. A-001 derives it from the
*invocation*, not the attempt, so a retry (spec §9) and a workflow replay
(D-004) both collapse to one external effect.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.kernel.ids import BusinessId, InvocationId
from jarvis.persistence.models import IdempotencyRow


def idempotency_key(
    *,
    business_id: BusinessId,
    invocation_id: InvocationId,
    action_type: str,
    payload: dict[str, Any],
) -> str:
    """Derive the A-001 idempotency key.

    The payload is canonicalised with sorted keys so that two structurally
    identical actions serialised in different key orders produce one key rather
    than two, which would otherwise let a retry publish twice.

    Args:
        business_id: Acting business.
        invocation_id: Owning invocation — the retry-stable component.
        action_type: Namespaced action identifier (A-003).
        payload: Action parameters.

    Returns:
        A hex digest usable as a primary key.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    material = f"{business_id}|{invocation_id}|{action_type}|{canonical}"
    return hashlib.sha256(material.encode()).hexdigest()


class IdempotencyStore:
    """Records and replays the results of external-facing actions."""

    def __init__(self, session: AsyncSession) -> None:
        """Args:
        session: Active session.
        """
        self._session = session

    async def existing(self, key: str) -> dict[str, Any] | None:
        """Return the recorded result for ``key``, if the action already ran.

        Returns:
            The prior result, or None if this action has not been performed.
        """
        row = await self._session.get(IdempotencyRow, key)
        return row.result if row else None

    async def record(
        self,
        *,
        key: str,
        business_id: BusinessId,
        action_type: str,
        result: dict[str, Any],
    ) -> None:
        """Record that an action completed, so a repeat becomes a replay."""
        if await self._session.get(IdempotencyRow, key) is not None:
            return
        self._session.add(
            IdempotencyRow(
                key=key,
                business_id=business_id,
                action_type=action_type,
                result=result,
            )
        )
        await self._session.flush()
