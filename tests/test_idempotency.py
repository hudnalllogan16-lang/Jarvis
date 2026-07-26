"""Idempotency tests (spec §6, key derivation per A-001)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.capabilities.idempotency import IdempotencyStore, idempotency_key
from jarvis.kernel.ids import BusinessId, InvocationId

BIZ = BusinessId("biz_" + "0123456789abcdef" * 2)


def _key(**overrides: object) -> str:
    args: dict[str, object] = {
        "business_id": BIZ,
        "invocation_id": InvocationId("inv_1"),
        "action_type": "affiliate.publish_post",
        "payload": {"title": "hello", "body": "world"},
    }
    args.update(overrides)
    return idempotency_key(**args)  # type: ignore[arg-type]


def test_key_is_stable_across_attempts() -> None:
    """A-001: derived from the invocation, not the attempt.

    This is what makes a retry (spec §9) and a workflow replay (D-004) collapse
    to one external effect.
    """
    assert _key() == _key()


def test_key_ignores_payload_key_order() -> None:
    """Two identical actions serialised differently must not publish twice."""
    assert _key(payload={"title": "hello", "body": "world"}) == _key(
        payload={"body": "world", "title": "hello"}
    )


def test_key_changes_with_payload() -> None:
    assert _key() != _key(payload={"title": "different", "body": "world"})


def test_key_changes_with_action_type() -> None:
    assert _key() != _key(action_type="affiliate.delete_post")


def test_key_is_business_scoped() -> None:
    """Two businesses performing the same action must not share an effect."""
    assert _key() != _key(business_id=BusinessId("biz_" + "f" * 32))


def test_key_changes_with_invocation() -> None:
    """Distinct invocations are distinct intents, even for identical payloads."""
    assert _key() != _key(invocation_id=InvocationId("inv_2"))


async def test_store_returns_none_before_the_action_runs(session: AsyncSession) -> None:
    assert await IdempotencyStore(session).existing(_key()) is None


async def test_store_replays_a_recorded_action(session: AsyncSession) -> None:
    store = IdempotencyStore(session)
    await store.record(
        key=_key(),
        business_id=BIZ,
        action_type="affiliate.publish_post",
        result={"output": "published"},
    )
    assert (await store.existing(_key()))["output"] == "published"


async def test_recording_twice_is_harmless(session: AsyncSession) -> None:
    """A retry that reaches the record step must not raise on the duplicate."""
    store = IdempotencyStore(session)
    for _ in range(2):
        await store.record(
            key=_key(),
            business_id=BIZ,
            action_type="affiliate.publish_post",
            result={"output": "published"},
        )
    assert (await store.existing(_key()))["output"] == "published"
