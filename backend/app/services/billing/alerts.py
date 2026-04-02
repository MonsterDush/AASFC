from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification_delivery_log import NotificationDeliveryLog
from app.models.user import User
from app.services import tg_notify
from app.services.notification_logs import log_notification_attempt


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def admin_billing_open_url(*, venue_id: int | None = None) -> str:
    base = f"{settings.frontend_base_url()}/admin-billing.html"
    if venue_id is None:
        return base
    return f"{base}?venue_id={int(venue_id)}"


def list_super_admin_notification_recipients(db: Session) -> list[User]:
    stmt = (
        select(User)
        .where(User.system_role == "SUPER_ADMIN")
        .order_by(User.id.asc())
    )
    recipients = list(db.execute(stmt).scalars().all())

    configured_ids = set(int(x) for x in settings.super_admin_ids())
    if not configured_ids:
        return recipients

    seen = {int(u.id) for u in recipients}
    extra = db.execute(
        select(User)
        .where(User.tg_user_id.in_(list(configured_ids)))
        .order_by(User.id.asc())
    ).scalars().all()
    for user in extra:
        if int(user.id) in seen:
            continue
        recipients.append(user)
        seen.add(int(user.id))
    return recipients


def _delivery_exists(db: Session, *, idempotency_key: str) -> bool:
    existing = db.execute(
        select(NotificationDeliveryLog.id).where(
            NotificationDeliveryLog.idempotency_key == str(idempotency_key),
            NotificationDeliveryLog.status == "sent",
        )
    ).scalar_one_or_none()
    return existing is not None


def send_super_admin_billing_alert_once(
    db: Session,
    *,
    notification_type: str,
    event_key: str,
    text: str,
    venue_id: int | None = None,
    button_text: str = "Открыть биллинг",
    users: Iterable[User] | None = None,
) -> int:
    recipients = list(users or list_super_admin_notification_recipients(db))
    if not recipients:
        return 0

    sent = 0
    open_url = admin_billing_open_url(venue_id=venue_id)
    now = _utc_now()

    for user in recipients:
        chat_id = getattr(user, "tg_user_id", None)
        if not chat_id:
            continue
        if not getattr(user, "notify_enabled", True):
            continue
        key = f"billing-admin-alert:{notification_type}:venue:{int(venue_id or 0)}:user:{int(user.id)}:{event_key}"
        if _delivery_exists(db, idempotency_key=key):
            continue
        entry = log_notification_attempt(
            db,
            notification_type=f"billing_admin_alert_{notification_type}",
            status="pending",
            user_id=int(user.id),
            venue_id=int(venue_id) if venue_id else None,
            planned_at=now,
            idempotency_key=key,
            payload_preview=str(text or "")[:1000],
        )
        db.flush()
        result = tg_notify.notify_result(chat_id=int(chat_id), text=text, url=open_url, button_text=button_text)
        entry.status = "sent" if result.get("ok") else "failed"
        entry.sent_at = _utc_now()
        if result.get("error"):
            entry.error_text = str(result.get("error"))[:500]
        sent += 1 if result.get("ok") else 0
    return sent
