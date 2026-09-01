from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import hmac
import json
import math
from typing import Any, Iterable, Mapping

from app.services.integrations.credentials import decrypt_integration_payload, encrypt_integration_payload


_SNAPSHOT_SCHEMA_VERSION = 1
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_SHIFT_FIELDS = (
    "id",
    "_id",
    "frontId",
    "version",
    "status",
    "shiftNumber",
    "localOpenedTime",
    "localClosedTime",
    "opened",
    "closed",
    "ordersCount",
    "returnOrdersCount",
    "totalCash",
    "totalCard",
    "totalBonuses",
    "nonFiscalTotalCash",
    "nonFiscalTotalCard",
    "nonFiscalTotalBonuses",
    "totalReturnCash",
    "totalReturnCard",
    "totalReturnBonuses",
    "nonFiscalTotalReturnCash",
    "nonFiscalTotalReturnCard",
    "nonFiscalTotalReturnBonuses",
    "writeOffTotalCash",
    "writeOffTotalCard",
    "writeOffTotalBonuses",
    "writeOffTotalReturnCash",
    "writeOffTotalReturnCard",
    "writeOffTotalReturnBonuses",
)
_ORDER_FIELDS = (
    "id",
    "version",
    "shiftId",
    "returned",
    "frontTotalPrice",
    "frontTotalAbsoluteDiscount",
)
_PAYMENT_FIELDS = ("amount", "operationType")
_PAYMENT_TYPE_FIELDS = ("id", "operationType", "paymentMechanismWeb")
_ORDER_ITEM_FIELDS = (
    "amount",
    "totalPrice",
    "totalAbsoluteDiscount",
    "totalAbsoluteCharge",
)
_PRODUCT_FIELDS = ("id", "parentId")
_LOCATION_REFERENCE_FIELDS = ("id", "version", "name", "title", "itemTitle")
_SHIFT_LOCATION_FIELDS = ("tableScheme", "salePlace", "createTerminalSalePlace")


class QuickRestoSnapshotError(ValueError):
    """Raised when a source snapshot cannot be sanitized or verified safely."""


@dataclass(frozen=True)
class SealedQuickRestoSnapshot:
    source_fingerprint: str
    payload_hash: str
    encrypted_payload: str
    encryption_key_version: str
    sanitized_payload: dict[str, Any]
    external_shift_id: str | None
    external_shift_pk: int | None
    source_version: int | None
    business_date: date | None
    shift_slot: str | None
    local_opened_at: datetime | None
    local_closed_at: datetime | None


def _safe_scalar(value: Any, *, field: str) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QuickRestoSnapshotError(f"QuickResto snapshot field {field} is not finite")
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    raise QuickRestoSnapshotError(f"QuickResto snapshot field {field} has an unsupported value")


def _copy_fields(source: Mapping[str, Any], fields: Iterable[str], *, prefix: str) -> dict[str, Any]:
    return {key: _safe_scalar(source[key], field=f"{prefix}.{key}") for key in fields if key in source}


def _sanitize_payment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    output = _copy_fields(value, _PAYMENT_FIELDS, prefix="payment")
    payment_type = value.get("paymentType")
    if isinstance(payment_type, Mapping):
        output["paymentType"] = _copy_fields(payment_type, _PAYMENT_TYPE_FIELDS, prefix="payment.paymentType")
    return output


def _sanitize_order_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    output = _copy_fields(value, _ORDER_ITEM_FIELDS, prefix="orderItem")
    product = value.get("product")
    if isinstance(product, Mapping):
        output["product"] = _copy_fields(product, _PRODUCT_FIELDS, prefix="orderItem.product")
    return output


