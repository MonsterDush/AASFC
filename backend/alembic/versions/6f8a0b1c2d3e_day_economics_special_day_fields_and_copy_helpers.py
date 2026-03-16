"""day economics special day fields and copy helpers

Revision ID: 6f8a0b1c2d3e
Revises: 5e7f9a1b2c3d
Create Date: 2026-03-16 02:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6f8a0b1c2d3e"
down_revision = "5e7f9a1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("day_economics_plans", sa.Column("day_kind", sa.String(length=16), nullable=True))
    op.add_column("day_economics_plans", sa.Column("title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("day_economics_plans", "title")
    op.drop_column("day_economics_plans", "day_kind")
