"""add venue position permission codes

Revision ID: 8d9e0f1a2b3c
Revises: 6b7c8d9e0f1a
Create Date: 2026-03-04 15:57:57

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d9e0f1a2b3c"
down_revision: Union[str, Sequence[str], None] = "6b7c8d9e0f1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("venue_positions", sa.Column("permission_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("venue_positions", "permission_codes")
