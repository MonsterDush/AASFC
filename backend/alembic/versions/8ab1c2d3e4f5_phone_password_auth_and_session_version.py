"""phone password auth and session version

Revision ID: 8ab1c2d3e4f5
Revises: 7a9e1c2d3f4b
Create Date: 2026-03-17 15:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8ab1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "7a9e1c2d3f4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("users", "session_version", server_default=None)

    op.add_column(
        "phone_otp_challenges",
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="PHONE_LOGIN"),
    )
    op.create_index("ix_phone_otp_challenges_purpose", "phone_otp_challenges", ["purpose"])
    op.alter_column("phone_otp_challenges", "purpose", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_phone_otp_challenges_purpose", table_name="phone_otp_challenges")
    op.drop_column("phone_otp_challenges", "purpose")

    op.drop_column("users", "session_version")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "password_set_at")
    op.drop_column("users", "password_hash")
