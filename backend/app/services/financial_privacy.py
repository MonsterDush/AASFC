from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models.user import User
from app.settings import settings


FINANCIAL_VALUES_HIDDEN_MESSAGE = (
    "Финансовые показатели скрыты для SUPER_ADMIN текущей настройкой окружения."
)


def _role(user: User | None) -> str:
    return str(getattr(user, "system_role", "") or "").strip().upper()


def should_hide_financial_values_for_user(user: User | None) -> bool:
    """Hide venue-internal financial figures from SUPER_ADMIN when env flag is disabled.

    SUPER_ADMIN keeps navigation, settings and rule-management access; only report-derived
    amounts/metrics are masked in read payloads and financial exports are blocked.
    """
    if _role(user) != "SUPER_ADMIN":
        return False
    return not bool(getattr(settings, "SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES", True))


def financial_visibility_payload(user: User | None) -> dict[str, Any]:
    hidden = should_hide_financial_values_for_user(user)
    return {
        "can_view_financial_values": not hidden,
        "financial_values_hidden": hidden,
        "financial_values_hidden_reason": FINANCIAL_VALUES_HIDDEN_MESSAGE if hidden else None,
    }


_SAFE_KEY_SUFFIXES = (
    "_id",
    "_ids",
    "_count",
    "_counts",
    "_date",
    "_at",
    "_until",
    "_from",
    "_to",
    "_year",
    "_month",
    "_day",
    "_days",
    "_hour",
    "_hours",
    "_minute",
    "_minutes",
    "_second",
    "_seconds",
    "_code",
    "_title",
    "_name",
    "_role",
    "_status",
    "_mode",
    "_kind",
    "_type",
    "_url",
    "_path",
    "_label",
    "_description",
    "_comment",
    "_reason",
    "_unit",
)

_SAFE_KEYS = {
    "id",
    "code",
    "title",
    "name",
    "date",
    "month",
    "year",
    "period_start",
    "period_end",
    "start_date",
    "end_date",
    "status",
    "mode",
    "kind",
    "type",
    "role",
    "comment",
    "description",
    "unit",
    "currency",
    "source",
    "ok",
    "exists",
    "is_active",
    "is_deleted",
    "is_archived",
    "created_at",
    "updated_at",
    "closed_at",
    "closed_reports",
    "report_id",
    "venue_id",
    "user_id",
    "member_user_id",
    "payment_method_id",
    "category_id",
    "supplier_id",
    "department_id",
    "metric_id",
    "ref_id",
    "sort_order",
    "permissions",
    "position",
    "financial_values_hidden",
    "can_view_financial_values",
    "financial_values_hidden_reason",
}

_FINANCIAL_EXACT_KEYS = {
    "amount",
    "amount_minor",
    "cash",
    "cashless",
    "delta",
    "earned",
    "earned_minor",
    "expense",
    "expense_minor",
    "income",
    "income_minor",
    "inflow_minor",
    "outflow_minor",
    "balance_minor",
    "payroll_minor",
    "profit",
    "profit_minor",
    "refunds_minor",
    "revenue",
    "revenue_minor",
    "revenue_total",
    "tips_total",
    "total",
    "total_minor",
    "total_amount_minor",
    "value",
    "value_numeric",
}

_FINANCIAL_PARTS = (
    "amount",
    "balance",
    "cash",
    "cashless",
    "discrepancy",
    "earned",
    "expense",
    "income",
    "inflow",
    "margin",
    "outflow",
    "payroll",
    "profit",
    "refund",
    "revenue",
    "salary",
    "tips",
    "turnover",
    "value_numeric",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _is_financial_key(key: str) -> bool:
    k = str(key or "").strip().lower()
    if not k:
        return False
    if k in _SAFE_KEYS:
        return k in _FINANCIAL_EXACT_KEYS
    if k.endswith(_SAFE_KEY_SUFFIXES) and not any(part in k for part in _FINANCIAL_PARTS):
        return False
    if k.endswith("_minor"):
        return True
    if k.endswith("_bps"):
        return any(part in k for part in ("revenue", "expense", "payroll", "profit", "margin", "income"))
    if k.endswith("_total"):
        return any(part in k for part in ("revenue", "expense", "payroll", "profit", "income", "tips", "amount", "cash", "cashless"))
    return any(part in k for part in _FINANCIAL_PARTS)


def _mask_numeric(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if _is_number(value):
        return 0
    return value


def sanitize_financial_payload(payload: Any, *, hidden: bool = True, _top: bool = True) -> Any:
    """Return a copy with report-derived financial numeric values masked.

    This helper is intentionally conservative and is used only on finance/report read
    endpoints, not on configuration/rule endpoints where numeric thresholds are editable.
    """
    if not hidden:
        return payload

    if hasattr(payload, "model_dump"):
        try:
            payload = payload.model_dump(mode="json")
        except Exception:
            pass

    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if _is_financial_key(str(key)):
                out[key] = _mask_numeric(value)
            else:
                out[key] = sanitize_financial_payload(value, hidden=True, _top=False)
        if _top:
            out.update({
                "financial_values_hidden": True,
                "can_view_financial_values": False,
                "financial_values_hidden_reason": FINANCIAL_VALUES_HIDDEN_MESSAGE,
            })
        return out

    if isinstance(payload, list):
        return [sanitize_financial_payload(item, hidden=True, _top=False) for item in payload]

    if isinstance(payload, tuple):
        return tuple(sanitize_financial_payload(item, hidden=True, _top=False) for item in payload)

    # Dates/strings are left as-is; standalone numbers are not masked without a key.
    if isinstance(payload, (str, date, datetime)) or payload is None:
        return payload
    return payload


def sanitize_financial_payload_for_user(user: User | None, payload: Any) -> Any:
    return sanitize_financial_payload(payload, hidden=should_hide_financial_values_for_user(user))
