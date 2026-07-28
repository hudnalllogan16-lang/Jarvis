"""SQLAlchemy ORM models for Kernel-owned state.

Covers the Business Registry (spec §0.1), the Audit Log (spec §11), and the
Decision Log (spec §11.5). Per §11.5 the two logs are separate artifacts for
separate audiences — the Decision Log is not a filtered view of the audit log —
so they are separate tables with separate write paths, not one table with a flag.

Both log tables are append-only at the application layer (A-006): no update or
delete path exists anywhere in this codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Wall-clock read. Never called from workflow code (D-004)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all Jarvis tables."""


class BusinessTypeRow(Base):
    """An installed business type, i.e. a plugin (spec §0.1, §4).

    Records plugin metadata and installed version. A business type becomes
    instantiable by configuration alone once installed (spec §4).
    """

    __tablename__ = "business_types"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    """Semantic version. A **major** bump resets autonomy graduation counters
    for instances of this type (A-003)."""

    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    """Operator-facing "company template" name (D-007)."""

    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    """Operator toggle (D-017): a disabled type is hidden from the create flow.
    Existing companies are governed by their own pause state, not by this."""

    plugin_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class BusinessInstanceRow(Base):
    """A registered business instance (spec §0.1).

    Identifiers are permanent and never reused. `contract` holds the serialized
    Standard Business Contract (spec §5); the Registry is the only writer.
    """

    __tablename__ = "business_instances"
    __table_args__ = (
        UniqueConstraint("display_name", name="uq_business_display_name"),
        Index("ix_business_state", "lifecycle_state"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_type: Mapped[str] = mapped_column(
        ForeignKey("business_types.name", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False)
    contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ContractRefreshDeclineRow(Base):
    """The operator's most recent "Not now" to a company's contract refresh
    (D-030, design PLUGIN-FRAMEWORK.md Part 4.3; M8-F102/M9-4).

    One row per company, upserted on every `decline_refresh` call — this is
    not a history (the Decision Log already carries an append-only entry for
    every decline an operator can read; spec §11.5). It exists to answer one
    question for `plan_refresh`: "is the version installed right now the one
    this company's operator already said no to." A different version answers
    no, and the plan is offered again — Part 4.3's "re-offered only on the
    next version change" made literal.

    `declined_version` is what `plan_refresh` compares against, deliberately
    **not** a content digest. `business_type.py`'s `compute_digest` docstring
    records the live case this guards against (M8-F3): the installed
    `affiliate` type's stored definition once differed from what its own
    declared version implied, with no version bump in between. A digest keyed
    to content would treat that kind of same-version drift exactly like a
    real version change and silently clear a decline the operator never
    revisited. A digest cannot tell "the type changed" from "the type's stored
    row drifted while claiming to be the same" apart — only the version string
    can, so suppression is keyed on it. `source_digest`/`target_digest` are
    kept anyway, not for suppression but so a decline row is self-describing:
    what the company looked like and what it would have become, for an
    operator's or developer's own "why is this suppressed" question.
    """

    __tablename__ = "contract_refresh_declines"

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    declined_version: Mapped[str] = mapped_column(String(32), nullable=False)
    """The installed type version this decline suppresses. `plan_refresh`
    re-offers as soon as the currently installed version differs from this."""

    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    """Band B digest of the contract at decline time (audit context only)."""

    target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    """Band B digest the declined plan would have produced (audit context only)."""

    declined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AuditLogRow(Base):
    """Forensic record of every technical event (spec §11).

    Append-only. Complete: every tool call, model call, approval decision,
    workflow step, event, expense, retry, and Manager decision. This is the
    drill-down artifact, never the operator's default view (spec §12.5).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_business_time", "business_id", "recorded_at"),
        Index("ix_audit_workflow", "workflow_id", "sequence"),
        Index("ix_audit_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Null for platform-level events such as a circuit-breaker trip (spec §9)."""

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """Temporal run identifier. Temporal history is the replay substrate; this
    column is the join key back to it (D-004)."""

    sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class DecisionLogRow(Base):
    """Human-readable business narrative (spec §11.5).

    A first-class component, not a byproduct and not a filtered audit view. It
    must answer "why did this company do X" on its own, without reading raw
    audit logs (spec §11.5).

    `summary` and `rationale` are the operator-facing text (spec §12.5); the
    structured columns beside them exist so that approval prompts can be
    *rendered from data* rather than authored freely by a model — the action,
    amount, and counterparty an operator approves must be structured values
    (spec §8 requires the exact amount and downside be displayed).
    """

    __tablename__ = "decision_log"
    __table_args__ = (
        Index("ix_decision_business_time", "business_id", "decided_at"),
        Index("ix_decision_action_type", "action_type"),
        CheckConstraint("length(summary) > 0", name="ck_decision_summary_nonempty"),
    )

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Null for Executive and platform decisions — capital reallocation, company
    retirement, breaker trips — which have no owning business but still owe the
    operator a "why" (spec §3.1, §9, §12.5)."""

    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(96), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    """One plain sentence: what the company did. Shown in the activity feed."""

    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    """Plain-language why, readable without any technical context."""

    inputs_considered: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    alternatives_rejected: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    structured_action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Action, amount, counterparty, risk — as data, for rendering (spec §8)."""

    audit_ref: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Optional pointer into the audit log for drill-down (spec §12.5). The
    Decision Log must stand alone without following it."""

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── Milestone 2: execution spine ────────────────────────────────────────────


class EventRow(Base):
    """One published event (spec §2).

    Cross-business signals and independent reactions travel here, never as
    direct calls between workers (spec §2).
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_type_time", "event_type", "published_at"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Emitting business, or None for platform events."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class EventConsumptionRow(Base):
    """Deduplication record: this consumer has already handled this event (A-002).

    Delivery is at-least-once, so the composite primary key is the deduplication
    mechanism — a duplicate delivery collides on insert and is discarded rather
    than producing a second wake cycle or a second approval request.
    """

    __tablename__ = "event_consumptions"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumer_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class BudgetLedgerRow(Base):
    """One reservation or settlement against the budget hierarchy (D-003, D-022).

    Reservations count against ceilings from the moment they are taken, so two
    concurrent invocations cannot each pass a pre-flight check against the same
    remaining headroom and then both spend it. D-022 is what makes that true
    under concurrency: the row is written and committed in its own short
    transaction, under a per-scope advisory lock, before the work starts.
    """

    __tablename__ = "budget_ledger"
    __table_args__ = (
        Index("ix_ledger_business_time", "business_id", "recorded_at"),
        Index("ix_ledger_cycle", "cycle_id"),
        Index("ix_ledger_state_time", "state", "recorded_at"),
        Index("ix_ledger_business_state", "business_id", "state"),
        CheckConstraint("amount_usd >= 0", name="ck_ledger_amount_nonnegative"),
        CheckConstraint(
            "state in ('RESERVED', 'SETTLED', 'RELEASED')",
            name="ck_ledger_state_known",
        ),
    )
    """`ix_ledger_business_state` serves the business-cap aggregate, which under
    D-022 runs inside a globally serialized section — a sequential scan there is
    a throughput hazard for every business at once.

    `ck_ledger_state_known` is a security constraint, not tidiness: only
    RESERVED and SETTLED count toward a ceiling, so a row with any other state
    is spend that no ceiling sees. The database refusing the write is the only
    check that survives a future writer bypassing this module."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    invocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    """RESERVED, SETTLED, or RELEASED. Only RELEASED stops counting."""

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class IdempotencyRow(Base):
    """Result cache keyed by the A-001 idempotency key (spec §6).

    Keyed on the invocation rather than the attempt, so a retry (spec §9) or a
    workflow replay (D-004) collapses to a single external effect.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(96), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class DeadLetterRow(Base):
    """An invocation that exhausted its retries (spec §9).

    Visible in the dashboard as "[Company] got stuck — here's what happened"
    (spec §12.5). `operator_summary` is stored rather than derived at read time
    so the dashboard never renders a stack trace by accident.
    """

    __tablename__ = "dead_letters"
    __table_args__ = (Index("ix_dlq_business_time", "business_id", "recorded_at"),)

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False)
    operator_summary: Mapped[str] = mapped_column(Text, nullable=False)
    technical_detail: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── Milestone 3: operator surface ───────────────────────────────────────────


class ApprovalRow(Base):
    """One human approval request (spec §8).

    The structured columns are load-bearing, not convenience. Spec §8 requires
    the approval UI to display the specific action, exact amount, triggering
    condition, and downside — and §12.5 requires plain operator language. If
    those four facts were carried only inside model-authored prose, the numbers
    an operator approves would be regenerated text rather than data. They are
    stored as values and rendered into language at display time.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approval_state_time", "state", "requested_at"),
        Index("ix_approval_business", "business_id", "requested_at"),
    )

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(96), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)

    action_summary: Mapped[str] = mapped_column(Text, nullable=False)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(200), nullable=True)
    triggering_condition: Mapped[str] = mapped_column(Text, nullable=False)
    downside: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    decision_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Decision Log entry carrying the "why" (spec §11.5, §12.5)."""

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    """Drives the 24h re-notification requirement (spec §9)."""

    decided_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Set when the operator changed parameters before approving. A difference
    here is a correction, which counts as a denial for graduation (A-003)."""


class AutonomyCounterRow(Base):
    """Consecutive clean approvals per action type (spec §8, identity per A-003).

    Reset to zero by any denial or correction. Spec §8 requires the streak be
    unbroken, so this is a counter with a reset, not a ratio.
    """

    __tablename__ = "autonomy_counters"

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(96), primary_key=True)
    consecutive_approvals: Mapped[int] = mapped_column(default=0, nullable=False)
    graduated: Mapped[bool] = mapped_column(default=False, nullable=False)
    plugin_major_version: Mapped[int] = mapped_column(default=1, nullable=False)
    """A major version bump resets the counter (A-003): the action's behaviour
    may have changed, so the operator's prior approvals no longer vouch for it."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class NotificationRow(Base):
    """One operator-facing notification (spec §5, §9).

    Body text is written in plain consequence language at creation time rather
    than templated at read time, so a notification cannot leak a technical error
    into the default view (spec §12.5).
    """

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_unread", "read", "created_at"),)

    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    read: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class KpiValueRow(Base):
    """One recorded KPI observation (spec §5).

    §13 Step 1 lists a "KPI engine" that no normative section specifies. This is
    the minimum that satisfies §5's contract obligation and §11's dashboard
    requirement: an append-only series per business per metric.
    """

    __tablename__ = "kpi_values"
    __table_args__ = (Index("ix_kpi_business_key_time", "business_id", "key", "recorded_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
