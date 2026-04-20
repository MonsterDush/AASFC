"""pay component multi departments and daily minimum

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pay_components", sa.Column("department_ids_json", sa.Text(), nullable=True))
    op.add_column("pay_components", sa.Column("boost_department_ids_json", sa.Text(), nullable=True))
    op.add_column("pay_components", sa.Column("minimum_guarantee_scope", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "ck_pay_components_minimum_guarantee_scope",
        "pay_components",
        "minimum_guarantee_scope IS NULL OR minimum_guarantee_scope in ('MONTH','DAY')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pay_components_minimum_guarantee_scope", "pay_components", type_="check")
    op.drop_column("pay_components", "minimum_guarantee_scope")
    op.drop_column("pay_components", "boost_department_ids_json")
    op.drop_column("pay_components", "department_ids_json")
