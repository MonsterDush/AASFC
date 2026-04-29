from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_state import VenueBillingState
from app.models.venue_billing_transaction import VenueBillingTransaction
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from .promos import finalize_transaction_promo_redemption
from .state import (
    BILLING_STATUS_ACTIVE,
    BILLING_STATUS_GRACE,
    BILLING_STATUS_SUSPENDED,
    DEFAULT_BILLING_GRACE_DAYS as _DEFAULT_GRACE_DAYS,
    build_billing_snapshot,
    derive_billing_dates,
    utcnow,
)

DEFAULT_BILLING_PLAN_CODE = "AXELIO_VENUE_MONTHLY"
DEFAULT_BILLING_PRICE_MINOR = 299000
DEFAULT_BILLING_CURRENCY = "RUB"
DEFAULT_BILLING_PROVIDER = "ROBOKASSA"
DEFAULT_BILLING_DAYS = 30
DEFAULT_BILLING_GRACE_DAYS = _DEFAULT_GRACE_DAYS
DEFAULT_TRIAL_DAYS = 3
TRIAL_PROVIDER = "TRIAL"
TRIAL_TRANSACTION_SOURCE = "TRIAL"
TRIAL_TRANSACTION_TYPE = "TRIAL_GRANT"
DEFAULT_CHECKOUT_TTL_MINUTES = 60


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    return {"value": value}


def _checkout_ttl_minutes() -> int:
    configured = getattr(settings, "ROBOKASSA_CHECKOUT_TTL_MINUTES", None)
    try:
        value = int(configured or DEFAULT_CHECKOUT_TTL_MINUTES)
    except (TypeError, ValueError):
        value = DEFAULT_CHECKOUT_TTL_MINUTES
    return max(5, value)


def _pending_checkout_expires_at(*, created_at: datetime | None) -> datetime | None:
    created = _ensure_aware(created_at)
    if created is None:
        return None
    return created + timedelta(minutes=_checkout_ttl_minutes())


def get_checkout_expires_at(transaction: VenueBillingTransaction | None) -> datetime | None:
    if transaction is None:
        return None
    payload = _json_object(getattr(transaction, "provider_payload_json", None))
    value = payload.get("checkout_expires_at")
    if value:
        try:
            return _ensure_aware(datetime.fromisoformat(str(value)))
        except Exception:
            pass
    return _pending_checkout_expires_at(created_at=getattr(transaction, "created_at", None))


