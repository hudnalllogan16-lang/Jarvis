"""Runtime heartbeat table (design OPERATIONAL-RUNTIME.md Part 3.2, D-058, packet P0-B).

Revision ID: 0008
Revises: 0007

M10-F18: nothing in the repository recorded that a runtime existed, which
parts it ran, or when it last spoke — every liveness question was answered by
after-the-fact inference from Temporal's own history. `runtime_heartbeat` is
the self-report half of the two-signal liveness design (3.2/3.3): one row per
`(runtime_id, part_name)`, upserted by the Supervisor's heartbeat loop and
read back by `/api/health`'s `runtime` component (and, once packet P0-C wires
the poller probe, the Executive's liveness verdict). No existing table
changes and nothing here is read by anything shipped before this packet, so
there is no data to reconcile.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create `runtime_heartbeat`."""
    op.create_table(
        "runtime_heartbeat",
        sa.Column("runtime_id", sa.String(length=36), primary_key=True),
        sa.Column("part_name", sa.String(length=32), primary_key=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_beat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("consecutive_crashes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=300), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Drop `runtime_heartbeat`."""
    op.drop_table("runtime_heartbeat")
