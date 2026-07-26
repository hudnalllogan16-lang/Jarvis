"""Approval and autonomy ladder tests (spec §8, §9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalRequest, ApprovalState
from jarvis.approvals.service import ApprovalError, ApprovalService
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.ids import DecisionId
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import ApprovalRow

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _service(session: AsyncSession) -> ApprovalService:
    return ApprovalService(session, AuditLog(session), DecisionLog(session))


def _request(contract: BusinessContract, n: int = 1, **over: object) -> ApprovalRequest:
    base: dict[str, object] = {
        "approval_id": f"apr_{n}",
        "business_id": contract.business_id,
        "action_type": "affiliate.publish_post",
        "action_summary": "publish today's post",
        "triggering_condition": "Today's post is ready and scheduled.",
        "downside": "A weak post could lose a few readers.",
    }
    base.update(over)
    return ApprovalRequest(**base)  # type: ignore[arg-type]


async def test_unknown_action_requires_approval(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §8: absence of configuration is never permission."""
    assert await _service(session).requires_approval(contract, "affiliate.wire_funds")


async def test_configured_action_requires_approval_before_graduating(
    session: AsyncSession, contract: BusinessContract
) -> None:
    assert await _service(session).requires_approval(contract, "affiliate.publish_post")


async def test_graduation_after_an_unbroken_streak(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §8: threshold is 5 for this action in the fixture contract."""
    service = _service(session)
    for n in range(1, 6):
        await service.request(request=_request(contract, n), contract=contract)
        await service.approve(f"apr_{n}", contract=contract, decision_id=DecisionId(f"d{n}"))
    assert not await service.requires_approval(contract, "affiliate.publish_post")


async def test_denial_resets_the_streak(session: AsyncSession, contract: BusinessContract) -> None:
    service = _service(session)
    for n in range(1, 5):
        await service.request(request=_request(contract, n), contract=contract)
        await service.approve(f"apr_{n}", contract=contract, decision_id=DecisionId(f"d{n}"))

    await service.request(request=_request(contract, 5), contract=contract)
    await service.deny("apr_5", contract=contract, decision_id=DecisionId("d5"))

    await service.request(request=_request(contract, 6), contract=contract)
    await service.approve("apr_6", contract=contract, decision_id=DecisionId("d6"))
    assert await service.requires_approval(contract, "affiliate.publish_post")


async def test_correction_counts_as_a_denial(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """A-003 defines a correction as an approval with changed parameters.

    Counting an edited approval as an endorsement of the original would graduate
    an action the operator actually rejected.
    """
    service = _service(session)
    for n in range(1, 5):
        await service.request(request=_request(contract, n), contract=contract)
        await service.approve(f"apr_{n}", contract=contract, decision_id=DecisionId(f"d{n}"))

    await service.request(
        request=_request(contract, 5, parameters={"title": "original"}), contract=contract
    )
    await service.approve(
        "apr_5",
        contract=contract,
        decision_id=DecisionId("d5"),
        modified_parameters={"title": "operator rewrote this"},
    )
    assert await service.requires_approval(contract, "affiliate.publish_post")


async def test_identical_parameters_are_not_a_correction(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Resubmitting the same values is agreement, not an edit."""
    service = _service(session)
    for n in range(1, 6):
        await service.request(
            request=_request(contract, n, parameters={"title": "same"}), contract=contract
        )
        await service.approve(
            f"apr_{n}",
            contract=contract,
            decision_id=DecisionId(f"d{n}"),
            modified_parameters={"title": "same"},
        )
    assert not await service.requires_approval(contract, "affiliate.publish_post")


async def test_a_correction_persists_the_operators_parameters(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """D-011/A-003: the approved action runs from stored values, so pin them.

    `execute_approved_action` runs `decided_parameters or parameters`. Storing
    NULL on a correction would therefore execute the original wording the
    operator edited out, and storing the original on a plain approval would be
    indistinguishable from a correction. Neither is visible from the graduation
    counter, which is all the other tests here observe — this asserts the two
    persisted shapes directly (M6-0h Part 1: the pyright errors at
    `service.py:195` were unnarrowable-`None` noise, and this fixes the shape in
    place so a future type fix cannot quietly change it).
    """
    service = _service(session)
    await service.request(
        request=_request(contract, 1, parameters={"title": "original"}), contract=contract
    )
    await service.approve(
        "apr_1",
        contract=contract,
        decision_id=DecisionId("d1"),
        modified_parameters={"title": "operator rewrote this"},
    )
    corrected = await session.get(ApprovalRow, "apr_1")
    assert corrected is not None
    assert corrected.decided_parameters == {"title": "operator rewrote this"}
    assert corrected.parameters == {"title": "original"}

    await service.request(
        request=_request(contract, 2, parameters={"title": "original"}), contract=contract
    )
    await service.approve("apr_2", contract=contract, decision_id=DecisionId("d2"))
    plain = await session.get(ApprovalRow, "apr_2")
    assert plain is not None
    assert plain.decided_parameters is None


async def test_capital_actions_never_graduate(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §8 hard constraint: no graduation for capital movement in v1.

    Enforced against the action's own amount, not only its policy flag, so a
    misconfigured policy cannot graduate an action that moves money.
    """
    service = _service(session)
    for n in range(1, 9):
        await service.request(
            request=_request(contract, n, amount_usd=Decimal("25.00")), contract=contract
        )
        await service.approve(f"apr_{n}", contract=contract, decision_id=DecisionId(f"d{n}"))
    assert await service.requires_approval(contract, "affiliate.publish_post")


async def test_capital_action_without_an_amount_is_refused(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """§8 requires the exact amount be displayed; one that can't be shown must
    never reach the operator."""
    service = _service(session)
    with pytest.raises(ApprovalError):
        await service.request(
            request=_request(contract, 1, action_type="trading.execute_trade"),
            contract=contract,
        )


async def test_deciding_twice_is_refused(session: AsyncSession, contract: BusinessContract) -> None:
    service = _service(session)
    await service.request(request=_request(contract), contract=contract)
    await service.approve("apr_1", contract=contract, decision_id=DecisionId("d1"))
    with pytest.raises(ApprovalError):
        await service.deny("apr_1", contract=contract, decision_id=DecisionId("d2"))


async def test_renotification_after_24_hours(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §9."""
    service = _service(session)
    await service.request(request=_request(contract), contract=contract, now=NOW)
    assert await service.due_for_renotification(now=NOW + timedelta(hours=23)) == []
    assert len(await service.due_for_renotification(now=NOW + timedelta(hours=25))) == 1


async def test_marking_notified_restarts_the_clock(
    session: AsyncSession, contract: BusinessContract
) -> None:
    service = _service(session)
    await service.request(request=_request(contract), contract=contract, now=NOW)
    later = NOW + timedelta(hours=25)
    await service.mark_notified("apr_1", now=later)
    assert await service.due_for_renotification(now=later) == []


async def test_expiry_pauses_and_never_approves(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §9: auto-pause after 7 days, never auto-approve.

    Silence is treated as refusal. This is the single most important assertion
    in the approval subsystem — an implementation that drifted to auto-approve
    would hand an unattended platform the authority to spend.
    """
    service = _service(session)
    await service.request(request=_request(contract), contract=contract, now=NOW)
    paused = await service.expire_stale(
        decision_id=DecisionId("d_exp"), now=NOW + timedelta(days=8)
    )
    assert paused == [contract.business_id]
    pending = await service.pending()
    assert pending == []
    row = await session.get(ApprovalRow, "apr_1")
    assert row is not None
    assert row.state == ApprovalState.EXPIRED_PAUSED.value


async def test_approval_not_expired_before_seven_days(
    session: AsyncSession, contract: BusinessContract
) -> None:
    service = _service(session)
    await service.request(request=_request(contract), contract=contract, now=NOW)
    assert (
        await service.expire_stale(decision_id=DecisionId("d"), now=NOW + timedelta(days=6)) == []
    )


async def test_operator_can_revoke_a_graduation(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §12.5 requires graduation come "with an easy way to revoke it"."""
    service = _service(session)
    for n in range(1, 6):
        await service.request(request=_request(contract, n), contract=contract)
        await service.approve(f"apr_{n}", contract=contract, decision_id=DecisionId(f"d{n}"))
    assert not await service.requires_approval(contract, "affiliate.publish_post")

    await service.revoke_graduation(contract.business_id, "affiliate.publish_post")
    assert await service.requires_approval(contract, "affiliate.publish_post")


async def test_every_decision_writes_a_readable_record(
    session: AsyncSession, contract: BusinessContract
) -> None:
    """Spec §11.5: the operator must be able to ask why without raw logs."""
    service = _service(session)
    await service.request(request=_request(contract), contract=contract)
    await service.approve("apr_1", contract=contract, decision_id=DecisionId("d1"))
    feed = await DecisionLog(session).activity_feed(contract.business_id)
    assert any("approved" in entry.summary for entry in feed)
