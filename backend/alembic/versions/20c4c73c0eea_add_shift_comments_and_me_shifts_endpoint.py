"""add shift comments

Revision ID: 20c4c73c0eea
Revises: a827008c3b2f
Create Date: 2026-02-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20c4c73c0eea"
down_revision = "f4c7a9b1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_shift_comments_shift_id", "shift_comments", ["shift_id"])
    op.create_index("ix_shift_comments_author_user_id", "shift_comments", ["author_user_id"])


def downgrade() -> None:
    op.drop_index("ix_shift_comments_author_user_id", table_name="shift_comments")
    op.drop_index("ix_shift_comments_shift_id", table_name="shift_comments")
    op.drop_table("shift_comments")
