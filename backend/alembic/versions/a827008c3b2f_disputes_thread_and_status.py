"""disputes thread and status

Revision ID: a827008c3b2f
Revises: c66aca853298
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a827008c3b2f"
down_revision: Union[str, Sequence[str], None] = "d93f2cb0f95a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # adjustment_disputes: add venue_id, status, resolved fields (if missing)
    with op.batch_alter_table("adjustment_disputes") as batch:
        batch.add_column(sa.Column("venue_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"))
        batch.add_column(sa.Column("resolved_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        # keep legacy "message" column as-is

    # FKs for new cols (best-effort; batch_alter_table on postgres should handle)
    op.create_foreign_key(
        "fk_adj_disputes_venue_id",
        "adjustment_disputes",
        "venues",
        ["venue_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_adj_disputes_resolved_by",
        "adjustment_disputes",
        "users",
        ["resolved_by_user_id"],
        ["id"],
    )

    # Backfill venue_id from adjustments
    op.execute(
        """
        UPDATE adjustment_disputes d
        SET venue_id = a.venue_id
        FROM adjustments a
        WHERE d.adjustment_id = a.id
          AND d.venue_id IS NULL
        """
    )

    # Make venue_id NOT NULL after backfill
    with op.batch_alter_table("adjustment_disputes") as batch:
        batch.alter_column("venue_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("status", server_default=None)

    # Index for fast lookup
    op.create_index("ix_adj_disputes_venue_adjustment", "adjustment_disputes", ["venue_id", "adjustment_id"])
    op.create_index("ix_adj_disputes_status", "adjustment_disputes", ["status"])

    # Create comments table (thread)
    op.create_table(
        "adjustment_dispute_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispute_id", sa.Integer(), sa.ForeignKey("adjustment_disputes.id"), nullable=False, index=True),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # Backfill initial comment from legacy adjustment_disputes.message (if present)
    op.execute(
        """
        INSERT INTO adjustment_dispute_comments (dispute_id, author_user_id, message, created_at, is_active)
        SELECT d.id, d.created_by_user_id, d.message, d.created_at, true
        FROM adjustment_disputes d
        WHERE d.message IS NOT NULL AND d.message <> ''
        """
    )


def downgrade() -> None:
    op.drop_table("adjustment_dispute_comments")

    op.drop_index("ix_adj_disputes_status", table_name="adjustment_disputes")
    op.drop_index("ix_adj_disputes_venue_adjustment", table_name="adjustment_disputes")

    with op.batch_alter_table("adjustment_disputes") as batch:
        batch.drop_constraint("fk_adj_disputes_resolved_by", type_="foreignkey")
        batch.drop_constraint("fk_adj_disputes_venue_id", type_="foreignkey")
        batch.drop_column("resolved_at")
        batch.drop_column("resolved_by_user_id")
        batch.drop_column("status")
        batch.drop_column("venue_id")
