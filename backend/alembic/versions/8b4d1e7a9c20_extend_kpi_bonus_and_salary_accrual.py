"""extend KPI bonus calculation and salary accrual metadata

Revision ID: 8b4d1e7a9c20
Revises: 7d0f2b6c8e33
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8b4d1e7a9c20"
down_revision: Union[str, Sequence[str], None] = "7d0f2b6c8e33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pay_components",
        sa.Column(
            "kpi_calculation_mode",
            sa.String(length=16),
            server_default="FIXED",
            nullable=False,
        ),
    )
    op.add_column(
        "pay_components",
        sa.Column("salary_accrual_day", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pay_components", "salary_accrual_day")
    op.drop_column("pay_components", "kpi_calculation_mode")
