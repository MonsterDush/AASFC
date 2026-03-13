"""day economics weekday templates

Revision ID: 4d6e8f0a2b3c
Revises: 3c5e7f9a1b2c
Create Date: 2026-03-14 23:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4d6e8f0a2b3c"
down_revision = "3c5e7f9a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_economics_plan_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("revenue_plan_minor", sa.Integer(), nullable=True),
        sa.Column("profit_plan_minor", sa.Integer(), nullable=True),
        sa.Column("revenue_per_assigned_plan_minor", sa.Integer(), nullable=True),
        sa.Column("assigned_user_target", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "weekday", name="uq_day_economics_plan_templates_venue_weekday"),
    )
    op.create_index(op.f("ix_day_economics_plan_templates_venue_id"), "day_economics_plan_templates", ["venue_id"], unique=False)
    op.create_index(op.f("ix_day_economics_plan_templates_weekday"), "day_economics_plan_templates", ["weekday"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_day_economics_plan_templates_weekday"), table_name="day_economics_plan_templates")
    op.drop_index(op.f("ix_day_economics_plan_templates_venue_id"), table_name="day_economics_plan_templates")
    op.drop_table("day_economics_plan_templates")
