"""notification settings and shift reminders

Revision ID: f4c7a9b1d2e3
Revises: d93f2cb0f95a
Create Date: 2026-02-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c7a9b1d2e3"
down_revision: Union[str, Sequence[str], None] = "a827008c3b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: notification prefs
    op.add_column("users", sa.Column("notify_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("notify_adjustments", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("notify_shifts", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.alter_column("users", "notify_enabled", server_default=None)
    op.alter_column("users", "notify_adjustments", server_default=None)
    op.alter_column("users", "notify_shifts", server_default=None)

    # shift_assignments: reminder sent marker
    op.add_column("shift_assignments", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("shift_assignments", "reminder_sent_at")
    op.drop_column("users", "notify_shifts")
    op.drop_column("users", "notify_adjustments")
    op.drop_column("users", "notify_enabled")
