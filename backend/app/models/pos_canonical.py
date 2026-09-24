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


class POSTerminalGroup(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_terminal_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_terminal_groups_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    pos_venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_alive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_alive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    pos_venue = relationship("POSVenue")


class POSTerminal(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_terminals_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    pos_venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    terminal_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_terminal_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sale_place_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    pos_venue = relationship("POSVenue")
    terminal_group = relationship("POSTerminalGroup")


class POSRestaurantSection(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_restaurant_sections"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_restaurant_sections_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSTable(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_tables"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_tables_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_restaurant_sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    restaurant_section = relationship("POSRestaurantSection")


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
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")


class POSProductOptionGroup(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_option_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_option_groups_external_identity"),
        CheckConstraint("min_selection >= 0", name="ck_pos_product_option_groups_min_selection"),
        CheckConstraint(
            "max_selection IS NULL OR max_selection >= min_selection",
            name="ck_pos_product_option_groups_selection_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    min_selection: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_selection: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    product = relationship("POSProduct")


class POSProductOption(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_options"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_options_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    option_group_id: Mapped[int] = mapped_column(
        ForeignKey("pos_product_option_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price_delta: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    option_group = relationship("POSProductOptionGroup")


class POSProductVariant(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_variants"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_variants_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    option_signature_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    product = relationship("POSProduct")


class POSProductVariantOption(Base):
    __tablename__ = "pos_product_variant_options"
    __table_args__ = (UniqueConstraint("variant_id", "option_id", name="uq_pos_product_variant_options_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    option_id: Mapped[int] = mapped_column(
        ForeignKey("pos_product_options.id", ondelete="CASCADE"), nullable=False, index=True
    )

    variant = relationship("POSProductVariant")
    option = relationship("POSProductOption")


class POSModifierGroup(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_modifier_groups"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_modifier_groups_external_identity"),
        CheckConstraint("min_quantity >= 0", name="ck_pos_modifier_groups_min_quantity"),
        CheckConstraint(
            "max_quantity IS NULL OR max_quantity >= min_quantity", name="ck_pos_modifier_groups_quantity_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class POSModifier(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_modifiers"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_pos_modifiers_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifier_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    price_delta: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    modifier_group = relationship("POSModifierGroup")
    product = relationship("POSProduct")


class POSProductModifierRule(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_product_modifier_rules"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_product_modifier_rules_external_identity"),
        CheckConstraint("min_amount >= 0", name="ck_pos_product_modifier_rules_min_amount"),
        CheckConstraint(
            "max_amount IS NULL OR max_amount >= min_amount",
            name="ck_pos_product_modifier_rules_amount_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    modifier_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifier_groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    modifier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifiers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    min_amount: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False, default=0, server_default="0")
    max_amount: Mapped[Decimal | None] = mapped_column(QUANTITY_TYPE, nullable=True)
    default_amount: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False, default=0, server_default="0")
    free_amount: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False, default=0, server_default="0")
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")
    modifier_group = relationship("POSModifierGroup")
    modifier = relationship("POSModifier")


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


class POSStopListEntry(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_stop_list_entries"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_stop_list_entries_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    terminal_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_terminal_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    modifier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifiers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    balance: Mapped[Decimal | None] = mapped_column(QUANTITY_TYPE, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    terminal_group = relationship("POSTerminalGroup")
    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")
    modifier = relationship("POSModifier")


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
    current_orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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
            "status IN ('NEW', 'OPEN', 'IN_PROGRESS', 'BILL_PRINTED', 'READY', 'CLOSED', 'CANCELLED', 'RETURNED', "
            "'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED', 'UNKNOWN')",
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
    terminal_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_terminal_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    restaurant_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_restaurant_sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_tables.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_status: Mapped[str | None] = mapped_column(String(96), nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    guests_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    payment_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    refund_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    current_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    business_shift = relationship("POSBusinessShift")
    terminal = relationship("POSTerminal")
    terminal_group = relationship("POSTerminalGroup")
    restaurant_section = relationship("POSRestaurantSection")
    table = relationship("POSTable")
    employee = relationship("POSEmployee")

    @property
    def guest_count(self) -> int | None:
        """Canonical singular alias preserving the existing database column."""

        return self.guests_count

    @guest_count.setter
    def guest_count(self, value: int | None) -> None:
        self.guests_count = value


class POSOrderItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_order_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_order_items_external_identity"),
        CheckConstraint(
            "item_role IN ('PRODUCT', 'COMPOUND', 'COMPONENT', 'MODIFIER')",
            name="ck_pos_order_items_item_role",
        ),
        CheckConstraint(
            "component_role IS NULL OR component_role IN ('PRIMARY', 'SECONDARY', 'COMMON', 'MODIFIER')",
            name="ck_pos_order_items_component_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_order_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_line_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_role: Mapped[str] = mapped_column(String(16), nullable=False, default="PRODUCT", server_default="PRODUCT")
    component_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    attributed_net_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    cost_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    included_in_parent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_modifier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order = relationship("POSOrder")
    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")
    parent_item = relationship("POSOrderItem", remote_side="POSOrderItem.id", foreign_keys=[parent_item_id])


class POSOrderItemModifier(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_order_item_modifiers"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_order_item_modifiers_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("pos_order_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    modifier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifiers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    modifier_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_modifier_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    total_price: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order_item = relationship("POSOrderItem")
    modifier = relationship("POSModifier")
    modifier_group = relationship("POSModifierGroup")


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


class POSRecipe(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_recipes"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_recipes_external_identity"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_recipes_period"),
        CheckConstraint("yield_quantity > 0", name="ck_pos_recipes_yield_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    yield_quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    yield_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")
    items = relationship("POSRecipeItem", back_populates="recipe", cascade="all, delete-orphan")


class POSRecipeItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_recipe_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_recipe_items_external_identity"),
        CheckConstraint("quantity > 0", name="ck_pos_recipe_items_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("pos_recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    loss_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)

    recipe = relationship("POSRecipe", back_populates="items")
    ingredient = relationship("POSProduct")


class POSStockSnapshot(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_stock_snapshots"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_snapshots_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    warehouse = relationship("POSWarehouse")
    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")


class POSStockMovement(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_stock_movements"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_stock_movements_external_identity"),
        CheckConstraint(
            "movement_type IN ('PURCHASE', 'SALE', 'WRITEOFF', 'TRANSFER_IN', 'TRANSFER_OUT', "
            "'PRODUCTION', 'INVENTORY_CORRECTION', 'RETURN_TO_SUPPLIER', 'OTHER')",
            name="ck_pos_stock_movements_type",
        ),
        CheckConstraint("quantity <> 0", name="ck_pos_stock_movements_quantity_nonzero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    warehouse = relationship("POSWarehouse")
    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")


class POSPurchaseDocument(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_purchase_documents"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_documents_external_identity"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_purchase_documents_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    supplier = relationship("POSSupplier")
    warehouse = relationship("POSWarehouse")
    items = relationship("POSPurchaseItem", back_populates="document", cascade="all, delete-orphan")


class POSPurchaseItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_purchase_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_purchase_items_external_identity"),
        CheckConstraint("quantity > 0", name="ck_pos_purchase_items_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pos_purchase_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    price_per_unit: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    document = relationship("POSPurchaseDocument", back_populates="items")
    product = relationship("POSProduct")


class POSWriteoff(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_writeoffs"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoffs_external_identity"),
        CheckConstraint(
            "canonical_reason IN ('SPOILAGE', 'EXPIRED', 'STAFF_ERROR', 'STAFF_MEAL', "
            "'BREAKAGE', 'TECHNICAL', 'OTHER')",
            name="ck_pos_writeoffs_reason",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_writeoffs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    canonical_reason: Mapped[str] = mapped_column(String(24), nullable=False, default="OTHER", server_default="OTHER")
    source_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_cost: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    warehouse = relationship("POSWarehouse")
    employee = relationship("POSEmployee")
    items = relationship("POSWriteoffItem", back_populates="writeoff", cascade="all, delete-orphan")


class POSWriteoffItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_writeoff_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_writeoff_items_external_identity"),
        CheckConstraint("quantity > 0", name="ck_pos_writeoff_items_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    writeoff_id: Mapped[int] = mapped_column(
        ForeignKey("pos_writeoffs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    writeoff = relationship("POSWriteoff", back_populates="items")
    product = relationship("POSProduct")


class POSInventoryDocument(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_inventory_documents"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_documents_external_identity"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_inventory_documents_status",
        ),
        CheckConstraint(
            "document_type IN ('PURCHASE', 'OUTGOING_INVOICE', 'WRITEOFF', 'INVENTORY', "
            "'PRODUCTION', 'TRANSFORMATION', 'TRANSFER')",
            name="ck_pos_inventory_documents_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    warehouse_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    warehouse_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="INVENTORY", server_default="INVENTORY"
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    warehouse = relationship("POSWarehouse", foreign_keys=[warehouse_id])
    warehouse_from = relationship("POSWarehouse", foreign_keys=[warehouse_from_id])
    warehouse_to = relationship("POSWarehouse", foreign_keys=[warehouse_to_id])
    supplier = relationship("POSSupplier")
    items = relationship("POSInventoryItem", back_populates="document", cascade="all, delete-orphan")


class POSInventoryItem(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_inventory_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_inventory_items_external_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pos_inventory_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    book_quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    actual_quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    difference_quantity: Mapped[Decimal] = mapped_column(QUANTITY_TYPE, nullable=False)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    difference_cost: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    cost_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY_TYPE, nullable=True)
    price_per_unit: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY_TYPE, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    document = relationship("POSInventoryDocument", back_populates="items")
    product = relationship("POSProduct")
    variant = relationship("POSProductVariant")


class POSEmployeeAttendance(_CanonicalExternalMixin, Base):
    __tablename__ = "pos_employee_attendance"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_pos_employee_attendance_external_identity"),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_employee_attendance_status",
        ),
        CheckConstraint("clock_out_at IS NULL OR clock_out_at > clock_in_at", name="ck_pos_employee_attendance_period"),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0", name="ck_pos_employee_attendance_duration"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")

    employee = relationship("POSEmployee")
