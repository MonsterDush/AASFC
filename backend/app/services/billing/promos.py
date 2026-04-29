from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing_promo_code import BillingPromoCode
from app.models.billing_promo_redemption import BillingPromoRedemption
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_state import VenueBillingState
from app.models.venue_billing_transaction import VenueBillingTransaction
from .state import BILLING_STATUS_ACTIVE, DEFAULT_BILLING_GRACE_DAYS, derive_billing_dates, utcnow

PROMO_KIND_PERCENT = "PERCENT"
PROMO_KIND_FIXED_MINOR = "FIXED_MINOR"
PROMO_KIND_FREE_DAYS = "FREE_DAYS"
PROMO_SOURCE = "PROMOCODE"
PROMO_TRANSACTION_TYPE = "PROMO_GRANT"
DEFAULT_PROMO_BILLING_DAYS = 30


@dataclass(slots=True)
class PromoPreview:
    promo_id: int
    code: str
    title: str | None
    kind: str
    percent_value: int | None
    amount_minor_value: int | None
    free_days_value: int | None
    price_before_minor: int
    discount_minor: int
    amount_after_minor: int
    days_added: int
    payment_required: bool
    summary: str


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_promo_code(value: str | None) -> str:
    return str(value or "").strip().upper()


def validate_promo_payload(*, kind: str, percent_value: int | None, amount_minor: int | None, free_days: int | None) -> tuple[str, int | None, int | None, int | None]:
    kind_norm = str(kind or "").strip().upper()
    if kind_norm not in {PROMO_KIND_PERCENT, PROMO_KIND_FIXED_MINOR, PROMO_KIND_FREE_DAYS}:
        raise ValueError("Unsupported promo kind")

    percent_norm = int(percent_value) if percent_value is not None else None
    amount_norm = int(amount_minor) if amount_minor is not None else None
    days_norm = int(free_days) if free_days is not None else None

    if kind_norm == PROMO_KIND_PERCENT:
        if percent_norm is None or percent_norm <= 0 or percent_norm > 100:
            raise ValueError("Процент скидки должен быть от 1 до 100")
        amount_norm = None
        days_norm = None
    elif kind_norm == PROMO_KIND_FIXED_MINOR:
        if amount_norm is None or amount_norm <= 0:
            raise ValueError("Скидка в рублях должна быть больше 0")
        percent_norm = None
        days_norm = None
    elif kind_norm == PROMO_KIND_FREE_DAYS:
        if days_norm is None or days_norm <= 0:
            raise ValueError("Количество бесплатных дней должно быть больше 0")
        percent_norm = None
        amount_norm = None
    return kind_norm, percent_norm, amount_norm, days_norm


def serialize_promo_code(code: BillingPromoCode, *, usage_count: int = 0) -> dict[str, Any]:
    return {
        "id": int(code.id),
        "code": code.code,
        "title": code.title,
        "kind": code.kind,
        "percent_value": int(code.percent_value) if code.percent_value is not None else None,
        "amount_minor": int(code.amount_minor) if code.amount_minor is not None else None,
        "free_days": int(code.free_days) if code.free_days is not None else None,
        "is_active": bool(code.is_active),
        "comment": code.comment,
        "usage_count": int(usage_count),
        "created_by_user_id": code.created_by_user_id,
        "created_at": code.created_at.isoformat() if code.created_at else None,
        "updated_at": code.updated_at.isoformat() if code.updated_at else None,
    }


def serialize_promo_redemption(redemption: BillingPromoRedemption | None) -> dict[str, Any] | None:
    if redemption is None:
        return None
    promo = redemption.promo_code
    return {
        "id": int(redemption.id),
        "promo_code_id": int(redemption.promo_code_id),
        "venue_id": int(redemption.venue_id),
        "billing_transaction_id": int(redemption.billing_transaction_id) if redemption.billing_transaction_id is not None else None,
        "promo_code_value": redemption.promo_code_value,
        "discount_minor": int(redemption.discount_minor or 0),
        "free_days_added": int(redemption.free_days_added) if redemption.free_days_added is not None else None,
        "created_at": redemption.created_at.isoformat() if redemption.created_at else None,
        "promo": serialize_promo_code(promo, usage_count=1) if promo is not None else None,
        "snapshot": redemption.snapshot_json if isinstance(redemption.snapshot_json, dict) else (redemption.snapshot_json or {}),
    }


