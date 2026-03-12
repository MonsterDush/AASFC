"""balance adjustments and expense payment method

Revision ID: f9c8b7a6d5e4
Revises: e7f8a9b0c1d2
Create Date: 2026-03-12 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f9c8b7a6d5e4"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("payment_method_id", sa.Integer(), nullable=True))
    op.create_index("ix_expenses_payment_method_id", "expenses", ["payment_method_id"], unique=False)
    op.create_foreign_key("fk_expenses_payment_method_id", "expenses", "payment_methods", ["payment_method_id"], ["id"])

    op.create_table(
        "balance_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=False),
        sa.Column("adjustment_date", sa.Date(), nullable=False),
        sa.Column("delta_minor", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="CONFIRMED"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("delta_minor <> 0", name="ck_balance_adjustments_delta_non_zero"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_methods.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_balance_adjustments_venue_id", "balance_adjustments", ["venue_id"], unique=False)
    op.create_index("ix_balance_adjustments_payment_method_id", "balance_adjustments", ["payment_method_id"], unique=False)
    op.create_index("ix_balance_adjustments_adjustment_date", "balance_adjustments", ["adjustment_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_balance_adjustments_adjustment_date", table_name="balance_adjustments")
    op.drop_index("ix_balance_adjustments_payment_method_id", table_name="balance_adjustments")
    op.drop_index("ix_balance_adjustments_venue_id", table_name="balance_adjustments")
    op.drop_table("balance_adjustments")

    op.drop_constraint("fk_expenses_payment_method_id", "expenses", type_="foreignkey")
    op.drop_index("ix_expenses_payment_method_id", table_name="expenses")
    op.drop_column("expenses", "payment_method_id")
