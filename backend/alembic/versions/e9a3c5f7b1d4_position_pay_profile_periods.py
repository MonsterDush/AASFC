"""Add effective-dated payroll profiles for employee positions.

Revision ID: e9a3c5f7b1d4
Revises: d8f0a2c4e6b9
"""

from alembic import op
import sqlalchemy as sa


revision = "e9a3c5f7b1d4"
down_revision = "d8f0a2c4e6b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_pay_profile_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("venue_position_id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=False),
        sa.Column("pay_profile_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_position_pay_profile_periods_dates",
        ),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_position_id"], ["venue_positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pay_profile_id"], ["pay_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_position_pay_profile_periods_venue_id",
        "position_pay_profile_periods",
        ["venue_id"],
    )
    op.create_index(
        "ix_position_pay_profile_periods_venue_position_id",
        "position_pay_profile_periods",
        ["venue_position_id"],
    )
    op.create_index(
        "ix_position_pay_profile_periods_member_user_id",
        "position_pay_profile_periods",
        ["member_user_id"],
    )
    op.create_index(
        "ix_position_pay_profile_periods_pay_profile_id",
        "position_pay_profile_periods",
        ["pay_profile_id"],
    )
    op.create_index(
        "ix_position_pay_profile_periods_lookup",
        "position_pay_profile_periods",
        ["venue_id", "member_user_id", "venue_position_id", "valid_from", "valid_to"],
    )
    open_period = sa.text("is_active = true AND valid_to IS NULL")
    op.create_index(
        "uq_position_pay_profile_periods_open_position",
        "position_pay_profile_periods",
        ["venue_position_id"],
        unique=True,
        postgresql_where=open_period,
        sqlite_where=open_period,
    )

    # Existing active assignments have no trustworthy historical boundary.
    # An open NULL-start period preserves current results without rewriting any
    # stored PayrollLine. Owners can later confirm a concrete start date.
    op.execute(
        sa.text(
            "INSERT INTO position_pay_profile_periods "
            "(venue_id, venue_position_id, member_user_id, pay_profile_id, valid_from, valid_to, is_active) "
            "SELECT venue_id, id, member_user_id, pay_profile_id, NULL, NULL, true "
            "FROM venue_positions "
            "WHERE member_user_id IS NOT NULL AND pay_profile_id IS NOT NULL AND is_active = true"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "uq_position_pay_profile_periods_open_position",
        table_name="position_pay_profile_periods",
    )
    op.drop_index("ix_position_pay_profile_periods_lookup", table_name="position_pay_profile_periods")
    op.drop_index("ix_position_pay_profile_periods_pay_profile_id", table_name="position_pay_profile_periods")
    op.drop_index("ix_position_pay_profile_periods_member_user_id", table_name="position_pay_profile_periods")
    op.drop_index("ix_position_pay_profile_periods_venue_position_id", table_name="position_pay_profile_periods")
    op.drop_index("ix_position_pay_profile_periods_venue_id", table_name="position_pay_profile_periods")
    op.drop_table("position_pay_profile_periods")
