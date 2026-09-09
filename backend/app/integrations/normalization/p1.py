from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from app.integrations.base import ProviderRecord
from app.integrations.canonical import (
    CanonicalAttendance,
    CanonicalInventory,
    CanonicalInventoryItem,
    CanonicalPurchase,
    CanonicalPurchaseItem,
    CanonicalRecipe,
    CanonicalRecipeItem,
    CanonicalStockMovement,
    CanonicalStockSnapshot,
    CanonicalSupplier,
    CanonicalWarehouse,
    CanonicalWriteoff,
    CanonicalWriteoffItem,
)
from app.integrations.normalization.common import boolean, decimal_value, identifier, label, parse_datetime, text
from app.integrations.normalization.contracts import NormalizationContext


_MOVEMENT_TYPES = {
    "PURCHASE",
    "SALE",
    "WRITEOFF",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "PRODUCTION",
    "INVENTORY_CORRECTION",
    "RETURN_TO_SUPPLIER",
}
_WRITEOFF_REASONS = {
    "SPOILAGE",
    "EXPIRED",
    "STAFF_ERROR",
    "STAFF_MEAL",
    "BREAKAGE",
    "TECHNICAL",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return None


def _datetime(value: Any, *, context: NormalizationContext, required: bool = True) -> datetime | None:
    parsed = parse_datetime(value, timezone_name=context.timezone)
    if required and parsed is None:
        raise ValueError("Provider object has no required timestamp")
    return parsed


def _date(value: Any, *, context: NormalizationContext, fallback: datetime | None = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if value not in (None, ""):
        raw = text(value)
        if raw and len(raw) == 10:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
        parsed = _datetime(value, context=context)
        if parsed is not None:
            return parsed.astimezone(timezone.utc).date()
    if fallback is not None:
        normalized = fallback if fallback.tzinfo is not None else fallback.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).date()
    raise ValueError("Provider document has no document date")


def _canonical_token(value: Any, allowed: set[str], aliases: Mapping[str, str]) -> str:
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else "OTHER"


class ExtendedCanonicalNormalizer:
    """Provider payload aliases for the P1/P2 canonical inventory boundary.

    A provider may subclass and translate payloads before calling these methods.
    Capability audit must still prove that the configured endpoint is callable.
    """

    VERSION = "pos-p1-p2-v1"

    def normalize_recipes(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        product = _first(payload, "product", "dish", "productId", "dishId")
        valid_from = _datetime(
            _first(payload, "validFrom", "dateFrom", "startDate")
            or record.source_updated_at
            or datetime(1970, 1, 1, tzinfo=timezone.utc),
            context=context,
        )
        valid_to = _datetime(
            _first(payload, "validTo", "dateTo", "endDate"), context=context, required=False
        )
        items = tuple(self._recipe_items(_first(payload, "items", "ingredients", "composition") or ()))
        return (
            CanonicalRecipe(
                external_id=f"{record.external_id}:{valid_from.isoformat()}",
                product_external_id=identifier(product),
                valid_from=valid_from,
                valid_to=valid_to,
                yield_quantity=decimal_value(_first(payload, "yieldQuantity", "yield", "output"), default=Decimal("1")),
                yield_unit=label(_first(payload, "yieldUnit", "unit", "measureUnit"), default="unit") or "unit",
                source_updated_at=record.source_updated_at,
                items=items,
            ),
        )

    @staticmethod
    def _recipe_items(values: Iterable[Any]):
        for index, raw in enumerate(values):
            item = _mapping(raw)
            if not item:
                continue
            ingredient = _first(item, "ingredient", "product", "ingredientId", "productId")
            yield CanonicalRecipeItem(
                external_id=identifier(item) or f"ingredient:{index}",
                ingredient_external_id=identifier(ingredient),
                quantity=decimal_value(_first(item, "quantity", "amount", "netAmount")),
                unit=label(_first(item, "unit", "measureUnit"), default="unit") or "unit",
            )

    def normalize_warehouses(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        return (
            CanonicalWarehouse(
                external_id=record.external_id,
                name=label(payload, default=f"Warehouse {record.external_id}") or record.external_id,
                type=text(_first(payload, "type", "warehouseType", "storeType")),
                active=not boolean(_first(payload, "deleted", "isDeleted", "inactive"), default=False),
            ),
        )

    def normalize_stock_balances(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        warehouse = _first(payload, "warehouse", "store", "warehouseId", "storeId")
        product = _first(payload, "product", "item", "productId", "itemId")
        snapshot_at = _datetime(
            _first(payload, "snapshotAt", "date", "timestamp", "moment") or record.source_updated_at,
            context=context,
        )
        quantity = decimal_value(_first(payload, "quantity", "amount", "balance"))
        cost_per_unit = self._optional_decimal(_first(payload, "costPerUnit", "unitCost", "costPrice"))
        total_cost = self._optional_decimal(_first(payload, "totalCost", "sum", "cost"))
        if total_cost is None and cost_per_unit is not None:
            total_cost = quantity * cost_per_unit
        return (
            CanonicalStockSnapshot(
                external_id=f"{record.external_id}:{snapshot_at.isoformat()}",
                warehouse_external_id=identifier(warehouse),
                product_external_id=identifier(product),
                quantity=quantity,
                cost_per_unit=cost_per_unit,
                total_cost=total_cost,
                snapshot_at=snapshot_at,
            ),
        )

    def normalize_stock_movements(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        occurred_at = _datetime(
            _first(payload, "occurredAt", "date", "timestamp", "moment") or record.source_updated_at,
            context=context,
        )
        return (
            CanonicalStockMovement(
                external_id=record.external_id,
                warehouse_external_id=identifier(_first(payload, "warehouse", "store", "warehouseId", "storeId")),
                product_external_id=identifier(_first(payload, "product", "item", "productId", "itemId")),
                movement_type=_canonical_token(
                    _first(payload, "movementType", "operationType", "type"),
                    _MOVEMENT_TYPES,
                    {
                        "INVOICE": "PURCHASE",
                        "PURCHASE_INVOICE": "PURCHASE",
                        "WRITE_OFF": "WRITEOFF",
                        "TRANSFERIN": "TRANSFER_IN",
                        "TRANSFEROUT": "TRANSFER_OUT",
                        "INVENTORY": "INVENTORY_CORRECTION",
                        "SUPPLIER_RETURN": "RETURN_TO_SUPPLIER",
                    },
                ),
                quantity=decimal_value(_first(payload, "quantity", "amount")),
                unit=label(_first(payload, "unit", "measureUnit")),
                cost_per_unit=self._optional_decimal(_first(payload, "costPerUnit", "unitCost", "price")),
                total_cost=self._optional_decimal(_first(payload, "totalCost", "sum", "amountTotal")),
                occurred_at=occurred_at,
                source_reason=text(_first(payload, "reason", "comment", "operationName")),
                source_updated_at=record.source_updated_at,
            ),
        )

    def normalize_suppliers(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        return (
            CanonicalSupplier(
                external_id=record.external_id,
                name=label(record.payload, default=f"Supplier {record.external_id}") or record.external_id,
                active=not boolean(_first(record.payload, "deleted", "isDeleted", "inactive"), default=False),
            ),
        )

    def normalize_purchases(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        items = tuple(self._purchase_items(_first(payload, "items", "positions", "documentItems") or ()))
        explicit_total = self._optional_decimal(_first(payload, "totalAmount", "sum", "amount"))
        total = explicit_total if explicit_total is not None else sum((item.total_amount for item in items), Decimal("0"))
        return (
            CanonicalPurchase(
                external_id=record.external_id,
                supplier_external_id=identifier(_first(payload, "supplier", "counterparty", "supplierId")),
                warehouse_external_id=identifier(_first(payload, "warehouse", "store", "warehouseId", "storeId")),
                document_date=_date(
                    _first(payload, "documentDate", "date", "createdAt"),
                    context=context,
                    fallback=record.source_updated_at,
                ),
                document_number=text(_first(payload, "documentNumber", "number", "code")),
                total_amount=total,
                status=str(_first(payload, "status", "documentStatus") or "UNKNOWN").upper(),
                source_updated_at=record.source_updated_at,
                items=items,
            ),
        )

    @staticmethod
    def _purchase_items(values: Iterable[Any]):
        for index, raw in enumerate(values):
            item = _mapping(raw)
            if not item:
                continue
            quantity = decimal_value(_first(item, "quantity", "amount"))
            price = decimal_value(_first(item, "pricePerUnit", "price", "cost"))
            yield CanonicalPurchaseItem(
                external_id=identifier(item) or f"item:{index}",
                product_external_id=identifier(_first(item, "product", "item", "productId", "itemId")),
                quantity=quantity,
                unit=label(_first(item, "unit", "measureUnit")),
                price_per_unit=price,
                total_amount=decimal_value(_first(item, "totalAmount", "sum"), default=quantity * price),
            )

    def normalize_writeoffs(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        items = tuple(self._writeoff_items(_first(payload, "items", "positions", "documentItems") or ()))
        source_reason = text(_first(payload, "reason", "writeoffReason", "comment"))
        total = self._optional_decimal(_first(payload, "totalAmount", "sum", "amount"))
        return (
            CanonicalWriteoff(
                external_id=record.external_id,
                warehouse_external_id=identifier(_first(payload, "warehouse", "store", "warehouseId", "storeId")),
                document_date=_date(
                    _first(payload, "documentDate", "date", "createdAt"),
                    context=context,
                    fallback=record.source_updated_at,
                ),
                document_number=text(_first(payload, "documentNumber", "number", "code")),
                canonical_reason=_canonical_token(
                    source_reason,
                    _WRITEOFF_REASONS,
                    {
                        "SPOILED": "SPOILAGE",
                        "EXPIRATION": "EXPIRED",
                        "EMPLOYEE_ERROR": "STAFF_ERROR",
                        "EMPLOYEE_MEAL": "STAFF_MEAL",
                        "BROKEN": "BREAKAGE",
                    },
                ),
                source_reason=source_reason,
                total_amount=total if total is not None else sum((item.total_amount or Decimal("0") for item in items), Decimal("0")),
                status=str(_first(payload, "status", "documentStatus") or "UNKNOWN").upper(),
                source_updated_at=record.source_updated_at,
                items=items,
            ),
        )

    @staticmethod
    def _writeoff_items(values: Iterable[Any]):
        for index, raw in enumerate(values):
            item = _mapping(raw)
            if not item:
                continue
            quantity = decimal_value(_first(item, "quantity", "amount"))
            cost = ExtendedCanonicalNormalizer._optional_decimal(_first(item, "costPerUnit", "price", "cost"))
            total = ExtendedCanonicalNormalizer._optional_decimal(_first(item, "totalAmount", "sum"))
            yield CanonicalWriteoffItem(
                external_id=identifier(item) or f"item:{index}",
                product_external_id=identifier(_first(item, "product", "item", "productId", "itemId")),
                quantity=quantity,
                unit=label(_first(item, "unit", "measureUnit")),
                cost_per_unit=cost,
                total_amount=total if total is not None else (quantity * cost if cost is not None else None),
            )

    def normalize_inventories(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        return (
            CanonicalInventory(
                external_id=record.external_id,
                warehouse_external_id=identifier(_first(payload, "warehouse", "store", "warehouseId", "storeId")),
                document_date=_date(
                    _first(payload, "documentDate", "date", "createdAt"),
                    context=context,
                    fallback=record.source_updated_at,
                ),
                document_number=text(_first(payload, "documentNumber", "number", "code")),
                status=str(_first(payload, "status", "documentStatus") or "UNKNOWN").upper(),
                source_updated_at=record.source_updated_at,
                items=tuple(self._inventory_items(_first(payload, "items", "positions", "documentItems") or ())),
            ),
        )

    @staticmethod
    def _inventory_items(values: Iterable[Any]):
        for index, raw in enumerate(values):
            item = _mapping(raw)
            if not item:
                continue
            book = decimal_value(_first(item, "bookQuantity", "expectedQuantity", "bookAmount"))
            actual = decimal_value(_first(item, "actualQuantity", "quantity", "actualAmount"))
            difference = decimal_value(_first(item, "differenceQuantity", "difference"), default=actual - book)
            cost = ExtendedCanonicalNormalizer._optional_decimal(_first(item, "costPerUnit", "price", "cost"))
            difference_cost = ExtendedCanonicalNormalizer._optional_decimal(_first(item, "differenceCost", "sum"))
            yield CanonicalInventoryItem(
                external_id=identifier(item) or f"item:{index}",
                product_external_id=identifier(_first(item, "product", "item", "productId", "itemId")),
                book_quantity=book,
                actual_quantity=actual,
                difference_quantity=difference,
                cost_per_unit=cost,
                difference_cost=(difference_cost if difference_cost is not None else difference * cost if cost is not None else None),
            )

    def normalize_attendance(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        return (
            CanonicalAttendance(
                external_id=record.external_id,
                employee_external_id=identifier(_first(payload, "employee", "staff", "employeeId", "staffId")),
                clocked_in_at=_datetime(
                    _first(payload, "clockedInAt", "startAt", "openTime", "arrivalTime"),
                    context=context,
                ),
                clocked_out_at=_datetime(
                    _first(payload, "clockedOutAt", "endAt", "closeTime", "departureTime"),
                    context=context,
                    required=False,
                ),
                source_updated_at=record.source_updated_at,
            ),
        )

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        return None if value in (None, "") else decimal_value(value)