def get_promo_code_by_id(db: Session, *, promo_id: int) -> BillingPromoCode | None:
    return db.execute(select(BillingPromoCode).where(BillingPromoCode.id == int(promo_id))).scalar_one_or_none()


def get_promo_code_by_code(db: Session, *, code: str) -> BillingPromoCode | None:
    normalized = normalize_promo_code(code)
    if not normalized:
        return None
    return db.execute(select(BillingPromoCode).where(BillingPromoCode.code == normalized)).scalar_one_or_none()


def get_venue_promo_redemption(db: Session, *, venue_id: int) -> BillingPromoRedemption | None:
    return db.execute(
        select(BillingPromoRedemption)
        .where(BillingPromoRedemption.venue_id == int(venue_id))
        .order_by(BillingPromoRedemption.created_at.desc(), BillingPromoRedemption.id.desc())
    ).scalar_one_or_none()


def venue_has_redeemed_promo(db: Session, *, venue_id: int) -> bool:
    return get_venue_promo_redemption(db, venue_id=int(venue_id)) is not None


def list_promo_codes_with_usage(db: Session) -> list[tuple[BillingPromoCode, int]]:
    stmt = (
        select(BillingPromoCode, func.count(BillingPromoRedemption.id))
        .outerjoin(BillingPromoRedemption, BillingPromoRedemption.promo_code_id == BillingPromoCode.id)
        .group_by(BillingPromoCode.id)
        .order_by(BillingPromoCode.created_at.desc(), BillingPromoCode.id.desc())
    )
    rows = db.execute(stmt).all()
    return [(row[0], int(row[1] or 0)) for row in rows]


