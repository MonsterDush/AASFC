"""add staff availability and shift swap requests

Revision ID: 7d0f2b6c8e33
Revises: 6c9e1a4b7d22
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7d0f2b6c8e33"
down_revision: Union[str, Sequence[str], None] = "6c9e1a4b7d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_availabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shift_slot", sa.String(length=16), server_default="DAY", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "shift_slot IN ('DAY', 'NIGHT')",
            name="ck_shift_availabilities_slot_valid",
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE', 'UNAVAILABLE')",
            name="ck_shift_availabilities_status_valid",
        ),
        sa.ForeignKeyConstraint(["member_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue_id",
            "member_user_id",
            "date",
            "shift_slot",
            name="uq_shift_availability_member_date_slot",
        ),
    )
    op.create_index(
        "ix_shift_availabilities_venue_date_slot",
        "shift_availabilities",
        ["venue_id", "date", "shift_slot"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shift_availabilities_member_user_id"),
        "shift_availabilities",
        ["member_user_id"],
        unique=False,
    )

    op.create_table(
        "shift_swap_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("replacement_user_id", sa.Integer(), nullable=True),
        sa.Column("replacement_position_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("manager_comment", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="ck_shift_swap_requests_status_valid",
        ),
        sa.CheckConstraint(
            "replacement_user_id IS NULL OR replacement_user_id <> requester_user_id",
            name="ck_shift_swap_requests_different_users",
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["shift_assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["replacement_position_id"],
            ["venue_positions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["replacement_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shift_swap_requests_venue_status",
        "shift_swap_requests",
        ["venue_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_shift_swap_requests_open_assignment",
        "shift_swap_requests",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )
    op.create_index(op.f("ix_shift_swap_requests_shift_id"), "shift_swap_requests", ["shift_id"], unique=False)
    op.create_index(op.f("ix_shift_swap_requests_assignment_id"), "shift_swap_requests", ["assignment_id"], unique=False)
    op.create_index(op.f("ix_shift_swap_requests_requester_user_id"), "shift_swap_requests", ["requester_user_id"], unique=False)
    op.create_index(op.f("ix_shift_swap_requests_replacement_user_id"), "shift_swap_requests", ["replacement_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shift_swap_requests_replacement_user_id"), table_name="shift_swap_requests")
    op.drop_index(op.f("ix_shift_swap_requests_requester_user_id"), table_name="shift_swap_requests")
    op.drop_index("uq_shift_swap_requests_open_assignment", table_name="shift_swap_requests")
    op.drop_index(op.f("ix_shift_swap_requests_assignment_id"), table_name="shift_swap_requests")
    op.drop_index(op.f("ix_shift_swap_requests_shift_id"), table_name="shift_swap_requests")
    op.drop_index("ix_shift_swap_requests_venue_status", table_name="shift_swap_requests")
    op.drop_table("shift_swap_requests")
    op.drop_index(op.f("ix_shift_availabilities_member_user_id"), table_name="shift_availabilities")
    op.drop_index("ix_shift_availabilities_venue_date_slot", table_name="shift_availabilities")
    op.drop_table("shift_availabilities")
