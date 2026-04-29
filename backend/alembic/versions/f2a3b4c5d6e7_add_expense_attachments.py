"""add expense attachments

Revision ID: f2a3b4c5d6e7
Revises: d1e2f3a4b5c6, a1b2c3d4e5f6, 1b2c3d4e5f6a, c8d4e2f1a9b7, 7c1f6d2a4b10
Create Date: 2026-04-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = (
    "d1e2f3a4b5c6",
    "a1b2c3d4e5f6",
    "1b2c3d4e5f6a",
    "c8d4e2f1a9b7",
    "7c1f6d2a4b10",
)
branch_labels = None
depends_on = None


def _has_table(bind, table_name: str) -> bool:
    try:
        return table_name in sa.inspect(bind).get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "expense_attachments"):
        op.create_table(
            "expense_attachments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("venue_id", sa.Integer(), nullable=False),
            sa.Column("expense_id", sa.Integer(), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=120), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("storage_path", sa.String(length=600), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_expense_attachments_expense_id"), "expense_attachments", ["expense_id"], unique=False)
        op.create_index(op.f("ix_expense_attachments_venue_id"), "expense_attachments", ["venue_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "expense_attachments"):
        op.drop_index(op.f("ix_expense_attachments_venue_id"), table_name="expense_attachments")
        op.drop_index(op.f("ix_expense_attachments_expense_id"), table_name="expense_attachments")
        op.drop_table("expense_attachments")
