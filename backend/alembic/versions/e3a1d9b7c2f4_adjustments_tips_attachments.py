"""adjustments tips attachments

Revision ID: e3a1d9b7c2f4
Revises: c66aca853298
Create Date: 2026-02-16

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3a1d9b7c2f4"
down_revision: Union[str, Sequence[str], None] = "c66aca853298"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # daily_reports.tips_total
    op.add_column("daily_reports", sa.Column("tips_total", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("daily_reports", "tips_total", server_default=None)

    # venue_positions flags
    op.add_column("venue_positions", sa.Column("can_manage_adjustments", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_view_adjustments", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_resolve_disputes", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("venue_positions", "can_manage_adjustments", server_default=None)
    op.alter_column("venue_positions", "can_view_adjustments", server_default=None)
    op.alter_column("venue_positions", "can_resolve_disputes", server_default=None)

    # daily_report_attachments
    op.create_table(
        "daily_report_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_reports.id"), nullable=False, index=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_report_att_report", "daily_report_attachments", ["report_id"])

    # penalties
    op.create_table(
        "penalties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("member_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_penalties_venue_date", "penalties", ["venue_id", "date"])
    op.create_index("ix_penalties_venue_member_date", "penalties", ["venue_id", "member_user_id", "date"])

    # writeoffs
    op.create_table(
        "writeoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("member_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_writeoffs_venue_date", "writeoffs", ["venue_id", "date"])
    op.create_index("ix_writeoffs_venue_member_date", "writeoffs", ["venue_id", "member_user_id", "date"])

    # bonuses
    op.create_table(
        "bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("member_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_bonuses_venue_date", "bonuses", ["venue_id", "date"])
    op.create_index("ix_bonuses_venue_member_date", "bonuses", ["venue_id", "member_user_id", "date"])

    # disputes
    op.create_table(
        "adjustment_disputes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("target_type", sa.String(length=20), nullable=False, index=True),
        sa.Column("target_id", sa.Integer(), nullable=False, index=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_adj_disputes_venue_target", "adjustment_disputes", ["venue_id", "target_type", "target_id"])

    op.create_table(
        "adjustment_dispute_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispute_id", sa.Integer(), sa.ForeignKey("adjustment_disputes.id"), nullable=False, index=True),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_table("adjustment_dispute_comments")
    op.drop_index("ix_adj_disputes_venue_target", table_name="adjustment_disputes")
    op.drop_table("adjustment_disputes")

    op.drop_index("ix_bonuses_venue_member_date", table_name="bonuses")
    op.drop_index("ix_bonuses_venue_date", table_name="bonuses")
    op.drop_table("bonuses")

    op.drop_index("ix_writeoffs_venue_member_date", table_name="writeoffs")
    op.drop_index("ix_writeoffs_venue_date", table_name="writeoffs")
    op.drop_table("writeoffs")

    op.drop_index("ix_penalties_venue_member_date", table_name="penalties")
    op.drop_index("ix_penalties_venue_date", table_name="penalties")
    op.drop_table("penalties")

    op.drop_index("ix_report_att_report", table_name="daily_report_attachments")
    op.drop_table("daily_report_attachments")

    op.drop_column("venue_positions", "can_resolve_disputes")
    op.drop_column("venue_positions", "can_view_adjustments")
    op.drop_column("venue_positions", "can_manage_adjustments")

    op.drop_column("daily_reports", "tips_total")
