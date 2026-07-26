"""Kernel foundation: business registry, audit log, decision log.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Registry (spec §0.1), Audit Log (§11), Decision Log (§11.5)."""
    op.create_table(
        "business_types",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("plugin_metadata", sa.JSON(), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "business_instances",
        sa.Column("business_id", sa.String(64), primary_key=True),
        sa.Column(
            "business_type",
            sa.String(64),
            sa.ForeignKey("business_types.name", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("lifecycle_state", sa.String(24), nullable=False),
        sa.Column("contract", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("display_name", name="uq_business_display_name"),
    )
    op.create_index("ix_business_state", "business_instances", ["lifecycle_state"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=True),
        sa.Column("run_id", sa.String(128), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_business_time", "audit_log", ["business_id", "recorded_at"])
    op.create_index("ix_audit_workflow", "audit_log", ["workflow_id", "sequence"])
    op.create_index("ix_audit_event_type", "audit_log", ["event_type"])

    op.create_table(
        "decision_log",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("business_id", sa.String(64), nullable=True),
        sa.Column("cycle_id", sa.String(64), nullable=True),
        sa.Column("action_type", sa.String(96), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("inputs_considered", sa.JSON(), nullable=False),
        sa.Column("alternatives_rejected", sa.JSON(), nullable=False),
        sa.Column("structured_action", sa.JSON(), nullable=True),
        sa.Column("audit_ref", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(summary) > 0", name="ck_decision_summary_nonempty"),
    )
    op.create_index("ix_decision_business_time", "decision_log", ["business_id", "decided_at"])
    op.create_index("ix_decision_action_type", "decision_log", ["action_type"])


def downgrade() -> None:
    """Drop all kernel foundation tables."""
    op.drop_table("decision_log")
    op.drop_table("audit_log")
    op.drop_table("business_instances")
    op.drop_table("business_types")
