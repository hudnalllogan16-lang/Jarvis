"""Contract-refresh decline persistence (D-030, M8-F102/M9-4).

Revision ID: 0007
Revises: 0006

Design PLUGIN-FRAMEWORK.md Part 4.3: a declined contract-refresh plan is
re-offered only on the next version change to the company's installed type.
Until this, nothing stored that fact — "Not now" wrote a Decision Log entry
and suppressed nothing (audit Finding 3), so the same plan reappeared on the
very next look.

One new leaf table, `contract_refresh_declines`, one row per company,
upserted by `decline_refresh` and read by `plan_refresh`. No existing table
changes, so there is no data to reconcile and no `server_default` question —
this is a pure addition.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create `contract_refresh_declines`."""
    op.create_table(
        "contract_refresh_declines",
        sa.Column("business_id", sa.String(length=64), primary_key=True),
        sa.Column("declined_version", sa.String(length=32), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("target_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "declined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Drop `contract_refresh_declines`."""
    op.drop_table("contract_refresh_declines")
