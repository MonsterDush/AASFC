"""hybrid invites and owner pending flow

Revision ID: 7a9e1c2d3f4b
Revises: 7f6e5d4c3b2a
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7a9e1c2d3f4b"
down_revision: Union[str, Sequence[str], None] = "7f6e5d4c3b2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("venue_invites", sa.Column("invited_phone_e164", sa.String(length=32), nullable=True))
    op.add_column("venue_invites", sa.Column("invited_contact_label", sa.String(length=255), nullable=True))
    op.add_column("venue_invites", sa.Column("invite_channel", sa.String(length=16), nullable=True))
    op.add_column("venue_invites", sa.Column("invite_token", sa.String(length=64), nullable=True))
    op.add_column("venue_invites", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("venue_invites", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("venue_invites", sa.Column("accepted_via", sa.String(length=16), nullable=True))
    op.add_column("venue_invites", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_venue_invites_created_by_user_id_users",
        "venue_invites",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("UPDATE venue_invites SET invite_channel='TELEGRAM' WHERE invite_channel IS NULL")
    op.execute("UPDATE venue_invites SET invite_token=md5(random()::text || clock_timestamp()::text || id::text) WHERE invite_token IS NULL")

    op.alter_column("venue_invites", "invite_channel", existing_type=sa.String(length=16), nullable=False)
    op.alter_column("venue_invites", "invite_token", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("venue_invites", "invited_tg_username", existing_type=sa.String(length=64), nullable=True)

    op.create_index("ix_venue_invites_invite_token", "venue_invites", ["invite_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_venue_invites_invite_token", table_name="venue_invites")
    op.drop_constraint("fk_venue_invites_created_by_user_id_users", "venue_invites", type_="foreignkey")
    op.alter_column("venue_invites", "invited_tg_username", existing_type=sa.String(length=64), nullable=False)
    op.drop_column("venue_invites", "created_by_user_id")
    op.drop_column("venue_invites", "accepted_via")
    op.drop_column("venue_invites", "revoked_at")
    op.drop_column("venue_invites", "expires_at")
    op.drop_column("venue_invites", "invite_token")
    op.drop_column("venue_invites", "invite_channel")
    op.drop_column("venue_invites", "invited_contact_label")
    op.drop_column("venue_invites", "invited_phone_e164")
