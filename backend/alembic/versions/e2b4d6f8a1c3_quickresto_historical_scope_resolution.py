"""resolve historical QuickResto scope mismatches

Revision ID: e2b4d6f8a1c3
Revises: d0f8b6c4e2a1
Create Date: 2026-09-02 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2b4d6f8a1c3"
down_revision: Union[str, Sequence[str], None] = "d0f8b6c4e2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("quickresto_shift_imports") as batch_op:
        batch_op.add_column(sa.Column("scope_resolution_action", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("scope_resolution_generation", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("scope_resolved_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("scope_resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("scope_resolution_note", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_shift_imports_scope_resolved_by_user_id_users",
            "users",
            ["scope_resolved_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_quickresto_shift_imports_scope_resolution_action",
            "scope_resolution_action IS NULL OR "
            "scope_resolution_action IN ('KEEP_CURRENT', 'EXCLUDE_CURRENT')",
        )
        batch_op.create_index(
            "ix_quickresto_shift_imports_scope_resolution_action",
            ["scope_resolution_action"],
        )
        batch_op.create_index(
            "ix_quickresto_shift_imports_scope_resolved_by_user_id",
            ["scope_resolved_by_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("quickresto_shift_imports") as batch_op:
        batch_op.drop_index("ix_quickresto_shift_imports_scope_resolved_by_user_id")
        batch_op.drop_index("ix_quickresto_shift_imports_scope_resolution_action")
        batch_op.drop_constraint(
            "ck_quickresto_shift_imports_scope_resolution_action",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_quickresto_shift_imports_scope_resolved_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("scope_resolution_note")
        batch_op.drop_column("scope_resolved_at")
        batch_op.drop_column("scope_resolved_by_user_id")
        batch_op.drop_column("scope_resolution_generation")
        batch_op.drop_column("scope_resolution_action")
