from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_state import VenueBillingState
from app.models.venue_billing_transaction import VenueBillingTransaction
from .state import BILLING_STATUS_ACTIVE, DEFAULT_BILLING_GRACE_DAYS as _DEFAULT_GRACE_DAYS, utcnow, derive_billing_dates

DEFAULT_BILLING_PLAN_CODE = "AXELIO_VENUE_MONTHLY"
DEFAULT_BILLING_PRICE_MINOR = 299000
DEFAULT_BILLING_CURRENCY = "RUB"
DEFAULT_BILLING_PROVIDER = "ROBOKASSA"
DEFAULT_BILLING_DAYS = 30
DEFAULT_BILLING_GRACE_DAYS = _DEFAULT_GRACE_DAYS


def create_default_billing_state(db: Session, *, venue_id: int, commit: bool = False) -> VenueBillingState:
    now = utcnow()
    paid_until = now + timedelta(days=DEFAULT_BILLING_DAYS)
    grace_until = paid_until + timedelta(days=DEFAULT_BILLING_GRACE_DAYS)
    state = VenueBillingState(
        venue_id=int(venue_id),
        plan_code=DEFAULT_BILLING_PLAN_CODE,
        price_minor=DEFAULT_BILLING_PRICE_MINOR,
        currency=DEFAULT_BILLING_CURRENCY,
        status=BILLING_STATUS_ACTIVE,
        paid_until=paid_until,
        grace_until=grace_until,
        last_payment_at=now,
        next_payment_due_at=paid_until,
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


def list_billing_transactions(db: Session, *, venue_id: int, limit: int = 10) -> list[VenueBillingTransaction]:
    stmt = (
        select(VenueBillingTransaction)
        .where(VenueBillingTransaction.venue_id == int(venue_id))
        .order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
        .limit(max(1, int(limit)))
    )
    return list(db.execute(stmt).scalars().all())


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
