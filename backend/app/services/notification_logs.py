from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import NotificationDeliveryLog


def normalize_notification_idempotency_key(value: str | None) -> str | None:
    key = str(value or "").strip()
    return key or None


def notification_dedupe_scope(user) -> str:
    """Stable recipient scope for notification dedupe.

    Prefer Telegram chat id because one real recipient can have several user rows
    after account linking/merge edge cases. Fall back to internal user id.
    """
    tg_user_id = getattr(user, "tg_user_id", None)
    if tg_user_id is not None:
        try:
            return f"tg:{int(tg_user_id)}"
        except Exception:
            return f"tg:{str(tg_user_id).strip()}"
    user_id = getattr(user, "id", None)
    return f"user:{int(user_id)}" if user_id is not None else "user:unknown"


def lock_notification_idempotency_key(db: Session, idempotency_key: str | None) -> None:
    """Serialize same-key notification sends inside PostgreSQL.

    The delivery log does not have a unique constraint in older databases, so this
    advisory lock closes the most common parallel timer / background task race.
    It is a no-op for non-PostgreSQL dialects.
    """
    key = normalize_notification_idempotency_key(idempotency_key)
    if not key:
        return
    bind = db.get_bind()
    dialect_name = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    if dialect_name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


def notification_delivery_exists(
    db: Session,
    *,
    idempotency_key: str | None,
    statuses: tuple[str, ...] | list[str] | set[str] = ("pending", "sent"),
) -> bool:
    key = normalize_notification_idempotency_key(idempotency_key)
    if not key:
        return False
    normalized_statuses = [str(s).strip().lower() for s in statuses if str(s).strip()]
    stmt = select(NotificationDeliveryLog.id).where(NotificationDeliveryLog.idempotency_key == key)
    if normalized_statuses:
        stmt = stmt.where(NotificationDeliveryLog.status.in_(normalized_statuses))
    return db.execute(stmt.limit(1)).scalar_one_or_none() is not None


def log_notification_attempt(
    db: Session,
    *,
    notification_type: str,
    status: str,
    user_id: int | None = None,
    venue_id: int | None = None,
    shift_id: int | None = None,
    shift_assignment_id: int | None = None,
    planned_at: datetime | None = None,
    sent_at: datetime | None = None,
    idempotency_key: str | None = None,
    error_text: str | None = None,
    payload_preview: str | None = None,
) -> NotificationDeliveryLog:
    entry = NotificationDeliveryLog(
        notification_type=(notification_type or "unknown").strip()[:64],
        status=(status or "unknown").strip()[:32],
        user_id=user_id,
        venue_id=venue_id,
        shift_id=shift_id,
        shift_assignment_id=shift_assignment_id,
        planned_at=planned_at,
        sent_at=sent_at,
        idempotency_key=(idempotency_key or None),
        error_text=(error_text or None),
        payload_preview=(payload_preview or None),
    )
    db.add(entry)
    return entry
