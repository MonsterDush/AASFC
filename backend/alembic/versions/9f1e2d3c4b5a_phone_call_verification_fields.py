"""phone call verification fields

Revision ID: 9f1e2d3c4b5a
Revises: 1f2e3d4c5b6a
Create Date: 2026-03-18 17:55:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f1e2d3c4b5a"
down_revision = "1f2e3d4c5b6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("phone_otp_challenges", sa.Column("verification_channel", sa.String(length=16), nullable=False, server_default="SMS"))
    op.add_column("phone_otp_challenges", sa.Column("external_check_id", sa.String(length=64), nullable=True))
    op.add_column("phone_otp_challenges", sa.Column("external_target", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_phone_otp_challenges_verification_channel"), "phone_otp_challenges", ["verification_channel"], unique=False)
    op.create_index(op.f("ix_phone_otp_challenges_external_check_id"), "phone_otp_challenges", ["external_check_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_phone_otp_challenges_external_check_id"), table_name="phone_otp_challenges")
    op.drop_index(op.f("ix_phone_otp_challenges_verification_channel"), table_name="phone_otp_challenges")
    op.drop_column("phone_otp_challenges", "external_target")
    op.drop_column("phone_otp_challenges", "external_check_id")
    op.drop_column("phone_otp_challenges", "verification_channel")
