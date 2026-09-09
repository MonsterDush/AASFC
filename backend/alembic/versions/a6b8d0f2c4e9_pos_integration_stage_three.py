"""Add extended ACDM inventory, quarantine, and scheduled sync jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a6b8d0f2c4e9"
down_revision = "f5a7c9e1b3d6"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MONEY_TYPE = sa.Numeric(20, 6)
QUANTITY_TYPE = sa.Numeric(24, 9)


def _external_columns():
    return (
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
    )


def _index_external(table: str):
    op.create_index(f"ix_{table}_connection_id", table, ["connection_id"])


def upgrade():
    op.create_table(
        "pos_recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yield_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("yield_unit", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_recipes_external_identity"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_recipes_period"),
        sa.CheckConstraint("yield_quantity > 0", name="ck_pos_recipes_positive_yield"),
    )
    _index_external("pos_recipes")
    op.create_index("ix_pos_recipes_product_id", "pos_recipes", ["product_id"])
    op.create_table(
        "pos_recipe_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("pos_recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("recipe_id", "external_id", name="uq_pos_recipe_items_external_identity"),
        sa.CheckConstraint("quantity >= 0", name="ck_pos_recipe_items_quantity"),
    )
    op.create_index("ix_pos_recipe_items_recipe_id", "pos_recipe_items", ["recipe_id"])
    op.create_index("ix_pos_recipe_items_ingredient_id", "pos_recipe_items", ["ingredient_id"])

    op.create_table(
        "pos_warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_warehouses_external_identity"),
    )
    _index_external("pos_warehouses")
    op.create_index("ix_pos_warehouses_venue_id", "pos_warehouses", ["venue_id"])

    op.create_table(
        "pos_stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("total_cost", MONEY_TYPE, nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_snapshots_external_identity"),
    )
    _index_external("pos_stock_snapshots")
    for column in ("warehouse_id", "product_id", "snapshot_at"):
        op.create_index(f"ix_pos_stock_snapshots_{column}", "pos_stock_snapshots", [column])

    op.create_table(
        "pos_stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("movement_type", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("total_cost", MONEY_TYPE, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reason", sa.String(length=1000), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_movements_external_identity"),
        sa.CheckConstraint(
            "movement_type IN ('PURCHASE','SALE','WRITEOFF','TRANSFER_IN','TRANSFER_OUT','PRODUCTION',"
            "'INVENTORY_CORRECTION','RETURN_TO_SUPPLIER','OTHER')",
            name="ck_pos_stock_movements_type",
        ),
    )
    _index_external("pos_stock_movements")
    for column in ("warehouse_id", "product_id", "occurred_at"):
        op.create_index(f"ix_pos_stock_movements_{column}", "pos_stock_movements", [column])

    op.create_table(
        "pos_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_suppliers_external_identity"),
    )
    _index_external("pos_suppliers")

    op.create_table(
        "pos_purchase_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("pos_suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=255), nullable=True),
        sa.Column("total_amount", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="UNKNOWN"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_documents_external_identity"),
    )
    _index_external("pos_purchase_documents")
    for column in ("supplier_id", "warehouse_id", "document_date"):
        op.create_index(f"ix_pos_purchase_documents_{column}", "pos_purchase_documents", [column])
    op.create_table(
        "pos_purchase_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("pos_purchase_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("price_per_unit", MONEY_TYPE, nullable=False),
        sa.Column("total_amount", MONEY_TYPE, nullable=False),
        sa.UniqueConstraint("document_id", "external_id", name="uq_pos_purchase_items_external_identity"),
    )
    op.create_index("ix_pos_purchase_items_document_id", "pos_purchase_items", ["document_id"])
    op.create_index("ix_pos_purchase_items_product_id", "pos_purchase_items", ["product_id"])

    op.create_table(
        "pos_writeoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=255), nullable=True),
        sa.Column("canonical_reason", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("source_reason", sa.String(length=1000), nullable=True),
        sa.Column("total_amount", MONEY_TYPE, nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="UNKNOWN"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoffs_external_identity"),
        sa.CheckConstraint(
            "canonical_reason IN ('SPOILAGE','EXPIRED','STAFF_ERROR','STAFF_MEAL','BREAKAGE','TECHNICAL','OTHER')",
            name="ck_pos_writeoffs_reason",
        ),
    )
    _index_external("pos_writeoffs")
    op.create_index("ix_pos_writeoffs_warehouse_id", "pos_writeoffs", ["warehouse_id"])
    op.create_index("ix_pos_writeoffs_document_date", "pos_writeoffs", ["document_date"])
    op.create_table(
        "pos_writeoff_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("pos_writeoffs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("total_amount", MONEY_TYPE, nullable=True),
        sa.UniqueConstraint("document_id", "external_id", name="uq_pos_writeoff_items_external_identity"),
    )
    op.create_index("ix_pos_writeoff_items_document_id", "pos_writeoff_items", ["document_id"])
    op.create_index("ix_pos_writeoff_items_product_id", "pos_writeoff_items", ["product_id"])

    op.create_table(
        "pos_inventory_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="UNKNOWN"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_documents_external_identity"),
    )
    _index_external("pos_inventory_documents")
    op.create_index("ix_pos_inventory_documents_warehouse_id", "pos_inventory_documents", ["warehouse_id"])
    op.create_index("ix_pos_inventory_documents_document_date", "pos_inventory_documents", ["document_date"])
    op.create_table(
        "pos_inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("pos_inventory_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("book_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("actual_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("difference_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("difference_cost", MONEY_TYPE, nullable=True),
        sa.UniqueConstraint("document_id", "external_id", name="uq_pos_inventory_items_external_identity"),
    )
    op.create_index("ix_pos_inventory_items_document_id", "pos_inventory_items", ["document_id"])
    op.create_index("ix_pos_inventory_items_product_id", "pos_inventory_items", ["product_id"])

    op.create_table(
        "pos_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("pos_employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("clocked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clocked_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_attendance_external_identity"),
        sa.CheckConstraint("clocked_out_at IS NULL OR clocked_out_at >= clocked_in_at", name="ck_pos_attendance_period"),
    )
    _index_external("pos_attendance")
    op.create_index("ix_pos_attendance_pos_employee_id", "pos_attendance", ["pos_employee_id"])
    op.create_index("ix_pos_attendance_clocked_in_at", "pos_attendance", ["clocked_in_at"])

    op.create_table(
        "pos_customer_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_customer_identities_external_identity"),
    )
    _index_external("pos_customer_identities")
    with op.batch_alter_table("pos_orders") as batch:
        batch.add_column(sa.Column("customer_pos_identity_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_pos_orders_customer_pos_identity_id",
            "pos_customer_identities",
            ["customer_pos_identity_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_pos_orders_customer_pos_identity_id", ["customer_pos_identity_id"])

    op.create_table(
        "integration_quarantine",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_connection_id", sa.Integer(), sa.ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="ERROR"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("integration_connection_id", "entity_type", "external_id", "error_code", name="uq_integration_quarantine_issue"),
        sa.CheckConstraint("status IN ('OPEN','RETRYING','RESOLVED','IGNORED')", name="ck_integration_quarantine_status"),
        sa.CheckConstraint("severity IN ('WARNING','ERROR')", name="ck_integration_quarantine_severity"),
    )
    for column in ("integration_connection_id", "capability", "entity_type", "error_code", "status"):
        op.create_index(f"ix_integration_quarantine_{column}", "integration_quarantine", [column])

    op.create_table(
        "integration_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_connection_id", sa.Integer(), sa.ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("queue", sa.String(length=16), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=True),
        sa.Column("payload_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_integration_sync_jobs_idempotency_key"),
        sa.CheckConstraint("job_type IN ('CONNECTION_HEALTH','CAPABILITY_SYNC','HISTORICAL_BACKFILL','ROLLING_RESYNC','NIGHT_RECONCILIATION')", name="ck_integration_sync_jobs_type"),
        sa.CheckConstraint("queue IN ('CRITICAL','NORMAL','BULK')", name="ck_integration_sync_jobs_queue"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED')", name="ck_integration_sync_jobs_status"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_integration_sync_jobs_attempts"),
    )
    for column in ("integration_connection_id", "job_type", "queue", "capability", "status", "run_after"):
        op.create_index(f"ix_integration_sync_jobs_{column}", "integration_sync_jobs", [column])


def downgrade():
    with op.batch_alter_table("pos_orders") as batch:
        batch.drop_index("ix_pos_orders_customer_pos_identity_id")
        batch.drop_constraint("fk_pos_orders_customer_pos_identity_id", type_="foreignkey")
        batch.drop_column("customer_pos_identity_id")
    for table in (
        "integration_sync_jobs",
        "integration_quarantine",
        "pos_customer_identities",
        "pos_attendance",
        "pos_inventory_items",
        "pos_inventory_documents",
        "pos_writeoff_items",
        "pos_writeoffs",
        "pos_purchase_items",
        "pos_purchase_documents",
        "pos_suppliers",
        "pos_stock_movements",
        "pos_stock_snapshots",
        "pos_warehouses",
        "pos_recipe_items",
        "pos_recipes",
    ):
        op.drop_table(table)
