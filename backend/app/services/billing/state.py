from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


BILLING_STATUS_ACTIVE = "ACTIVE"
BILLING_STATUS_GRACE = "GRACE"
BILLING_STATUS_SUSPENDED = "SUSPENDED"

DEFAULT_BILLING_GRACE_DAYS = 3


@dataclass(slots=True)
class BillingSnapshot:
    status: str
    paid_until: datetime | None
    grace_until: datetime | None
    is_overdue: bool
    days_left: int | None
    restricted_reason: str | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def derive_billing_dates(
    *, paid_until: datetime | None, grace_until: datetime | None, grace_days: int = DEFAULT_BILLING_GRACE_DAYS
) -> tuple[datetime | None, datetime | None]:
    paid_until_utc = _ensure_aware(paid_until)
    grace_until_utc = _ensure_aware(grace_until)
    if paid_until_utc is not None and grace_until_utc is None:
        grace_until_utc = paid_until_utc + timedelta(days=max(0, int(grace_days)))
    return paid_until_utc, grace_until_utc


def build_billing_snapshot(
    *,
    paid_until: datetime | None,
    grace_until: datetime | None,
    status: str | None = None,
    now: datetime | None = None,
    grace_days: int = DEFAULT_BILLING_GRACE_DAYS,
) -> BillingSnapshot:
    current = _ensure_aware(now) or utcnow()
    paid_until_utc, grace_until_utc = derive_billing_dates(
        paid_until=paid_until, grace_until=grace_until, grace_days=grace_days
    )

    effective_status = str(status or "").strip().upper() or BILLING_STATUS_ACTIVE
    if paid_until_utc is not None:
        if current <= paid_until_utc:
            effective_status = BILLING_STATUS_ACTIVE
        elif grace_until_utc is not None and current <= grace_until_utc:
            effective_status = BILLING_STATUS_GRACE
        else:
            effective_status = BILLING_STATUS_SUSPENDED

    days_left = None
    restricted_reason = None
    is_overdue = False

    if effective_status == BILLING_STATUS_ACTIVE:
        if paid_until_utc is not None:
            delta_seconds = max(0.0, (paid_until_utc - current).total_seconds())
            days_left = int(delta_seconds // 86400)
    elif effective_status == BILLING_STATUS_GRACE:
        is_overdue = True
        if grace_until_utc is not None:
            delta_seconds = max(0.0, (grace_until_utc - current).total_seconds())
            days_left = int(delta_seconds // 86400)
            restricted_reason = (
                f"Оплаченный период закончился. Льготный период действует до {grace_until_utc.date().isoformat()}."
            )
        else:
            restricted_reason = "Оплаченный период закончился. Доступ ограничен льготным периодом."
    else:
        is_overdue = True
        restricted_reason = "Оплаченный период закончился. Доступ к заведению ограничен до продления."

    return BillingSnapshot(
        status=effective_status,
        paid_until=paid_until_utc,
        grace_until=grace_until_utc,
        is_overdue=is_overdue,
        days_left=days_left,
        restricted_reason=restricted_reason,
    )
