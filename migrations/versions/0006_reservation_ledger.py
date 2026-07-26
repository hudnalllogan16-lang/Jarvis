"""Reservation ledger integrity and lookup (D-022).

Revision ID: 0006
Revises: 0005

D-022 moves a budget reservation into its own short transaction, serialized per
scope, so that the check-then-insert cannot be interleaved (M6-F12). Two schema
consequences:

* ``ck_ledger_state_known`` — only RESERVED and SETTLED count toward a ceiling,
  so a row holding any other state is spend no ceiling can see. Enforced by the
  database because that is the check that still holds if some future writer
  bypasses `jarvis.budget.ledger`.
* ``ix_ledger_business_state`` — the business-cap aggregate now runs inside a
  serialized section, where a sequential scan costs every business at once.

Both are additive and neither rewrites a row. The CHECK is validated against
existing rows on creation, so it fails loudly rather than silently admitting bad
data — verified against a scratch copy of the live schema before this ran on the
real database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

KNOWN_STATES = ("RESERVED", "SETTLED", "RELEASED")


def upgrade() -> None:
    """Constrain ledger states and index the business-cap aggregate."""
    bind = op.get_bind()

    unknown = bind.execute(
        sa.text(
            "SELECT count(*) FROM budget_ledger "
            "WHERE state NOT IN ('RESERVED', 'SETTLED', 'RELEASED')"
        )
    ).scalar_one()
    if unknown:
        # Fail before the constraint does, with a message that says what to look
        # at. A migration that dies on an opaque integrity error against live
        # spend data is a bad half-hour for whoever is on the other end.
        msg = (
            f"{unknown} budget_ledger row(s) hold a state outside "
            f"{KNOWN_STATES}; those rows count toward no ceiling and must be "
            "reconciled before this constraint can be added"
        )
        raise RuntimeError(msg)

    op.create_check_constraint(
        "ck_ledger_state_known",
        "budget_ledger",
        "state in ('RESERVED', 'SETTLED', 'RELEASED')",
    )
    op.create_index("ix_ledger_business_state", "budget_ledger", ["business_id", "state"])


def downgrade() -> None:
    """Drop the constraint and the index."""
    op.drop_index("ix_ledger_business_state", table_name="budget_ledger")
    op.drop_constraint("ck_ledger_state_known", "budget_ledger", type_="check")
