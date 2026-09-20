"""add POS integration layer v0.4 core

Revision ID: a4c8e2f6b1d3
Revises: f8c2d4e6a1b3
"""

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a4c8e2f6b1d3"
down_revision = "f8c2d4e6a1b3"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MONEY_TYPE = sa.Numeric(20, 4)
QUANTITY_TYPE = sa.Numeric(20, 6)


def _external_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_timezone", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_metadata_json", JSON_TYPE, nullable=True),
    ]


def _create_external_indexes(table_name: str, *, extra: Iterable[str] = ()) -> None:
    op.create_index(f"ix_{table_name}_connection_id", table_name, ["connection_id"])
    op.create_index(f"ix_{table_name}_payload_hash", table_name, ["payload_hash"])
    for column_name in extra:
        op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])


def upgrade() -> None:
    op.create_table(
        "pos_terminal_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pos_venue_id", sa.Integer(), sa.ForeignKey("pos_venues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("is_alive", sa.Boolean(), nullable=True),
        sa.Column("last_alive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_terminal_groups_external_identity"),
    )
    _create_external_indexes("pos_terminal_groups", extra=("venue_id", "pos_venue_id"))

    with op.batch_alter_table("pos_terminals") as batch_op:
        batch_op.add_column(sa.Column("terminal_group_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_pos_terminals_terminal_group_id",
            "pos_terminal_groups",
            ["terminal_group_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_pos_terminals_terminal_group_id", ["terminal_group_id"])

    op.create_table(
        "pos_restaurant_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_restaurant_sections_external_identity"),
    )
    _create_external_indexes("pos_restaurant_sections", extra=("venue_id",))

    op.create_table(
        "pos_tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "restaurant_section_id",
            sa.Integer(),
            sa.ForeignKey("pos_restaurant_sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_tables_external_identity"),
    )
    _create_external_indexes("pos_tables", extra=("venue_id", "restaurant_section_id"))

    op.create_table(
        "pos_product_option_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("min_selection", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_selection", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_option_groups_external_identity"),
        sa.CheckConstraint("min_selection >= 0", name="ck_pos_product_option_groups_min_selection"),
        sa.CheckConstraint(
            "max_selection IS NULL OR max_selection >= min_selection",
            name="ck_pos_product_option_groups_selection_range",
        ),
    )
    _create_external_indexes("pos_product_option_groups", extra=("product_id",))

    op.create_table(
        "pos_product_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "option_group_id",
            sa.Integer(),
            sa.ForeignKey("pos_product_option_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price_delta", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_options_external_identity"),
    )
    _create_external_indexes("pos_product_options", extra=("option_group_id",))

    op.create_table(
        "pos_product_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("option_signature_json", JSON_TYPE, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_variants_external_identity"),
    )
    _create_external_indexes("pos_product_variants", extra=("product_id",))

    op.create_table(
        "pos_product_variant_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "variant_id",
            sa.Integer(),
            sa.ForeignKey("pos_product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "option_id",
            sa.Integer(),
            sa.ForeignKey("pos_product_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("variant_id", "option_id", name="uq_pos_product_variant_options_identity"),
    )
    op.create_index("ix_pos_product_variant_options_variant_id", "pos_product_variant_options", ["variant_id"])
    op.create_index("ix_pos_product_variant_options_option_id", "pos_product_variant_options", ["option_id"])

    op.create_table(
        "pos_modifier_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_quantity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_modifier_groups_external_identity"),
        sa.CheckConstraint("min_quantity >= 0", name="ck_pos_modifier_groups_min_quantity"),
        sa.CheckConstraint(
            "max_quantity IS NULL OR max_quantity >= min_quantity", name="ck_pos_modifier_groups_quantity_range"
        ),
    )
    _create_external_indexes("pos_modifier_groups")

    op.create_table(
        "pos_modifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "modifier_group_id",
            sa.Integer(),
            sa.ForeignKey("pos_modifier_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("price_delta", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_modifiers_external_identity"),
    )
    _create_external_indexes("pos_modifiers", extra=("modifier_group_id", "product_id"))

    op.create_table(
        "pos_product_modifier_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "variant_id", sa.Integer(), sa.ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "modifier_group_id",
            sa.Integer(),
            sa.ForeignKey("pos_modifier_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("modifier_id", sa.Integer(), sa.ForeignKey("pos_modifiers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("min_amount", QUANTITY_TYPE, nullable=False, server_default="0"),
        sa.Column("max_amount", QUANTITY_TYPE, nullable=True),
        sa.Column("default_amount", QUANTITY_TYPE, nullable=False, server_default="0"),
        sa.Column("free_amount", QUANTITY_TYPE, nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_modifier_rules_external_identity"),
        sa.CheckConstraint("min_amount >= 0", name="ck_pos_product_modifier_rules_min_amount"),
        sa.CheckConstraint(
            "max_amount IS NULL OR max_amount >= min_amount",
            name="ck_pos_product_modifier_rules_amount_range",
        ),
    )
    _create_external_indexes(
        "pos_product_modifier_rules", extra=("product_id", "variant_id", "modifier_group_id", "modifier_id")
    )

    op.create_table(
        "pos_stop_list_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "terminal_group_id",
            sa.Integer(),
            sa.ForeignKey("pos_terminal_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "variant_id", sa.Integer(), sa.ForeignKey("pos_product_variants.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("modifier_id", sa.Integer(), sa.ForeignKey("pos_modifiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("balance", QUANTITY_TYPE, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_stop_list_entries_external_identity"),
    )
    _create_external_indexes(
        "pos_stop_list_entries",
        extra=("venue_id", "terminal_group_id", "product_id", "variant_id", "modifier_id", "started_at"),
    )

    for table_name in ("pos_product_prices", "pos_recipes", "pos_stock_snapshots", "pos_stock_movements"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("variant_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table_name}_variant_id",
                "pos_product_variants",
                ["variant_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_index(f"ix_{table_name}_variant_id", ["variant_id"])

    with op.batch_alter_table("pos_business_shifts") as batch_op:
        batch_op.add_column(sa.Column("current_orders_count", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("pos_order_items") as batch_op:
        batch_op.add_column(sa.Column("variant_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_pos_order_items_variant_id",
            "pos_product_variants",
            ["variant_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_pos_order_items_variant_id", ["variant_id"])

    with op.batch_alter_table("pos_orders") as batch_op:
        batch_op.add_column(sa.Column("terminal_group_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("restaurant_section_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("table_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_status", sa.String(length=96), nullable=True))
        batch_op.add_column(sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("current_amount", MONEY_TYPE, nullable=True))
        batch_op.drop_constraint("ck_pos_orders_status", type_="check")
        batch_op.create_check_constraint(
            "ck_pos_orders_status",
            "status IN ('NEW', 'OPEN', 'IN_PROGRESS', 'BILL_PRINTED', 'READY', 'CLOSED', 'CANCELLED', 'RETURNED', "
            "'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED', 'UNKNOWN')",
        )
        batch_op.create_foreign_key(
            "fk_pos_orders_terminal_group_id", "pos_terminal_groups", ["terminal_group_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_pos_orders_restaurant_section_id",
            "pos_restaurant_sections",
            ["restaurant_section_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key("fk_pos_orders_table_id", "pos_tables", ["table_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_pos_orders_terminal_group_id", ["terminal_group_id"])
        batch_op.create_index("ix_pos_orders_restaurant_section_id", ["restaurant_section_id"])
        batch_op.create_index("ix_pos_orders_table_id", ["table_id"])
        batch_op.create_index("ix_pos_orders_is_final", ["is_final"])
    op.execute(
        "UPDATE pos_orders SET is_final = true WHERE status IN "
        "('CLOSED', 'CANCELLED', 'RETURNED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED')"
    )

    op.create_table(
        "pos_order_item_modifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "order_item_id", sa.Integer(), sa.ForeignKey("pos_order_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("modifier_id", sa.Integer(), sa.ForeignKey("pos_modifiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "modifier_group_id",
            sa.Integer(),
            sa.ForeignKey("pos_modifier_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("amount", QUANTITY_TYPE, nullable=False),
        sa.Column("unit_price", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("total_price", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_order_item_modifiers_external_identity"),
    )
    _create_external_indexes("pos_order_item_modifiers", extra=("order_item_id", "modifier_id", "modifier_group_id"))

    with op.batch_alter_table("pos_inventory_documents") as batch_op:
        batch_op.add_column(sa.Column("warehouse_from_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("warehouse_to_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("supplier_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("document_type", sa.String(length=48), nullable=False, server_default="INVENTORY")
        )
        batch_op.add_column(sa.Column("comment", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("total_amount", MONEY_TYPE, nullable=True))
        batch_op.create_check_constraint(
            "ck_pos_inventory_documents_type",
            "document_type IN ('PURCHASE', 'OUTGOING_INVOICE', 'WRITEOFF', 'INVENTORY', "
            "'PRODUCTION', 'TRANSFORMATION', 'TRANSFER')",
        )
        batch_op.create_foreign_key(
            "fk_pos_inventory_documents_warehouse_from_id",
            "pos_warehouses",
            ["warehouse_from_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_pos_inventory_documents_warehouse_to_id",
            "pos_warehouses",
            ["warehouse_to_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_pos_inventory_documents_supplier_id",
            "pos_suppliers",
            ["supplier_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_pos_inventory_documents_warehouse_from_id", ["warehouse_from_id"])
        batch_op.create_index("ix_pos_inventory_documents_warehouse_to_id", ["warehouse_to_id"])
        batch_op.create_index("ix_pos_inventory_documents_supplier_id", ["supplier_id"])

    with op.batch_alter_table("pos_inventory_items") as batch_op:
        batch_op.add_column(sa.Column("variant_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_pos_inventory_items_variant_id",
            "pos_product_variants",
            ["variant_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_pos_inventory_items_variant_id", ["variant_id"])
        batch_op.add_column(sa.Column("cost_amount", MONEY_TYPE, nullable=True))
        batch_op.add_column(sa.Column("quantity", QUANTITY_TYPE, nullable=True))
        batch_op.add_column(sa.Column("price_per_unit", MONEY_TYPE, nullable=True))
        batch_op.add_column(sa.Column("total_amount", MONEY_TYPE, nullable=True))

    op.create_table(
        "integration_commands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=48), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("target_external_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_command_id", sa.String(length=255), nullable=True),
        sa.Column("provider_correlation_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_request", sa.Text(), nullable=False),
        sa.Column("encrypted_response", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "idempotency_key", name="uq_integration_commands_idempotency"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBMITTING', 'ACCEPTED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', "
            "'CANCELLED', 'UNKNOWN')",
            name="ck_integration_commands_status",
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_integration_commands_attempts"),
    )
    for column in (
        "connection_id",
        "venue_id",
        "provider",
        "command_type",
        "target_external_id",
        "external_command_id",
        "provider_correlation_id",
        "request_hash",
    ):
        op.create_index(f"ix_integration_commands_{column}", "integration_commands", [column])

    op.create_table(
        "integration_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=48), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("deduplication_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="RECEIVED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("connection_id", "deduplication_key", name="uq_integration_webhook_events_dedupe"),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'IGNORED', 'FAILED')",
            name="ck_integration_webhook_events_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_integration_webhook_events_attempts"),
    )
    for column in (
        "connection_id",
        "provider",
        "event_type",
        "external_event_id",
        "payload_hash",
        "received_at",
    ):
        op.create_index(f"ix_integration_webhook_events_{column}", "integration_webhook_events", [column])

    op.create_table(
        "pos_operational_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_status", sa.String(length=96), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("current_amount", MONEY_TYPE, nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "business_shift_id",
            sa.Integer(),
            sa.ForeignKey("pos_business_shifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("open_orders_count", sa.Integer(), nullable=True),
        sa.Column("open_tables_count", sa.Integer(), nullable=True),
        sa.Column("open_orders_amount", MONEY_TYPE, nullable=True),
        sa.Column("closed_orders_count", sa.Integer(), nullable=True),
        sa.Column("closed_revenue_amount", MONEY_TYPE, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "connection_id", "object_type", "external_id", "payload_hash", name="uq_pos_operational_snapshots_state"
        ),
        sa.CheckConstraint(
            "object_type IN ('VENUE', 'BUSINESS_SHIFT', 'ORDER', 'STOP_LIST')",
            name="ck_pos_operational_snapshots_object_type",
        ),
    )
    for column in (
        "connection_id",
        "venue_id",
        "object_type",
        "payload_hash",
        "observed_at",
        "fresh_until",
        "business_shift_id",
    ):
        op.create_index(f"ix_pos_operational_snapshots_{column}", "pos_operational_snapshots", [column])


def downgrade() -> None:
    op.drop_table("pos_operational_snapshots")
    op.drop_table("integration_webhook_events")
    op.drop_table("integration_commands")

    with op.batch_alter_table("pos_inventory_items") as batch_op:
        batch_op.drop_index("ix_pos_inventory_items_variant_id")
        batch_op.drop_constraint("fk_pos_inventory_items_variant_id", type_="foreignkey")
        batch_op.drop_column("total_amount")
        batch_op.drop_column("price_per_unit")
        batch_op.drop_column("quantity")
        batch_op.drop_column("cost_amount")
        batch_op.drop_column("variant_id")

    with op.batch_alter_table("pos_inventory_documents") as batch_op:
        batch_op.drop_constraint("ck_pos_inventory_documents_type", type_="check")
        batch_op.drop_index("ix_pos_inventory_documents_supplier_id")
        batch_op.drop_index("ix_pos_inventory_documents_warehouse_to_id")
        batch_op.drop_index("ix_pos_inventory_documents_warehouse_from_id")
        batch_op.drop_constraint("fk_pos_inventory_documents_supplier_id", type_="foreignkey")
        batch_op.drop_constraint("fk_pos_inventory_documents_warehouse_to_id", type_="foreignkey")
        batch_op.drop_constraint("fk_pos_inventory_documents_warehouse_from_id", type_="foreignkey")
        batch_op.drop_column("total_amount")
        batch_op.drop_column("comment")
        batch_op.drop_column("document_type")
        batch_op.drop_column("supplier_id")
        batch_op.drop_column("warehouse_to_id")
        batch_op.drop_column("warehouse_from_id")

    op.drop_table("pos_order_item_modifiers")

    with op.batch_alter_table("pos_order_items") as batch_op:
        batch_op.drop_index("ix_pos_order_items_variant_id")
        batch_op.drop_constraint("fk_pos_order_items_variant_id", type_="foreignkey")
        batch_op.drop_column("variant_id")

    with op.batch_alter_table("pos_orders") as batch_op:
        batch_op.drop_index("ix_pos_orders_is_final")
        batch_op.drop_index("ix_pos_orders_table_id")
        batch_op.drop_index("ix_pos_orders_restaurant_section_id")
        batch_op.drop_index("ix_pos_orders_terminal_group_id")
        batch_op.drop_constraint("fk_pos_orders_table_id", type_="foreignkey")
        batch_op.drop_constraint("fk_pos_orders_restaurant_section_id", type_="foreignkey")
        batch_op.drop_constraint("fk_pos_orders_terminal_group_id", type_="foreignkey")
        batch_op.drop_constraint("ck_pos_orders_status", type_="check")
        batch_op.create_check_constraint(
            "ck_pos_orders_status",
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED', 'UNKNOWN')",
        )
        batch_op.drop_column("current_amount")
        batch_op.drop_column("is_final")
        batch_op.drop_column("source_status")
        batch_op.drop_column("table_id")
        batch_op.drop_column("restaurant_section_id")
        batch_op.drop_column("terminal_group_id")

    with op.batch_alter_table("pos_business_shifts") as batch_op:
        batch_op.drop_column("current_orders_count")

    op.drop_table("pos_stop_list_entries")

    for table_name in ("pos_stock_movements", "pos_stock_snapshots", "pos_recipes", "pos_product_prices"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_variant_id")
            batch_op.drop_constraint(f"fk_{table_name}_variant_id", type_="foreignkey")
            batch_op.drop_column("variant_id")

    op.drop_table("pos_product_modifier_rules")
    op.drop_table("pos_modifiers")
    op.drop_table("pos_modifier_groups")
    op.drop_table("pos_product_variant_options")
    op.drop_table("pos_product_variants")
    op.drop_table("pos_product_options")
    op.drop_table("pos_product_option_groups")
    op.drop_table("pos_tables")
    op.drop_table("pos_restaurant_sections")

    with op.batch_alter_table("pos_terminals") as batch_op:
        batch_op.drop_index("ix_pos_terminals_terminal_group_id")
        batch_op.drop_constraint("fk_pos_terminals_terminal_group_id", type_="foreignkey")
        batch_op.drop_column("terminal_group_id")

    op.drop_table("pos_terminal_groups")
