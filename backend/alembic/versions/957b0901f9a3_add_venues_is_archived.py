"""add venues is_archived

Revision ID: 957b0901f9a3
Revises: cbaaa4e35e14
Create Date: 2026-02-11 04:14:32.758635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '957b0901f9a3'
down_revision: Union[str, Sequence[str], None] = 'cbaaa4e35e14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("venues", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("venues", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def upgrade():
    op.add_column("venues", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("venues", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
