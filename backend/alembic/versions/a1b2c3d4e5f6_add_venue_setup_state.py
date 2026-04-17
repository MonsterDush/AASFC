"""add venue setup state

Revision ID: a1b2c3d4e5f6
Revises: 9b1c2d3e4f5b
Create Date: 2026-04-09 17:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9b1c2d3e4f5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "venue_setup_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wizard_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="NOT_STARTED"),
        sa.Column("phase", sa.String(length=16), nullable=False, server_default="PREPARE"),
        sa.Column("current_step_key", sa.String(length=64), nullable=True),
        sa.Column("completed_steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("skipped_steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("step_meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prepare_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("venue_id", name="uq_venue_setup_state_venue_id"),
    )
    op.create_index("ix_venue_setup_state_venue_id", "venue_setup_state", ["venue_id"])
    op.create_index("ix_venue_setup_state_status", "venue_setup_state", ["status"])
    op.create_index("ix_venue_setup_state_phase", "venue_setup_state", ["phase"])


def downgrade() -> None:
    op.drop_index("ix_venue_setup_state_phase", table_name="venue_setup_state")
    op.drop_index("ix_venue_setup_state_status", table_name="venue_setup_state")
    op.drop_index("ix_venue_setup_state_venue_id", table_name="venue_setup_state")
    op.drop_table("venue_setup_state")
