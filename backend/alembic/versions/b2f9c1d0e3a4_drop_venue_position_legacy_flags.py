"""drop venue_position legacy boolean flags

Revision ID: b2f9c1d0e3a4
Revises: 8d9e0f1a2b3c
Create Date: 2026-03-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2f9c1d0e3a4"
down_revision: Union[str, Sequence[str], None] = "8d9e0f1a2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We treat permission_codes as the only source of truth.
    # Drop legacy boolean columns (Postgres).
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_make_reports")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_view_reports")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_view_revenue")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_edit_schedule")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_view_adjustments")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_manage_adjustments")
    op.execute("ALTER TABLE venue_positions DROP COLUMN IF EXISTS can_resolve_disputes")


def downgrade() -> None:
    # Re-create legacy columns (best-effort). Defaults are FALSE.
    op.add_column("venue_positions", sa.Column("can_make_reports", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_view_reports", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_view_revenue", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_edit_schedule", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_view_adjustments", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_manage_adjustments", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("venue_positions", sa.Column("can_resolve_disputes", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Remove server defaults to match typical schema style
    op.alter_column("venue_positions", "can_make_reports", server_default=None)
    op.alter_column("venue_positions", "can_view_reports", server_default=None)
    op.alter_column("venue_positions", "can_view_revenue", server_default=None)
    op.alter_column("venue_positions", "can_edit_schedule", server_default=None)
    op.alter_column("venue_positions", "can_view_adjustments", server_default=None)
    op.alter_column("venue_positions", "can_manage_adjustments", server_default=None)
    op.alter_column("venue_positions", "can_resolve_disputes", server_default=None)
