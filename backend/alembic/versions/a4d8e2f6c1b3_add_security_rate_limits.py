"""add durable security rate limits

Revision ID: a4d8e2f6c1b3
Revises: 9c2e4f6a8b10
Create Date: 2026-08-11 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a4d8e2f6c1b3"
down_revision: Union[str, Sequence[str], None] = "9c2e4f6a8b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_rate_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "subject_hash", name="uq_security_rate_limits_scope_subject"),
    )
    op.create_index("ix_security_rate_limits_scope", "security_rate_limits", ["scope"], unique=False)
    op.create_index("ix_security_rate_limits_blocked_until", "security_rate_limits", ["blocked_until"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_rate_limits_blocked_until", table_name="security_rate_limits")
    op.drop_index("ix_security_rate_limits_scope", table_name="security_rate_limits")
    op.drop_table("security_rate_limits")
