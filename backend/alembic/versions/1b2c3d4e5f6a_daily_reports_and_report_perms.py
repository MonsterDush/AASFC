"""daily reports + report view perms

Revision ID: 1b2c3d4e5f6a
Revises: 957b0901f9a3
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa

revision = "1b2c3d4e5f6a"
down_revision = "957b0901f9a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venue_positions",
        sa.Column("can_view_reports", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "venue_positions",
        sa.Column("can_view_revenue", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("cash", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cashless", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "date", name="uq_daily_reports_venue_date"),
    )


def downgrade():
    op.drop_table("daily_reports")
    op.drop_column("venue_positions", "can_view_revenue")
    op.drop_column("venue_positions", "can_view_reports")
