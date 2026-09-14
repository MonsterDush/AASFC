from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


MONEY_TYPE = Numeric(20, 4)
QUANTITY_TYPE = Numeric(20, 6)


class _CanonicalExternalMixin:
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)


class POSOrganization(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_organizations"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_organizations_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSVenue(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_venues"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_venues_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    organization = relationship("POSOrganization")


class POSTerminal(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_terminals_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    pos_venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sale_place_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    pos_venue = relationship("POSVenue")


class POSPaymentType(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_payment_types"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_payment_types_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_operation_type: Mapped[str | None] = mapped_column(String(96), nullable=True)
    canonical_hint: Mapped[str | None] = mapped_column(String(96), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class POSProductGroup(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_groups_external_identity"),
        CheckConstraint("kind IN ('GROUP', 'CATEGORY')", name="ck_pos_product_groups_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="GROUP", server_default="GROUP")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    parent = relationship("POSProductGroup", remote_side="POSProductGroup.id")


class POSProduct(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_products"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_products_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    group = relationship("POSProductGroup", foreign_keys=[group_id])
    category = relationship("POSProductGroup", foreign_keys=[category_id])


class POSProductPrice(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_prices"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_prices_external_identity"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_product_prices_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product = relationship("POSProduct")


class POSEmployee(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_employees"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_employees_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSWarehouse(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_warehouses"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_warehouses_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSSupplier(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_suppliers"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_suppliers_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSBusinessShift(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_business_shifts"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_business_shifts_external_identity"),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_business_shifts_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    terminal_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_terminals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shift_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revenue_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    refund_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    writeoff_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    terminal = relationship("POSTerminal")


class POSOrder(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_orders"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_orders_external_identity"),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_orders_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    business_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_business_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    terminal_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_terminals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    guests_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    payment_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    refund_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    business_shift = relationship("POSBusinessShift")
    terminal = relationship("POSTerminal")
    employee = relationship("POSEmployee")


class POSOrderItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_order_items"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_order_items_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_line_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    cost_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    is_modifier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order = relationship("POSOrder")
    product = relationship("POSProduct")


class POSOrderEvent(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_order_events"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_order_events_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)

    order = relationship("POSOrder")


class POSPayment(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_payments"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_payments_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_payment_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    canonical_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order = relationship("POSOrder")
    payment_type = relationship("POSPaymentType")


class POSRefund(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_refunds"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_refunds_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_payments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order = relationship("POSOrder")
    payment = relationship("POSPayment")
    employee = relationship("POSEmployee")


class POSOrderDiscount(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_order_discounts"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_order_discounts_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    source_discount_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order = relationship("POSOrder")
