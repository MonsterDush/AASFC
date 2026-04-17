"""add demo template split and analytics events

Revision ID: 9b1c2d3e4f5b
Revises: 8e9f0a1b2c3d
Create Date: 2026-04-06 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from typing import Sequence, Union

revision: str = "9b1c2d3e4f5b"
down_revision: Union[str, Sequence[str], None] = "8e9f0a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("demo_kind", sa.String(length=16), nullable=True))

    op.create_table(
        "demo_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("persona", sa.String(length=16), nullable=True),
        sa.Column("page_path", sa.String(length=255), nullable=True),
        sa.Column("cta_code", sa.String(length=64), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_demo_events_venue_id", "demo_events", ["venue_id"])
    op.create_index("ix_demo_events_user_id", "demo_events", ["user_id"])
    op.create_index("ix_demo_events_session_id", "demo_events", ["session_id"])
    op.create_index("ix_demo_events_event_name", "demo_events", ["event_name"])
    op.create_index("ix_demo_events_persona", "demo_events", ["persona"])
    op.create_index("ix_demo_events_created_at", "demo_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_demo_events_created_at", table_name="demo_events")
    op.drop_index("ix_demo_events_persona", table_name="demo_events")
    op.drop_index("ix_demo_events_event_name", table_name="demo_events")
    op.drop_index("ix_demo_events_session_id", table_name="demo_events")
    op.drop_index("ix_demo_events_user_id", table_name="demo_events")
    op.drop_index("ix_demo_events_venue_id", table_name="demo_events")
    op.drop_table("demo_events")
    op.drop_column("venues", "demo_kind")
