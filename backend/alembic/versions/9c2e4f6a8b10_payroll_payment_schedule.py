"""add payroll payment settings and payout expenses

Revision ID: 9c2e4f6a8b10
Revises: 8b4d1e7a9c20
Create Date: 2026-08-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9c2e4f6a8b10"
down_revision: Union[str, Sequence[str], None] = "8b4d1e7a9c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_payment_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=True),
        sa.Column("cadence", sa.String(length=16), server_default="MONTHLY", nullable=False),
        sa.Column("weekly_payment_weekday", sa.Integer(), nullable=True),
        sa.Column("monthly_rules_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "cadence IN ('DAILY', 'WEEKLY', 'MONTHLY')",
            name="ck_payroll_payment_settings_cadence",
        ),
        sa.CheckConstraint(
            "weekly_payment_weekday IS NULL OR (weekly_payment_weekday >= 0 AND weekly_payment_weekday <= 6)",
            name="ck_payroll_payment_settings_weekday",
        ),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_methods.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", name="uq_payroll_payment_settings_venue"),
    )
    op.create_index("ix_payroll_payment_settings_venue_id", "payroll_payment_settings", ["venue_id"], unique=False)
    op.create_index(
        "ix_payroll_payment_settings_payment_method_id",
        "payroll_payment_settings",
        ["payment_method_id"],
        unique=False,
    )

    op.add_column(
        "expenses",
        sa.Column("expense_kind", sa.String(length=24), server_default="OPERATING", nullable=False),
    )
    op.add_column("expenses", sa.Column("payroll_run_id", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("payroll_period_start", sa.Date(), nullable=True))
    op.add_column("expenses", sa.Column("payroll_period_end", sa.Date(), nullable=True))
    op.add_column("expenses", sa.Column("payroll_payout_key", sa.String(length=160), nullable=True))
    op.create_check_constraint(
        "ck_expenses_expense_kind_valid",
        "expenses",
        "expense_kind IN ('OPERATING', 'PAYROLL')",
    )
    op.create_foreign_key(
        "fk_expenses_payroll_run_id_payroll_runs",
        "expenses",
        "payroll_runs",
        ["payroll_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_expenses_payroll_payout_key", "expenses", ["payroll_payout_key"])
    op.create_index("ix_expenses_payroll_run_id", "expenses", ["payroll_run_id"], unique=False)
    op.create_index("ix_expenses_payroll_period_start", "expenses", ["payroll_period_start"], unique=False)
    op.create_index("ix_expenses_payroll_period_end", "expenses", ["payroll_period_end"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_expenses_payroll_period_end", table_name="expenses")
    op.drop_index("ix_expenses_payroll_period_start", table_name="expenses")
    op.drop_index("ix_expenses_payroll_run_id", table_name="expenses")
    op.drop_constraint("uq_expenses_payroll_payout_key", "expenses", type_="unique")
    op.drop_constraint("fk_expenses_payroll_run_id_payroll_runs", "expenses", type_="foreignkey")
    op.drop_constraint("ck_expenses_expense_kind_valid", "expenses", type_="check")
    op.drop_column("expenses", "payroll_payout_key")
    op.drop_column("expenses", "payroll_period_end")
    op.drop_column("expenses", "payroll_period_start")
    op.drop_column("expenses", "payroll_run_id")
    op.drop_column("expenses", "expense_kind")

    op.drop_index("ix_payroll_payment_settings_payment_method_id", table_name="payroll_payment_settings")
    op.drop_index("ix_payroll_payment_settings_venue_id", table_name="payroll_payment_settings")
    op.drop_table("payroll_payment_settings")