def parse_amount_minor(value: str | int | float | Decimal | None) -> int:
    if value is None:
        return 0
    dec = Decimal(str(value).strip() or "0")
    return int((dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_default_billing_state(db: Session, *, venue_id: int, commit: bool = False) -> VenueBillingState:
    now = utcnow()
    grace_until = now + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    state = VenueBillingState(
        venue_id=int(venue_id),
        plan_code=DEFAULT_BILLING_PLAN_CODE,
        price_minor=DEFAULT_BILLING_PRICE_MINOR,
        currency=DEFAULT_BILLING_CURRENCY,
        status=BILLING_STATUS_GRACE,
        paid_until=None,
        grace_until=grace_until,
        last_payment_at=None,
        next_payment_due_at=now,
        auto_renew_enabled=False,
        provider=DEFAULT_BILLING_PROVIDER,
        created_at=now,
        updated_at=now,
    )
    db.add(state)
    db.flush()
    if commit:
        db.commit()
        db.refresh(state)
    return state


def get_or_create_billing_state(db: Session, *, venue_id: int, commit: bool = False) -> VenueBillingState:
    state = db.execute(
        select(VenueBillingState).where(VenueBillingState.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if state is not None:
        return state
    return create_default_billing_state(db, venue_id=int(venue_id), commit=commit)


def has_user_used_self_service_trial(db: Session, *, user_id: int) -> bool:
    """One free self-service trial per user.

    We rely on billing transactions, so removing a member from a venue
    does not reset the free trial.
    """
    existing_trial = db.execute(
        select(VenueBillingTransaction.id)
        .where(
            VenueBillingTransaction.created_by_user_id == int(user_id),
            VenueBillingTransaction.type == TRIAL_TRANSACTION_TYPE,
            VenueBillingTransaction.status == "SUCCEEDED",
        )
        .limit(1)
    ).scalar_one_or_none()
    return existing_trial is not None


def user_has_owned_real_venue(db: Session, *, user_id: int) -> bool:
    existing_owned_venue = db.execute(
        select(Venue.id)
        .join(VenueMember, VenueMember.venue_id == Venue.id)
        .where(
            VenueMember.user_id == int(user_id),
            VenueMember.venue_role == "OWNER",
            VenueMember.is_active.is_(True),
            or_(Venue.is_demo.is_(False), Venue.is_demo.is_(None)),
        )
        .limit(1)
    ).scalar_one_or_none()
    return existing_owned_venue is not None


def can_grant_self_service_trial(db: Session, *, user_id: int) -> bool:
    return (
        not has_user_used_self_service_trial(db, user_id=int(user_id))
        and not user_has_owned_real_venue(db, user_id=int(user_id))
    )


def grant_self_service_trial(
    db: Session,
    *,
    venue_id: int,
    created_by_user_id: int,
    days: int = DEFAULT_TRIAL_DAYS,
) -> tuple[VenueBillingState, VenueBillingTransaction, VenueBillingEvent]:
    trial_days = max(1, int(days or DEFAULT_TRIAL_DAYS))
    now = utcnow()
    state = get_or_create_billing_state(db, venue_id=int(venue_id))

    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()
    old_paid_until = state.paid_until
    old_grace_until = state.grace_until

    period_from = now
    period_until = now + timedelta(days=trial_days)
    grace_until = period_until + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)

    state.status = BILLING_STATUS_ACTIVE
    state.paid_until = period_until
    state.grace_until = grace_until
    state.last_payment_at = None
    state.next_payment_due_at = period_until
    state.provider = TRIAL_PROVIDER
    state.updated_at = now

    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source=TRIAL_TRANSACTION_SOURCE,
        type=TRIAL_TRANSACTION_TYPE,
        status="SUCCEEDED",
        amount_minor=0,
        days_added=trial_days,
        period_from=period_from,
        period_until=period_until,
        provider_invoice_id=None,
        provider_payment_id=None,
        provider_payload_json={
            "trial": True,
            "trial_days": trial_days,
            "grace_days": DEFAULT_BILLING_GRACE_DAYS,
            "old_paid_until": old_paid_until.isoformat() if old_paid_until else None,
            "old_grace_until": old_grace_until.isoformat() if old_grace_until else None,
        },
        comment="Self-service trial granted",
        created_by_user_id=int(created_by_user_id),
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()

    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="TRIAL_STARTED",
        old_status=old_status,
        new_status=BILLING_STATUS_ACTIVE,
        meta_json={
            "trial": True,
            "days_added": trial_days,
            "period_from": period_from.isoformat(),
            "period_until": period_until.isoformat(),
            "grace_until": grace_until.isoformat(),
            "transaction_id": int(tx.id),
        },
        created_by_user_id=int(created_by_user_id),
        created_at=now,
    )
    db.add(event)
    db.flush()

    return state, tx, event


def list_billing_transactions(db: Session, *, venue_id: int, limit: int = 10) -> list[VenueBillingTransaction]:
    stmt = (
        select(VenueBillingTransaction)
        .where(VenueBillingTransaction.venue_id == int(venue_id))
        .order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
        .limit(max(1, int(limit)))
    )
    return list(db.execute(stmt).scalars().all())


def list_billing_transactions_global(
    db: Session,
    *,
    venue_id: int | None = None,
    status: str | None = None,
    tx_type: str | None = None,
    source: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[VenueBillingTransaction], int]:
    stmt = select(VenueBillingTransaction)
    if venue_id is not None:
        stmt = stmt.where(VenueBillingTransaction.venue_id == int(venue_id))
    if status:
        stmt = stmt.where(VenueBillingTransaction.status == str(status).upper())
    if tx_type:
        stmt = stmt.where(VenueBillingTransaction.type == str(tx_type).upper())
    if source:
        stmt = stmt.where(VenueBillingTransaction.source == str(source).upper())
    stmt = stmt.order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    page_norm = max(1, int(page or 1))
    size_norm = max(1, min(500, int(page_size or 50)))
    items = list(db.execute(stmt.offset((page_norm - 1) * size_norm).limit(size_norm)).scalars().all())
    return items, total


def list_billing_events(db: Session, *, venue_id: int, limit: int = 20) -> list[VenueBillingEvent]:
    stmt = (
        select(VenueBillingEvent)
        .where(VenueBillingEvent.venue_id == int(venue_id))
        .order_by(VenueBillingEvent.created_at.desc(), VenueBillingEvent.id.desc())
        .limit(max(1, int(limit)))
    )
    return list(db.execute(stmt).scalars().all())


def get_latest_pending_checkout(db: Session, *, venue_id: int) -> VenueBillingTransaction | None:
    stmt = (
        select(VenueBillingTransaction)
        .where(
            VenueBillingTransaction.venue_id == int(venue_id),
            VenueBillingTransaction.type == "PAYMENT",
            VenueBillingTransaction.status == "PENDING",
        )
        .order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
        .limit(1)
    )
    tx = db.execute(stmt).scalar_one_or_none()
    if tx is None:
        return None
    expires_at = get_checkout_expires_at(tx)
    if expires_at is not None and expires_at <= utcnow():
        return None
    return tx


def get_billing_transaction_by_invoice_id(db: Session, *, invoice_id: str | int) -> VenueBillingTransaction | None:
    invoice_str = str(invoice_id).strip()
    conditions = [VenueBillingTransaction.provider_invoice_id == invoice_str]
    if invoice_str.isdigit():
        conditions.append(VenueBillingTransaction.id == int(invoice_str))
    return db.execute(select(VenueBillingTransaction).where(or_(*conditions))).scalar_one_or_none()


def sync_billing_state(
    db: Session,
    *,
    state: VenueBillingState,
    now: datetime | None = None,
    created_by_user_id: int | None = None,
    event_type: str = "BILLING_STATUS_CHANGED_AUTO",
) -> tuple[VenueBillingState, Any, VenueBillingEvent | None]:
    current = _ensure_aware(now) or utcnow()
    snapshot = build_billing_snapshot(
        paid_until=state.paid_until,
        grace_until=state.grace_until,
        status=state.status,
        now=current,
        grace_days=DEFAULT_BILLING_GRACE_DAYS,
    )
    event: VenueBillingEvent | None = None
    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()
    paid_until, grace_until = derive_billing_dates(
        paid_until=state.paid_until,
        grace_until=state.grace_until,
        grace_days=DEFAULT_BILLING_GRACE_DAYS,
    )

    changed = (
        old_status != snapshot.status
        or _ensure_aware(state.paid_until) != paid_until
        or _ensure_aware(state.grace_until) != grace_until
    )
    if changed:
        state.status = snapshot.status
        state.paid_until = paid_until
        state.grace_until = grace_until
        state.next_payment_due_at = paid_until
        state.updated_at = current
        event = VenueBillingEvent(
            venue_id=int(state.venue_id),
            event_type=event_type,
            old_status=old_status,
            new_status=snapshot.status,
            meta_json={
                "paid_until": paid_until.isoformat() if paid_until else None,
                "grace_until": grace_until.isoformat() if grace_until else None,
            },
            created_by_user_id=created_by_user_id,
            created_at=current,
        )
        db.add(event)
        db.flush()
    return state, snapshot, event


def extend_venue_billing(
    db: Session,
    *,
    venue_id: int,
    days: int,
    created_by_user_id: int | None = None,
    comment: str | None = None,
    source: str = "MANUAL_ADMIN",
    tx_type: str = "EXTEND",
    tx_status: str = "SUCCEEDED",
    amount_minor: int = 0,
    provider: str | None = None,
    provider_invoice_id: str | None = None,
    provider_payment_id: str | None = None,
    provider_payload_json: dict | list | None = None,
) -> tuple[VenueBillingState, VenueBillingTransaction, VenueBillingEvent]:
    add_days = max(1, int(days))
    now = utcnow()
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    current_paid_until, _ = derive_billing_dates(
        paid_until=state.paid_until,
        grace_until=state.grace_until,
        grace_days=DEFAULT_BILLING_GRACE_DAYS,
    )
    period_from = current_paid_until if current_paid_until is not None and current_paid_until > now else now
    period_until = period_from + timedelta(days=add_days)

    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()
    old_paid_until = state.paid_until
    old_grace_until = state.grace_until

    state.status = BILLING_STATUS_ACTIVE
    state.paid_until = period_until
    state.grace_until = period_until + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    state.last_payment_at = now
    state.next_payment_due_at = period_until
    state.provider = provider or state.provider or DEFAULT_BILLING_PROVIDER
    state.updated_at = now

    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source=str(source or "MANUAL_ADMIN").upper(),
        type=str(tx_type or "EXTEND").upper(),
        status=str(tx_status or "SUCCEEDED").upper(),
        amount_minor=int(amount_minor or 0),
        days_added=add_days,
        period_from=period_from,
        period_until=period_until,
        provider_invoice_id=provider_invoice_id,
        provider_payment_id=provider_payment_id,
        provider_payload_json=provider_payload_json,
        comment=comment,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()

    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="BILLING_EXTENDED_MANUALLY" if str(source or "").upper() == "MANUAL_ADMIN" else "BILLING_EXTENDED",
        old_status=old_status,
        new_status=BILLING_STATUS_ACTIVE,
        meta_json={
            "days_added": add_days,
            "period_from": period_from.isoformat() if period_from else None,
            "period_until": period_until.isoformat() if period_until else None,
            "old_paid_until": old_paid_until.isoformat() if old_paid_until else None,
            "old_grace_until": old_grace_until.isoformat() if old_grace_until else None,
            "transaction_id": int(tx.id),
            "source": str(source or "").upper() or None,
        },
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()

    return state, tx, event


def set_venue_billing_paid_until(
    db: Session,
    *,
    venue_id: int,
    paid_until,
    created_by_user_id: int | None = None,
    comment: str | None = None,
    amount_minor: int = 0,
) -> tuple[VenueBillingState, VenueBillingTransaction, VenueBillingEvent]:
    now = utcnow()
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    paid_until_value = _ensure_aware(paid_until)
    if paid_until_value is None:
        raise ValueError("paid_until is required")

    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()
    old_paid_until = state.paid_until
    old_grace_until = state.grace_until

    computed_grace_until = paid_until_value + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    if paid_until_value >= now:
        new_status = BILLING_STATUS_ACTIVE
    elif computed_grace_until >= now:
        new_status = BILLING_STATUS_GRACE
    else:
        new_status = BILLING_STATUS_SUSPENDED

    state.status = new_status
    state.paid_until = paid_until_value
    state.grace_until = computed_grace_until
    state.next_payment_due_at = paid_until_value
    state.updated_at = now

    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source="MANUAL_ADMIN",
        type="SET_PAID_UNTIL",
        status="SUCCEEDED",
        amount_minor=int(amount_minor or 0),
        days_added=None,
        period_from=old_paid_until if old_paid_until is not None else now,
        period_until=paid_until_value,
        provider_invoice_id=None,
        provider_payment_id=None,
        provider_payload_json={
            "old_paid_until": old_paid_until.isoformat() if old_paid_until else None,
            "old_grace_until": old_grace_until.isoformat() if old_grace_until else None,
            "new_paid_until": paid_until_value.isoformat() if paid_until_value else None,
        },
        comment=comment,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()

    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="BILLING_PAID_UNTIL_SET_MANUALLY",
        old_status=old_status,
        new_status=new_status,
        meta_json={
            "transaction_id": int(tx.id),
            "old_paid_until": old_paid_until.isoformat() if old_paid_until else None,
            "old_grace_until": old_grace_until.isoformat() if old_grace_until else None,
            "new_paid_until": paid_until_value.isoformat() if paid_until_value else None,
        },
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()

    return state, tx, event


def create_refund_transaction(
    db: Session,
    *,
    venue_id: int,
    amount_minor: int,
    created_by_user_id: int | None,
    comment: str | None = None,
    revoke_access_hint: bool = False,
) -> tuple[VenueBillingTransaction, VenueBillingEvent]:
    now = utcnow()
    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source="MANUAL_ADMIN",
        type="REFUND",
        status="SUCCEEDED",
        amount_minor=max(0, int(amount_minor or 0)),
        days_added=0,
        period_from=None,
        period_until=None,
        provider_invoice_id=None,
        provider_payment_id=None,
        provider_payload_json={"revoke_access_hint": bool(revoke_access_hint)},
        comment=comment,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()
    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="BILLING_REFUND_CREATED",
        old_status=None,
        new_status=None,
        meta_json={
            "transaction_id": int(tx.id),
            "amount_minor": int(tx.amount_minor or 0),
            "revoke_access_hint": bool(revoke_access_hint),
        },
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return tx, event



def create_checkout_transaction(
    db: Session,
    *,
    venue_id: int,
    created_by_user_id: int | None,
    amount_minor: int | None = None,
    days_added: int = DEFAULT_BILLING_DAYS,
    provider: str = DEFAULT_BILLING_PROVIDER,
    comment: str | None = None,
    provider_payload_json: dict | list | None = None,
    replace_existing: bool = False,
) -> VenueBillingTransaction:
    existing = get_latest_pending_checkout(db, venue_id=int(venue_id))
    if existing is not None and not replace_existing:
        return existing
    if existing is not None and replace_existing:
        mark_checkout_transaction_failed(
            db,
            transaction=existing,
            status="CANCELED",
            provider_payload_json={"replaced_at": utcnow().isoformat()},
            comment="Billing checkout replaced",
            event_type="BILLING_CHECKOUT_REPLACED",
        )

    now = utcnow()
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    checkout_expires_at = _pending_checkout_expires_at(created_at=now)
    base_payload = {
            "checkout_created_at": now.isoformat(),
            "checkout_expires_at": checkout_expires_at.isoformat() if checkout_expires_at else None,
        }
    if isinstance(provider_payload_json, dict):
        base_payload.update(provider_payload_json)
    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source=str(provider or DEFAULT_BILLING_PROVIDER).upper(),
        type="PAYMENT",
        status="PENDING",
        amount_minor=int(amount_minor if amount_minor is not None else (state.price_minor or DEFAULT_BILLING_PRICE_MINOR)),
        days_added=max(1, int(days_added or DEFAULT_BILLING_DAYS)),
        period_from=None,
        period_until=None,
        provider_invoice_id=None,
        provider_payment_id=None,
        provider_payload_json=base_payload,
        comment=comment,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()
    tx.provider_invoice_id = str(tx.id)
    tx.updated_at = now
    db.flush()
    return tx


def expire_stale_pending_checkouts(db: Session, *, now: datetime | None = None) -> tuple[int, list[VenueBillingEvent]]:
    current = _ensure_aware(now) or utcnow()
    txs = db.execute(
        select(VenueBillingTransaction).where(
            VenueBillingTransaction.type == "PAYMENT",
            VenueBillingTransaction.status == "PENDING",
        )
    ).scalars().all()
    expired_count = 0
    events: list[VenueBillingEvent] = []
    for tx in txs:
        expires_at = get_checkout_expires_at(tx)
        if expires_at is None or expires_at > current:
            continue
        tx, event = mark_checkout_transaction_failed(
            db,
            transaction=tx,
            status="FAILED",
            provider_payload_json={"expired_at": current.isoformat()},
            comment="Billing checkout expired",
            event_type="ROBOKASSA_PAYMENT_EXPIRED",
        )
        expired_count += 1
        if event is not None:
            events.append(event)
    return expired_count, events


def apply_checkout_payment_success(
    db: Session,
    *,
    transaction: VenueBillingTransaction,
    provider_payment_id: str | None = None,
    provider_payload_json: dict | list | None = None,
    amount_minor: int | None = None,
) -> tuple[VenueBillingState, VenueBillingTransaction, VenueBillingEvent | None, bool]:
    now = utcnow()
    tx = transaction
    if str(tx.status or "").upper() == "SUCCEEDED":
        state = get_or_create_billing_state(db, venue_id=int(tx.venue_id))
        return state, tx, None, False

    expected_amount_minor = int(tx.amount_minor or 0)
    if amount_minor is not None and expected_amount_minor and int(amount_minor) != expected_amount_minor:
        raise ValueError("Robokassa amount mismatch")

    state = get_or_create_billing_state(db, venue_id=int(tx.venue_id))
    current_paid_until, _ = derive_billing_dates(
        paid_until=state.paid_until,
        grace_until=state.grace_until,
        grace_days=DEFAULT_BILLING_GRACE_DAYS,
    )
    period_from = current_paid_until if current_paid_until is not None and current_paid_until > now else now
    add_days = max(1, int(tx.days_added or DEFAULT_BILLING_DAYS))
    period_until = period_from + timedelta(days=add_days)
    old_status = str(state.status or BILLING_STATUS_ACTIVE).upper()

    state.status = BILLING_STATUS_ACTIVE
    state.paid_until = period_until
    state.grace_until = period_until + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    state.last_payment_at = now
    state.next_payment_due_at = period_until
    state.provider = tx.source or DEFAULT_BILLING_PROVIDER
    state.updated_at = now

    payload = _json_object(tx.provider_payload_json)
    payload.update(_json_object(provider_payload_json))
    payload["applied_at"] = now.isoformat()

    tx.status = "SUCCEEDED"
    tx.period_from = period_from
    tx.period_until = period_until
    tx.provider_payment_id = provider_payment_id or tx.provider_payment_id
    tx.provider_payload_json = payload
    tx.updated_at = now

    finalize_transaction_promo_redemption(db, transaction=tx)

    event = VenueBillingEvent(
        venue_id=int(tx.venue_id),
        event_type="PROMO_PAYMENT_SUCCEEDED" if str(tx.source or "").upper() == "PROMOCODE" else "ROBOKASSA_PAYMENT_SUCCEEDED",
        old_status=old_status,
        new_status=BILLING_STATUS_ACTIVE,
        meta_json={
            "transaction_id": int(tx.id),
            "period_from": period_from.isoformat() if period_from else None,
            "period_until": period_until.isoformat() if period_until else None,
            "provider_payment_id": provider_payment_id or tx.provider_payment_id,
        },
        created_by_user_id=tx.created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return state, tx, event, True


def mark_checkout_transaction_failed(
    db: Session,
    *,
    transaction: VenueBillingTransaction,
    status: str = "FAILED",
    provider_payload_json: dict | list | None = None,
    comment: str | None = None,
    event_type: str = "ROBOKASSA_PAYMENT_FAILED",
) -> tuple[VenueBillingTransaction, VenueBillingEvent | None]:
    tx = transaction
    current_status = str(tx.status or "").upper()
    if current_status == "SUCCEEDED":
        return tx, None
    now = utcnow()
    old_status = current_status or "PENDING"
    tx.status = str(status or "FAILED").upper()
    payload = _json_object(tx.provider_payload_json)
    payload.update(_json_object(provider_payload_json))
    if comment:
        payload["comment"] = comment
    tx.provider_payload_json = payload
    tx.updated_at = now
    if comment:
        tx.comment = comment
    event = VenueBillingEvent(
        venue_id=int(tx.venue_id),
        event_type=event_type,
        old_status=None,
        new_status=None,
        meta_json={
            "transaction_id": int(tx.id),
            "transaction_old_status": old_status,
            "transaction_new_status": tx.status,
        },
        created_by_user_id=tx.created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return tx, event


def _refund_target_payment_tx_id(tx: VenueBillingTransaction) -> int | None:
    payload = _json_object(getattr(tx, "provider_payload_json", None))
    value = payload.get("target_payment_transaction_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None




def get_reserved_refund_amount_for_payment(
    db: Session,
    *,
    payment_transaction_id: int,
) -> int:
    refund_txs = list(db.execute(
        select(VenueBillingTransaction).where(
            VenueBillingTransaction.type == "REFUND",
        )
    ).scalars().all())
    total = 0
    for refund_tx in refund_txs:
        if _refund_target_payment_tx_id(refund_tx) != int(payment_transaction_id):
            continue
        if str(refund_tx.status or "").upper() not in {"PENDING", "SUCCEEDED"}:
            continue
        total += int(refund_tx.amount_minor or 0)
    return total
def get_refundable_payment_transaction(
    db: Session,
    *,
    venue_id: int,
    requested_amount_minor: int,
) -> VenueBillingTransaction | None:
    payment_txs = list(db.execute(
        select(VenueBillingTransaction).where(
            VenueBillingTransaction.venue_id == int(venue_id),
            VenueBillingTransaction.type == "PAYMENT",
            VenueBillingTransaction.status == "SUCCEEDED",
            VenueBillingTransaction.source == "ROBOKASSA",
        ).order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
    ).scalars().all())
    if not payment_txs:
        return None
    requested = max(0, int(requested_amount_minor or 0))
    for payment_tx in payment_txs:
        op_key = str(payment_tx.provider_payment_id or "").strip()
        remaining = max(0, int(payment_tx.amount_minor or 0) - get_reserved_refund_amount_for_payment(db, payment_transaction_id=int(payment_tx.id)))
        if requested > remaining:
            continue
        if op_key:
            return payment_tx
        payload = _json_object(getattr(payment_tx, "provider_payload_json", None))
        if payload.get("op_key"):
            return payment_tx
        return payment_tx
    return None


def create_external_refund_transaction(
    db: Session,
    *,
    venue_id: int,
    target_payment_transaction: VenueBillingTransaction,
    amount_minor: int,
    request_id: str,
    op_key: str,
    created_by_user_id: int | None,
    comment: str | None = None,
) -> tuple[VenueBillingTransaction, VenueBillingEvent]:
    now = utcnow()
    tx = VenueBillingTransaction(
        venue_id=int(venue_id),
        source="ROBOKASSA",
        type="REFUND",
        status="PENDING",
        amount_minor=max(0, int(amount_minor or 0)),
        days_added=0,
        period_from=None,
        period_until=None,
        provider_invoice_id=str(target_payment_transaction.provider_invoice_id or target_payment_transaction.id),
        provider_payment_id=str(request_id or "").strip() or None,
        provider_payload_json={
            "target_payment_transaction_id": int(target_payment_transaction.id),
            "target_payment_invoice_id": target_payment_transaction.provider_invoice_id,
            "op_key": str(op_key or "").strip() or None,
            "refund_requested_at": now.isoformat(),
            "refund_state_label": "processing",
        },
        comment=comment,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()
    event = VenueBillingEvent(
        venue_id=int(venue_id),
        event_type="ROBOKASSA_REFUND_REQUESTED",
        old_status=None,
        new_status=None,
        meta_json={
            "transaction_id": int(tx.id),
            "target_payment_transaction_id": int(target_payment_transaction.id),
            "request_id": tx.provider_payment_id,
            "amount_minor": int(tx.amount_minor or 0),
        },
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return tx, event


def sync_external_refund_transaction_state(
    db: Session,
    *,
    transaction: VenueBillingTransaction,
    refund_state_label: str,
    provider_payload_json: dict | None = None,
) -> tuple[VenueBillingTransaction, VenueBillingEvent | None]:
    tx = transaction
    now = utcnow()
    label = str(refund_state_label or "").strip().lower()
    payload = _json_object(getattr(tx, "provider_payload_json", None))
    payload.update(_json_object(provider_payload_json))
    payload["refund_state_label"] = label or payload.get("refund_state_label")
    payload["refund_state_checked_at"] = now.isoformat()
    tx.provider_payload_json = payload
    tx.updated_at = now

    current_status = str(tx.status or "").upper()
    new_status = current_status
    event_type = None
    if label == "finished":
        new_status = "SUCCEEDED"
        event_type = "ROBOKASSA_REFUND_FINISHED" if current_status != "SUCCEEDED" else None
    elif label == "canceled":
        new_status = "CANCELED"
        event_type = "ROBOKASSA_REFUND_CANCELED" if current_status != "CANCELED" else None
    elif label == "processing":
        new_status = "PENDING"
    elif label:
        new_status = "FAILED"
        event_type = "ROBOKASSA_REFUND_FAILED" if current_status != "FAILED" else None

    tx.status = new_status
    event = None
    if event_type is not None:
        event = VenueBillingEvent(
            venue_id=int(tx.venue_id),
            event_type=event_type,
            old_status=current_status or None,
            new_status=new_status,
            meta_json={
                "transaction_id": int(tx.id),
                "refund_state_label": label,
            },
            created_by_user_id=tx.created_by_user_id,
            created_at=now,
        )
        db.add(event)
        db.flush()
    return tx, event


def list_pending_external_refund_transactions(db: Session, *, limit: int = 100) -> list[VenueBillingTransaction]:
    stmt = (
        select(VenueBillingTransaction)
        .where(
            VenueBillingTransaction.type == "REFUND",
            VenueBillingTransaction.source == "ROBOKASSA",
            VenueBillingTransaction.status == "PENDING",
            VenueBillingTransaction.provider_payment_id.isnot(None),
        )
        .order_by(VenueBillingTransaction.created_at.asc(), VenueBillingTransaction.id.asc())
        .limit(max(1, int(limit or 100)))
    )
    return list(db.execute(stmt).scalars().all())
