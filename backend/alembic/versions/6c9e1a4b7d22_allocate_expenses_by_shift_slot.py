"""allocate expenses by DAY and NIGHT shift slots

Revision ID: 6c9e1a4b7d22
Revises: 5b8d0f3a7e21
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6c9e1a4b7d22"
down_revision: Union[str, Sequence[str], None] = "5b8d0f3a7e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="TOTAL"),
    )
    op.create_check_constraint(
        "ck_expenses_shift_slot_valid",
        "expenses",
        "shift_slot IN ('TOTAL', 'DAY', 'NIGHT')",
    )

    op.add_column(
        "recurring_expense_rules",
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="TOTAL"),
    )
    op.create_check_constraint(
        "ck_recurring_expense_rules_shift_slot_valid",
        "recurring_expense_rules",
        "shift_slot IN ('TOTAL', 'DAY', 'NIGHT')",
    )

    op.add_column(
        "expense_recognition_entries",
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"),
    )
    op.create_check_constraint(
        "ck_expense_recognition_entries_shift_slot_valid",
        "expense_recognition_entries",
        "shift_slot IN ('DAY', 'NIGHT')",
    )
    op.create_index(
        "ix_expense_recognition_entries_venue_date_slot",
        "expense_recognition_entries",
        ["venue_id", "recognition_date", "shift_slot"],
        unique=False,
    )

    # Existing recognition rows already contain the correct total for a date.
    # For venues with NIGHT enabled, keep the odd kopeck in DAY and create the
    # complementary NIGHT row so the monthly total remains unchanged.
    op.execute(
        """
        INSERT INTO expense_recognition_entries (
            expense_id,
            venue_id,
            recognition_date,
            shift_slot,
            amount_minor,
            meta_json,
            created_at
        )
        SELECT
            ere.expense_id,
            ere.venue_id,
            ere.recognition_date,
            'NIGHT',
            ere.amount_minor / 2,
            COALESCE(ere.meta_json, '{}'::jsonb)
                || jsonb_build_object(
                    'shift_slot', 'NIGHT',
                    'shift_index', 1,
                    'shifts_in_period', 2
                ),
            ere.created_at
        FROM expense_recognition_entries AS ere
        JOIN venues AS venue ON venue.id = ere.venue_id
        WHERE venue.night_shifts_enabled IS TRUE
          AND ere.amount_minor / 2 > 0
        """
    )
    op.execute(
        """
        UPDATE expense_recognition_entries AS ere
        SET
            shift_slot = 'DAY',
            amount_minor = CASE
                WHEN venue.night_shifts_enabled IS TRUE
                    THEN ere.amount_minor - (ere.amount_minor / 2)
                ELSE ere.amount_minor
            END,
            meta_json = COALESCE(ere.meta_json, '{}'::jsonb)
                || jsonb_build_object(
                    'shift_slot', 'DAY',
                    'shift_index', 0,
                    'shifts_in_period',
                    CASE WHEN venue.night_shifts_enabled IS TRUE THEN 2 ELSE 1 END
                )
        FROM venues AS venue
        WHERE venue.id = ere.venue_id
          AND ere.shift_slot = 'DAY'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expense_recognition_entries_venue_date_slot",
        table_name="expense_recognition_entries",
    )
    op.drop_constraint(
        "ck_expense_recognition_entries_shift_slot_valid",
        "expense_recognition_entries",
        type_="check",
    )
    op.drop_column("expense_recognition_entries", "shift_slot")

    op.drop_constraint(
        "ck_recurring_expense_rules_shift_slot_valid",
        "recurring_expense_rules",
        type_="check",
    )
    op.drop_column("recurring_expense_rules", "shift_slot")

    op.drop_constraint("ck_expenses_shift_slot_valid", "expenses", type_="check")
    op.drop_column("expenses", "shift_slot")
