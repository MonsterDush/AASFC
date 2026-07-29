"""enforce DAY and NIGHT shift slot values

Revision ID: 5b8d0f3a7e21
Revises: 4a7c9e2b6d10
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "5b8d0f3a7e21"
down_revision: Union[str, Sequence[str], None] = "4a7c9e2b6d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SHIFT_SLOT_TABLES = (
    ("shifts", "ck_shifts_shift_slot_valid"),
    ("daily_reports", "ck_daily_reports_shift_slot_valid"),
    (
        "daily_report_attachments",
        "ck_daily_report_attachments_shift_slot_valid",
    ),
    (
        "shift_schedule_template_items",
        "ck_shift_schedule_template_items_shift_slot_valid",
    ),
)


def upgrade() -> None:
    for table_name, constraint_name in _SHIFT_SLOT_TABLES:
        op.execute(
            f"UPDATE {table_name} SET shift_slot = 'DAY' "
            "WHERE shift_slot IS NULL OR shift_slot NOT IN ('DAY', 'NIGHT')"
        )
        op.create_check_constraint(
            constraint_name,
            table_name,
            "shift_slot IN ('DAY', 'NIGHT')",
        )


def downgrade() -> None:
    for table_name, constraint_name in reversed(_SHIFT_SLOT_TABLES):
        op.drop_constraint(constraint_name, table_name, type_="check")
