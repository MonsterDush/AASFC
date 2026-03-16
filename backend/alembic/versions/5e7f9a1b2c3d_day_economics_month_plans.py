"""day economics month plans

Revision ID: 5e7f9a1b2c3d
Revises: 4d6e8f0a2b3c
Create Date: 2026-03-16 05:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5e7f9a1b2c3d"
down_revision = "4d6e8f0a2b3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_economics_month_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("revenue_plan_minor", sa.Integer(), nullable=True),
        sa.Column("profit_plan_minor", sa.Integer(), nullable=True),
        sa.Column("revenue_per_assigned_plan_minor", sa.Integer(), nullable=True),
        sa.Column("assigned_user_target", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "month_start", name="uq_day_economics_month_plans_venue_month"),
    )
    op.create_index("ix_day_economics_month_plans_venue_id", "day_economics_month_plans", ["venue_id"])
    op.create_index("ix_day_economics_month_plans_month_start", "day_economics_month_plans", ["month_start"])


def downgrade() -> None:
    op.drop_index("ix_day_economics_month_plans_month_start", table_name="day_economics_month_plans")
    op.drop_index("ix_day_economics_month_plans_venue_id", table_name="day_economics_month_plans")
    op.drop_table("day_economics_month_plans")
