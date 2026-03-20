from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import NotificationDeliveryLog


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
