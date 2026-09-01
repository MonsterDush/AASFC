"""harden QuickResto venue scope audit

Revision ID: d0f8b6c4e2a1
Revises: c9e7a5b3d1f0
Create Date: 2026-09-01 23:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d0f8b6c4e2a1"
down_revision: Union[str, Sequence[str], None] = "c9e7a5b3d1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _portable_json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.add_column(sa.Column("external_venue_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("scope_confirmed_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_connections_scope_confirmed_by_user_id_users",
            "users",
            ["scope_confirmed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("quickresto_sale_place_scopes") as batch_op:
        batch_op.add_column(sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_sale_place_scopes_confirmed_by_user_id_users",
            "users",
            ["confirmed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        sa.text(
            "UPDATE quickresto_connections "
            "SET external_venue_version = ("
            "SELECT qev.external_version FROM quickresto_external_venues qev "
            "WHERE qev.connection_id = quickresto_connections.id "
            "AND qev.external_id = quickresto_connections.external_venue_id LIMIT 1"
            ") WHERE external_venue_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE quickresto_sale_place_scopes "
            "SET confirmed_at = ("
            "SELECT qrc.scope_confirmed_at FROM quickresto_connections qrc "
            "WHERE qrc.id = quickresto_sale_place_scopes.connection_id"
            ") WHERE is_confirmed = true AND confirmed_at IS NULL"
        )
    )

    op.create_table(
        "quickresto_scope_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_generation", sa.Integer(), nullable=False),
        sa.Column("previous_scope_json", _portable_json_type(), nullable=False),
        sa.Column("current_scope_json", _portable_json_type(), nullable=False),
        sa.Column("changes_json", _portable_json_type(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_quickresto_scope_audits_connection_id",
        "quickresto_scope_audits",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_scope_audits_actor_user_id",
        "quickresto_scope_audits",
        ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_quickresto_scope_audits_actor_user_id", table_name="quickresto_scope_audits")
    op.drop_index("ix_quickresto_scope_audits_connection_id", table_name="quickresto_scope_audits")
    op.drop_table("quickresto_scope_audits")

    with op.batch_alter_table("quickresto_sale_place_scopes") as batch_op:
        batch_op.drop_constraint(
            "fk_quickresto_sale_place_scopes_confirmed_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("confirmed_by_user_id")

    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.drop_constraint(
            "fk_quickresto_connections_scope_confirmed_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("scope_confirmed_by_user_id")
        batch_op.drop_column("external_venue_version")
