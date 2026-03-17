"""phone auth identities and otp challenges

Revision ID: 7f6e5d4c3b2a
Revises: 6f8a0b1c2d3e
Create Date: 2026-03-17 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f6e5d4c3b2a"
down_revision: Union[str, Sequence[str], None] = "6f8a0b1c2d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "tg_user_id", existing_type=sa.BigInteger(), nullable=True)

    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("provider_user_id", sa.String(length=128), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "provider", name="uq_auth_identities_user_provider"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_auth_identities_provider_user"),
        sa.UniqueConstraint("phone_e164", name="uq_auth_identities_phone_e164"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
    op.create_index("ix_auth_identities_provider", "auth_identities", ["provider"])
    op.create_index("ix_auth_identities_phone_e164", "auth_identities", ["phone_e164"])
    op.alter_column("auth_identities", "is_verified", server_default=None)

    op.create_table(
        "phone_otp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="debug"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_phone_otp_challenges_phone_e164", "phone_otp_challenges", ["phone_e164"])
    op.create_index("ix_phone_otp_challenges_status", "phone_otp_challenges", ["status"])
    op.alter_column("phone_otp_challenges", "status", server_default=None)
    op.alter_column("phone_otp_challenges", "provider", server_default=None)
    op.alter_column("phone_otp_challenges", "attempts", server_default=None)
    op.alter_column("phone_otp_challenges", "max_attempts", server_default=None)

    op.execute(
        """
        INSERT INTO auth_identities (user_id, provider, provider_user_id, is_verified)
        SELECT id, 'TELEGRAM', CAST(tg_user_id AS VARCHAR(128)), true
        FROM users
        WHERE tg_user_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_auth_identities_provider_user DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_phone_otp_challenges_status", table_name="phone_otp_challenges")
    op.drop_index("ix_phone_otp_challenges_phone_e164", table_name="phone_otp_challenges")
    op.drop_table("phone_otp_challenges")

    op.drop_index("ix_auth_identities_phone_e164", table_name="auth_identities")
    op.drop_index("ix_auth_identities_provider", table_name="auth_identities")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")

    op.alter_column("users", "tg_user_id", existing_type=sa.BigInteger(), nullable=False)
