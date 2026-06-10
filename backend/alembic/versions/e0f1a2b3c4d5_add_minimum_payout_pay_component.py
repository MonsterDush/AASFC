"""add minimum payout pay component

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_COMPONENT_TYPE_CHECK = (
    "component_type in ("
    "'SALARY_FIXED_MONTH','SALARY_HOURLY','SALARY_PER_SHIFT',"
    "'PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE','KPI_BONUS'"
    ")"
)
NEW_COMPONENT_TYPE_CHECK = (
    "component_type in ("
    "'SALARY_FIXED_MONTH','SALARY_HOURLY','SALARY_PER_SHIFT',"
    "'PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE','KPI_BONUS','MINIMUM_PAYOUT'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_pay_components_type", "pay_components", type_="check")
    op.create_check_constraint("ck_pay_components_type", "pay_components", NEW_COMPONENT_TYPE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_pay_components_type", "pay_components", type_="check")
    op.create_check_constraint("ck_pay_components_type", "pay_components", OLD_COMPONENT_TYPE_CHECK)
