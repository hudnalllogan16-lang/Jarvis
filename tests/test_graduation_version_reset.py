"""A-003's major-version graduation reset (M8-F8).

The rule is asserted in four places — `BusinessTypeRow.version`'s docstring,
`install_business_type`'s docstring, `BusinessTypeDefinition.major_version`, and
the version comments of both live type modules, which each explain that their
bump was minor *on purpose* so as not to trigger it. It is backed by a database
column, `AutonomyCounterRow.plugin_major_version`.

Until M8-8 it had zero readers and zero writers. The column defaulted to 1 and
was never set from a definition, nothing compared an installed major version to
anything, and `_reset_counter` was called on correction, on denial, and on
operator revocation — never on a version change. That is the `KpiEngine.record`
shape exactly (M7-F21: written in M3, callerless for four milestones, found by a
live run), and like it, it was not in the deferred-completion ledger.

These are the reader and the writer, stated as behaviour. The reset runs at
install, not at refresh acceptance: A-003 keys the rule to the version change
itself, and a reset that waited for consent would leave a graduated action
running unattended under changed behaviour for as long as an operator ignored
the offer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.approvals.models import ApprovalRequest
from jarvis.approvals.service import ApprovalService
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId
from jarvis.observability.audit import AuditLog
from jarvis.observability.decision_log import DecisionLog
from jarvis.persistence.models import AuditLogRow, AutonomyCounterRow
from jarvis.registry.registry import BusinessRegistry

ACTION = "affiliate.publish_post"


async def _install(registry: BusinessRegistry, version: str) -> None:
    await registry.install_business_type(
        name=BusinessTypeName("affiliate"),
        version=version,
        display_name="Affiliate publisher",
    )


async def _graduated_counter(
    session: AsyncSession, business_id: BusinessId, *, major: int = 1
) -> AutonomyCounterRow:
    """Seed a counter mid-streak and graduated — what a reset has to undo."""
    row = AutonomyCounterRow(
        business_id=business_id,
        action_type=ACTION,
        consecutive_approvals=5,
        graduated=True,
        plugin_major_version=major,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.fixture
async def company(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> BusinessId:
    await _install(registry, "1.0.0")
    await registry.register_instance(contract)
    return contract.business_id


async def test_a_minor_bump_leaves_the_streak_alone(
    session: AsyncSession, registry: BusinessRegistry, company: BusinessId
) -> None:
    """A-003: "minor versions do not". The two live bumps were deliberately
    minor for exactly this reason, and both type modules say so in a comment."""
    await _graduated_counter(session, company)

    await _install(registry, "1.0.1")
    await _install(registry, "1.1.0")

    counter = await session.get(AutonomyCounterRow, (company, ACTION))
    assert counter is not None
    assert counter.consecutive_approvals == 5
    assert counter.graduated is True


async def test_a_major_bump_resets_the_streak_and_the_graduation(
    session: AsyncSession, registry: BusinessRegistry, company: BusinessId
) -> None:
    """The rule, finally executable: the action's behaviour may have changed,
    so the operator's prior approvals no longer vouch for it."""
    await _graduated_counter(session, company)

    await _install(registry, "2.0.0")

    counter = await session.get(AutonomyCounterRow, (company, ACTION))
    assert counter is not None
    assert counter.consecutive_approvals == 0
    assert counter.graduated is False
    assert counter.plugin_major_version == 2


