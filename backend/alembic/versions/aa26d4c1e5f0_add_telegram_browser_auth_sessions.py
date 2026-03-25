"""add telegram browser auth sessions

Revision ID: aa26d4c1e5f0
Revises: 20c4c73c0eea, 6f8a0b1c2d3e, 7c1f6d2a4b10, 9f1e2d3c4b5a, b7d3f1a4c9e2, c8d4e2f1a9b7, d93f2cb0f95a, 1b2c3d4e5f6a
Create Date: 2026-03-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aa26d4c1e5f0"
down_revision: Union[str, Sequence[str], None] = (
    "20c4c73c0eea",
    "6f8a0b1c2d3e",
    "7c1f6d2a4b10",
    "9f1e2d3c4b5a",
    "b7d3f1a4c9e2",
    "c8d4e2f1a9b7",
    "d93f2cb0f95a",
    "1b2c3d4e5f6a",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_browser_auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_token", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("next_path", sa.String(length=1024), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_username", sa.String(length=64), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tg_browser_auth_sessions_public_token", "telegram_browser_auth_sessions", ["public_token"], unique=True)
    op.create_index("ix_tg_browser_auth_sessions_status", "telegram_browser_auth_sessions", ["status"], unique=False)
    op.create_index("ix_tg_browser_auth_sessions_user_id", "telegram_browser_auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_tg_browser_auth_sessions_tg_user_id", "telegram_browser_auth_sessions", ["tg_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tg_browser_auth_sessions_tg_user_id", table_name="telegram_browser_auth_sessions")
    op.drop_index("ix_tg_browser_auth_sessions_user_id", table_name="telegram_browser_auth_sessions")
    op.drop_index("ix_tg_browser_auth_sessions_status", table_name="telegram_browser_auth_sessions")
    op.drop_index("ix_tg_browser_auth_sessions_public_token", table_name="telegram_browser_auth_sessions")
    op.drop_table("telegram_browser_auth_sessions")
