"""add user preferred locale

Revision ID: b7d9e1f3a5c8
Revises: a4d8e2f6c1b3
Create Date: 2026-08-13 22:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7d9e1f3a5c8"
down_revision: Union[str, Sequence[str], None] = "a4d8e2f6c1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_locale", sa.String(length=8), nullable=True))
    op.create_check_constraint(
        "ck_users_preferred_locale",
        "users",
        "preferred_locale IS NULL OR preferred_locale IN ('ru', 'en')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_preferred_locale", "users", type_="check")
    op.drop_column("users", "preferred_locale")

