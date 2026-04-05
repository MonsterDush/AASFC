"""add demo mode foundation

Revision ID: 8e9f0a1b2c3d
Revises: b1c23d4e5f6a
Create Date: 2026-04-05 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "8e9f0a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "b1c23d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("venues", sa.Column("demo_reference_year", sa.Integer(), nullable=True))
    op.add_column("venues", sa.Column("demo_reference_month", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("is_demo_user", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("demo_persona", sa.String(length=16), nullable=True))

    op.alter_column("venues", "is_demo", server_default=None)
    op.alter_column("users", "is_demo_user", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "demo_persona")
    op.drop_column("users", "is_demo_user")
    op.drop_column("venues", "demo_reference_month")
    op.drop_column("venues", "demo_reference_year")
    op.drop_column("venues", "is_demo")
