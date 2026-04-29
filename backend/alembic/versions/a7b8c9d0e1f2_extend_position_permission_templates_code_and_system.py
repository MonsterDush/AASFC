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


TABLE_NAME = "position_permission_templates"
UNIQUE_NAME = "uq_position_permission_templates_code"
CODE_INDEX_NAME = "ix_position_permission_templates_code"
IS_SYSTEM_INDEX_NAME = "ix_position_permission_templates_is_system"


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _unique_constraint_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table_name) if constraint.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = _column_names(inspector, TABLE_NAME)

    if "code" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("code", sa.String(length=80), nullable=True),
        )
        columns.add("code")

    if "is_system" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        columns.add("is_system")

    if "code" in columns:
        op.execute(
            """
            UPDATE position_permission_templates
            SET code = 'legacy_' || id::text
            WHERE code IS NULL OR btrim(code) = ''
            """
        )
        op.alter_column(TABLE_NAME, "code", nullable=False)

    indexes = _index_names(inspector, TABLE_NAME)
    unique_constraints = _unique_constraint_names(inspector, TABLE_NAME)

    if UNIQUE_NAME not in unique_constraints:
        op.create_unique_constraint(
            UNIQUE_NAME,
            TABLE_NAME,
            ["code"],
        )

    if CODE_INDEX_NAME not in indexes:
        op.create_index(
            CODE_INDEX_NAME,
            TABLE_NAME,
            ["code"],
            unique=False,
        )

    if IS_SYSTEM_INDEX_NAME not in indexes:
        op.create_index(
            IS_SYSTEM_INDEX_NAME,
            TABLE_NAME,
            ["is_system"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, TABLE_NAME)
    unique_constraints = _unique_constraint_names(inspector, TABLE_NAME)
    columns = _column_names(inspector, TABLE_NAME)

    if IS_SYSTEM_INDEX_NAME in indexes:
        op.drop_index(IS_SYSTEM_INDEX_NAME, table_name=TABLE_NAME)
    if CODE_INDEX_NAME in indexes:
        op.drop_index(CODE_INDEX_NAME, table_name=TABLE_NAME)
    if UNIQUE_NAME in unique_constraints:
        op.drop_constraint(UNIQUE_NAME, TABLE_NAME, type_="unique")
    if "is_system" in columns:
        op.drop_column(TABLE_NAME, "is_system")
    if "code" in columns:
        op.drop_column(TABLE_NAME, "code")