def create_promo_code(
    db: Session,
    *,
    code: str,
    kind: str,
    title: str | None = None,
    percent_value: int | None = None,
    amount_minor: int | None = None,
    free_days: int | None = None,
    comment: str | None = None,
    is_active: bool = True,
    created_by_user_id: int | None = None,
) -> BillingPromoCode:
    normalized = normalize_promo_code(code)
    if not normalized:
        raise ValueError("Promo code is required")
    existing = get_promo_code_by_code(db, code=normalized)
    if existing is not None:
        raise ValueError("Промокод с таким кодом уже существует")
    kind_norm, percent_norm, amount_norm, days_norm = validate_promo_payload(
        kind=kind,
        percent_value=percent_value,
        amount_minor=amount_minor,
        free_days=free_days,
    )
    now = utcnow()
    promo = BillingPromoCode(
        code=normalized,
        title=(str(title).strip() or None) if title is not None else None,
        kind=kind_norm,
        percent_value=percent_norm,
        amount_minor=amount_norm,
        free_days=days_norm,
        comment=(str(comment).strip() or None) if comment is not None else None,
        is_active=bool(is_active),
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(promo)
    db.flush()
    return promo


def update_promo_code(
    db: Session,
    *,
    promo: BillingPromoCode,
    code: str | None = None,
    title: str | None = None,
    kind: str | None = None,
    percent_value: int | None = None,
    amount_minor: int | None = None,
    free_days: int | None = None,
    comment: str | None = None,
    is_active: bool | None = None,
) -> BillingPromoCode:
    code_norm = promo.code if code is None else normalize_promo_code(code)
    if not code_norm:
        raise ValueError("Promo code is required")
    existing = get_promo_code_by_code(db, code=code_norm)
    if existing is not None and int(existing.id) != int(promo.id):
        raise ValueError("Промокод с таким кодом уже существует")

    kind_norm, percent_norm, amount_norm, days_norm = validate_promo_payload(
        kind=kind or promo.kind,
        percent_value=percent_value if kind is not None or promo.kind == PROMO_KIND_PERCENT else promo.percent_value,
        amount_minor=amount_minor if kind is not None or promo.kind == PROMO_KIND_FIXED_MINOR else promo.amount_minor,
        free_days=free_days if kind is not None or promo.kind == PROMO_KIND_FREE_DAYS else promo.free_days,
    )
    promo.code = code_norm
    promo.title = promo.title if title is None else (str(title).strip() or None)
    promo.kind = kind_norm
    promo.percent_value = percent_norm
    promo.amount_minor = amount_norm
    promo.free_days = days_norm
    if comment is not None:
        promo.comment = str(comment).strip() or None
    if is_active is not None:
        promo.is_active = bool(is_active)
    promo.updated_at = utcnow()
    db.flush()
    return promo


def compute_promo_preview(db: Session, *, venue_id: int, code: str, base_price_minor: int) -> PromoPreview:
    normalized = normalize_promo_code(code)
    if not normalized:
        raise ValueError("Введи промокод")
    existing_redemption = get_venue_promo_redemption(db, venue_id=int(venue_id))
    if existing_redemption is not None:
        raise ValueError(f"Для этого заведения уже использован промокод {existing_redemption.promo_code_value}")
    promo = get_promo_code_by_code(db, code=normalized)
    if promo is None or not bool(promo.is_active):
        raise ValueError("Промокод не найден или выключен")

    price_before = max(0, int(base_price_minor or 0))
    discount_minor = 0
    amount_after = price_before
    days_added = DEFAULT_PROMO_BILLING_DAYS
    summary = ""

    if promo.kind == PROMO_KIND_PERCENT:
        percent_value = max(0, int(promo.percent_value or 0))
        discount_minor = min(price_before, round(price_before * percent_value / 100))
        amount_after = max(0, price_before - discount_minor)
        summary = f"Скидка {percent_value}%"
    elif promo.kind == PROMO_KIND_FIXED_MINOR:
        amount_value = max(0, int(promo.amount_minor or 0))
        discount_minor = min(price_before, amount_value)
        amount_after = max(0, price_before - discount_minor)
        summary = f"Скидка {(discount_minor / 100):.0f} ₽"
    elif promo.kind == PROMO_KIND_FREE_DAYS:
        days_added = max(1, int(promo.free_days or 0))
        amount_after = 0
        discount_minor = 0
        summary = f"Бесплатный доступ на {days_added} дн."
    else:
        raise ValueError("Unsupported promo kind")

    return PromoPreview(
        promo_id=int(promo.id),
        code=promo.code,
        title=promo.title,
        kind=promo.kind,
        percent_value=int(promo.percent_value) if promo.percent_value is not None else None,
        amount_minor_value=int(promo.amount_minor) if promo.amount_minor is not None else None,
        free_days_value=int(promo.free_days) if promo.free_days is not None else None,
        price_before_minor=price_before,
        discount_minor=int(discount_minor),
        amount_after_minor=int(amount_after),
        days_added=int(days_added),
        payment_required=amount_after > 0,
        summary=summary,
    )


def promo_preview_to_payload(preview: PromoPreview) -> dict[str, Any]:
    payload = asdict(preview)
    payload["price_before_minor"] = int(payload.pop("price_before_minor", 0))
    payload["amount_after_minor"] = int(payload.pop("amount_after_minor", 0))
    payload["discount_minor"] = int(payload.get("discount_minor", 0))
    return payload


def extract_transaction_promo_payload(tx: VenueBillingTransaction | None) -> dict[str, Any]:
    if tx is None:
        return {}
    payload = tx.provider_payload_json if isinstance(tx.provider_payload_json, dict) else {}
    promo = payload.get("promo")
    return dict(promo) if isinstance(promo, dict) else {}


def create_promo_redemption(
    db: Session,
    *,
    venue_id: int,
    promo: BillingPromoCode,
    promo_payload: dict[str, Any],
    billing_transaction_id: int | None = None,
) -> BillingPromoRedemption:
    existing = get_venue_promo_redemption(db, venue_id=int(venue_id))
    if existing is not None:
        if billing_transaction_id is not None and int(existing.billing_transaction_id or 0) == int(billing_transaction_id):
            return existing
        raise ValueError(f"Для этого заведения уже использован промокод {existing.promo_code_value}")
    redemption = BillingPromoRedemption(
        promo_code_id=int(promo.id),
        venue_id=int(venue_id),
        billing_transaction_id=int(billing_transaction_id) if billing_transaction_id is not None else None,
        promo_code_value=promo.code,
        discount_minor=int(promo_payload.get("discount_minor") or 0),
        free_days_added=int(promo_payload.get("days_added") or 0) if promo.kind == PROMO_KIND_FREE_DAYS else (int(promo_payload.get("free_days_value") or 0) or None),
        snapshot_json=promo_payload,
        created_at=utcnow(),
    )
    db.add(redemption)
    db.flush()
    return redemption


def finalize_transaction_promo_redemption(db: Session, *, transaction: VenueBillingTransaction) -> BillingPromoRedemption | None:
    promo_payload = extract_transaction_promo_payload(transaction)
    if not promo_payload:
        return None
    promo_id = int(promo_payload.get("promo_id") or 0)
    if promo_id <= 0:
        return None
    promo = get_promo_code_by_id(db, promo_id=promo_id)
    if promo is None:
        return None
    return create_promo_redemption(
        db,
        venue_id=int(transaction.venue_id),
        promo=promo,
        promo_payload=promo_payload,
        billing_transaction_id=int(transaction.id),
    )


def apply_free_promo_code(
    db: Session,
    *,
    venue_id: int,
    created_by_user_id: int | None,
    state: VenueBillingState,
    preview: PromoPreview,
) -> tuple[VenueBillingState, VenueBillingTransaction, VenueBillingEvent, BillingPromoRedemption]:
    now = utcnow()
    current_paid_until, _ = derive_billing_dates(
        paid_until=state.paid_until,
        grace_until=state.grace_until,
        grace_days=DEFAULT_BILLING_GRACE_DAYS,
    )
    period_from = current_paid_until if current_paid_until is not None and current_paid_until > now else now
    period_until = period_from + timedelta(days=max(1, int(preview.days_added or 1)))
    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()

    state.status = BILLING_STATUS_ACTIVE
    state.paid_until = period_until
    state.grace_until = period_until + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    state.last_payment_at = now
    state.next_payment_due_at = period_until
    state.provider = PROMO_SOURCE
    state.updated_at = now

    promo_payload = promo_preview_to_payload(preview)
    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source=PROMO_SOURCE,
        type=PROMO_TRANSACTION_TYPE,
        status="SUCCEEDED",
        amount_minor=0,
        days_added=max(1, int(preview.days_added or 1)),
        period_from=period_from,
        period_until=period_until,
        provider_invoice_id=None,
        provider_payment_id=None,
        provider_payload_json={
            "promo": promo_payload,
            "applied_at": now.isoformat(),
        },
        comment=f"Promo code {preview.code} applied",
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()

    promo = get_promo_code_by_id(db, promo_id=int(preview.promo_id))
    if promo is None:
        raise ValueError("Промокод не найден")
    redemption = create_promo_redemption(
        db,
        venue_id=int(venue_id),
        promo=promo,
        promo_payload=promo_payload,
        billing_transaction_id=int(tx.id),
    )

    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="PROMO_CODE_APPLIED",
        old_status=old_status,
        new_status=BILLING_STATUS_ACTIVE,
        meta_json={
            "transaction_id": int(tx.id),
            "promo_code": preview.code,
            "period_from": period_from.isoformat() if period_from else None,
            "period_until": period_until.isoformat() if period_until else None,
        },
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return state, tx, event, redemption
