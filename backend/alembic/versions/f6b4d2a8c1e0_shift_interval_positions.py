"""link shift intervals to stable venue positions

Revision ID: f6b4d2a8c1e0
Revises: a7d3e5f1c9b2
Create Date: 2026-09-03 16:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b4d2a8c1e0"
down_revision: Union[str, Sequence[str], None] = "a7d3e5f1c9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("shift_intervals") as batch_op:
        batch_op.add_column(sa.Column("position_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shift_intervals_position_id_venue_positions",
            "venue_positions",
            ["position_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_shift_intervals_position_id",
            ["position_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("shift_intervals") as batch_op:
        batch_op.drop_index("ix_shift_intervals_position_id")
        batch_op.drop_constraint(
            "fk_shift_intervals_position_id_venue_positions",
            type_="foreignkey",
        )
        batch_op.drop_column("position_id")
