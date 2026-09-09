from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from app.integrations.base import ProviderRecord
from app.integrations.canonical import (
    CanonicalDiscount,
    CanonicalCustomerIdentity,
    CanonicalEmployee,
    CanonicalOrder,
    CanonicalOrderEvent,
    CanonicalOrderItem,
    CanonicalPayment,
    CanonicalProduct,
    CanonicalProductGroup,
    CanonicalRefund,
    CanonicalTerminal,
    CanonicalVenue,
)
from app.integrations.normalization.common import (
    boolean,
    decimal_value,
    identifier,
    label,
    local_date,
    parse_datetime,
    payment_type,
    product_type,
    provider_status,
    text,
)
from app.integrations.normalization.contracts import NormalizationContext
from app.integrations.normalization.p1 import ExtendedCanonicalNormalizer


class QuickRestoP0Normalizer(ExtendedCanonicalNormalizer):
    VERSION = "quickresto-p0-p2-v2"

    def normalize_venues(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        return (
            CanonicalVenue(
                external_id=record.external_id,
                name=label(payload, default=f"QuickResto {record.external_id}") or record.external_id,
                address=self._address(payload.get("address")),
                timezone=text(payload.get("timezone"), default=context.timezone) or context.timezone,
                active=not boolean(payload.get("deleted"), default=False),
            ),
        )

    def normalize_terminals(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        return (
            CanonicalTerminal(
                external_id=record.external_id,
                name=label(record.payload, default=f"QuickResto {record.external_id}") or record.external_id,
                active=not boolean(record.payload.get("deleted"), default=False),
            ),
        )

    def normalize_employees(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        position = payload.get("position") or payload.get("role") or payload.get("employeePosition")
        return (
            CanonicalEmployee(
                external_id=record.external_id,
                name=label(payload, default=f"Сотрудник {record.external_id}") or record.external_id,
                position_name=label(position),
                active=not boolean(payload.get("deleted") or payload.get("blocked"), default=False),
            ),
        )

    def normalize_product_groups(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        return (
            CanonicalProductGroup(
                external_id=record.external_id,
                name=label(payload, default=f"Группа {record.external_id}") or record.external_id,
                parent_external_id=identifier(payload.get("parent") or payload.get("parentId")),
                kind="CATEGORY" if "category" in str(payload.get("@type") or "").lower() else "GROUP",
                active=not boolean(payload.get("deleted"), default=False),
            ),
        )

    def normalize_products(self, record: ProviderRecord, *, context: NormalizationContext):
        del context
        payload = record.payload
        group = payload.get("group") or payload.get("parent") or payload.get("parentId")
        category = payload.get("category") or payload.get("dishCategory")
        return (
            CanonicalProduct(
                external_id=record.external_id,
                name=label(payload, default=f"Позиция {record.external_id}") or record.external_id,
                code=text(payload.get("code") or payload.get("article")),
                barcode=text(payload.get("barcode")),
                type=product_type(payload.get("type") or payload.get("productType") or "DISH"),
                group_external_id=identifier(group),
                category_external_id=identifier(category),
                unit=label(payload.get("unit")) or text(payload.get("unitName")),
                active=not boolean(payload.get("deleted"), default=False),
            ),
        )

    def normalize_orders(self, record: ProviderRecord, *, context: NormalizationContext):
        payload = record.payload
        payment_rows = [item for item in (payload.get("payments") or ()) if isinstance(item, Mapping)]
        operation_types = {str(item.get("operationType") or "").strip().lower() for item in payment_rows}
        if operation_types and operation_types == {"writeoff"}:
            return ()
        opened_at = self._datetime(payload, context, "localOpenedTime", "opened", "openedAt", "created")
        closed_at = self._datetime(payload, context, "localClosedTime", "closed", "closedAt")
        explicit_date = text(payload.get("_axelio_business_date") or payload.get("businessDate"))
        business_date = date.fromisoformat(explicit_date) if explicit_date else local_date(
            closed_at or opened_at,
            timezone_name=context.timezone,
            cutoff_hour=context.business_day_cutoff_hour,
        )
        calendar_date = local_date(
            closed_at or opened_at,
            timezone_name=context.timezone,
            cutoff_hour=0,
        )

        returned = boolean(payload.get("returned"), default=False)
        source_order_total = abs(
            decimal_value(payload.get("frontTotalPrice") or payload.get("total") or payload.get("sum"))
        )
        order_total = Decimal("0") if returned else source_order_total
        order_discount = abs(
            decimal_value(payload.get("frontTotalAbsoluteDiscount") or payload.get("discountAmount"))
        )
        service_charge = decimal_value(payload.get("frontTotalAbsoluteCharge") or payload.get("serviceCharge"))
        delivery_fee = decimal_value(payload.get("deliveryFee"))
        refunds = self._refunds(payload, record.external_id, closed_at, returned, source_order_total)
        refund_amount = sum((item.amount for item in refunds), Decimal("0"))
        items = tuple(self._items(payload.get("orderItemList") or payload.get("items") or (), order_id=record.external_id))
        subtotal = decimal_value(payload.get("subtotal"), default=order_total + order_discount - service_charge - delivery_fee)
        payments = tuple(self._payments(payload, record.external_id, closed_at, returned))
        discounts = tuple(self._discounts(payload, record.external_id, order_discount))
        status = provider_status(payload.get("status"), returned=returned, refund_amount=refund_amount)
        events = self._events(payload, record.external_id, opened_at, closed_at, status, refunds)
        table = payload.get("table") or payload.get("tableInfo")
        customer = payload.get("customer") or payload.get("client") or payload.get("guest")
        customer_id = identifier(customer or payload.get("customerId") or payload.get("clientId"))
        order = CanonicalOrder(
                external_id=record.external_id,
                order_number=text(payload.get("number") or payload.get("orderNumber")),
                check_number=text(payload.get("checkNumber") or payload.get("receiptNumber")),
                business_date=business_date,
                calendar_date=calendar_date,
                opened_at=opened_at,
                closed_at=closed_at,
                status=status,
                order_type=text(payload.get("orderType") or payload.get("type")),
                table_external_id=identifier(table or payload.get("tableId")),
                table_name=label(table) or text(payload.get("tableName")),
                guest_count=self._integer(payload.get("guestCount") or payload.get("guestsCount")),
                cashier_external_id=identifier(payload.get("cashier") or payload.get("cashierId")),
                waiter_external_id=identifier(payload.get("waiter") or payload.get("waiterId") or payload.get("employee")),
                customer_external_id=customer_id,
                subtotal=subtotal,
                discount_amount=order_discount,
                service_charge=service_charge,
                delivery_fee=delivery_fee,
                total_amount=order_total,
                refund_amount=refund_amount,
                currency=(text(payload.get("currency"), default="RUB") or "RUB")[:3].upper(),
                source_created_at=opened_at,
                source_updated_at=record.source_updated_at or closed_at or opened_at,
                items=items,
                events=events,
                payments=payments,
                refunds=refunds,
                discounts=discounts,
            )
        if not customer_id:
            return (order,)
        return (
            order,
            CanonicalCustomerIdentity(
                external_id=customer_id,
                display_name=label(customer),
                source_updated_at=record.source_updated_at,
            ),
        )

    @staticmethod
    def _address(value: Any) -> str | None:
        if isinstance(value, Mapping):
            return text(value.get("fullAddress") or value.get("value") or value.get("address"))
        return text(value)

    @staticmethod
    def _datetime(payload: Mapping[str, Any], context: NormalizationContext, *keys: str):
        for key in keys:
            if payload.get(key) not in (None, ""):
                return parse_datetime(payload[key], timezone_name=context.timezone)
        return None

    @staticmethod
    def _integer(value: Any) -> int | None:
        if value in (None, ""):
            return None
        result = int(value)
        return max(result, 0)

    def _items(self, values: Iterable[Any], *, order_id: str, parent_id: str | None = None):
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                continue
            product = raw.get("product") if isinstance(raw.get("product"), Mapping) else {}
            external_id = identifier(raw) or f"{order_id}:item:{index}"
            quantity = decimal_value(raw.get("amount") or raw.get("quantity"), default=Decimal("1"))
            base_price = decimal_value(raw.get("price") or raw.get("basePrice"))
            gross = decimal_value(raw.get("totalPrice") or raw.get("grossAmount"), default=base_price * quantity)
            discount = abs(decimal_value(raw.get("totalAbsoluteDiscount") or raw.get("discountAmount")))
            charge = decimal_value(raw.get("totalAbsoluteCharge") or raw.get("chargeAmount"))
            net = decimal_value(raw.get("netAmount"), default=gross - discount + charge)
            yield CanonicalOrderItem(
                external_id=external_id,
                product_external_id=identifier(product or raw.get("productId")),
                product_name=label(product) or text(raw.get("productName"), default=f"Позиция {external_id}") or external_id,
                category_name=label(product.get("parent") if isinstance(product, Mapping) else None),
                quantity=quantity,
                base_price=base_price,
                final_price=decimal_value(raw.get("finalPrice"), default=(net / quantity if quantity else Decimal("0"))),
                gross_amount=gross,
                discount_amount=discount,
                net_amount=net,
                cost_amount=(decimal_value(raw.get("cost")) if raw.get("cost") not in (None, "") else None),
                is_modifier=parent_id is not None or boolean(raw.get("isModifier"), default=False),
                parent_external_id=parent_id,
                is_deleted=boolean(raw.get("deleted"), default=False),
                is_refunded=boolean(raw.get("returned") or raw.get("refunded"), default=False),
            )
            modifiers = raw.get("modifiers") or raw.get("modifierItems") or ()
            yield from self._items(modifiers, order_id=order_id, parent_id=external_id)

    @staticmethod
    def _payments(payload, order_id, closed_at, returned):
        for index, raw in enumerate(payload.get("payments") or ()):
            if not isinstance(raw, Mapping):
                continue
            source = raw.get("paymentType") or raw.get("type") or raw.get("paymentMechanismWeb")
            operation = str(raw.get("operationType") or "").upper()
            if returned or "RETURN" in operation or "REFUND" in operation:
                continue
            yield CanonicalPayment(
                external_id=identifier(raw) or f"{order_id}:payment:{index}",
                canonical_type=payment_type(label(source) or identifier(source) or operation),
                source_type=label(source) or identifier(source),
                amount=abs(decimal_value(raw.get("amount") or raw.get("sum"))),
                paid_at=closed_at,
            )

    @staticmethod
    def _refunds(payload, order_id, closed_at, returned, order_total):
        rows = payload.get("refunds") or payload.get("returns") or ()
        output = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                continue
            output.append(
                CanonicalRefund(
                    external_id=identifier(raw) or f"{order_id}:refund:{index}",
                    amount=decimal_value(raw.get("amount") or raw.get("sum")),
                    reason=text(raw.get("reason") or raw.get("comment")),
                    refunded_at=closed_at,
                    employee_external_id=identifier(raw.get("employee")),
                )
            )
        if returned and not output and order_total:
            output.append(CanonicalRefund(external_id=f"{order_id}:return", amount=order_total, refunded_at=closed_at))
        return tuple(output)

    @staticmethod
    def _discounts(payload, order_id, order_discount):
        rows = payload.get("discounts") or payload.get("discountItems") or ()
        output = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                continue
            source = raw.get("discountType") or raw.get("type")
            output.append(
                CanonicalDiscount(
                    external_id=identifier(raw) or identifier(source) or f"{order_id}:discount:{index}",
                    source_name=label(source) or label(raw),
                    amount=decimal_value(raw.get("amount") or raw.get("sum")),
                    percent=(decimal_value(raw.get("percent")) if raw.get("percent") not in (None, "") else None),
                    employee_external_id=identifier(raw.get("employee")),
                )
            )
        if order_discount and not output:
            output.append(CanonicalDiscount(external_id=f"{order_id}:discount", amount=order_discount))
        return tuple(output)

    @staticmethod
    def _events(payload, order_id, opened_at, closed_at, status, refunds):
        output = []
        for index, raw in enumerate(payload.get("events") or payload.get("history") or ()):
            if not isinstance(raw, Mapping):
                continue
            event_type = str(raw.get("eventType") or raw.get("type") or "").upper()
            if event_type not in {
                "ORDER_OPENED", "ORDER_CLOSED", "ITEM_ADDED", "ITEM_REMOVED", "ITEM_CHANGED",
                "DISCOUNT_APPLIED", "PAYMENT_ADDED", "PAYMENT_REMOVED", "ORDER_CANCELLED", "REFUND_CREATED",
            }:
                continue
            output.append(CanonicalOrderEvent(identifier(raw) or f"{order_id}:event:{index}", event_type))
        if opened_at and not any(item.event_type == "ORDER_OPENED" for item in output):
            output.append(CanonicalOrderEvent(f"{order_id}:opened", "ORDER_OPENED", opened_at))
        if closed_at and status in {"CLOSED", "REFUNDED", "PARTIALLY_REFUNDED"}:
            output.append(CanonicalOrderEvent(f"{order_id}:closed", "ORDER_CLOSED", closed_at))
        if status == "CANCELLED":
            output.append(CanonicalOrderEvent(f"{order_id}:cancelled", "ORDER_CANCELLED", closed_at))
        for refund in refunds:
            output.append(CanonicalOrderEvent(f"{refund.external_id}:event", "REFUND_CREATED", refund.refunded_at))
        return tuple(output)
