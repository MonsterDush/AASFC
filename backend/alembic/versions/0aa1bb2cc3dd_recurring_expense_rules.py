"""recurring expense rules

Revision ID: 0aa1bb2cc3dd
Revises: f9c8b7a6d5e4
Create Date: 2026-03-12 16:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0aa1bb2cc3dd"
down_revision = "f9c8b7a6d5e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_expense_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("payment_method_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("frequency", sa.String(length=16), nullable=False, server_default="MONTHLY"),
        sa.Column("day_of_month", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generation_mode", sa.String(length=16), nullable=False, server_default="FIXED"),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("percent_bps", sa.Integer(), nullable=True),
        sa.Column("spread_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("day_of_month >= 1 AND day_of_month <= 31", name="ck_recurring_expense_rules_day_of_month_range"),
        sa.CheckConstraint("spread_months >= 1", name="ck_recurring_expense_rules_spread_months_positive"),
        sa.CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_recurring_expense_rules_amount_minor_non_negative"),
        sa.CheckConstraint("percent_bps IS NULL OR percent_bps >= 0", name="ck_recurring_expense_rules_percent_bps_non_negative"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["expense_categories.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_methods.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_expense_rules_venue_id", "recurring_expense_rules", ["venue_id"], unique=False)
    op.create_index("ix_recurring_expense_rules_category_id", "recurring_expense_rules", ["category_id"], unique=False)
    op.create_index("ix_recurring_expense_rules_supplier_id", "recurring_expense_rules", ["supplier_id"], unique=False)
    op.create_index("ix_recurring_expense_rules_payment_method_id", "recurring_expense_rules", ["payment_method_id"], unique=False)
    op.create_index("ix_recurring_expense_rules_start_date", "recurring_expense_rules", ["start_date"], unique=False)
    op.create_index("ix_recurring_expense_rules_end_date", "recurring_expense_rules", ["end_date"], unique=False)

    op.create_table(
        "recurring_expense_rule_payment_methods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["recurring_expense_rules.id"]),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_methods.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "payment_method_id", name="uq_recurring_expense_rule_payment_method"),
    )
    op.create_index("ix_recurring_expense_rule_payment_methods_rule_id", "recurring_expense_rule_payment_methods", ["rule_id"], unique=False)
    op.create_index("ix_recurring_expense_rule_payment_methods_payment_method_id", "recurring_expense_rule_payment_methods", ["payment_method_id"], unique=False)

    op.add_column("expenses", sa.Column("recurring_rule_id", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("generated_for_month", sa.Date(), nullable=True))
    op.create_index("ix_expenses_recurring_rule_id", "expenses", ["recurring_rule_id"], unique=False)
    op.create_index("ix_expenses_generated_for_month", "expenses", ["generated_for_month"], unique=False)
    op.create_foreign_key("fk_expenses_recurring_rule_id", "expenses", "recurring_expense_rules", ["recurring_rule_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_expenses_recurring_rule_id", "expenses", type_="foreignkey")
    op.drop_index("ix_expenses_generated_for_month", table_name="expenses")
    op.drop_index("ix_expenses_recurring_rule_id", table_name="expenses")
    op.drop_column("expenses", "generated_for_month")
    op.drop_column("expenses", "recurring_rule_id")

    op.drop_index("ix_recurring_expense_rule_payment_methods_payment_method_id", table_name="recurring_expense_rule_payment_methods")
    op.drop_index("ix_recurring_expense_rule_payment_methods_rule_id", table_name="recurring_expense_rule_payment_methods")
    op.drop_table("recurring_expense_rule_payment_methods")

    op.drop_index("ix_recurring_expense_rules_end_date", table_name="recurring_expense_rules")
    op.drop_index("ix_recurring_expense_rules_start_date", table_name="recurring_expense_rules")
    op.drop_index("ix_recurring_expense_rules_payment_method_id", table_name="recurring_expense_rules")
    op.drop_index("ix_recurring_expense_rules_supplier_id", table_name="recurring_expense_rules")
    op.drop_index("ix_recurring_expense_rules_category_id", table_name="recurring_expense_rules")
    op.drop_index("ix_recurring_expense_rules_venue_id", table_name="recurring_expense_rules")
    op.drop_table("recurring_expense_rules")
