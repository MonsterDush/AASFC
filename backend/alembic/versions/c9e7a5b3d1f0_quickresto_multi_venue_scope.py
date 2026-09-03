"""add QuickResto multi-venue scope

Revision ID: c9e7a5b3d1f0
Revises: b8d4f6a2c1e9
Create Date: 2026-09-01 16:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c9e7a5b3d1f0"
down_revision: Union[str, Sequence[str], None] = "b8d4f6a2c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCOPE_SELECTION_REQUIRED_MESSAGE = (
    "После обновления QuickResto требуется выбрать конкретное заведение и места реализации. "
    "Автосинхронизация приостановлена до сохранения области импорта."
)


def _portable_json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "venue_pos_integration_selections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "venue_id",
            name="uq_venue_pos_integration_selection_venue",
        ),
    )
    op.create_index(
        "ix_venue_pos_integration_selections_venue_id",
        "venue_pos_integration_selections",
        ["venue_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO venue_pos_integration_selections (venue_id, provider, selected_at) "
            "SELECT venue_id, 'QUICKRESTO', CURRENT_TIMESTAMP "
            "FROM quickresto_connections WHERE is_active = true"
        )
    )

    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.add_column(sa.Column("external_venue_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("external_venue_name", sa.String(length=160), nullable=True))
        batch_op.add_column(
            sa.Column(
                "scope_status",
                sa.String(length=24),
                nullable=False,
                server_default="NEEDS_SELECTION",
            )
        )
        batch_op.add_column(sa.Column("scope_generation", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("scope_confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_quickresto_connections_cloud_external_venue",
            ["cloud", "external_venue_id"],
        )
        batch_op.create_check_constraint(
            "ck_quickresto_connections_scope_status",
            "scope_status IN ('NEEDS_SELECTION', 'READY', 'STALE')",
        )
        batch_op.create_check_constraint(
            "ck_quickresto_connections_scope_generation",
            "scope_generation >= 1",
        )

    op.execute(
        sa.text(
            "UPDATE quickresto_connections "
            "SET last_sync_error = :message "
            "WHERE is_active = true AND auto_sync_enabled = true "
            "AND (last_sync_error IS NULL OR last_sync_error = '')"
        ).bindparams(message=_SCOPE_SELECTION_REQUIRED_MESSAGE)
    )

    op.create_table(
        "quickresto_external_venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column("address_label", sa.String(length=500), nullable=True),
        sa.Column("external_version", sa.Integer(), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_external_venue_connection_external",
        ),
    )
    op.create_index(
        "ix_quickresto_external_venues_connection_id",
        "quickresto_external_venues",
        ["connection_id"],
    )

    op.create_table(
        "quickresto_sale_place_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column("external_venue_id", sa.Integer(), nullable=True),
        sa.Column("default_cooking_place_id", sa.Integer(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_sale_place_scope_connection_external",
        ),
    )
    op.create_index(
        "ix_quickresto_sale_place_scopes_connection_id",
        "quickresto_sale_place_scopes",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_sale_place_scopes_external_venue_id",
        "quickresto_sale_place_scopes",
        ["external_venue_id"],
    )

    op.create_table(
        "quickresto_store_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column("discovered_via_sale_place_id", sa.Integer(), nullable=True),
        sa.Column("discovered_via_cooking_place_id", sa.Integer(), nullable=True),
        sa.Column(
            "source_sale_place_ids_json",
            _portable_json_type(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "source_cooking_place_ids_json",
            _portable_json_type(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_store_scope_connection_external",
        ),
    )
    op.create_index(
        "ix_quickresto_store_scopes_connection_id",
        "quickresto_store_scopes",
        ["connection_id"],
    )

    with op.batch_alter_table("quickresto_payment_mappings") as batch_op:
        batch_op.add_column(sa.Column("is_applicable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(
            sa.Column(
                "allowed_sale_place_ids_json",
                _portable_json_type(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE quickresto_connections "
            "SET last_sync_error = NULL "
            "WHERE last_sync_error = :message"
        ).bindparams(message=_SCOPE_SELECTION_REQUIRED_MESSAGE)
    )

    with op.batch_alter_table("quickresto_payment_mappings") as batch_op:
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("allowed_sale_place_ids_json")
        batch_op.drop_column("is_available")
        batch_op.drop_column("is_applicable")

    op.drop_index(
        "ix_quickresto_store_scopes_connection_id",
        table_name="quickresto_store_scopes",
    )
    op.drop_table("quickresto_store_scopes")

    op.drop_index(
        "ix_quickresto_sale_place_scopes_external_venue_id",
        table_name="quickresto_sale_place_scopes",
    )
    op.drop_index(
        "ix_quickresto_sale_place_scopes_connection_id",
        table_name="quickresto_sale_place_scopes",
    )
    op.drop_table("quickresto_sale_place_scopes")

    op.drop_index(
        "ix_quickresto_external_venues_connection_id",
        table_name="quickresto_external_venues",
    )
    op.drop_table("quickresto_external_venues")

    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.drop_constraint(
            "ck_quickresto_connections_scope_generation",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_quickresto_connections_scope_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_quickresto_connections_cloud_external_venue",
            type_="unique",
        )
        batch_op.drop_column("scope_confirmed_at")
        batch_op.drop_column("scope_generation")
        batch_op.drop_column("scope_status")
        batch_op.drop_column("external_venue_name")
        batch_op.drop_column("external_venue_id")

    op.drop_index(
        "ix_venue_pos_integration_selections_venue_id",
        table_name="venue_pos_integration_selections",
    )
    op.drop_table("venue_pos_integration_selections")
