"""add shift comments

Revision ID: 20c4c73c0eea
Revises: a827008c3b2f
Create Date: 2026-02-18

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20c4c73c0eea"
down_revision = "f4c7a9b1d2e3"  # оставляю как у тебя, но ниже см. важное примечание
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "shift_id",
            sa.Integer(),
            sa.ForeignKey("shifts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Индексы делаем idempotent, чтобы не падало если они уже есть
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shift_comments_shift_id "
        "ON shift_comments (shift_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_shift_comments_author_user_id "
        "ON shift_comments (author_user_id)"
    )


def downgrade() -> None:
    # Безопасно удаляем (не упадёт, если уже удалены)
    op.execute("DROP INDEX IF EXISTS ix_shift_comments_author_user_id")
    op.execute("DROP INDEX IF EXISTS ix_shift_comments_shift_id")
    op.drop_table("shift_comments")
