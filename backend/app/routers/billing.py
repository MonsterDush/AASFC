from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_member import VenueMember
from app.services.billing import (
    apply_checkout_payment_success,
    build_checkout_url,
    create_checkout_transaction,
    format_out_sum,
    get_billing_transaction_by_invoice_id,
    get_checkout_expires_at,
    get_or_create_billing_state,
    get_robokassa_config,
    get_user_billing_access,
    is_valid_result_signature,
    is_valid_success_signature,
    list_billing_events,
    list_billing_transactions,
    mark_checkout_transaction_failed,
    parse_amount_minor,
    send_owner_billing_notification_once,
)
from app.services.xlsx_export import build_billing_transactions_xlsx

router = APIRouter(prefix="/venues", tags=["billing"])
public_router = APIRouter(tags=["billing-public"])


def _require_owner_or_admin_billing_access(db: Session, *, venue_id: int, user: User) -> str:
    if user.system_role in {"SUPER_ADMIN", "MODERATOR"}:
        return "SUPER_ADMIN"
    member = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id == int(user.id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if member is None or str(member.venue_role or "").upper() != "OWNER":
        raise HTTPException(status_code=403, detail="Forbidden")
    return "OWNER"


def _serialize_billing_transaction(tx) -> dict[str, Any]:
    return {
        "id": int(tx.id),
        "source": tx.source,
        "type": tx.type,
        "status": tx.status,
        "amount_minor": int(tx.amount_minor or 0),
        "days_added": int(tx.days_added or 0) if tx.days_added is not None else None,
        "period_from": tx.period_from.isoformat() if tx.period_from else None,
        "period_until": tx.period_until.isoformat() if tx.period_until else None,
        "provider_invoice_id": tx.provider_invoice_id,
        "provider_payment_id": tx.provider_payment_id,
        "comment": tx.comment,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
        "provider_payload_json": tx.provider_payload_json,
    }


def _serialize_billing_event(event) -> dict[str, Any]:
    return {
        "id": int(event.id),
        "event_type": event.event_type,
        "old_status": event.old_status,
        "new_status": event.new_status,
        "meta": event.meta_json if isinstance(event.meta_json, dict) else (event.meta_json or {}),
        "created_by_user_id": event.created_by_user_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.get("/{venue_id}/billing")
def get_venue_billing(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = _require_owner_or_admin_billing_access(db, venue_id=venue_id, user=user)
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    access = get_user_billing_access(db, venue_id=int(venue_id), user=user, membership_role=role)
    txs = list_billing_transactions(db, venue_id=int(venue_id), limit=20)
    events = list_billing_events(db, venue_id=int(venue_id), limit=20)
    robo_cfg = get_robokassa_config()
    latest_pending = next((tx for tx in txs if str(tx.status or "").upper() == "PENDING" and str(tx.type or "").upper() == "PAYMENT"), None)
    checkout_expires_at = get_checkout_expires_at(latest_pending)

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "plan": {
            "code": state.plan_code,
            "price_minor": int(state.price_minor or 0),
            "currency": state.currency,
            "label": "Axelio · 2990 ₽ / 30 дней",
        },
        "provider": state.provider,
        "provider_ready": robo_cfg.is_enabled,
        "provider_mode": "test" if robo_cfg.test_mode else "prod",
        "status": access.get("billing_status"),
        "billing_access_mode": access.get("billing_access_mode"),
        "paid_until": access.get("paid_until").isoformat() if access.get("paid_until") else None,
        "grace_until": access.get("grace_until").isoformat() if access.get("grace_until") else None,
        "last_payment_at": state.last_payment_at.isoformat() if state.last_payment_at else None,
        "next_payment_due_at": state.next_payment_due_at.isoformat() if state.next_payment_due_at else None,
        "auto_renew_enabled": bool(state.auto_renew_enabled),
        "can_extend": True,
        "billing_restricted_reason": access.get("billing_restricted_reason"),
        "checkout_expires_at": checkout_expires_at.isoformat() if checkout_expires_at else None,
        "transactions": [_serialize_billing_transaction(tx) for tx in txs],
        "events": [_serialize_billing_event(event) for event in events],
    }


@router.post("/{venue_id}/billing/checkout")
def create_venue_billing_checkout(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = _require_owner_or_admin_billing_access(db, venue_id=venue_id, user=user)
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    access = get_user_billing_access(db, venue_id=int(venue_id), user=user, membership_role=role)
    if str(access.get("billing_access_mode") or "").upper() not in {"FULL", "BILLING_READONLY"}:
        raise HTTPException(status_code=403, detail=access.get("billing_restricted_reason") or "Billing access denied")

    robo_cfg = get_robokassa_config()
    if not robo_cfg.is_enabled:
        raise HTTPException(status_code=503, detail="Robokassa is not configured")

    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    tx = create_checkout_transaction(
        db,
        venue_id=int(venue_id),
        created_by_user_id=int(user.id),
        amount_minor=int(state.price_minor or 0),
        days_added=30,
        provider="ROBOKASSA",
        comment="Robokassa checkout created",
    )
    out_sum = format_out_sum(int(tx.amount_minor or 0), test_mode=robo_cfg.test_mode)
    extra_params = {
        "Shp_venueId": str(int(venue_id)),
        "Shp_tx": str(int(tx.id)),
    }
    checkout_expires_at = get_checkout_expires_at(tx)
    expiration_value = checkout_expires_at if bool(getattr(settings, "ROBOKASSA_SEND_EXPIRATION_DATE", False)) else None
    checkout_url = build_checkout_url(
        merchant_login=robo_cfg.merchant_login,
        out_sum=out_sum,
        invoice_id=str(tx.provider_invoice_id or tx.id),
        description=f"Axelio · продление доступа к заведению «{venue.name}» на 30 дней",
        password1=robo_cfg.password1,
        algorithm=robo_cfg.hash_algorithm,
        payment_url=robo_cfg.payment_url,
        result_url=robo_cfg.result_url,
        success_url=robo_cfg.success_url,
        fail_url=robo_cfg.fail_url,
        extra_params=extra_params,
        test_mode=robo_cfg.test_mode,
        culture="ru",
        expiration_date=expiration_value,
        use_return_url2=bool(getattr(settings, "ROBOKASSA_USE_RETURN_URL2", False)),
    )
    payload = dict(tx.provider_payload_json or {})
    payload.update({
        "out_sum": out_sum,
        "venue_name": venue.name,
        "checkout_url": checkout_url,
        "extra_params": extra_params,
        "test_mode": robo_cfg.test_mode,
        "checkout_expires_at": checkout_expires_at.isoformat() if checkout_expires_at else None,
    })
    tx.provider_payload_json = payload
    db.commit()
    db.refresh(tx)

    return {
        "transaction_id": int(tx.id),
        "provider": "ROBOKASSA",
        "amount_minor": int(tx.amount_minor or 0),
        "checkout_url": checkout_url,
        "test_mode": robo_cfg.test_mode,
        "checkout_expires_at": checkout_expires_at.isoformat() if checkout_expires_at else None,
    }


@router.get("/{venue_id}/billing/transactions/export")
def export_venue_billing_transactions(
    venue_id: int,
    fmt: str = Query(default="xlsx"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = _require_owner_or_admin_billing_access(db, venue_id=venue_id, user=user)
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    access = get_user_billing_access(db, venue_id=int(venue_id), user=user, membership_role=role)
    if str(access.get("billing_access_mode") or "").upper() not in {"FULL", "BILLING_READONLY"}:
        raise HTTPException(status_code=403, detail="Billing access denied")
    txs = list_billing_transactions(db, venue_id=int(venue_id), limit=500)
    rows = [
        {
            "created_at": tx.created_at,
            "venue_name": venue.name,
            "status": tx.status,
            "type": tx.type,
            "source": tx.source,
            "amount_major": int(tx.amount_minor or 0) / 100.0,
            "days_added": int(tx.days_added or 0) if tx.days_added is not None else None,
            "period_from": tx.period_from,
            "period_until": tx.period_until,
            "provider_invoice_id": tx.provider_invoice_id,
            "provider_payment_id": tx.provider_payment_id,
            "comment": tx.comment,
        }
        for tx in txs
    ]
    fmt_norm = str(fmt or "xlsx").lower().strip()
    if fmt_norm == "csv":
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(["created_at", "venue_name", "status", "type", "source", "amount_major", "days_added", "period_from", "period_until", "provider_invoice_id", "provider_payment_id", "comment"])
        for row in rows:
            writer.writerow([row.get("created_at"), row.get("venue_name"), row.get("status"), row.get("type"), row.get("source"), row.get("amount_major"), row.get("days_added"), row.get("period_from"), row.get("period_until"), row.get("provider_invoice_id"), row.get("provider_payment_id"), row.get("comment")])
        data = out.getvalue().encode("utf-8-sig")
        return StreamingResponse(BytesIO(data), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="billing_{int(venue_id)}.csv"'})
    xlsx = build_billing_transactions_xlsx(title=f"Axelio · Подписка · {venue.name}", rows=rows, filters=[("Заведение", venue.name)])
    return StreamingResponse(BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="billing_{int(venue_id)}.xlsx"'})


async def _extract_callback_params(request: Request) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        params[str(key)] = str(value)
    if request.method.upper() == "POST":
        form = await request.form()
        for key, value in form.multi_items():
            params[str(key)] = str(value)
    return params


def _frontend_payment_redirect(*, venue_id: int, invoice_id: str | None, payment_status: str, reason: str | None = None) -> str:
    base = f"{settings.frontend_base_url()}/app-venue.html"
    query = {
        "venue_id": str(int(venue_id)),
        "billing_payment": payment_status,
    }
    if invoice_id:
        query["billing_invoice_id"] = str(invoice_id)
    if reason:
        query["billing_reason"] = str(reason)
    return f"{base}?{urlencode(query)}"


@public_router.api_route("/billing/robokassa/result", methods=["GET", "POST"], response_class=PlainTextResponse)
async def robokassa_result(request: Request, db: Session = Depends(get_db)):
    params = await _extract_callback_params(request)
    invoice_id = str(params.get("InvId") or params.get("InvoiceID") or "").strip()
    out_sum = str(params.get("OutSum") or params.get("IncSum") or "").strip()
    signature = str(params.get("SignatureValue") or "").strip()
    if not invoice_id or not out_sum:
        raise HTTPException(status_code=400, detail="Missing callback params")

    tx = get_billing_transaction_by_invoice_id(db, invoice_id=invoice_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Billing transaction not found")

    extra_params = {k: v for k, v in params.items() if str(k).startswith("Shp_")}
    robo_cfg = get_robokassa_config()
    if not is_valid_result_signature(
        out_sum=out_sum,
        invoice_id=invoice_id,
        received_signature=signature,
        password2=robo_cfg.password2,
        algorithm=robo_cfg.hash_algorithm,
        extra_params=extra_params,
    ):
        mark_checkout_transaction_failed(
            db,
            transaction=tx,
            status="FAILED",
            provider_payload_json={"result_params": params, "invalid_signature": True},
            comment="Robokassa invalid result signature",
            event_type="ROBOKASSA_RESULT_SIGNATURE_INVALID",
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid signature")

    amount_minor = parse_amount_minor(out_sum)
    try:
        state, tx, event, applied = apply_checkout_payment_success(
            db,
            transaction=tx,
            provider_payment_id=str(params.get("OpKey") or params.get("PaymentMethod") or tx.provider_payment_id or invoice_id),
            provider_payload_json={"result_params": params},
            amount_minor=amount_minor,
        )
    except ValueError:
        mark_checkout_transaction_failed(
            db,
            transaction=tx,
            status="FAILED",
            provider_payload_json={"result_params": params, "amount_mismatch": True},
            comment="Robokassa amount mismatch",
            event_type="ROBOKASSA_AMOUNT_MISMATCH",
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Amount mismatch")
    if not applied:
        db.add(VenueBillingEvent(
            venue_id=int(tx.venue_id),
            event_type="ROBOKASSA_RESULT_DUPLICATE",
            old_status=None,
            new_status=None,
            meta_json={"transaction_id": int(tx.id), "invoice_id": invoice_id},
            created_by_user_id=tx.created_by_user_id,
            created_at=datetime.now(timezone.utc),
        ))
    db.commit()
    if applied:
        venue_name = db.execute(select(Venue.name).where(Venue.id == int(tx.venue_id))).scalar_one_or_none() or f"Заведение #{int(tx.venue_id)}"
        paid_until = state.paid_until.strftime("%d.%m.%Y") if state.paid_until else "—"
        send_owner_billing_notification_once(
            db,
            venue_id=int(tx.venue_id),
            notification_type="payment_success",
            event_key=str(tx.id),
            text=f"Оплата по заведению «{venue_name}» подтверждена. Доступ продлён до {paid_until}.",
            button_text="Открыть заведение",
        )
        db.commit()
    return PlainTextResponse(f"OK{invoice_id}")


@public_router.api_route("/billing/robokassa/success", methods=["GET", "POST"])
async def robokassa_success(request: Request, db: Session = Depends(get_db)):
    params = await _extract_callback_params(request)
    invoice_id = str(params.get("InvId") or params.get("InvoiceID") or "").strip()
    tx = get_billing_transaction_by_invoice_id(db, invoice_id=invoice_id) if invoice_id else None
    venue_id = int(tx.venue_id) if tx is not None else int(params.get("Shp_venueId") or 0)
    if venue_id <= 0:
        return RedirectResponse(url=f"{settings.frontend_base_url()}/app-venues.html?billing_payment=success", status_code=302)

    payment_status = "processing"
    robo_cfg = get_robokassa_config()
    if tx is not None:
        payment_status = "success" if str(tx.status or "").upper() == "SUCCEEDED" else "processing"
        out_sum = str(params.get("OutSum") or params.get("IncSum") or "").strip()
        signature = str(params.get("SignatureValue") or "").strip()
        extra_params = {k: v for k, v in params.items() if str(k).startswith("Shp_")}
        if out_sum and signature:
            if not is_valid_success_signature(
                out_sum=out_sum,
                invoice_id=invoice_id,
                received_signature=signature,
                password1=robo_cfg.password1,
                algorithm=robo_cfg.hash_algorithm,
                extra_params=extra_params,
            ):
                payment_status = "processing"
    return RedirectResponse(url=_frontend_payment_redirect(venue_id=venue_id, invoice_id=invoice_id, payment_status=payment_status), status_code=302)


@public_router.api_route("/billing/robokassa/fail", methods=["GET", "POST"])
async def robokassa_fail(request: Request, db: Session = Depends(get_db)):
    params = await _extract_callback_params(request)
    invoice_id = str(params.get("InvId") or params.get("InvoiceID") or "").strip()
    tx = get_billing_transaction_by_invoice_id(db, invoice_id=invoice_id) if invoice_id else None
    venue_id = int(tx.venue_id) if tx is not None else int(params.get("Shp_venueId") or 0)
    if tx is not None:
        mark_checkout_transaction_failed(
            db,
            transaction=tx,
            status="CANCELED",
            provider_payload_json={"fail_params": params},
            comment="Robokassa payment canceled by user",
            event_type="ROBOKASSA_PAYMENT_CANCELED",
        )
        db.commit()
    if venue_id <= 0:
        return RedirectResponse(url=f"{settings.frontend_base_url()}/app-venues.html?billing_payment=failed", status_code=302)
    return RedirectResponse(url=_frontend_payment_redirect(venue_id=venue_id, invoice_id=invoice_id, payment_status="failed"), status_code=302)
