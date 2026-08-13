from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.services import tg_notify
from app.services.notification_logs import (
    lock_notification_idempotency_key,
    log_notification_attempt,
    notification_delivery_exists,
    notification_dedupe_scope,
)


def billing_open_url(*, venue_id: int) -> str:
    return f"{settings.frontend_base_url()}/app-venue.html?venue_id={int(venue_id)}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def list_owner_notification_recipients(db: Session, *, venue_id: int) -> list[User]:
    stmt = (
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.venue_role == "OWNER",
            VenueMember.is_active.is_(True),
        )
        .order_by(User.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def venue_label(db: Session, *, venue_id: int) -> str:
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    return str(getattr(venue, "name", None) or f"Заведение #{int(venue_id)}")


def _delivery_exists(db: Session, *, idempotency_key: str) -> bool:
    return notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent"))


def send_owner_billing_notification_once(
    db: Session,
    *,
    venue_id: int,
    notification_type: str,
    event_key: str,
    text: str,
    button_text: str = "Открыть Axelio",
    users: Iterable[User] | None = None,
) -> int:
    recipients = list(users or list_owner_notification_recipients(db, venue_id=venue_id))
    if not recipients:
        return 0

    sent = 0
    open_url = billing_open_url(venue_id=venue_id)
    now = _utc_now()
    seen_scopes: set[str] = set()

    for user in recipients:
        if not getattr(user, "notify_enabled", True):
            continue
        chat_id = getattr(user, "tg_user_id", None)
        if not chat_id:
            continue

        dedupe_scope = notification_dedupe_scope(user)
        if dedupe_scope in seen_scopes:
            continue
        seen_scopes.add(dedupe_scope)

        key = f"billing:{notification_type}:venue:{int(venue_id)}:{dedupe_scope}:{event_key}"
        lock_notification_idempotency_key(db, key)
        if _delivery_exists(db, idempotency_key=key):
            continue

        entry = log_notification_attempt(
            db,
            notification_type=f"billing_{notification_type}",
            status="pending",
            user_id=int(user.id),
            venue_id=int(venue_id),
            planned_at=now,
            idempotency_key=key,
            payload_preview=str(text or "")[:1000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(chat_id=int(chat_id), text=text, url=open_url, button_text=button_text)
        entry.status = "sent" if result.get("ok") else "failed"
        entry.sent_at = _utc_now() if result.get("ok") else None
        if result.get("error"):
            entry.error_text = str(result.get("error"))[:500]
        db.add(entry)
        db.commit()
        sent += 1 if result.get("ok") else 0
    return sent
