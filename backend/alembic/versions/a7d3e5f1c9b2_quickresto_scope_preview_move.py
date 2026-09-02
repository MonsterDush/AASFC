"""allow confirmed QuickResto historical shifts to move to another connection

Revision ID: a7d3e5f1c9b2
Revises: f4c6e8a0b2d5
Create Date: 2026-09-02 19:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "a7d3e5f1c9b2"
down_revision: Union[str, Sequence[str], None] = "f4c6e8a0b2d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSTRAINT = "ck_quickresto_shift_imports_scope_resolution_action"


def upgrade() -> None:
    with op.batch_alter_table("quickresto_shift_imports") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT,
            "scope_resolution_action IS NULL OR "
            "scope_resolution_action IN ('KEEP_CURRENT', 'EXCLUDE_CURRENT', 'MOVE_TO_CONNECTED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("quickresto_shift_imports") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT,
            "scope_resolution_action IS NULL OR "
            "scope_resolution_action IN ('KEEP_CURRENT', 'EXCLUDE_CURRENT')",
        )
