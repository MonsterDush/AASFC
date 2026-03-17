"""add payroll profiles, assignments, components and runs

Revision ID: 1f2e3d4c5b6a
Revises: 8ab1c2d3e4f5
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, Sequence[str], None] = "8ab1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PAY_COMPONENT_CHECK = "component_type in ('SALARY_FIXED_MONTH','SALARY_HOURLY','SALARY_PER_SHIFT','PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE','KPI_BONUS')"


def upgrade() -> None:
    op.create_table(
        "pay_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pay_profiles_venue_id"), "pay_profiles", ["venue_id"], unique=False)

    op.create_table(
        "pay_profile_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("pay_profile_id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_pay_profile_assignments_dates"),
        sa.ForeignKeyConstraint(["member_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["pay_profile_id"], ["pay_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pay_profile_assignments_venue_id"), "pay_profile_assignments", ["venue_id"], unique=False)
    op.create_index(op.f("ix_pay_profile_assignments_pay_profile_id"), "pay_profile_assignments", ["pay_profile_id"], unique=False)
    op.create_index(op.f("ix_pay_profile_assignments_member_user_id"), "pay_profile_assignments", ["member_user_id"], unique=False)
    op.create_index(
        "ix_pay_profile_assignments_venue_member_dates",
        "pay_profile_assignments",
        ["venue_id", "member_user_id", "start_date", "end_date"],
        unique=False,
    )

    op.create_table(
        "pay_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("pay_profile_id", sa.Integer(), nullable=False),
        sa.Column("component_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("rate_minor", sa.Integer(), nullable=True),
        sa.Column("percent_bps", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("kpi_metric_id", sa.Integer(), nullable=True),
        sa.Column("threshold_value", sa.Integer(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(PAY_COMPONENT_CHECK, name="ck_pay_components_type"),
        sa.CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_pay_components_amount_minor_non_negative"),
        sa.CheckConstraint("rate_minor IS NULL OR rate_minor >= 0", name="ck_pay_components_rate_minor_non_negative"),
        sa.CheckConstraint("percent_bps IS NULL OR percent_bps >= 0", name="ck_pay_components_percent_bps_non_negative"),
        sa.CheckConstraint("threshold_value IS NULL OR threshold_value >= 0", name="ck_pay_components_threshold_value_non_negative"),
        sa.CheckConstraint("sort_order >= 0", name="ck_pay_components_sort_order_non_negative"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["kpi_metric_id"], ["kpi_metrics.id"]),
        sa.ForeignKeyConstraint(["pay_profile_id"], ["pay_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pay_components_venue_id"), "pay_components", ["venue_id"], unique=False)
    op.create_index(op.f("ix_pay_components_pay_profile_id"), "pay_components", ["pay_profile_id"], unique=False)

    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("calculated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lines_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["calculated_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "period_month", name="uq_payroll_runs_venue_period_month"),
    )
    op.create_index(op.f("ix_payroll_runs_venue_id"), "payroll_runs", ["venue_id"], unique=False)
    op.create_index(op.f("ix_payroll_runs_period_month"), "payroll_runs", ["period_month"], unique=False)

    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=False),
        sa.Column("pay_profile_id", sa.Integer(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("breakdown_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["member_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["pay_profile_id"], ["pay_profiles.id"]),
        sa.ForeignKeyConstraint(["payroll_run_id"], ["payroll_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_run_id", "member_user_id", name="uq_payroll_lines_run_member"),
    )
    op.create_index(op.f("ix_payroll_lines_payroll_run_id"), "payroll_lines", ["payroll_run_id"], unique=False)
    op.create_index(op.f("ix_payroll_lines_venue_id"), "payroll_lines", ["venue_id"], unique=False)
    op.create_index(op.f("ix_payroll_lines_member_user_id"), "payroll_lines", ["member_user_id"], unique=False)

    perms = [
        ("PAY_PROFILES_VIEW", "Payroll", "Профили зарплаты: просмотр", "Видеть список и состав профилей зарплаты"),
        ("PAY_PROFILES_MANAGE", "Payroll", "Профили зарплаты: управление", "Создавать, редактировать и удалять профили зарплаты, компоненты и назначения"),
        ("PAYROLL_VIEW", "Payroll", "Начисления зарплаты: просмотр", "Видеть рассчитанные начисления зарплаты"),
        ("PAYROLL_CALCULATE", "Payroll", "Начисления зарплаты: расчёт", "Запускать расчёт зарплаты за период"),
    ]

    for code, group, title, desc in perms:
        op.execute(
            sa.text(
                '''
                INSERT INTO permissions(code, "group", title, description, is_active)
                VALUES (:code, :group, :title, :desc, true)
                ON CONFLICT (code) DO UPDATE
                SET "group" = EXCLUDED."group", title = EXCLUDED.title, description = EXCLUDED.description
                '''
            ).bindparams(code=code, group=group, title=title, desc=desc)
        )
        for role, granted in (
            ("MODERATOR", False),
            ("VENUE_OWNER", True),
            ("VENUE_MANAGER", False),
            ("STAFF", False),
        ):
            op.execute(
                sa.text(
                    '''
                    INSERT INTO role_permission_defaults(role, permission_code, is_granted_by_default)
                    VALUES (:role, :code, :granted)
                    ON CONFLICT (role, permission_code) DO UPDATE
                    SET is_granted_by_default = EXCLUDED.is_granted_by_default
                    '''
                ).bindparams(role=role, code=code, granted=granted)
            )

    op.alter_column("pay_profiles", "is_active", server_default=None)
    op.alter_column("pay_profiles", "created_at", server_default=None)
    op.alter_column("pay_profile_assignments", "is_active", server_default=None)
    op.alter_column("pay_profile_assignments", "created_at", server_default=None)
    op.alter_column("pay_components", "is_active", server_default=None)
    op.alter_column("pay_components", "sort_order", server_default=None)
    op.alter_column("pay_components", "created_at", server_default=None)
    op.alter_column("payroll_runs", "calculated_at", server_default=None)
    op.alter_column("payroll_runs", "total_amount_minor", server_default=None)
    op.alter_column("payroll_runs", "lines_count", server_default=None)
    op.alter_column("payroll_lines", "amount_minor", server_default=None)
    op.alter_column("payroll_lines", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_payroll_lines_member_user_id"), table_name="payroll_lines")
    op.drop_index(op.f("ix_payroll_lines_venue_id"), table_name="payroll_lines")
    op.drop_index(op.f("ix_payroll_lines_payroll_run_id"), table_name="payroll_lines")
    op.drop_table("payroll_lines")

    op.drop_index(op.f("ix_payroll_runs_period_month"), table_name="payroll_runs")
    op.drop_index(op.f("ix_payroll_runs_venue_id"), table_name="payroll_runs")
    op.drop_table("payroll_runs")

    op.drop_index(op.f("ix_pay_components_pay_profile_id"), table_name="pay_components")
    op.drop_index(op.f("ix_pay_components_venue_id"), table_name="pay_components")
    op.drop_table("pay_components")

    op.drop_index("ix_pay_profile_assignments_venue_member_dates", table_name="pay_profile_assignments")
    op.drop_index(op.f("ix_pay_profile_assignments_member_user_id"), table_name="pay_profile_assignments")
    op.drop_index(op.f("ix_pay_profile_assignments_pay_profile_id"), table_name="pay_profile_assignments")
    op.drop_index(op.f("ix_pay_profile_assignments_venue_id"), table_name="pay_profile_assignments")
    op.drop_table("pay_profile_assignments")

    op.drop_index(op.f("ix_pay_profiles_venue_id"), table_name="pay_profiles")
    op.drop_table("pay_profiles")
