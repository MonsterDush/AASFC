from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Iterable


class QuickRestoDataError(RuntimeError):
    """Raised when QuickResto data cannot be represented safely in an Axelio report."""


_MONEY_QUANT = Decimal("0.01")
_MONEY_TOLERANCE = Decimal("0.000001")


def _money_minor(value: Any, *, field: str) -> int:
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise QuickRestoDataError(f"QuickResto field {field} is not numeric") from exc
    if not number.is_finite():
        raise QuickRestoDataError(f"QuickResto field {field} is not finite")
    rounded = number.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    if abs(number - rounded) > _MONEY_TOLERANCE:
        raise QuickRestoDataError(f"QuickResto field {field} has precision smaller than one kopeck")
    return int(rounded * 100)


def _round_minor_to_rubles(value_minor: int) -> int:
    return int((Decimal(int(value_minor)) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _allocate_minor_to_rubles(values: dict[str, int]) -> dict[str, int]:
    """Round a split while preserving the rounded total exactly.

    Each bucket starts at mathematical floor rubles. Remaining rubles are
    assigned by the largest kopeck remainder and then stable external id, so
    payments and departments are reproducible across retries.
    """

    if not values:
        return {}
    normalized = {str(key): int(value or 0) for key, value in values.items()}
    allocated = {key: value // 100 for key, value in normalized.items()}
    target_total = _round_minor_to_rubles(sum(normalized.values()))
    remaining = target_total - sum(allocated.values())
    if remaining < 0 or remaining > len(allocated):
        raise QuickRestoDataError("QuickResto monetary rounding could not be reconciled")
    ranked = sorted(
        allocated,
        key=lambda key: (-(normalized[key] - allocated[key] * 100), key),
    )
    for key in ranked[:remaining]:
        allocated[key] += 1
    return dict(sorted(allocated.items()))


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

    payment_totals_minor: dict[str, int] = {}
    department_totals_minor: dict[str, int] = {}
    writeoff_department_totals_minor: dict[str, int] = {}
    revenue_total_minor = 0
    writeoff_total_minor = 0
    discount_total_minor = 0
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

        payment_sum_minor = sum(_money_minor(item.get("amount"), field="payment.amount") for item in payments)
        order_total_minor = _money_minor(order.get("frontTotalPrice"), field="frontTotalPrice")
        if payment_sum_minor != order_total_minor:
            raise QuickRestoDataError(f"QuickResto order {int(order.get('id') or 0)} payments do not match its total")

        operation_types = {_payment_operation_type(payment) for payment in payments}
        is_writeoff = bool(operation_types) and operation_types == {"writeoff"}
        if "writeoff" in operation_types and not is_writeoff:
            raise QuickRestoDataError("QuickResto order mixes write-off and revenue payment types")

        line_total_minor = 0
        for item in items:
            line_net_minor = (
                _money_minor(item.get("totalPrice"), field="orderItem.totalPrice")
                - _money_minor(item.get("totalAbsoluteDiscount"), field="orderItem.totalAbsoluteDiscount")
                + _money_minor(item.get("totalAbsoluteCharge"), field="orderItem.totalAbsoluteCharge")
            )
            line_total_minor += line_net_minor
            product = item.get("product") if isinstance(item.get("product"), dict) else {}
            department_id = int(product.get("parentId") or 0)
            if department_id <= 0 and line_net_minor:
                raise QuickRestoDataError("QuickResto order item has no dish category id")
            target = writeoff_department_totals_minor if is_writeoff else department_totals_minor
            key = str(department_id)
            target[key] = target.get(key, 0) + line_net_minor
        if line_total_minor != order_total_minor:
            raise QuickRestoDataError(f"QuickResto order {int(order.get('id') or 0)} items do not match its total")

        order_discount_minor = _money_minor(
            order.get("frontTotalAbsoluteDiscount"),
            field="frontTotalAbsoluteDiscount",
        )
        discount_total_minor += order_discount_minor
        if is_writeoff:
            writeoff_total_minor += order_total_minor
            continue

        revenue_total_minor += order_total_minor
        for payment in payments:
            payment_type_id = _payment_type_id(payment)
            amount_minor = _money_minor(payment.get("amount"), field="payment.amount")
            key = str(payment_type_id)
            payment_totals_minor[key] = payment_totals_minor.get(key, 0) + amount_minor

    expected_revenue_minor = sum(
        _money_minor(shift.get(key), field=key)
        for key in (
            "totalCash",
            "totalCard",
            "totalBonuses",
            "nonFiscalTotalCash",
            "nonFiscalTotalCard",
            "nonFiscalTotalBonuses",
        )
    ) - sum(
        _money_minor(shift.get(key), field=key)
        for key in (
            "totalReturnCash",
            "totalReturnCard",
            "totalReturnBonuses",
            "nonFiscalTotalReturnCash",
            "nonFiscalTotalReturnCard",
            "nonFiscalTotalReturnBonuses",
        )
    )
    expected_writeoff_minor = sum(
        _money_minor(shift.get(key), field=key)
        for key in ("writeOffTotalCash", "writeOffTotalCard", "writeOffTotalBonuses")
    ) - sum(
        _money_minor(shift.get(key), field=key)
        for key in (
            "writeOffTotalReturnCash",
            "writeOffTotalReturnCard",
            "writeOffTotalReturnBonuses",
        )
    )
    if revenue_total_minor != expected_revenue_minor:
        raise QuickRestoDataError("QuickResto shift revenue does not reconcile with its orders")
    if writeoff_total_minor != expected_writeoff_minor:
        raise QuickRestoDataError("QuickResto shift write-offs do not reconcile with its orders")

    local_closed_at = _parse_local_datetime(shift.get("localClosedTime"), field="localClosedTime")
    revenue_total = _round_minor_to_rubles(revenue_total_minor)
    writeoff_total = _round_minor_to_rubles(writeoff_total_minor)
    discount_total = _round_minor_to_rubles(discount_total_minor)
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
        "payments_external": _allocate_minor_to_rubles(payment_totals_minor),
        "departments_external": _allocate_minor_to_rubles(department_totals_minor),
        "writeoff_departments_external": _allocate_minor_to_rubles(writeoff_department_totals_minor),
        "revenue_total": revenue_total,
        "writeoff_total": writeoff_total,
        "discount_total": discount_total,
        "payments_external_minor": dict(sorted(payment_totals_minor.items())),
        "departments_external_minor": dict(sorted(department_totals_minor.items())),
        "writeoff_departments_external_minor": dict(sorted(writeoff_department_totals_minor.items())),
        "revenue_total_minor": revenue_total_minor,
        "writeoff_total_minor": writeoff_total_minor,
        "discount_total_minor": discount_total_minor,
        "rounding_adjustment_minor": revenue_total * 100 - revenue_total_minor,
        "source_money_scale": 100,
        "orders_count": order_count,
        "returned_orders_count": returned_order_count,
    }
    has_fractional_amounts = any(
        value % 100
        for value in (
            revenue_total_minor,
            writeoff_total_minor,
            discount_total_minor,
            *payment_totals_minor.values(),
            *department_totals_minor.values(),
            *writeoff_department_totals_minor.values(),
        )
    )
    if has_fractional_amounts:
        payload["source_amounts_have_fractional_rubles"] = True
    # Keep whole-ruble hashes compatible with imports created before exact
    # source-minor audit fields and shift_slot were persisted.
    hash_payload = {
        key: value
        for key, value in payload.items()
        if key != "shift_slot"
        and (has_fractional_amounts or not (key.endswith("_minor") or key == "source_money_scale"))
    }
    payload["payload_hash"] = stable_payload_hash(hash_payload)
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

    payments_minor: dict[str, int] = {}
    departments_minor: dict[str, int] = {}
    writeoff_departments_minor: dict[str, int] = {}

    def minor_map(row: dict[str, Any], *, exact_key: str, legacy_key: str) -> dict[str, int]:
        exact = row.get(exact_key)
        if isinstance(exact, dict):
            return {str(key): int(value or 0) for key, value in exact.items()}
        legacy = row.get(legacy_key) or {}
        return {str(key): int(value or 0) * 100 for key, value in legacy.items()}

    def minor_total(row: dict[str, Any], *, exact_key: str, legacy_key: str) -> int:
        value = row.get(exact_key)
        return int(value) if value is not None else int(row.get(legacy_key) or 0) * 100

    for row in rows:
        for source, target in (
            (
                minor_map(row, exact_key="payments_external_minor", legacy_key="payments_external"),
                payments_minor,
            ),
            (
                minor_map(row, exact_key="departments_external_minor", legacy_key="departments_external"),
                departments_minor,
            ),
            (
                minor_map(
                    row,
                    exact_key="writeoff_departments_external_minor",
                    legacy_key="writeoff_departments_external",
                ),
                writeoff_departments_minor,
            ),
        ):
            for key, value in source.items():
                target[str(key)] = target.get(str(key), 0) + int(value or 0)

    revenue_total_minor = sum(
        minor_total(row, exact_key="revenue_total_minor", legacy_key="revenue_total") for row in rows
    )
    writeoff_total_minor = sum(
        minor_total(row, exact_key="writeoff_total_minor", legacy_key="writeoff_total") for row in rows
    )
    discount_total_minor = sum(
        minor_total(row, exact_key="discount_total_minor", legacy_key="discount_total") for row in rows
    )
    revenue_total = _round_minor_to_rubles(revenue_total_minor)
    writeoff_total = _round_minor_to_rubles(writeoff_total_minor)
    discount_total = _round_minor_to_rubles(discount_total_minor)
    has_fractional_amounts = any(
        value % 100
        for value in (
            revenue_total_minor,
            writeoff_total_minor,
            discount_total_minor,
            *payments_minor.values(),
            *departments_minor.values(),
            *writeoff_departments_minor.values(),
        )
    )

    aggregate = {
        "business_date": next(iter(business_dates)),
        "shift_slot": next(iter(shift_slots)),
        "external_shift_ids": sorted(str(row["external_shift_id"]) for row in rows),
        "shift_count": len(rows),
        "payments_external": _allocate_minor_to_rubles(payments_minor),
        "departments_external": _allocate_minor_to_rubles(departments_minor),
        "writeoff_departments_external": _allocate_minor_to_rubles(writeoff_departments_minor),
        "revenue_total": revenue_total,
        "writeoff_total": writeoff_total,
        "discount_total": discount_total,
        "payments_external_minor": dict(sorted(payments_minor.items())),
        "departments_external_minor": dict(sorted(departments_minor.items())),
        "writeoff_departments_external_minor": dict(sorted(writeoff_departments_minor.items())),
        "revenue_total_minor": revenue_total_minor,
        "writeoff_total_minor": writeoff_total_minor,
        "discount_total_minor": discount_total_minor,
        "rounding_adjustment_minor": revenue_total * 100 - revenue_total_minor,
        "source_money_scale": 100,
        "orders_count": sum(int(row.get("orders_count") or 0) for row in rows),
        "returned_orders_count": sum(int(row.get("returned_orders_count") or 0) for row in rows),
    }
    if has_fractional_amounts:
        aggregate["source_amounts_have_fractional_rubles"] = True
    # shift_slot is already part of the unique report key. Excluding it keeps
    # existing whole-ruble DAY imports idempotent across the night-split and
    # exact-source-money migrations.
    hash_aggregate = {
        key: value
        for key, value in aggregate.items()
        if key != "shift_slot"
        and (has_fractional_amounts or not (key.endswith("_minor") or key == "source_money_scale"))
    }
    aggregate["aggregate_hash"] = stable_payload_hash(hash_aggregate)
    return aggregate
