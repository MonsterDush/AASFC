"""add shift schedule templates

Revision ID: 3a4b5c6d7e8f
Revises: e1f9b7c3d2a1, f2a3b4c5d6e7, d93f2cb0f95a, b7d3f1a4c9e2, 6f8a0b1c2d3e, 20c4c73c0eea, 9f1e2d3c4b5a
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3a4b5c6d7e8f"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_schedule_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "title", name="uq_shift_schedule_templates_venue_title"),
    )
    op.create_index("ix_shift_schedule_templates_venue_id", "shift_schedule_templates", ["venue_id"])

    op.create_table(
        "shift_schedule_template_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("interval_id", sa.Integer(), nullable=False),
        sa.Column("shift_slot", sa.String(length=16), server_default="DAY", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["interval_id"], ["shift_intervals.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["shift_schedule_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "weekday",
            "interval_id",
            "shift_slot",
            name="uq_shift_schedule_template_items_unique_interval",
        ),
    )
    op.create_index("ix_shift_schedule_template_items_template_id", "shift_schedule_template_items", ["template_id"])
    op.create_index("ix_shift_schedule_template_items_weekday", "shift_schedule_template_items", ["weekday"])
    op.create_index("ix_shift_schedule_template_items_interval_id", "shift_schedule_template_items", ["interval_id"])
    op.create_index("ix_shift_schedule_template_items_shift_slot", "shift_schedule_template_items", ["shift_slot"])


def downgrade() -> None:
    op.drop_index("ix_shift_schedule_template_items_shift_slot", table_name="shift_schedule_template_items")
    op.drop_index("ix_shift_schedule_template_items_interval_id", table_name="shift_schedule_template_items")
    op.drop_index("ix_shift_schedule_template_items_weekday", table_name="shift_schedule_template_items")
    op.drop_index("ix_shift_schedule_template_items_template_id", table_name="shift_schedule_template_items")
    op.drop_table("shift_schedule_template_items")
    op.drop_index("ix_shift_schedule_templates_venue_id", table_name="shift_schedule_templates")
    op.drop_table("shift_schedule_templates")
