"""add pay component weekday rates

Revision ID: c8e1f4a7b2d9
Revises: b7d9e1f3a5c8
Create Date: 2026-08-20 16:15:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8e1f4a7b2d9"
down_revision: Union[str, Sequence[str], None] = "b7d9e1f3a5c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pay_components", sa.Column("weekday_rates_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pay_components", "weekday_rates_json")
