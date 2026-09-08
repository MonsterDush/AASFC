from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")
_MONEY_TYPE = Numeric(20, 6)
_QUANTITY_TYPE = Numeric(24, 9)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class POSVenue(Base):
    __tablename__ = "pos_venues"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_venues_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    venue = relationship("Venue")
    connection = relationship("IntegrationConnection")


class POSTerminal(Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_terminals_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSEmployee(Base):
    __tablename__ = "pos_employees"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_employees_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSEmployeeMapping(Base):
    __tablename__ = "pos_employee_mappings"
    __table_args__ = (
        UniqueConstraint("pos_employee_id", name="uq_pos_employee_mappings_employee"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_pos_employee_mappings_confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pos_employee_id: Mapped[int] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_member_id: Mapped[int] = mapped_column(
        ForeignKey("venue_members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class POSProductGroup(Base):
    __tablename__ = "pos_product_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_groups_external_identity"),
        CheckConstraint("kind IN ('GROUP','CATEGORY')", name="ck_pos_product_groups_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="GROUP", server_default="GROUP")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSProduct(Base):
    __tablename__ = "pos_products"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_products_external_identity"),
        CheckConstraint(
            "type IN ('DISH','INGREDIENT','SEMI_FINISHED','MODIFIER','GOOD','SERVICE','OTHER')",
            name="ck_pos_products_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER", server_default="OTHER")
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSProductPrice(Base):
    __tablename__ = "pos_product_prices"
    __table_args__ = (
        UniqueConstraint("product_id", "venue_id", "valid_from", name="uq_pos_product_prices_period"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_product_prices_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class POSOrder(Base):
    __tablename__ = "pos_orders"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_orders_external_identity"),
        CheckConstraint(
            "status IN ('OPEN','CLOSED','CANCELLED','REFUNDED','PARTIALLY_REFUNDED','DELETED','UNKNOWN')",
            name="ck_pos_orders_status",
        ),
        CheckConstraint("guest_count IS NULL OR guest_count >= 0", name="ck_pos_orders_guest_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    check_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    order_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cashier_pos_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    waiter_pos_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subtotal: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    service_charge: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    delivery_fee: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    refund_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB", server_default="RUB")
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)

    items = relationship("POSOrderItem", back_populates="order", cascade="all, delete-orphan")
    events = relationship("POSOrderEvent", back_populates="order", cascade="all, delete-orphan")
    payments = relationship("POSPayment", back_populates="order", cascade="all, delete-orphan")
    refunds = relationship("POSRefund", back_populates="order", cascade="all, delete-orphan")
    discounts = relationship("POSOrderDiscount", back_populates="order", cascade="all, delete-orphan")


class POSOrderItem(Base):
    __tablename__ = "pos_order_items"
    __table_args__ = (UniqueConstraint("order_id", "external_id", name="uq_pos_order_items_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    category_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY_TYPE, nullable=False)
    base_price: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    final_price: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    gross_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    net_amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    cost_amount: Mapped[Decimal | None] = mapped_column(_MONEY_TYPE, nullable=True)
    is_modifier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    parent_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_order_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_refunded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    order = relationship("POSOrder", back_populates="items")


class POSOrderEvent(Base):
    __tablename__ = "pos_order_events"
    __table_args__ = (
        UniqueConstraint("order_id", "external_id", name="uq_pos_order_events_external_identity"),
        CheckConstraint(
            "event_type IN ('ORDER_OPENED','ORDER_CLOSED','ITEM_ADDED','ITEM_REMOVED','ITEM_CHANGED',"
            "'DISCOUNT_APPLIED','PAYMENT_ADDED','PAYMENT_REMOVED','ORDER_CANCELLED','REFUND_CREATED')",
            name="ck_pos_order_events_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")

    order = relationship("POSOrder", back_populates="events")


class POSPayment(Base):
    __tablename__ = "pos_payments"
    __table_args__ = (
        UniqueConstraint("order_id", "external_id", name="uq_pos_payments_external_identity"),
        CheckConstraint(
            "canonical_type IN ('CASH','CARD','SBP','ONLINE','BONUS','CERTIFICATE','COMPLIMENTARY','STAFF','OTHER')",
            name="ck_pos_payments_canonical_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_type: Mapped[str] = mapped_column(String(24), nullable=False, default="OTHER", server_default="OTHER")
    source_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order = relationship("POSOrder", back_populates="payments")


class POSRefund(Base):
    __tablename__ = "pos_refunds"
    __table_args__ = (
        UniqueConstraint("order_id", "external_id", name="uq_pos_refunds_external_identity"),
        CheckConstraint("amount >= 0", name="ck_pos_refunds_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pos_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    order = relationship("POSOrder", back_populates="refunds")


class POSOrderDiscount(Base):
    __tablename__ = "pos_order_discounts"
    __table_args__ = (
        UniqueConstraint("order_id", "external_discount_id", name="uq_pos_order_discounts_external_identity"),
        CheckConstraint("percent IS NULL OR (percent >= 0 AND percent <= 100)", name="ck_pos_order_discounts_percent"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    external_discount_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_type: Mapped[str] = mapped_column(String(64), nullable=False, default="OTHER", server_default="OTHER")
    amount: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    order = relationship("POSOrder", back_populates="discounts")
