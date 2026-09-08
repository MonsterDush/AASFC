"""Add provider-neutral POS integration foundation and P0 canonical entities."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4f6a8c0b2d7"
down_revision = "d3e5f7a9b1c2"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PROVIDERS = "'IIKO','QUICK_RESTO','R_KEEPER','PALOMA','SYRVE','OTHER'"


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade():
    op.add_column(
        "venues",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
    )

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="CONNECTING"),
        sa.Column("external_organization_id", sa.String(length=255), nullable=True),
        sa.Column("external_venue_id", sa.String(length=255), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("capabilities", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("historical_sync_status", sa.String(length=24), nullable=False, server_default="NOT_STARTED"),
        sa.Column("coverage_start", sa.Date(), nullable=True),
        sa.Column("coverage_end", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "venue_id",
            "provider",
            "external_organization_id",
            "external_venue_id",
            name="uq_integration_connections_provider_scope",
        ),
        sa.CheckConstraint(f"provider IN ({PROVIDERS})", name="ck_integration_connections_provider"),
        sa.CheckConstraint(
            "status IN ('CONNECTING','ACTIVE','DEGRADED','PAUSED','FAILED','DISCONNECTED')",
            name="ck_integration_connections_status",
        ),
        sa.CheckConstraint(
            "historical_sync_status IN ('NOT_STARTED','RUNNING','PARTIAL','COMPLETED','FAILED')",
            name="ck_integration_connections_historical_status",
        ),
        sa.CheckConstraint(
            "coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end",
            name="ck_integration_connections_coverage_range",
        ),
    )
    for column in ("organization_id", "venue_id", "provider"):
        _index("integration_connections", column)

    op.create_table(
        "integration_capability_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("details_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("integration_connection_id", "capability", name="uq_integration_capability_state"),
        sa.CheckConstraint(
            "status IN ('UNKNOWN','AVAILABLE','UNAVAILABLE','DEGRADED')",
            name="ck_integration_capability_states_status",
        ),
    )
    _index("integration_capability_states", "integration_connection_id")
    _index("integration_capability_states", "capability")

    op.create_table(
        "integration_raw_objects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.UniqueConstraint(
            "integration_connection_id",
            "entity_type",
            "external_id",
            name="uq_integration_raw_objects_external_identity",
        ),
    )
    for column in ("integration_connection_id", "entity_type", "payload_hash", "received_at"):
        _index("integration_raw_objects", column)

    _create_reference_tables()
    _create_sales_tables()


def _create_reference_tables():
    op.create_table(
        "pos_venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=1000), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_venues_external_identity"),
    )
    for column in ("organization_id", "venue_id", "source", "connection_id"):
        _index("pos_venues", column)

    op.create_table(
        "pos_terminals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_terminals_external_identity"),
    )
    for column in ("venue_id", "source", "connection_id"):
        _index("pos_terminals", column)

    op.create_table(
        "pos_employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position_name", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_employees_external_identity"),
    )
    _index("pos_employees", "connection_id")

    op.create_table(
        "pos_employee_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pos_employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "venue_member_id", sa.Integer(), sa.ForeignKey("venue_members.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("pos_employee_id", name="uq_pos_employee_mappings_employee"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_pos_employee_mappings_confidence"),
    )
    for column in ("pos_employee_id", "venue_member_id", "confirmed_by_user_id"):
        _index("pos_employee_mappings", column)

    _create_product_tables()


def _create_product_tables():
    op.create_table(
        "pos_product_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "parent_group_id", sa.Integer(), sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="GROUP"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_groups_external_identity"),
        sa.CheckConstraint("kind IN ('GROUP','CATEGORY')", name="ck_pos_product_groups_kind"),
    )
    _index("pos_product_groups", "connection_id")
    _index("pos_product_groups", "parent_group_id")

    op.create_table(
        "pos_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=True),
        sa.Column("barcode", sa.String(length=255), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_products_external_identity"),
        sa.CheckConstraint(
            "type IN ('DISH','INGREDIENT','SEMI_FINISHED','MODIFIER','GOOD','SERVICE','OTHER')",
            name="ck_pos_products_type",
        ),
    )
    for column in ("connection_id", "group_id", "category_id"):
        _index("pos_products", column)

    op.create_table(
        "pos_product_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("product_id", "venue_id", "valid_from", name="uq_pos_product_prices_period"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_product_prices_period"),
    )
    _index("pos_product_prices", "product_id")
    _index("pos_product_prices", "venue_id")


def _create_sales_tables():
    op.create_table(
        "pos_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("order_number", sa.String(length=255), nullable=True),
        sa.Column("check_number", sa.String(length=255), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("order_type", sa.String(length=64), nullable=True),
        sa.Column("table_external_id", sa.String(length=255), nullable=True),
        sa.Column("table_name", sa.String(length=255), nullable=True),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column(
            "cashier_pos_employee_id",
            sa.Integer(),
            sa.ForeignKey("pos_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "waiter_pos_employee_id",
            sa.Integer(),
            sa.ForeignKey("pos_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subtotal", sa.Numeric(20, 6), nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("service_charge", sa.Numeric(20, 6), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(20, 6), nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("refund_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_orders_external_identity"),
        sa.CheckConstraint(
            "status IN ('OPEN','CLOSED','CANCELLED','REFUNDED','PARTIALLY_REFUNDED','DELETED','UNKNOWN')",
            name="ck_pos_orders_status",
        ),
        sa.CheckConstraint("guest_count IS NULL OR guest_count >= 0", name="ck_pos_orders_guest_count"),
    )
    for column in (
        "organization_id",
        "venue_id",
        "source",
        "connection_id",
        "business_date",
        "calendar_date",
        "cashier_pos_employee_id",
        "waiter_pos_employee_id",
        "synced_at",
    ):
        _index("pos_orders", column)

    _create_order_detail_tables()


def _create_order_detail_tables():
    op.create_table(
        "pos_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("category_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(24, 9), nullable=False),
        sa.Column("base_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("final_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("gross_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("net_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("cost_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("is_modifier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "parent_item_id", sa.Integer(), sa.ForeignKey("pos_order_items.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_refunded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("order_id", "external_id", name="uq_pos_order_items_external_identity"),
    )
    for column in ("order_id", "product_id", "parent_item_id"):
        _index("pos_order_items", column)

    op.create_table(
        "pos_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("order_id", "external_id", name="uq_pos_order_events_external_identity"),
        sa.CheckConstraint(
            "event_type IN ('ORDER_OPENED','ORDER_CLOSED','ITEM_ADDED','ITEM_REMOVED','ITEM_CHANGED',"
            "'DISCOUNT_APPLIED','PAYMENT_ADDED','PAYMENT_REMOVED','ORDER_CANCELLED','REFUND_CREATED')",
            name="ck_pos_order_events_type",
        ),
    )
    _index("pos_order_events", "order_id")
    _index("pos_order_events", "event_type")

    op.create_table(
        "pos_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_type", sa.String(length=24), nullable=False, server_default="OTHER"),
        sa.Column("source_type", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_id", "external_id", name="uq_pos_payments_external_identity"),
        sa.CheckConstraint(
            "canonical_type IN ('CASH','CARD','SBP','ONLINE','BONUS','CERTIFICATE','COMPLIMENTARY','STAFF','OTHER')",
            name="ck_pos_payments_canonical_type",
        ),
    )
    _index("pos_payments", "order_id")

    op.create_table(
        "pos_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "pos_employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True
        ),
        sa.UniqueConstraint("order_id", "external_id", name="uq_pos_refunds_external_identity"),
        sa.CheckConstraint("amount >= 0", name="ck_pos_refunds_amount"),
    )
    _index("pos_refunds", "order_id")
    _index("pos_refunds", "pos_employee_id")

    op.create_table(
        "pos_order_discounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_discount_id", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_type", sa.String(length=64), nullable=False, server_default="OTHER"),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("percent", sa.Numeric(9, 6), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("order_id", "external_discount_id", name="uq_pos_order_discounts_external_identity"),
        sa.CheckConstraint(
            "percent IS NULL OR (percent >= 0 AND percent <= 100)",
            name="ck_pos_order_discounts_percent",
        ),
    )
    _index("pos_order_discounts", "order_id")
    _index("pos_order_discounts", "employee_id")


def downgrade():
    for table in (
        "pos_order_discounts",
        "pos_refunds",
        "pos_payments",
        "pos_order_events",
        "pos_order_items",
        "pos_orders",
        "pos_product_prices",
        "pos_products",
        "pos_product_groups",
        "pos_employee_mappings",
        "pos_employees",
        "pos_terminals",
        "pos_venues",
        "integration_raw_objects",
        "integration_capability_states",
        "integration_connections",
    ):
        op.drop_table(table)
    op.drop_column("venues", "timezone")