async def test_the_reset_is_audited_per_counter_and_per_type(
    session: AsyncSession, registry: BusinessRegistry, company: BusinessId
) -> None:
    """§11: a company that could act on its own and now cannot owes an operator
    a record of why, and the audit log is where that is recorded."""
    await _graduated_counter(session, company)

    await _install(registry, "2.0.0")

    rows = list(
        (
            await session.scalars(
                select(AuditLogRow).where(AuditLogRow.event_type == "autonomy.reset")
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].actor == "platform"
    assert rows[0].payload["reason"] == "plugin_major_version"
    assert rows[0].payload["action_type"] == ACTION

    summary = await session.scalar(
        select(AuditLogRow).where(AuditLogRow.event_type == "business_type.graduation_reset")
    )
    assert summary is not None
    assert summary.payload == {
        "name": "affiliate",
        "from_major": 1,
        "to_major": 2,
        "counters_reset": 1,
    }


async def test_a_major_bump_touches_only_its_own_type_s_companies(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """Counters are keyed `(business_instance_id, action_type)` (A-003), and
    the instance belongs to one type. A bump must not reach across."""
    await _install(registry, "1.0.0")
    await registry.install_business_type(
        name=BusinessTypeName("finance_tracking"), version="1.0.2", display_name="Finance tracker"
    )
    await registry.register_instance(contract)
    other = contract.model_copy(
        update={
            "business_id": BusinessId("biz_" + "f" * 32),
            "business_type": BusinessTypeName("finance_tracking"),
            "display_name": "Portfolio Watch",
        }
    )
    await registry.register_instance(other)
    await _graduated_counter(session, contract.business_id)
    await _graduated_counter(session, other.business_id)

    await _install(registry, "2.0.0")

    untouched = await session.get(AutonomyCounterRow, (other.business_id, ACTION))
    assert untouched is not None
    assert untouched.graduated is True


async def test_a_first_install_resets_nothing(
    session: AsyncSession, registry: BusinessRegistry
) -> None:
    """There is no previous version to compare against, and no counter can
    exist yet — a company cannot predate the type it is an instance of."""
    await _install(registry, "3.0.0")

    reset = await session.scalar(
        select(AuditLogRow).where(AuditLogRow.event_type == "business_type.graduation_reset")
    )
    assert reset is None


async def test_a_major_bump_with_nothing_graduated_records_a_reset_of_zero(
    session: AsyncSession, registry: BusinessRegistry, company: BusinessId
) -> None:
    """The live case, which design 4.5 verified read-only: one counter row
    exists in the entire system, at zero and ungraduated, so every migration in
    Part 5 is provably graduation-neutral. A reset that rewrote it anyway would
    produce an audit entry describing something that did not happen."""
    session.add(AutonomyCounterRow(business_id=company, action_type=ACTION, plugin_major_version=2))
    await session.flush()

    await _install(registry, "2.0.0")

    summary = await session.scalar(
        select(AuditLogRow).where(AuditLogRow.event_type == "business_type.graduation_reset")
    )
    assert summary is not None
    assert summary.payload["counters_reset"] == 0
    assert (
        await session.scalar(select(AuditLogRow).where(AuditLogRow.event_type == "autonomy.reset"))
    ) is None


async def test_a_new_counter_is_stamped_with_the_installed_major_version(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """The column's writer. It defaulted to 1 and was never set from a
    definition, which is what made the schema-backed rule unexecutable."""
    await _install(registry, "2.1.0")
    await registry.register_instance(contract)
    approvals = ApprovalService(session, AuditLog(session), DecisionLog(session))
    await approvals.request(
        request=ApprovalRequest(
            approval_id="apr_stamp",
            business_id=contract.business_id,
            action_type=ACTION,
            action_summary="publish today's post",
            triggering_condition="Today's post is ready.",
            downside="A weak post could lose a few readers.",
        ),
        contract=contract,
    )

    await approvals.approve(
        "apr_stamp",
        contract=contract,
        decision_id=DecisionId("dec_stamp"),
    )

    counter = await session.get(AutonomyCounterRow, (contract.business_id, ACTION))
    assert counter is not None
    assert counter.plugin_major_version == 2


async def test_a_stamped_counter_survives_its_own_major_version(
    session: AsyncSession, registry: BusinessRegistry, contract: BusinessContract
) -> None:
    """A counter earned under major 2 is not reset by an unrelated later minor
    bump, which is the whole point of storing the version beside the streak."""
    await _install(registry, "2.0.0")
    await registry.register_instance(contract)
    await _graduated_counter(session, contract.business_id, major=2)

    await _install(registry, "2.5.1")

    counter = await session.get(AutonomyCounterRow, (contract.business_id, ACTION))
    assert counter is not None
    assert counter.graduated is True
    assert counter.consecutive_approvals == 5


async def test_a_refresh_is_not_a_graduation_event(
    session: AsyncSession, registry: BusinessRegistry, company: BusinessId
) -> None:
    """Design 4.5's boundary: v1 refresh is minor-version-scoped, and a
    graduation counter is not a contract field at all (design 4.2). Nothing on
    the refresh path may touch one."""
    from jarvis.businesses.refresh import ContractRefreshService

    await _graduated_counter(session, company)
    service = ContractRefreshService(registry, DecisionLog(session))
    contract = await registry.get_contract(company)
    plan_before = await session.get(AutonomyCounterRow, (company, ACTION))
    assert plan_before is not None

    # The installed type carries no definition blob, so planning refuses rather
    # than guessing — and refusing must also leave the counter alone.
    with pytest.raises(Exception):  # noqa: B017 — any refusal, the point is the counter
        await service.plan_refresh(contract.business_id)

    counter = await session.get(AutonomyCounterRow, (company, ACTION))
    assert counter is not None
    assert counter.graduated is True
    assert counter.consecutive_approvals == 5


def test_major_version_is_read_from_the_definition() -> None:
    """`BusinessTypeDefinition.major_version`'s only consumer anywhere used to
    be one test assertion. Pinned here beside the rule that consumes it."""
    from jarvis.businesses.affiliate import AFFILIATE
    from jarvis.businesses.finance import FINANCE

    assert AFFILIATE.major_version == 1
    assert FINANCE.major_version == 1
    assert Decimal(AFFILIATE.major_version) == 1
