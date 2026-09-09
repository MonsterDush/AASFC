from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.integrations.base import ProviderRecord
from app.integrations.canonical import (
    CanonicalEmployee,
    CanonicalProduct,
    CanonicalProductGroup,
    CanonicalTerminal,
    CanonicalVenue,
)
from app.integrations.normalization.common import boolean, identifier, label, product_type, text
from app.integrations.normalization.contracts import NormalizationContext
from app.integrations.normalization.quick_resto import QuickRestoP0Normalizer


class IikoP0Normalizer(QuickRestoP0Normalizer):
    VERSION = "iiko-p0-p2-v2"

    def normalize_venues(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        return (
            CanonicalVenue(
                external_id=record.external_id,
                name=label(payload, default=f"iiko {record.external_id}") or record.external_id,
                address=text(payload.get("restaurantAddress") or payload.get("address")),
                timezone=text(payload.get("timeZone") or payload.get("timezone"), default=context.timezone)
                or context.timezone,
                active=not boolean(payload.get("isDisabled") or payload.get("deleted"), default=False),
            ),
        )

    def normalize_terminals(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        return (
            CanonicalTerminal(
                external_id=record.external_id,
                name=label(record.payload, default=f"iiko {record.external_id}") or record.external_id,
                active=not boolean(record.payload.get("isDeleted") or record.payload.get("deleted"), default=False),
            ),
        )

    def normalize_employees(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        position = payload.get("role") or payload.get("position") or payload.get("department")
        return (
            CanonicalEmployee(
                external_id=record.external_id,
                name=label(payload, default=f"Сотрудник {record.external_id}") or record.external_id,
                position_name=label(position),
                active=not boolean(payload.get("isDeleted") or payload.get("deleted"), default=False),
            ),
        )

    def normalize_product_groups(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        return (
            CanonicalProductGroup(
                external_id=record.external_id,
                name=label(payload, default=f"Группа {record.external_id}") or record.external_id,
                parent_external_id=identifier(payload.get("parentGroup") or payload.get("parentGroupId")),
                kind="CATEGORY" if boolean(payload.get("isCategory"), default=False) else "GROUP",
                active=not boolean(payload.get("isDeleted") or payload.get("deleted"), default=False),
            ),
        )

    def normalize_products(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        return (
            CanonicalProduct(
                external_id=record.external_id,
                name=label(payload, default=f"Позиция {record.external_id}") or record.external_id,
                code=text(payload.get("code") or payload.get("num")),
                barcode=text(payload.get("barcode")),
                type=product_type(payload.get("type") or payload.get("productType")),
                group_external_id=identifier(payload.get("parentGroup") or payload.get("parentGroupId")),
                category_external_id=identifier(payload.get("productCategory") or payload.get("productCategoryId")),
                unit=text(payload.get("measureUnit") or payload.get("unit")),
                active=not boolean(payload.get("isDeleted") or payload.get("deleted"), default=False),
            ),
        )

    def normalize_orders(self, record: ProviderRecord, *, context: NormalizationContext):
        translated = self._translate_order(record.payload, record.external_id)
        return super().normalize_orders(
            ProviderRecord(
                external_id=record.external_id,
                payload=translated,
                source_updated_at=record.source_updated_at,
            ),
            context=context,
        )

    def _translate_order(self, payload: Mapping[str, Any], order_id: str) -> dict[str, Any]:
        items = []
        for index, raw in enumerate(payload.get("items") or payload.get("orderItems") or ()):
            if not isinstance(raw, Mapping):
                continue
            items.append(self._translate_item(raw, order_id=order_id, index=index))

        payments = []
        for index, raw in enumerate(payload.get("payments") or ()):
            if not isinstance(raw, Mapping):
                continue
            source = raw.get("paymentType") or {
                "id": raw.get("paymentTypeId"),
                "name": raw.get("paymentTypeKind") or raw.get("type"),
            }
            payments.append(
                {
                    "id": identifier(raw) or f"{order_id}:payment:{index}",
                    "paymentType": source,
                    "amount": raw.get("sum", raw.get("amount", 0)),
                    "operationType": raw.get("operationType"),
                }
            )

        discounts = []
        discount_rows = payload.get("discounts") or (payload.get("discountsInfo") or {}).get("discounts") or ()
        for index, raw in enumerate(discount_rows):
            if not isinstance(raw, Mapping):
                continue
            source = raw.get("discountType") or raw.get("type")
            discounts.append(
                {
                    "id": identifier(raw) or identifier(source) or f"{order_id}:discount:{index}",
                    "discountType": source,
                    "amount": raw.get("sum", raw.get("amount", 0)),
                    "percent": raw.get("percent"),
                    "employee": raw.get("employee"),
                }
            )

        refunds = []
        for index, raw in enumerate(payload.get("refunds") or payload.get("returns") or ()):
            if not isinstance(raw, Mapping):
                continue
            refunds.append(
                {
                    "id": identifier(raw) or f"{order_id}:refund:{index}",
                    "amount": raw.get("sum", raw.get("amount", 0)),
                    "reason": raw.get("reason") or raw.get("comment"),
                    "employee": raw.get("employee"),
                }
            )

        total = payload.get("sum", payload.get("resultSum", payload.get("total", 0)))
        discount_total = payload.get("discountSum", payload.get("discountAmount", 0))
        if not discount_total and discounts:
            discount_total = sum(Decimal(str(item.get("amount") or 0)) for item in discounts)
        return {
            "id": order_id,
            "frontId": order_id,
            "number": payload.get("number") or payload.get("externalNumber"),
            "checkNumber": payload.get("checkNumber"),
            "status": payload.get("status") or payload.get("orderStatus"),
            "returned": payload.get("isRefund") or payload.get("returned"),
            "localOpenedTime": payload.get("whenCreated") or payload.get("createdAt") or payload.get("openedAt"),
            "localClosedTime": payload.get("whenClosed") or payload.get("closedAt") or payload.get("completeBefore"),
            "businessDate": payload.get("businessDate"),
            "orderType": label(payload.get("orderType")) or payload.get("orderServiceType"),
            "table": payload.get("table"),
            "tableId": payload.get("tableId"),
            "tableName": payload.get("tableName"),
            "guestCount": (payload.get("guests") or {}).get("count")
            if isinstance(payload.get("guests"), Mapping)
            else payload.get("guestCount"),
            "cashier": payload.get("cashier") or payload.get("operator"),
            "cashierId": payload.get("cashierId") or payload.get("operatorId"),
            "waiter": payload.get("waiter"),
            "waiterId": payload.get("waiterId"),
            "frontTotalPrice": total,
            "subtotal": payload.get("subtotal", Decimal(str(total or 0)) + Decimal(str(discount_total or 0))),
            "frontTotalAbsoluteDiscount": discount_total,
            "frontTotalAbsoluteCharge": payload.get("serviceCharge", 0),
            "deliveryFee": payload.get("deliveryFee", 0),
            "customer": payload.get("customer") or payload.get("client") or payload.get("guest"),
            "customerId": payload.get("customerId") or payload.get("clientId"),
            "currency": payload.get("currency", "RUB"),
            "orderItemList": items,
            "payments": payments,
            "discounts": discounts,
            "refunds": refunds,
            "events": payload.get("events") or payload.get("history") or (),
        }

    def _translate_item(self, raw: Mapping[str, Any], *, order_id: str, index: int) -> dict[str, Any]:
        item_id = identifier(raw) or f"{order_id}:item:{index}"
        product = raw.get("product") if isinstance(raw.get("product"), Mapping) else {
            "id": raw.get("productId"),
            "name": raw.get("productName") or raw.get("name"),
        }
        amount = raw.get("amount", raw.get("quantity", 1))
        price = raw.get("price", raw.get("basePrice", 0))
        result_sum = raw.get("resultSum", raw.get("sum", raw.get("total", Decimal(str(amount or 0)) * Decimal(str(price or 0)))))
        discount = raw.get("discountSum", raw.get("discountAmount", 0))
        gross = raw.get("grossSum", Decimal(str(result_sum or 0)) + Decimal(str(discount or 0)))
        modifiers = []
        for modifier_index, modifier in enumerate(raw.get("modifiers") or ()):
            if isinstance(modifier, Mapping):
                modifiers.append(self._translate_item(modifier, order_id=order_id, index=modifier_index))
        return {
            "id": item_id,
            "product": product,
            "amount": amount,
            "price": price,
            "totalPrice": gross,
            "totalAbsoluteDiscount": discount,
            "netAmount": result_sum,
            "cost": raw.get("cost"),
            "deleted": raw.get("isDeleted") or raw.get("deleted"),
            "returned": raw.get("isRefunded") or raw.get("returned"),
            "modifiers": modifiers,
        }
