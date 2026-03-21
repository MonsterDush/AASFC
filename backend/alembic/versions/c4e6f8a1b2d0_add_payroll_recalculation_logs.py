"""add payroll recalculation logs

Revision ID: c4e6f8a1b2d0
Revises: b7d3f1a4c9e2
Create Date: 2026-03-21 03:25:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e6f8a1b2d0"
down_revision: Union[str, Sequence[str], None] = "b7d3f1a4c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_recalculation_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("triggered_by_user_id", sa.Integer(), nullable=True),
        sa.Column("trigger_reason", sa.String(length=64), nullable=False),
        sa.Column("target_dates_json", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payroll_recalculation_logs_venue_id"), "payroll_recalculation_logs", ["venue_id"], unique=False)
    op.create_index(op.f("ix_payroll_recalculation_logs_period_month"), "payroll_recalculation_logs", ["period_month"], unique=False)
    op.alter_column("payroll_recalculation_logs", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_payroll_recalculation_logs_period_month"), table_name="payroll_recalculation_logs")
    op.drop_index(op.f("ix_payroll_recalculation_logs_venue_id"), table_name="payroll_recalculation_logs")
    op.drop_table("payroll_recalculation_logs")
