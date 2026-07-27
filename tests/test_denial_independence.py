"""D-025.1 proved where SQLite cannot see it (D-025.2, closing M6-F40).

**Why this file is not part of the SQLite suite.** D-025.1's claim has two
halves: the denial record commits, *and* the caller's in-flight work still rolls
back. `test_denial_persistence.py` can assert the first half only, and says so in
`test_a_denial_alongside_other_work_still_persists`: under `StaticPool` every
session shares one connection, so the independent commit sweeps up whatever the
caller had pending, and a file-backed SQLite goes the other way and blocks the
independent write behind the single-writer lock, losing the denial instead. Both
are substitution artefacts. A test asserting either would be asserting SQLite.

D-025.2 decided that the correctness of D-022 and D-025.1 is therefore gated by
Postgres-backed tests, and recorded the outstanding half as M6-F40 — "denial
rows 1, caller-work rows 0" was verified by hand against a throwaway database
and never committed as a test. This is that test. D-022's half already lives in
`test_budget_reservation_concurrency.py`; this is the same pattern, same
disposable schema, same visible skip when the stack is down.

The refusals exercised here are the tool boundary's two: the unpermitted tool
(M6-F39) and the unresolvable credential (M6-F42, closed by D-034.4). Both reach
`AuditLog.record_independently`, so what is under test is the mechanism, and the
two call sites are here to keep it from being proved for one of them only.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from jarvis.capabilities.idempotency import IdempotencyStore
from jarvis.capabilities.tools import ToolExecutor
from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import InvocationId
from jarvis.observability.audit import AuditLog
from jarvis.persistence.models import AuditLogRow, IdempotencyRow
from jarvis.security.credentials import CredentialManager

pytestmark = pytest.mark.postgres

DATABASE_URL = os.environ.get(
    "JARVIS_TEST_DATABASE_URL", "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
)
"""Same default as `migrations/env.py`. Overridable, so this can be pointed at a
throwaway instance without editing the test."""

CALLER_WORK = "probe.work_in_progress"
"""An ordinary, transaction-bound audit write standing in for whatever the
refusing caller had already done. It is the control: a mechanism that made
*everything* survive a rollback would not be independence, it would be a missing
transaction."""


@pytest_asyncio.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory over a disposable schema on the live database."""
    admin = create_async_engine(DATABASE_URL, poolclass=NullPool)
    schema = f"jarvis_denial_probe_{uuid.uuid4().hex[:12]}"
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:
        await admin.dispose()
        pytest.skip(f"live Postgres unavailable ({type(exc).__name__}); D-025.1 UNPROVEN here")

    engine = create_async_engine(
        DATABASE_URL, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(AuditLogRow.__table__.create)
            await conn.run_sync(IdempotencyRow.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


def _executor(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    *,
    secrets: dict[str, str] | None = None,
) -> ToolExecutor:
    """Build the tool boundary the way the Kernel does: audit log with a factory."""
    return ToolExecutor(
        credentials=CredentialManager(secrets or {}),
        idempotency=IdempotencyStore(session),
        audit=AuditLog(session, denial_sessions=factory),
    )


async def _counts(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Return audit-row counts per event type, read on a fresh connection."""
    async with factory() as session:
        rows = await session.execute(
            select(AuditLogRow.event_type, func.count()).group_by(AuditLogRow.event_type)
        )
        return dict(rows.all())  # type: ignore[arg-type]


async def _refuse_inside_a_doomed_transaction(
    sessions: async_sessionmaker[AsyncSession],
    contract: BusinessContract,
    *,
    tool_name: str,
    credential_handle: str | None,
) -> None:
    """Do some work, get refused, and let the refusal unwind the transaction.

    Exactly the shape of the live path: `execute_approved_action` opens a scope,
    does work in it, and `kernel.services()` rolls that scope back when the
    refusal propagates.
    """
    session = sessions()
    try:
        await AuditLog(session, denial_sessions=sessions).record(
            event_type=CALLER_WORK, actor="platform", business_id=contract.business_id
        )
        with pytest.raises(ScopeViolationError):
            await _executor(session, sessions).execute(
                contract=contract,
                invocation_id=InvocationId("inv_probe"),
                tool_name=tool_name,
                implementation_key="webhook_publish",
                action_type="affiliate.publish_post",
                params={"title": "T", "body": "B"},
                credential_handle=credential_handle,
                granted_credentials=frozenset(),
            )
        await session.rollback()
    finally:
        await session.close()


async def test_a_credential_refusal_outlives_the_transaction_it_aborted(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """M6-F42 closed, and proved on the engine that can show it (D-034.4).

    The contract permits `web_search` and the handle `serp_key`, and the
    invocation is granted nothing — so resolution refuses, the effect never
    happens, and before D-034.4 that was the end of it: no record anywhere, and
    an owner left looking at an approval they gave that nothing acted on.

    Both halves in one read. The denial row survived a transaction that rolled
    back; the caller's own row, written moments earlier in that same
    transaction, did not.
    """
    await _refuse_inside_a_doomed_transaction(
        sessions, contract, tool_name="web_search", credential_handle="serp_key"
    )

    counts = await _counts(sessions)
    assert counts.get("tool.refused") == 1, "the refusal is on the record"
    assert counts.get(CALLER_WORK) is None, "and the work it aborted is not"


async def test_an_unpermitted_tool_refusal_is_independent_too(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """M6-F39's refusal, through the same mechanism, on the same engine.

    Proved separately rather than assumed from the test above, because
    `record_independently` is reached from two call sites and a future edit that
    turned one of them back into a plain `record` would leave this file green
    while the sweep in `test_denial_persistence.py` — which reads source, not
    behaviour — is the only other thing watching.
    """
    await _refuse_inside_a_doomed_transaction(
        sessions, contract, tool_name="wire_transfer", credential_handle=None
    )

    counts = await _counts(sessions)
    assert counts.get("tool.refused") == 1
    assert counts.get(CALLER_WORK) is None


async def test_an_ordinary_audit_write_is_not_independent(
    sessions: async_sessionmaker[AsyncSession], contract: BusinessContract
) -> None:
    """The negative control: independence is a property of `record_independently`.

    Without it, "the denial survived" would be equally true of a codebase whose
    audit writes committed eagerly one at a time — which would break D-008 I-6's
    requirement that a lifecycle change and its log entries commit together, and
    would make this whole file prove nothing about the denial path in particular.
    """
    async with sessions() as session:
        log = AuditLog(session, denial_sessions=sessions)
        await log.record(event_type=CALLER_WORK, actor="platform")
        await log.record_independently(event_type="tool.refused", actor="platform")
        await session.rollback()

    counts = await _counts(sessions)
    assert counts.get("tool.refused") == 1
    assert counts.get(CALLER_WORK) is None
