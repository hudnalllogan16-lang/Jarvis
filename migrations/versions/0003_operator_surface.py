"""Operator surface: approvals, autonomy counters, notifications, KPI values.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Milestone 3 tables (spec §5, §8, §9)."""
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(64), primary_key=True),
        sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(96), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("counterparty", sa.String(200), nullable=True),
        sa.Column("triggering_condition", sa.Text(), nullable=False),
        sa.Column("downside", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("decision_ref", sa.String(64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_parameters", sa.JSON(), nullable=True),
    )
    op.create_index("ix_approval_state_time", "approvals", ["state", "requested_at"])
    op.create_index("ix_approval_business", "approvals", ["business_id", "requested_at"])

    op.create_table(
        "autonomy_counters",
        sa.Column("business_id", sa.String(64), primary_key=True),
        sa.Column("action_type", sa.String(96), primary_key=True),
        sa.Column("consecutive_approvals", sa.Integer(), nullable=False),
        sa.Column("graduated", sa.Boolean(), nullable=False),
        sa.Column("plugin_major_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(64), primary_key=True),
        sa.Column("business_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link_ref", sa.String(64), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_unread", "notifications", ["read", "created_at"])

    op.create_table(
        "kpi_values",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_kpi_business_key_time", "kpi_values", ["business_id", "key", "recorded_at"])


def downgrade() -> None:
    """Drop Milestone 3 tables."""
    op.drop_table("kpi_values")
    op.drop_table("notifications")
    op.drop_table("autonomy_counters")
    op.drop_table("approvals")
