"""add pay component boost and scope fields

Revision ID: d5e7f9a1b3c4
Revises: c4e6f8a1b2d0
Create Date: 2026-03-24 14:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e7f9a1b3c4"
down_revision: Union[str, Sequence[str], None] = "c4e6f8a1b2d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pay_components", sa.Column("base_scope", sa.String(length=24), nullable=True))
    op.add_column("pay_components", sa.Column("boost_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("pay_components", sa.Column("boost_percent_bps", sa.Integer(), nullable=True))
    op.add_column("pay_components", sa.Column("boost_source_type", sa.String(length=40), nullable=True))
    op.add_column("pay_components", sa.Column("boost_recalc_mode", sa.String(length=24), nullable=True))
    op.add_column("pay_components", sa.Column("boost_department_id", sa.Integer(), nullable=True))
    op.add_column("pay_components", sa.Column("boost_kpi_metric_id", sa.Integer(), nullable=True))
    op.add_column("pay_components", sa.Column("boost_threshold_value", sa.Integer(), nullable=True))
    op.add_column("pay_components", sa.Column("minimum_guarantee_minor", sa.Integer(), nullable=True))
    op.add_column("pay_components", sa.Column("maximum_cap_minor", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_pay_components_boost_department_id_departments",
        "pay_components",
        "departments",
        ["boost_department_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_pay_components_boost_kpi_metric_id_kpi_metrics",
        "pay_components",
        "kpi_metrics",
        ["boost_kpi_metric_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_pay_components_boost_percent_bps_non_negative",
        "pay_components",
        "boost_percent_bps IS NULL OR boost_percent_bps >= 0",
    )
    op.create_check_constraint(
        "ck_pay_components_boost_threshold_value_non_negative",
        "pay_components",
        "boost_threshold_value IS NULL OR boost_threshold_value >= 0",
    )
    op.create_check_constraint(
        "ck_pay_components_minimum_guarantee_non_negative",
        "pay_components",
        "minimum_guarantee_minor IS NULL OR minimum_guarantee_minor >= 0",
    )
    op.create_check_constraint(
        "ck_pay_components_maximum_cap_non_negative",
        "pay_components",
        "maximum_cap_minor IS NULL OR maximum_cap_minor >= 0",
    )
    op.alter_column("pay_components", "boost_enabled", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_pay_components_maximum_cap_non_negative", "pay_components", type_="check")
    op.drop_constraint("ck_pay_components_minimum_guarantee_non_negative", "pay_components", type_="check")
    op.drop_constraint("ck_pay_components_boost_threshold_value_non_negative", "pay_components", type_="check")
    op.drop_constraint("ck_pay_components_boost_percent_bps_non_negative", "pay_components", type_="check")
    op.drop_constraint("fk_pay_components_boost_kpi_metric_id_kpi_metrics", "pay_components", type_="foreignkey")
    op.drop_constraint("fk_pay_components_boost_department_id_departments", "pay_components", type_="foreignkey")
    op.drop_column("pay_components", "maximum_cap_minor")
    op.drop_column("pay_components", "minimum_guarantee_minor")
    op.drop_column("pay_components", "boost_threshold_value")
    op.drop_column("pay_components", "boost_kpi_metric_id")
    op.drop_column("pay_components", "boost_department_id")
    op.drop_column("pay_components", "boost_recalc_mode")
    op.drop_column("pay_components", "boost_source_type")
    op.drop_column("pay_components", "boost_percent_bps")
    op.drop_column("pay_components", "boost_enabled")
    op.drop_column("pay_components", "base_scope")
