"""add expense allocations

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f7
Create Date: 2026-03-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expense_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("expenses.id"), nullable=False),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount_minor >= 0", name="ck_expense_allocations_amount_minor_non_negative"),
        sa.UniqueConstraint("expense_id", "month", name="uq_expense_allocations_expense_month"),
    )
    op.create_index("ix_expense_allocations_expense_id", "expense_allocations", ["expense_id"])
    op.create_index("ix_expense_allocations_venue_id", "expense_allocations", ["venue_id"])
    op.create_index("ix_expense_allocations_month", "expense_allocations", ["month"])
    op.create_index("ix_expense_allocations_venue_month", "expense_allocations", ["venue_id", "month"])

    op.alter_column("expense_allocations", "amount_minor", server_default=None)
    op.alter_column("expense_allocations", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_expense_allocations_venue_month", table_name="expense_allocations")
    op.drop_index("ix_expense_allocations_month", table_name="expense_allocations")
    op.drop_index("ix_expense_allocations_venue_id", table_name="expense_allocations")
    op.drop_index("ix_expense_allocations_expense_id", table_name="expense_allocations")
    op.drop_table("expense_allocations")
