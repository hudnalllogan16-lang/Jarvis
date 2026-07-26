"""Manager runtime: no schema change.

Revision ID: 0004
Revises: 0003

Milestone 4 adds the Business Manager workflow and the scheduler, both of which
persist their state in Temporal or in tables that already exist. This revision
is a deliberate no-op so the migration history stays aligned with milestone
history — a gap would make it ambiguous later whether a migration was missed or
never needed.
"""

from __future__ import annotations

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No schema change (see module docstring)."""


def downgrade() -> None:
    """No schema change (see module docstring)."""
