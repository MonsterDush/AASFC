from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def text(value: Any, *, default: str | None = None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or default


def identifier(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("id", "externalId", "frontId", "_id", "uuid"):
            if result := text(value.get(key)):
                return result
        return None
    return text(value)


def label(value: Any, *, default: str | None = None) -> str | None:
    if isinstance(value, Mapping):
        for key in ("name", "title", "itemTitle", "caption"):
            if result := text(value.get(key)):
                return result
        return default
    return text(value, default=default)


def decimal_value(value: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc


def boolean(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "active", "enabled"}:
        return True
    if normalized in {"false", "0", "no", "inactive", "disabled", "deleted"}:
        return False
    return default


def parse_datetime(value: Any, *, timezone_name: str) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = text(value)
        if raw is None:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
            for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, pattern)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError(f"Invalid provider datetime: {value}")
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(timezone.utc)
    try:
        local_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return parsed.replace(tzinfo=local_tz).astimezone(timezone.utc)


def local_date(value: datetime | None, *, timezone_name: str, cutoff_hour: int) -> date:
    if value is None:
        raise ValueError("Order has no timestamp for business date")
    local = value.astimezone(ZoneInfo(timezone_name))
    return (local - timedelta(hours=int(cutoff_hour))).date()


def provider_status(value: Any, *, returned: bool = False, refund_amount: Decimal = Decimal("0")) -> str:
    if returned:
        return "REFUNDED"
    normalized = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "NEW": "OPEN",
        "OPENED": "OPEN",
        "BILL": "OPEN",
        "CLOSE": "CLOSED",
        "COMPLETED": "CLOSED",
        "DONE": "CLOSED",
        "CANCELED": "CANCELLED",
        "CANCEL": "CANCELLED",
        "DELETED": "DELETED",
        "REFUND": "REFUNDED",
        "RETURNED": "REFUNDED",
    }
    result = aliases.get(normalized, normalized)
    if result == "CLOSED" and refund_amount > 0:
        return "PARTIALLY_REFUNDED"
    return result if result in {"OPEN", "CLOSED", "CANCELLED", "REFUNDED", "PARTIALLY_REFUNDED", "DELETED"} else "UNKNOWN"


def payment_type(value: Any) -> str:
    normalized = str(value or "").strip().upper().replace(" ", "_")
    if any(token in normalized for token in ("CASH", "НАЛИЧ")):
        return "CASH"
    if any(token in normalized for token in ("CARD", "BANK", "БАНК", "КАРТ")):
        return "CARD"
    if "SBP" in normalized or "СБП" in normalized:
        return "SBP"
    if any(token in normalized for token in ("ONLINE", "INTERNET", "ОНЛАЙН")):
        return "ONLINE"
    if any(token in normalized for token in ("BONUS", "LOYAL", "БОНУС")):
        return "BONUS"
    if any(token in normalized for token in ("CERT", "СЕРТИФ")):
        return "CERTIFICATE"
    if any(token in normalized for token in ("COMPL", "КОМПЛИМ")):
        return "COMPLIMENTARY"
    if any(token in normalized for token in ("STAFF", "EMPLOYEE", "ПЕРСОНАЛ")):
        return "STAFF"
    return "OTHER"


def product_type(value: Any) -> str:
    normalized = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "DISH": "DISH",
        "PRODUCT": "DISH",
        "FOOD": "DISH",
        "INGREDIENT": "INGREDIENT",
        "SEMI_FINISHED": "SEMI_FINISHED",
        "PREPARED": "SEMI_FINISHED",
        "MODIFIER": "MODIFIER",
        "GOOD": "GOOD",
        "GOODS": "GOOD",
        "SERVICE": "SERVICE",
    }
    return aliases.get(normalized, "OTHER")
