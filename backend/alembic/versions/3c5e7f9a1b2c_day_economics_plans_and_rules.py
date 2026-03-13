"""day economics plans and rules

Revision ID: 3c5e7f9a1b2c
Revises: 2b4c6d8e0f1b
Create Date: 2026-03-13 03:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3c5e7f9a1b2c"
down_revision = "2b4c6d8e0f1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_economics_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("revenue_plan_minor", sa.Integer(), nullable=True),
        sa.Column("profit_plan_minor", sa.Integer(), nullable=True),
        sa.Column("revenue_per_assigned_plan_minor", sa.Integer(), nullable=True),
        sa.Column("assigned_user_target", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "target_date", name="uq_day_economics_plans_venue_date"),
    )
    op.create_index(op.f("ix_day_economics_plans_venue_id"), "day_economics_plans", ["venue_id"], unique=False)
    op.create_index(op.f("ix_day_economics_plans_target_date"), "day_economics_plans", ["target_date"], unique=False)

    op.create_table(
        "venue_economics_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("max_expense_ratio_bps", sa.Integer(), nullable=True),
        sa.Column("max_payroll_ratio_bps", sa.Integer(), nullable=True),
        sa.Column("min_revenue_per_assigned_minor", sa.Integer(), nullable=True),
        sa.Column("min_assigned_shift_coverage_bps", sa.Integer(), nullable=True),
        sa.Column("min_profit_minor", sa.Integer(), nullable=True),
        sa.Column("warn_on_draft_expenses", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", name="uq_venue_economics_rules_venue"),
    )
    op.create_index(op.f("ix_venue_economics_rules_venue_id"), "venue_economics_rules", ["venue_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_venue_economics_rules_venue_id"), table_name="venue_economics_rules")
    op.drop_table("venue_economics_rules")
    op.drop_index(op.f("ix_day_economics_plans_target_date"), table_name="day_economics_plans")
    op.drop_index(op.f("ix_day_economics_plans_venue_id"), table_name="day_economics_plans")
    op.drop_table("day_economics_plans")
