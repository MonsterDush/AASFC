"""extend position permission templates with code and is_system

Revision ID: a7b8c9d0e1f2
Revises: f0a1b2c3d4e5
Create Date: 2026-04-09 18:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "position_permission_templates",
        sa.Column("code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "position_permission_templates",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute(
        """
        UPDATE position_permission_templates
        SET code = 'legacy_' || id::text
        WHERE code IS NULL OR btrim(code) = ''
        """
    )

    op.alter_column("position_permission_templates", "code", nullable=False)

    op.create_unique_constraint(
        "uq_position_permission_templates_code",
        "position_permission_templates",
        ["code"],
    )

    op.create_index(
        op.f("ix_position_permission_templates_code"),
        "position_permission_templates",
        ["code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_position_permission_templates_is_system"),
        "position_permission_templates",
        ["is_system"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_position_permission_templates_is_system"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_code"), table_name="position_permission_templates")
    op.drop_constraint("uq_position_permission_templates_code", "position_permission_templates", type_="unique")
    op.drop_column("position_permission_templates", "is_system")
    op.drop_column("position_permission_templates", "code")