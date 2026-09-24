"""add provider-neutral POS operational depth entities

Revision ID: f8c2d4e6a1b3
Revises: f7a1c3e5b9d2
"""

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f8c2d4e6a1b3"
down_revision = "f7a1c3e5b9d2"
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
        "pos_recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yield_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("yield_unit", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_recipes_external_identity"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_recipes_period"),
        sa.CheckConstraint("yield_quantity > 0", name="ck_pos_recipes_yield_positive"),
    )
    _create_external_indexes("pos_recipes", extra=("product_id",))

    op.create_table(
        "pos_recipe_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("pos_recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("loss_percent", sa.Numeric(9, 4), nullable=True),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_recipe_items_external_identity"),
        sa.CheckConstraint("quantity > 0", name="ck_pos_recipe_items_quantity_positive"),
    )
    _create_external_indexes("pos_recipe_items", extra=("recipe_id", "ingredient_id"))

    op.create_table(
        "pos_stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("total_cost", MONEY_TYPE, nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_snapshots_external_identity"),
    )
    _create_external_indexes("pos_stock_snapshots", extra=("warehouse_id", "product_id", "snapshot_at"))

    op.create_table(
        "pos_stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("amount", MONEY_TYPE, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reason", sa.String(length=255), nullable=True),
        sa.Column("source_document_external_id", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_movements_external_identity"),
        sa.CheckConstraint(
            "movement_type IN ('PURCHASE', 'SALE', 'WRITEOFF', 'TRANSFER_IN', 'TRANSFER_OUT', "
            "'PRODUCTION', 'INVENTORY_CORRECTION', 'RETURN_TO_SUPPLIER', 'OTHER')",
            name="ck_pos_stock_movements_type",
        ),
        sa.CheckConstraint("quantity <> 0", name="ck_pos_stock_movements_quantity_nonzero"),
    )
    _create_external_indexes(
        "pos_stock_movements",
        extra=("warehouse_id", "product_id", "occurred_at", "source_document_external_id"),
    )

    op.create_table(
        "pos_purchase_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("pos_suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=128), nullable=True),
        sa.Column("total_amount", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_documents_external_identity"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_purchase_documents_status",
        ),
    )
    _create_external_indexes(
        "pos_purchase_documents", extra=("venue_id", "supplier_id", "warehouse_id", "document_date")
    )

    op.create_table(
        "pos_purchase_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "document_id", sa.Integer(), sa.ForeignKey("pos_purchase_documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("price_per_unit", MONEY_TYPE, nullable=False),
        sa.Column("total_amount", MONEY_TYPE, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_items_external_identity"),
        sa.CheckConstraint("quantity > 0", name="ck_pos_purchase_items_quantity_positive"),
    )
    _create_external_indexes("pos_purchase_items", extra=("document_id", "product_id"))

    op.create_table(
        "pos_writeoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_reason", sa.String(length=24), nullable=False, server_default="OTHER"),
        sa.Column("source_reason", sa.String(length=255), nullable=True),
        sa.Column("total_cost", MONEY_TYPE, nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoffs_external_identity"),
        sa.CheckConstraint(
            "canonical_reason IN ('SPOILAGE', 'EXPIRED', 'STAFF_ERROR', 'STAFF_MEAL', "
            "'BREAKAGE', 'TECHNICAL', 'OTHER')",
            name="ck_pos_writeoffs_reason",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_writeoffs_status",
        ),
    )
    _create_external_indexes("pos_writeoffs", extra=("venue_id", "warehouse_id", "employee_id", "occurred_at"))

    op.create_table(
        "pos_writeoff_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("writeoff_id", sa.Integer(), sa.ForeignKey("pos_writeoffs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("cost_amount", MONEY_TYPE, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoff_items_external_identity"),
        sa.CheckConstraint("quantity > 0", name="ck_pos_writeoff_items_quantity_positive"),
    )
    _create_external_indexes("pos_writeoff_items", extra=("writeoff_id", "product_id"))

    op.create_table(
        "pos_inventory_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_documents_external_identity"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_inventory_documents_status",
        ),
    )
    _create_external_indexes("pos_inventory_documents", extra=("venue_id", "warehouse_id", "document_date"))

    op.create_table(
        "pos_inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "document_id", sa.Integer(), sa.ForeignKey("pos_inventory_documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("book_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("actual_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("difference_quantity", QUANTITY_TYPE, nullable=False),
        sa.Column("cost_per_unit", MONEY_TYPE, nullable=True),
        sa.Column("difference_cost", MONEY_TYPE, nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_items_external_identity"),
    )
    _create_external_indexes("pos_inventory_items", extra=("document_id", "product_id"))

    op.create_table(
        "pos_employee_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_employee_attendance_external_identity"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_employee_attendance_status",
        ),
        sa.CheckConstraint(
            "clock_out_at IS NULL OR clock_out_at > clock_in_at",
            name="ck_pos_employee_attendance_period",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_pos_employee_attendance_duration",
        ),
    )
    _create_external_indexes("pos_employee_attendance", extra=("venue_id", "employee_id", "clock_in_at"))


def downgrade() -> None:
    for table_name in (
        "pos_employee_attendance",
        "pos_inventory_items",
        "pos_inventory_documents",
        "pos_writeoff_items",
        "pos_writeoffs",
        "pos_purchase_items",
        "pos_purchase_documents",
        "pos_stock_movements",
        "pos_stock_snapshots",
        "pos_recipe_items",
        "pos_recipes",
    ):
        op.drop_table(table_name)
