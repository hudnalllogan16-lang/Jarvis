"""Execution spine: events, deduplication, budget ledger, idempotency, dead letters.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Milestone 2 tables (spec §2, §6, §9; D-003, A-001, A-002)."""
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("business_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_type_time", "events", ["event_type", "published_at"])

    # Composite primary key is the deduplication mechanism (A-002): a duplicate
    # delivery collides on insert rather than producing a second wake cycle.
    op.create_table(
        "event_consumptions",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("consumer_id", sa.String(96), primary_key=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "budget_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("invocation_id", sa.String(64), nullable=True),
        sa.Column("cycle_id", sa.String(64), nullable=True),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_usd >= 0", name="ck_ledger_amount_nonnegative"),
    )
    op.create_index("ix_ledger_business_time", "budget_ledger", ["business_id", "recorded_at"])
    op.create_index("ix_ledger_cycle", "budget_ledger", ["cycle_id"])
    op.create_index("ix_ledger_state_time", "budget_ledger", ["state", "recorded_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(96), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "dead_letters",
        sa.Column("invocation_id", sa.String(64), primary_key=True),
        sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("operator_summary", sa.Text(), nullable=False),
        sa.Column("technical_detail", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dlq_business_time", "dead_letters", ["business_id", "recorded_at"])


def downgrade() -> None:
    """Drop Milestone 2 tables."""
    op.drop_table("dead_letters")
    op.drop_table("idempotency_keys")
    op.drop_table("budget_ledger")
    op.drop_table("event_consumptions")
    op.drop_table("events")
