"""stage QuickResto scope changes before historical reconciliation

Revision ID: f4c6e8a0b2d5
Revises: e2b4d6f8a1c3
Create Date: 2026-09-02 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c6e8a0b2d5"
down_revision: Union[str, Sequence[str], None] = "e2b4d6f8a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.add_column(sa.Column("pending_external_venue_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pending_sale_place_ids_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("pending_store_ids_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("pending_scope_generation", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pending_scope_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("pending_scope_requested_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_qr_conn_pending_scope_user",
            "users",
            ["pending_scope_requested_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_quickresto_connections_pending_external_venue_id",
            ["pending_external_venue_id"],
        )
        batch_op.create_index(
            "ix_quickresto_connections_pending_scope_requested_by_user_id",
            ["pending_scope_requested_by_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.drop_index("ix_quickresto_connections_pending_scope_requested_by_user_id")
        batch_op.drop_index("ix_quickresto_connections_pending_external_venue_id")
        batch_op.drop_constraint(
            "fk_qr_conn_pending_scope_user",
            type_="foreignkey",
        )
        batch_op.drop_column("pending_scope_requested_by_user_id")
        batch_op.drop_column("pending_scope_requested_at")
        batch_op.drop_column("pending_scope_generation")
        batch_op.drop_column("pending_store_ids_json")
        batch_op.drop_column("pending_sale_place_ids_json")
        batch_op.drop_column("pending_external_venue_id")

