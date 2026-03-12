"""expense recognition and recurring accruals

Revision ID: 2b4c6d8e0f1b
Revises: 1dd2ee3ff4aa
Create Date: 2026-03-12 20:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "2b4c6d8e0f1b"
down_revision = "1dd2ee3ff4aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expense_recognition_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("recognition_date", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_expense_recognition_entries_amount_non_negative"),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expense_recognition_entries_expense", "expense_recognition_entries", ["expense_id", "recognition_date"], unique=False)
    op.create_index(op.f("ix_expense_recognition_entries_expense_id"), "expense_recognition_entries", ["expense_id"], unique=False)
    op.create_index(op.f("ix_expense_recognition_entries_recognition_date"), "expense_recognition_entries", ["recognition_date"], unique=False)
    op.create_index(op.f("ix_expense_recognition_entries_venue_id"), "expense_recognition_entries", ["venue_id"], unique=False)
    op.create_index("ix_expense_recognition_entries_venue_date", "expense_recognition_entries", ["venue_id", "recognition_date"], unique=False)

    op.create_table(
        "recurring_expense_accruals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("accrual_date", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("basis_minor", sa.Integer(), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_minor >= 0", name="ck_recurring_expense_accruals_amount_non_negative"),
        sa.CheckConstraint("basis_minor IS NULL OR basis_minor >= 0", name="ck_recurring_expense_accruals_basis_non_negative"),
        sa.ForeignKeyConstraint(["rule_id"], ["recurring_expense_rules.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "accrual_date", name="uq_recurring_expense_accrual_rule_date"),
    )
    op.create_index(op.f("ix_recurring_expense_accruals_rule_id"), "recurring_expense_accruals", ["rule_id"], unique=False)
    op.create_index(op.f("ix_recurring_expense_accruals_accrual_date"), "recurring_expense_accruals", ["accrual_date"], unique=False)
    op.create_index(op.f("ix_recurring_expense_accruals_venue_id"), "recurring_expense_accruals", ["venue_id"], unique=False)
    op.create_index("ix_recurring_expense_accruals_venue_date", "recurring_expense_accruals", ["venue_id", "accrual_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_recurring_expense_accruals_venue_date", table_name="recurring_expense_accruals")
    op.drop_index(op.f("ix_recurring_expense_accruals_venue_id"), table_name="recurring_expense_accruals")
    op.drop_index(op.f("ix_recurring_expense_accruals_accrual_date"), table_name="recurring_expense_accruals")
    op.drop_index(op.f("ix_recurring_expense_accruals_rule_id"), table_name="recurring_expense_accruals")
    op.drop_table("recurring_expense_accruals")

    op.drop_index("ix_expense_recognition_entries_venue_date", table_name="expense_recognition_entries")
    op.drop_index(op.f("ix_expense_recognition_entries_venue_id"), table_name="expense_recognition_entries")
    op.drop_index(op.f("ix_expense_recognition_entries_recognition_date"), table_name="expense_recognition_entries")
    op.drop_index(op.f("ix_expense_recognition_entries_expense_id"), table_name="expense_recognition_entries")
    op.drop_index("ix_expense_recognition_entries_expense", table_name="expense_recognition_entries")
    op.drop_table("expense_recognition_entries")
