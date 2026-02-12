"""add user profile fields

Revision ID: 7c1f6d2a4b10
Revises: 4f2c0d1b7a21
Create Date: 2026-02-12

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c1f6d2a4b10"
down_revision = "4f2c0d1b7a21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("short_name", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "short_name")
    op.drop_column("users", "full_name")
