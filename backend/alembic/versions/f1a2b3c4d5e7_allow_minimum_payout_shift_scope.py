"""allow minimum payout per worked shift scope

Revision ID: f1a2b3c4d5e7
Revises: e0f1a2b3c4d5
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, Sequence[str], None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_MINIMUM_SCOPE_CHECK = "minimum_guarantee_scope IS NULL OR minimum_guarantee_scope in ('MONTH','DAY')"
NEW_MINIMUM_SCOPE_CHECK = "minimum_guarantee_scope IS NULL OR minimum_guarantee_scope in ('MONTH','DAY','SHIFT')"


def upgrade() -> None:
    op.drop_constraint("ck_pay_components_minimum_guarantee_scope", "pay_components", type_="check")
    op.create_check_constraint("ck_pay_components_minimum_guarantee_scope", "pay_components", NEW_MINIMUM_SCOPE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_pay_components_minimum_guarantee_scope", "pay_components", type_="check")
    op.create_check_constraint("ck_pay_components_minimum_guarantee_scope", "pay_components", OLD_MINIMUM_SCOPE_CHECK)
