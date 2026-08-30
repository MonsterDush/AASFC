"""add QuickResto report import mode

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a1b2c9
Create Date: 2026-08-28 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5f7a9b1c3d5"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a1b2c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quickresto_connections",
        sa.Column("report_import_mode", sa.String(length=16), nullable=False, server_default="CLOSED"),
    )
    op.create_check_constraint(
        "ck_quickresto_connections_report_import_mode",
        "quickresto_connections",
        "report_import_mode IN ('DRAFT', 'CLOSED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_quickresto_connections_report_import_mode",
        "quickresto_connections",
        type_="check",
    )
    op.drop_column("quickresto_connections", "report_import_mode")
