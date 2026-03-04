"""tips settings invite default position and tip allocations

Revision ID: 6b7c8d9e0f1a
Revises: 3f8a1b2c4d5e
Create Date: 2026-03-03 23:52:48

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6b7c8d9e0f1a"
down_revision: Union[str, Sequence[str], None] = "3f8a1b2c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # venues: tips settings
    op.add_column("venues", sa.Column("tips_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venues", sa.Column("tips_split_mode", sa.String(length=24), nullable=False, server_default="EQUAL"))
    op.add_column("venues", sa.Column("tips_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.alter_column("venues", "tips_enabled", server_default=None)
    op.alter_column("venues", "tips_split_mode", server_default=None)

    # venue_invites: preset position for invited user (MVP)
    op.add_column("venue_invites", sa.Column("default_position_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # daily_report_tip_allocations
    op.create_table(
        "daily_report_tip_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("split_mode", sa.String(length=24), nullable=False, server_default="EQUAL"),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("report_id", "user_id", name="uq_tip_alloc_report_user"),
    )
    op.create_index("ix_tip_alloc_report_id", "daily_report_tip_allocations", ["report_id"])
    op.create_index("ix_tip_alloc_user_id", "daily_report_tip_allocations", ["user_id"])
    op.alter_column("daily_report_tip_allocations", "amount", server_default=None)
    op.alter_column("daily_report_tip_allocations", "split_mode", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_tip_alloc_user_id", table_name="daily_report_tip_allocations")
    op.drop_index("ix_tip_alloc_report_id", table_name="daily_report_tip_allocations")
    op.drop_table("daily_report_tip_allocations")

    op.drop_column("venue_invites", "default_position_json")

    op.drop_column("venues", "tips_weights")
    op.drop_column("venues", "tips_split_mode")
    op.drop_column("venues", "tips_enabled")
