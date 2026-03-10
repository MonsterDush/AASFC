"""add expenses core tables

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "code", name="uq_expense_categories_venue_code"),
    )
    op.create_index("ix_expense_categories_venue_id", "expense_categories", ["venue_id"])

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "title", name="uq_suppliers_venue_title"),
    )
    op.create_index("ix_suppliers_venue_id", "suppliers", ["venue_id"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("spread_months", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_minor >= 0", name="ck_expenses_amount_minor_non_negative"),
        sa.CheckConstraint("spread_months >= 1", name="ck_expenses_spread_months_positive"),
    )
    op.create_index("ix_expenses_venue_id", "expenses", ["venue_id"])
    op.create_index("ix_expenses_category_id", "expenses", ["category_id"])
    op.create_index("ix_expenses_supplier_id", "expenses", ["supplier_id"])
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])

    op.alter_column("expense_categories", "created_at", server_default=None)
    op.alter_column("suppliers", "created_at", server_default=None)
    op.alter_column("expenses", "amount_minor", server_default=None)
    op.alter_column("expenses", "spread_months", server_default=None)
    op.alter_column("expenses", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_expenses_expense_date", table_name="expenses")
    op.drop_index("ix_expenses_supplier_id", table_name="expenses")
    op.drop_index("ix_expenses_category_id", table_name="expenses")
    op.drop_index("ix_expenses_venue_id", table_name="expenses")
    op.drop_table("expenses")

    op.drop_index("ix_suppliers_venue_id", table_name="suppliers")
    op.drop_table("suppliers")

    op.drop_index("ix_expense_categories_venue_id", table_name="expense_categories")
    op.drop_table("expense_categories")
