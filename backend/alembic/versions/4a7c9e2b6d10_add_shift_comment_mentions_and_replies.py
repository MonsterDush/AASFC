"""add shift comment mentions and replies

Revision ID: 4a7c9e2b6d10
Revises: f1a2b3c4d5e7
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4a7c9e2b6d10"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shift_comments",
        sa.Column(
            "parent_comment_id",
            sa.Integer(),
            sa.ForeignKey("shift_comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_shift_comments_parent_comment_id", "shift_comments", ["parent_comment_id"])

    op.create_table(
        "shift_comment_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "comment_id",
            sa.Integer(),
            sa.ForeignKey("shift_comments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mentioned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("comment_id", "mentioned_user_id", name="uq_shift_comment_mention_user"),
    )
    op.create_index("ix_shift_comment_mentions_comment_id", "shift_comment_mentions", ["comment_id"])
    op.create_index(
        "ix_shift_comment_mentions_mentioned_user_id",
        "shift_comment_mentions",
        ["mentioned_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shift_comment_mentions_mentioned_user_id", table_name="shift_comment_mentions")
    op.drop_index("ix_shift_comment_mentions_comment_id", table_name="shift_comment_mentions")
    op.drop_table("shift_comment_mentions")
    op.drop_index("ix_shift_comments_parent_comment_id", table_name="shift_comments")
    op.drop_column("shift_comments", "parent_comment_id")
