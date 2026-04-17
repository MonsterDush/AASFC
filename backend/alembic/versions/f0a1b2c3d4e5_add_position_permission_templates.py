"""add position permission templates

Revision ID: f0a1b2c3d4e5
Revises: a1b2c3d4e5f6, c8d4e2f1a9b7
Create Date: 2026-04-09 18:50:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = ("a1b2c3d4e5f6", "c8d4e2f1a9b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "position_permission_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("permission_codes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="GLOBAL"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_position_permission_templates_code"),
    )
    op.create_index(op.f("ix_position_permission_templates_code"), "position_permission_templates", ["code"], unique=False)
    op.create_index(op.f("ix_position_permission_templates_title"), "position_permission_templates", ["title"], unique=False)
    op.create_index(op.f("ix_position_permission_templates_sort_order"), "position_permission_templates", ["sort_order"], unique=False)
    op.create_index(op.f("ix_position_permission_templates_is_active"), "position_permission_templates", ["is_active"], unique=False)
    op.create_index(op.f("ix_position_permission_templates_is_system"), "position_permission_templates", ["is_system"], unique=False)
    op.create_index(op.f("ix_position_permission_templates_scope"), "position_permission_templates", ["scope"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_position_permission_templates_scope"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_is_system"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_is_active"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_sort_order"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_title"), table_name="position_permission_templates")
    op.drop_index(op.f("ix_position_permission_templates_code"), table_name="position_permission_templates")
    op.drop_table("position_permission_templates")
