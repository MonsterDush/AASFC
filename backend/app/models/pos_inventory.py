from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_MONEY_TYPE = Numeric(20, 6)
_QUANTITY_TYPE = Numeric(24, 9)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class POSRecipe(Base):
    __tablename__ = "pos_recipes"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_recipes_external_identity"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_recipes_period"),
        CheckConstraint("yield_quantity > 0", name="ck_pos_recipes_positive_yield"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    yield_quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    yield_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    items = relationship("POSRecipeItem", back_populates="recipe", cascade="all, delete-orphan")


class POSRecipeItem(Base):
    __tablename__ = "pos_recipe_items"
    __table_args__ = (
        UniqueConstraint("recipe_id", "external_id", name="uq_pos_recipe_items_external_identity"),
        CheckConstraint("quantity >= 0", name="ck_pos_recipe_items_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("pos_recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)

    recipe = relationship("POSRecipe", back_populates="items")


class POSWarehouse(Base):
    __tablename__ = "pos_warehouses"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_warehouses_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSStockSnapshot(Base):
    __tablename__ = "pos_stock_snapshots"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_snapshots_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class POSStockMovement(Base):
    __tablename__ = "pos_stock_movements"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_movements_external_identity"),
        CheckConstraint(
            "movement_type IN ('PURCHASE','SALE','WRITEOFF','TRANSFER_IN','TRANSFER_OUT','PRODUCTION',"
            "'INVENTORY_CORRECTION','RETURN_TO_SUPPLIER','OTHER')",
            name="ck_pos_stock_movements_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER", server_default="OTHER")
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class POSSupplier(Base):
    __tablename__ = "pos_suppliers"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_suppliers_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSPurchaseDocument(Base):
    __tablename__ = "pos_purchase_documents"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_documents_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    items = relationship("POSPurchaseItem", back_populates="document", cascade="all, delete-orphan")


class POSPurchaseItem(Base):
    __tablename__ = "pos_purchase_items"
    __table_args__ = (
        UniqueConstraint("document_id", "external_id", name="uq_pos_purchase_items_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pos_purchase_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_per_unit: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)

    document = relationship("POSPurchaseDocument", back_populates="items")


class POSWriteoff(Base):
    __tablename__ = "pos_writeoffs"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoffs_external_identity"),
        CheckConstraint(
            "canonical_reason IN ('SPOILAGE','EXPIRED','STAFF_ERROR','STAFF_MEAL','BREAKAGE','TECHNICAL','OTHER')",
            name="ck_pos_writeoffs_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_reason: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER", server_default="OTHER")
    source_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    items = relationship("POSWriteoffItem", back_populates="document", cascade="all, delete-orphan")


class POSWriteoffItem(Base):
    __tablename__ = "pos_writeoff_items"
    __table_args__ = (
        UniqueConstraint("document_id", "external_id", name="uq_pos_writeoff_items_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("pos_writeoffs.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)

    document = relationship("POSWriteoff", back_populates="items")


class POSInventoryDocument(Base):
    __tablename__ = "pos_inventory_documents"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_documents_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    items = relationship("POSInventoryItem", back_populates="document", cascade="all, delete-orphan")


class POSInventoryItem(Base):
    __tablename__ = "pos_inventory_items"
    __table_args__ = (
        UniqueConstraint("document_id", "external_id", name="uq_pos_inventory_items_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pos_inventory_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    book_quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    actual_quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    difference_quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    difference_cost: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)

    document = relationship("POSInventoryDocument", back_populates="items")


class POSAttendance(Base):
    __tablename__ = "pos_attendance"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_attendance_external_identity"),
        CheckConstraint("clocked_out_at IS NULL OR clocked_out_at >= clocked_in_at", name="ck_pos_attendance_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    pos_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    clocked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    clocked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class POSCustomerIdentity(Base):
    __tablename__ = "pos_customer_identities"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_customer_identities_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
