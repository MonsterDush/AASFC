from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from typing import Any, Iterable


class QuickRestoDataError(RuntimeError):
    """Raised when QuickResto data cannot be represented safely in an Axelio report."""


def _money_int(value: Any, *, field: str) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise QuickRestoDataError(f"QuickResto field {field} is not numeric") from exc
    rounded = round(number)
    if abs(number - rounded) > 0.0001:
        raise QuickRestoDataError(f"QuickResto field {field} contains fractional rubles unsupported by Axelio reports")
    return int(rounded)


def _parse_local_datetime(value: Any, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise QuickRestoDataError(f"Closed QuickResto shift has no {field}")
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise QuickRestoDataError(f"QuickResto {field} has an invalid format") from exc


def business_date_for_shift(shift: dict[str, Any], *, cutoff_hour: int) -> date:
    cutoff = int(cutoff_hour)
    if not 0 <= cutoff <= 23:
        raise ValueError("business day cutoff hour must be between 0 and 23")
    local_opened_at = _parse_local_datetime(shift.get("localOpenedTime"), field="localOpenedTime")
    target = local_opened_at.date()
    if local_opened_at.hour < cutoff:
        target -= timedelta(days=1)
    return target


def shift_slot_for_shift(
    shift: dict[str, Any],
    *,
    cutoff_hour: int,
    night_shift_split_enabled: bool = False,
    night_shift_start_hour: int = 22,
) -> str:
    cutoff = int(cutoff_hour)
    night_start = int(night_shift_start_hour)
    if not 0 <= cutoff <= 23:
        raise ValueError("business day cutoff hour must be between 0 and 23")
    if not 0 <= night_start <= 23:
        raise ValueError("night shift start hour must be between 0 and 23")
    if not night_shift_split_enabled:
        return "DAY"
    if night_start <= cutoff:
        raise ValueError("night shift start hour must be greater than business day cutoff hour")

    local_opened_at = _parse_local_datetime(shift.get("localOpenedTime"), field="localOpenedTime")
    return "NIGHT" if local_opened_at.hour >= night_start or local_opened_at.hour < cutoff else "DAY"


def stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _payment_operation_type(payment: dict[str, Any]) -> str:
    payment_type = payment.get("paymentType") if isinstance(payment.get("paymentType"), dict) else {}
    return str(payment.get("operationType") or payment_type.get("operationType") or "").strip().lower()


def _payment_type_id(payment: dict[str, Any]) -> int:
    payment_type = payment.get("paymentType") if isinstance(payment.get("paymentType"), dict) else {}
    value = int(payment_type.get("id") or 0)
    if value <= 0:
        raise QuickRestoDataError("QuickResto order payment has no payment type id")
    return value


def normalize_closed_shift(
    shift: dict[str, Any],
    orders: Iterable[dict[str, Any]],
    *,
    cutoff_hour: int,
    night_shift_split_enabled: bool = False,
    night_shift_start_hour: int = 22,
) -> dict[str, Any]:
    if str(shift.get("status") or "").upper() != "CLOSED":
        raise QuickRestoDataError("Only closed QuickResto shifts can be imported")
    external_shift_id = str(shift.get("frontId") or shift.get("_id") or "").strip()
    external_shift_pk = int(shift.get("id") or 0)
    if not external_shift_id or external_shift_pk <= 0:
        raise QuickRestoDataError("QuickResto shift identifier is missing")

    payment_totals: dict[str, int] = {}
    department_totals: dict[str, int] = {}
    writeoff_department_totals: dict[str, int] = {}
    revenue_total = 0
    writeoff_total = 0
    discount_total = 0
    returned_order_count = 0
    order_count = 0

    for order in orders:
        if str(order.get("shiftId") or "") != external_shift_id:
            raise QuickRestoDataError("QuickResto order is linked to another shift")
        payments = [item for item in (order.get("payments") or []) if isinstance(item, dict)]
        items = [item for item in (order.get("orderItemList") or []) if isinstance(item, dict)]
        returned = bool(order.get("returned"))
        returned_order_count += int(returned)
        order_count += int(not returned)

        # QuickResto exposes a returned OrderInfo as a positive audit copy of
        # the original receipt. The Shift counters already subtract it through
        # totalReturn* / writeOffTotalReturn*, so applying a second negative
        # sign here would understate revenue, payments, and departments.
        if returned:
            continue

        payment_sum = sum(_money_int(item.get("amount"), field="payment.amount") for item in payments)
        order_total = _money_int(order.get("frontTotalPrice"), field="frontTotalPrice")
        if payment_sum != order_total:
            raise QuickRestoDataError(f"QuickResto order {int(order.get('id') or 0)} payments do not match its total")

        operation_types = {_payment_operation_type(payment) for payment in payments}
        is_writeoff = bool(operation_types) and operation_types == {"writeoff"}
        if "writeoff" in operation_types and not is_writeoff:
            raise QuickRestoDataError("QuickResto order mixes write-off and revenue payment types")

        line_total = 0
        for item in items:
            line_net = (
                _money_int(item.get("totalPrice"), field="orderItem.totalPrice")
                - _money_int(item.get("totalAbsoluteDiscount"), field="orderItem.totalAbsoluteDiscount")
                + _money_int(item.get("totalAbsoluteCharge"), field="orderItem.totalAbsoluteCharge")
            )
            line_total += line_net
            product = item.get("product") if isinstance(item.get("product"), dict) else {}
            department_id = int(product.get("parentId") or 0)
            if department_id <= 0 and line_net:
                raise QuickRestoDataError("QuickResto order item has no dish category id")
            target = writeoff_department_totals if is_writeoff else department_totals
            key = str(department_id)
            target[key] = target.get(key, 0) + line_net
        if line_total != order_total:
            raise QuickRestoDataError(f"QuickResto order {int(order.get('id') or 0)} items do not match its total")

        order_discount = _money_int(order.get("frontTotalAbsoluteDiscount"), field="frontTotalAbsoluteDiscount")
        discount_total += order_discount
        if is_writeoff:
            writeoff_total += order_total
            continue

        revenue_total += order_total
        for payment in payments:
            payment_type_id = _payment_type_id(payment)
            amount = _money_int(payment.get("amount"), field="payment.amount")
            key = str(payment_type_id)
            payment_totals[key] = payment_totals.get(key, 0) + amount

    expected_revenue = sum(
        _money_int(shift.get(key), field=key)
        for key in (
            "totalCash",
            "totalCard",
            "totalBonuses",
            "nonFiscalTotalCash",
            "nonFiscalTotalCard",
            "nonFiscalTotalBonuses",
        )
    ) - sum(
        _money_int(shift.get(key), field=key)
        for key in (
            "totalReturnCash",
            "totalReturnCard",
            "totalReturnBonuses",
            "nonFiscalTotalReturnCash",
            "nonFiscalTotalReturnCard",
            "nonFiscalTotalReturnBonuses",
        )
    )
    expected_writeoff = sum(
        _money_int(shift.get(key), field=key)
        for key in ("writeOffTotalCash", "writeOffTotalCard", "writeOffTotalBonuses")
    ) - sum(
        _money_int(shift.get(key), field=key)
        for key in (
            "writeOffTotalReturnCash",
            "writeOffTotalReturnCard",
            "writeOffTotalReturnBonuses",
        )
    )
    if revenue_total != expected_revenue:
        raise QuickRestoDataError("QuickResto shift revenue does not reconcile with its orders")
    if writeoff_total != expected_writeoff:
        raise QuickRestoDataError("QuickResto shift write-offs do not reconcile with its orders")

    local_closed_at = _parse_local_datetime(shift.get("localClosedTime"), field="localClosedTime")
    payload = {
        "external_shift_id": external_shift_id,
        "external_shift_pk": external_shift_pk,
        "source_version": int(shift.get("version") or 0),
        "business_date": business_date_for_shift(shift, cutoff_hour=cutoff_hour).isoformat(),
        "shift_slot": shift_slot_for_shift(
            shift,
            cutoff_hour=cutoff_hour,
            night_shift_split_enabled=night_shift_split_enabled,
            night_shift_start_hour=night_shift_start_hour,
        ),
        "local_closed_at": local_closed_at.isoformat(),
        "payments_external": dict(sorted(payment_totals.items())),
        "departments_external": dict(sorted(department_totals.items())),
        "writeoff_departments_external": dict(sorted(writeoff_department_totals.items())),
        "revenue_total": revenue_total,
        "writeoff_total": writeoff_total,
        "discount_total": discount_total,
        "orders_count": order_count,
        "returned_orders_count": returned_order_count,
    }
    # Keep the content hash compatible with imports created before shift_slot
    # was persisted. A slot move is detected explicitly from the report key.
    payload["payload_hash"] = stable_payload_hash({key: value for key, value in payload.items() if key != "shift_slot"})
    return payload


def aggregate_normalized_shifts(shifts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(shifts)
    if not rows:
        raise QuickRestoDataError("Cannot aggregate an empty QuickResto shift set")
    business_dates = {str(row.get("business_date") or "") for row in rows}
    if len(business_dates) != 1:
        raise QuickRestoDataError("QuickResto shifts from different business dates cannot share a report")
    shift_slots = {str(row.get("shift_slot") or "DAY").upper() for row in rows}
    if len(shift_slots) != 1 or not shift_slots.issubset({"DAY", "NIGHT"}):
        raise QuickRestoDataError("QuickResto day and night shifts cannot share a report")

    payments: dict[str, int] = {}
    departments: dict[str, int] = {}
    writeoff_departments: dict[str, int] = {}
    for row in rows:
        for source, target in (
            (row.get("payments_external") or {}, payments),
            (row.get("departments_external") or {}, departments),
            (row.get("writeoff_departments_external") or {}, writeoff_departments),
        ):
            for key, value in source.items():
                target[str(key)] = target.get(str(key), 0) + int(value or 0)

    aggregate = {
        "business_date": next(iter(business_dates)),
        "shift_slot": next(iter(shift_slots)),
        "external_shift_ids": sorted(str(row["external_shift_id"]) for row in rows),
        "shift_count": len(rows),
        "payments_external": dict(sorted(payments.items())),
        "departments_external": dict(sorted(departments.items())),
        "writeoff_departments_external": dict(sorted(writeoff_departments.items())),
        "revenue_total": sum(int(row.get("revenue_total") or 0) for row in rows),
        "writeoff_total": sum(int(row.get("writeoff_total") or 0) for row in rows),
        "discount_total": sum(int(row.get("discount_total") or 0) for row in rows),
        "orders_count": sum(int(row.get("orders_count") or 0) for row in rows),
        "returned_orders_count": sum(int(row.get("returned_orders_count") or 0) for row in rows),
    }
    # shift_slot is already part of the unique report key. Excluding it keeps
    # existing DAY imports idempotent across the night-split migration.
    aggregate["aggregate_hash"] = stable_payload_hash(
        {key: value for key, value in aggregate.items() if key != "shift_slot"}
    )
    return aggregate
