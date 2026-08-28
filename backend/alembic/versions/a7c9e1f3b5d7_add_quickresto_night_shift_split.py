"""add QuickResto night shift split

Revision ID: a7c9e1f3b5d7
Revises: e5f7a9b1c3d5
Create Date: 2026-08-29 00:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7c9e1f3b5d7"
down_revision: Union[str, Sequence[str], None] = "e5f7a9b1c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quickresto_connections",
        sa.Column("night_shift_split_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "quickresto_connections",
        sa.Column("night_shift_start_hour", sa.Integer(), nullable=False, server_default="22"),
    )
    op.create_check_constraint(
        "ck_quickresto_connections_night_start_hour",
        "quickresto_connections",
        "night_shift_start_hour >= 0 AND night_shift_start_hour <= 23",
    )
    op.create_check_constraint(
        "ck_quickresto_connections_night_after_cutoff",
        "quickresto_connections",
        "NOT night_shift_split_enabled OR night_shift_start_hour > business_day_cutoff_hour",
    )

    op.add_column(
        "quickresto_shift_imports",
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"),
    )
    op.create_check_constraint(
        "ck_quickresto_shift_imports_shift_slot",
        "quickresto_shift_imports",
        "shift_slot IN ('DAY', 'NIGHT')",
    )
    op.create_index(
        "ix_quickresto_shift_imports_connection_date_slot",
        "quickresto_shift_imports",
        ["connection_id", "business_date", "shift_slot"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quickresto_shift_imports_connection_date_slot",
        table_name="quickresto_shift_imports",
    )
    op.drop_constraint(
        "ck_quickresto_shift_imports_shift_slot",
        "quickresto_shift_imports",
        type_="check",
    )
    op.drop_column("quickresto_shift_imports", "shift_slot")

    op.drop_constraint(
        "ck_quickresto_connections_night_after_cutoff",
        "quickresto_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_quickresto_connections_night_start_hour",
        "quickresto_connections",
        type_="check",
    )
    op.drop_column("quickresto_connections", "night_shift_start_hour")
    op.drop_column("quickresto_connections", "night_shift_split_enabled")