def _canonical_sort_key(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sanitize_order(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    output = _copy_fields(value, _ORDER_FIELDS, prefix="order")
    payments = [row for item in (value.get("payments") or ()) if (row := _sanitize_payment(item)) is not None]
    order_items = [
        row for item in (value.get("orderItemList") or ()) if (row := _sanitize_order_item(item)) is not None
    ]
    output["payments"] = sorted(payments, key=_canonical_sort_key)
    output["orderItemList"] = sorted(order_items, key=_canonical_sort_key)
    return output


def _sanitize_shift(value: Mapping[str, Any]) -> dict[str, Any]:
    output = _copy_fields(value, _SHIFT_FIELDS, prefix="shift")
    for field in _SHIFT_LOCATION_FIELDS:
        reference = value.get(field)
        if isinstance(reference, Mapping):
            output[field] = _copy_fields(
                reference,
                _LOCATION_REFERENCE_FIELDS,
                prefix=f"shift.{field}",
            )
    return output


def sanitize_quickresto_source_snapshot(
    *,
    shift: Mapping[str, Any],
    orders: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the strict allowlisted subset needed to retry one shift import.

    Guest, employee, table and free-form order fields are intentionally not
    copied. The result is safe to encrypt and retain for a bounded period.
    """

    if not isinstance(shift, Mapping):
        raise QuickRestoSnapshotError("QuickResto snapshot shift must be an object")
    sanitized_orders = [row for item in orders if (row := _sanitize_order(item)) is not None]
    sanitized_orders.sort(key=_canonical_sort_key)
    return {
        "schema_version": _SNAPSHOT_SCHEMA_VERSION,
        "shift": _sanitize_shift(shift),
        "orders": sanitized_orders,
    }


def _canonical_payload(payload: Mapping[str, Any]) -> tuple[str, bytes]:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = serialized.encode("utf-8")
    if len(encoded) > _MAX_SNAPSHOT_BYTES:
        raise QuickRestoSnapshotError("QuickResto source snapshot exceeds the retention size limit")
    return serialized, encoded


def quickresto_source_fingerprint(
    *,
    external_shift_id: str | None,
    external_shift_pk: int | None,
    source_key: str | None = None,
) -> str:
    external_id = str(external_shift_id or "").strip()
    stable_source_key = str(source_key or "").strip()
    if external_id:
        identity = f"external:{external_id}"
    elif external_shift_pk is not None and int(external_shift_pk) > 0:
        identity = f"pk:{int(external_shift_pk)}"
    elif stable_source_key:
        identity = f"source:{stable_source_key}"
    else:
        raise QuickRestoSnapshotError("QuickResto source snapshot has no stable shift identity")
    return hashlib.sha256(f"axelio:quickresto-source:v1\0{identity}".encode()).hexdigest()


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise QuickRestoSnapshotError("QuickResto source metadata contains an invalid integer") from exc
    return result if result > 0 else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise QuickRestoSnapshotError("QuickResto source metadata contains an invalid integer") from exc
    return result if result >= 0 else None


def _optional_local_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise QuickRestoSnapshotError("QuickResto source metadata contains an invalid local datetime") from exc
    return parsed.replace(tzinfo=None)


def seal_quickresto_source_snapshot(
    *,
    shift: Mapping[str, Any],
    orders: Iterable[Mapping[str, Any]],
    business_date: date | None = None,
    shift_slot: str | None = None,
    source_key: str | None = None,
) -> SealedQuickRestoSnapshot:
    sanitized = sanitize_quickresto_source_snapshot(shift=shift, orders=orders)
    serialized, encoded = _canonical_payload(sanitized)
    payload_hash = hashlib.sha256(encoded).hexdigest()
    encrypted = encrypt_integration_payload(serialized)
    key_version, separator, _token = encrypted.partition(":")
    if not separator or not key_version:
        raise QuickRestoSnapshotError("Integration payload encryption returned an unsupported format")

    sanitized_shift = sanitized["shift"]
    external_shift_id = str(sanitized_shift.get("frontId") or sanitized_shift.get("_id") or "").strip() or None
    external_shift_pk = _optional_positive_int(sanitized_shift.get("id"))
    source_version = _optional_nonnegative_int(sanitized_shift.get("version"))
    normalized_slot = str(shift_slot or "").strip().upper() or None
    if normalized_slot not in {None, "DAY", "NIGHT"}:
        raise QuickRestoSnapshotError("QuickResto source snapshot has an invalid shift slot")
    return SealedQuickRestoSnapshot(
        source_fingerprint=quickresto_source_fingerprint(
            external_shift_id=external_shift_id,
            external_shift_pk=external_shift_pk,
            source_key=source_key,
        ),
        payload_hash=payload_hash,
        encrypted_payload=encrypted,
        encryption_key_version=key_version,
        sanitized_payload=sanitized,
        external_shift_id=external_shift_id,
        external_shift_pk=external_shift_pk,
        source_version=source_version,
        business_date=business_date,
        shift_slot=normalized_slot,
        local_opened_at=_optional_local_datetime(sanitized_shift.get("localOpenedTime")),
        local_closed_at=_optional_local_datetime(sanitized_shift.get("localClosedTime")),
    )


def open_quickresto_source_snapshot(
    *,
    encrypted_payload: str,
    expected_payload_hash: str,
    expected_key_version: str,
) -> dict[str, Any]:
    key_version, separator, _token = str(encrypted_payload or "").partition(":")
    if not separator or key_version != str(expected_key_version or ""):
        raise QuickRestoSnapshotError("QuickResto source snapshot key version does not match")
    plaintext = decrypt_integration_payload(encrypted_payload)
    encoded = plaintext.encode("utf-8")
    actual_hash = hashlib.sha256(encoded).hexdigest()
    if not hmac.compare_digest(actual_hash, str(expected_payload_hash or "")):
        raise QuickRestoSnapshotError("QuickResto source snapshot integrity check failed")
    try:
        payload = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise QuickRestoSnapshotError("QuickResto source snapshot is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _SNAPSHOT_SCHEMA_VERSION:
        raise QuickRestoSnapshotError("QuickResto source snapshot schema is unsupported")
    shift = payload.get("shift")
    orders = payload.get("orders")
    if not isinstance(shift, dict) or not isinstance(orders, list):
        raise QuickRestoSnapshotError("QuickResto source snapshot has an invalid shape")
    sanitized = sanitize_quickresto_source_snapshot(shift=shift, orders=orders)
    canonical, _canonical_bytes = _canonical_payload(sanitized)
    if canonical != plaintext:
        raise QuickRestoSnapshotError("QuickResto source snapshot is not canonical")
    return sanitized
