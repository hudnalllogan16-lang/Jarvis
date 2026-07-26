"""Subsystem toggles: enabled flag on business types (D-017).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the operator's enable/disable toggle to business types."""
    op.add_column(
        "business_types",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Remove the toggle."""
    op.drop_column("business_types", "enabled")
