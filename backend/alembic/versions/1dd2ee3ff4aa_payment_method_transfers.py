"""payment method transfers

Revision ID: 1dd2ee3ff4aa
Revises: 0aa1bb2cc3dd
Create Date: 2026-03-12 16:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1dd2ee3ff4aa"
down_revision = "0aa1bb2cc3dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_method_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("from_payment_method_id", sa.Integer(), nullable=False),
        sa.Column("to_payment_method_id", sa.Integer(), nullable=False),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="CONFIRMED"),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_method_transfers_amount_positive"),
        sa.CheckConstraint("from_payment_method_id <> to_payment_method_id", name="ck_payment_method_transfers_methods_not_equal"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_payment_method_id"], ["payment_methods.id"]),
        sa.ForeignKeyConstraint(["to_payment_method_id"], ["payment_methods.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_method_transfers_venue_id"), "payment_method_transfers", ["venue_id"], unique=False)
    op.create_index(op.f("ix_payment_method_transfers_from_payment_method_id"), "payment_method_transfers", ["from_payment_method_id"], unique=False)
    op.create_index(op.f("ix_payment_method_transfers_to_payment_method_id"), "payment_method_transfers", ["to_payment_method_id"], unique=False)
    op.create_index(op.f("ix_payment_method_transfers_transfer_date"), "payment_method_transfers", ["transfer_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_payment_method_transfers_transfer_date"), table_name="payment_method_transfers")
    op.drop_index(op.f("ix_payment_method_transfers_to_payment_method_id"), table_name="payment_method_transfers")
    op.drop_index(op.f("ix_payment_method_transfers_from_payment_method_id"), table_name="payment_method_transfers")
    op.drop_index(op.f("ix_payment_method_transfers_venue_id"), table_name="payment_method_transfers")
    op.drop_table("payment_method_transfers")
