"""add venue_invites

Revision ID: cbaaa4e35e14
Revises: f844727060f4
Create Date: 2026-02-11 02:54:38.249877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbaaa4e35e14'
down_revision: Union[str, Sequence[str], None] = 'f844727060f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "venue_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),

        sa.Column("invited_tg_username", sa.String(length=64), nullable=False),  # без @, lower
        sa.Column("venue_role", sa.String(length=32), nullable=False),  # OWNER/STAFF

        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),

        sa.Column("accepted_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_venue_invites_venue_id", "venue_invites", ["venue_id"])
    op.create_index("ix_venue_invites_invited_tg_username", "venue_invites", ["invited_tg_username"])
    op.create_unique_constraint(
        "uq_venue_invites_venue_username_role",
        "venue_invites",
        ["venue_id", "invited_tg_username", "venue_role"],
    )


def downgrade():
    op.drop_constraint("uq_venue_invites_venue_username_role", "venue_invites", type_="unique")
    op.drop_index("ix_venue_invites_invited_tg_username", table_name="venue_invites")
    op.drop_index("ix_venue_invites_venue_id", table_name="venue_invites")
    op.drop_table("venue_invites")