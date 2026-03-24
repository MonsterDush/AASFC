"""add department month/day plans for payroll boost

Revision ID: e8f1a2b3c4d5
Revises: d5e7f9a1b3c4
Create Date: 2026-03-24 16:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d5e7f9a1b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "department_month_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("revenue_plan_minor", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "department_id", "month_start", name="uq_department_month_plans_venue_department_month"),
    )
    op.create_index(op.f("ix_department_month_plans_venue_id"), "department_month_plans", ["venue_id"], unique=False)
    op.create_index(op.f("ix_department_month_plans_department_id"), "department_month_plans", ["department_id"], unique=False)
    op.create_index(op.f("ix_department_month_plans_month_start"), "department_month_plans", ["month_start"], unique=False)

    op.create_table(
        "department_day_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("revenue_plan_minor", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "department_id", "target_date", name="uq_department_day_plans_venue_department_date"),
    )
    op.create_index(op.f("ix_department_day_plans_venue_id"), "department_day_plans", ["venue_id"], unique=False)
    op.create_index(op.f("ix_department_day_plans_department_id"), "department_day_plans", ["department_id"], unique=False)
    op.create_index(op.f("ix_department_day_plans_target_date"), "department_day_plans", ["target_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_department_day_plans_target_date"), table_name="department_day_plans")
    op.drop_index(op.f("ix_department_day_plans_department_id"), table_name="department_day_plans")
    op.drop_index(op.f("ix_department_day_plans_venue_id"), table_name="department_day_plans")
    op.drop_table("department_day_plans")

    op.drop_index(op.f("ix_department_month_plans_month_start"), table_name="department_month_plans")
    op.drop_index(op.f("ix_department_month_plans_department_id"), table_name="department_month_plans")
    op.drop_index(op.f("ix_department_month_plans_venue_id"), table_name="department_month_plans")
    op.drop_table("department_month_plans")
