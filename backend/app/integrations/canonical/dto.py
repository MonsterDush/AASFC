from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


def _money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class CanonicalVenue:
    external_id: str
    name: str
    timezone: str
    address: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CanonicalTerminal:
    external_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class CanonicalEmployee:
    external_id: str
    name: str
    position_name: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CanonicalProductGroup:
    external_id: str
    name: str
    kind: str = "GROUP"
    parent_external_id: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CanonicalProduct:
    external_id: str
    name: str
    type: str = "OTHER"
    code: str | None = None
    barcode: str | None = None
    group_external_id: str | None = None
    category_external_id: str | None = None
    unit: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CanonicalOrderItem:
    external_id: str
    product_external_id: str | None
    product_name: str
    quantity: Decimal
    base_price: Decimal
    final_price: Decimal
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    category_name: str | None = None
    cost_amount: Decimal | None = None
    is_modifier: bool = False
    parent_external_id: str | None = None
    is_deleted: bool = False
    is_refunded: bool = False

    def __post_init__(self) -> None:
        for name in ("quantity", "base_price", "final_price", "gross_amount", "discount_amount", "net_amount"):
            object.__setattr__(self, name, _money(getattr(self, name)))
        if self.cost_amount is not None:
            object.__setattr__(self, "cost_amount", _money(self.cost_amount))


@dataclass(frozen=True)
class CanonicalOrderEvent:
    external_id: str
    event_type: str
    occurred_at: datetime | None = None
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalPayment:
    external_id: str
    canonical_type: str
    amount: Decimal
    source_type: str | None = None
    paid_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _money(self.amount))


@dataclass(frozen=True)
class CanonicalRefund:
    external_id: str
    amount: Decimal
    reason: str | None = None
    refunded_at: datetime | None = None
    employee_external_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", abs(_money(self.amount)))


@dataclass(frozen=True)
class CanonicalDiscount:
    external_id: str
    amount: Decimal
    source_name: str | None = None
    canonical_type: str = "OTHER"
    percent: Decimal | None = None
    employee_external_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", abs(_money(self.amount)))
        if self.percent is not None:
            object.__setattr__(self, "percent", _money(self.percent))


@dataclass(frozen=True)
class CanonicalOrder:
    external_id: str
    business_date: date
    calendar_date: date
    status: str
    subtotal: Decimal
    discount_amount: Decimal
    service_charge: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
    refund_amount: Decimal
    currency: str = "RUB"
    order_number: str | None = None
    check_number: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    order_type: str | None = None
    table_external_id: str | None = None
    table_name: str | None = None
    guest_count: int | None = None
    cashier_external_id: str | None = None
    waiter_external_id: str | None = None
    customer_external_id: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    items: tuple[CanonicalOrderItem, ...] = ()
    events: tuple[CanonicalOrderEvent, ...] = ()
    payments: tuple[CanonicalPayment, ...] = ()
    refunds: tuple[CanonicalRefund, ...] = ()
    discounts: tuple[CanonicalDiscount, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "subtotal",
            "discount_amount",
            "service_charge",
            "delivery_fee",
            "total_amount",
            "refund_amount",
        ):
            object.__setattr__(self, name, _money(getattr(self, name)))
        for name in ("items", "events", "payments", "refunds", "discounts"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalRecipeItem:
    external_id: str
    ingredient_external_id: str | None
    quantity: Decimal
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _money(self.quantity))


@dataclass(frozen=True)
class CanonicalRecipe:
    external_id: str
    product_external_id: str | None
    valid_from: datetime
    valid_to: datetime | None
    yield_quantity: Decimal
    yield_unit: str
    source_updated_at: datetime | None = None
    items: tuple[CanonicalRecipeItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "yield_quantity", _money(self.yield_quantity))
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class CanonicalWarehouse:
    external_id: str
    name: str
    type: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CanonicalStockSnapshot:
    external_id: str
    warehouse_external_id: str | None
    product_external_id: str | None
    quantity: Decimal
    snapshot_at: datetime
    cost_per_unit: Decimal | None = None
    total_cost: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _money(self.quantity))
        for name in ("cost_per_unit", "total_cost"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _money(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalStockMovement:
    external_id: str
    warehouse_external_id: str | None
    product_external_id: str | None
    movement_type: str
    quantity: Decimal
    occurred_at: datetime
    unit: str | None = None
    cost_per_unit: Decimal | None = None
    total_cost: Decimal | None = None
    source_reason: str | None = None
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _money(self.quantity))
        for name in ("cost_per_unit", "total_cost"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _money(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalSupplier:
    external_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class CanonicalPurchaseItem:
    external_id: str
    product_external_id: str | None
    quantity: Decimal
    price_per_unit: Decimal
    total_amount: Decimal
    unit: str | None = None

    def __post_init__(self) -> None:
        for name in ("quantity", "price_per_unit", "total_amount"):
            object.__setattr__(self, name, _money(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalPurchase:
    external_id: str
    document_date: date
    total_amount: Decimal
    status: str
    supplier_external_id: str | None = None
    warehouse_external_id: str | None = None
    document_number: str | None = None
    source_updated_at: datetime | None = None
    items: tuple[CanonicalPurchaseItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_amount", _money(self.total_amount))
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class CanonicalWriteoffItem:
    external_id: str
    product_external_id: str | None
    quantity: Decimal
    unit: str | None = None
    cost_per_unit: Decimal | None = None
    total_amount: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _money(self.quantity))
        for name in ("cost_per_unit", "total_amount"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _money(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalWriteoff:
    external_id: str
    document_date: date
    canonical_reason: str
    warehouse_external_id: str | None = None
    document_number: str | None = None
    source_reason: str | None = None
    total_amount: Decimal | None = None
    status: str = "UNKNOWN"
    source_updated_at: datetime | None = None
    items: tuple[CanonicalWriteoffItem, ...] = ()

    def __post_init__(self) -> None:
        if self.total_amount is not None:
            object.__setattr__(self, "total_amount", _money(self.total_amount))
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class CanonicalInventoryItem:
    external_id: str
    product_external_id: str | None
    book_quantity: Decimal
    actual_quantity: Decimal
    difference_quantity: Decimal
    cost_per_unit: Decimal | None = None
    difference_cost: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("book_quantity", "actual_quantity", "difference_quantity"):
            object.__setattr__(self, name, _money(getattr(self, name)))
        for name in ("cost_per_unit", "difference_cost"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _money(getattr(self, name)))


@dataclass(frozen=True)
class CanonicalInventory:
    external_id: str
    document_date: date
    warehouse_external_id: str | None = None
    document_number: str | None = None
    status: str = "UNKNOWN"
    source_updated_at: datetime | None = None
    items: tuple[CanonicalInventoryItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class CanonicalAttendance:
    external_id: str
    employee_external_id: str | None
    clocked_in_at: datetime
    clocked_out_at: datetime | None = None
    source_updated_at: datetime | None = None


@dataclass(frozen=True)
class CanonicalCustomerIdentity:
    external_id: str
    display_name: str | None = None
    source_updated_at: datetime | None = None
