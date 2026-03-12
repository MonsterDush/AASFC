"""add expense status confirmed flow

Revision ID: e7b1c2d3f4a5
Revises: c3d4e5f6a7b8
Create Date: 2026-03-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e7b1c2d3f4a5"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("status", sa.String(length=16), nullable=True))
    op.execute("UPDATE expenses SET status = 'CONFIRMED' WHERE status IS NULL")
    op.alter_column("expenses", "status", nullable=False, server_default=sa.text("'DRAFT'"))
    op.create_index(op.f("ix_expenses_status"), "expenses", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_expenses_status"), table_name="expenses")
    op.drop_column("expenses", "status")
