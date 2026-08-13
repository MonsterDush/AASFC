from __future__ import annotations

from datetime import datetime, timezone, date
import os
from urllib.parse import quote
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services import tg_notify
from app.services.notification_logs import (
    log_notification_attempt,
    lock_notification_idempotency_key,
    notification_delivery_exists,
)
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.auth.venue_permissions import has_venue_permission
from app.settings import settings



class NotificationDeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = bool(retryable)


_ADJ_TYPE_LABELS = {
    "ru": {"penalty": "Штраф", "writeoff": "Списание", "bonus": "Премия", "tip": "Чаевые"},
    "en": {"penalty": "Penalty", "writeoff": "Write-off", "bonus": "Bonus", "tip": "Tips"},
}

def _ui_lang() -> str:
    # Minimal v1: default RU. Later we can store per-user language in DB and use it here.
    return (os.getenv("DEFAULT_UI_LANG") or "ru").lower()

def _adj_type_label(adj_type: str, lang: str | None = None) -> str:
    lt = (lang or _ui_lang() or "ru").lower()
    mp = _ADJ_TYPE_LABELS.get(lt) or _ADJ_TYPE_LABELS.get("ru", {})
    return mp.get(adj_type, adj_type)

def _venue_name(db: Session, venue_id: int) -> str:
    v = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    return (v.name if v else "Axelio")

def _should_notify_user(u: User, kind: str) -> bool:
    """Best-effort per-user notification gate.

    kind: 'adjustments' | 'shifts' | 'shift_comments' | 'day_economics' | 'salary' | 'soft_alerts'
    """
    if not u:
        return False
    if not getattr(u, "notify_enabled", True):
        return False
    if kind == "adjustments":
        return bool(getattr(u, "notify_adjustments", True))
    if kind == "shifts":
        return bool(getattr(u, "notify_shifts", True))
    if kind == "shift_comments":
        return bool(getattr(u, "notify_shift_comments", True))
    if kind == "day_economics":
        return bool(getattr(u, "notify_day_economics", True))
    if kind == "salary":
        return bool(getattr(u, "notify_salary", True))
    if kind == "soft_alerts":
        return bool(getattr(u, "notify_soft_alerts", True))
    return True



def _frontend_base_url() -> str:
    return settings.frontend_base_url()


def _notification_shift_slot_query(shift_slot: str | None) -> str:
    slot = str(shift_slot or "TOTAL").strip().upper()
    return f"&shift_slot={quote(slot)}" if slot in {"DAY", "NIGHT"} else ""


def _build_owner_day_economics_link(
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> str:
    slot_query = _notification_shift_slot_query(shift_slot)
    return (
        f"{_frontend_base_url()}/owner-day-economics.html?venue_id={int(venue_id)}"
        f"&date={quote(target_date.isoformat())}{slot_query}"
    )


def _build_staff_salary_day_link(
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> str:
    month_value = target_date.strftime("%Y-%m")
    slot_query = _notification_shift_slot_query(shift_slot)
    return (
        f"{_frontend_base_url()}/staff-salary.html?venue_id={int(venue_id)}"
        f"&month={quote(month_value)}&date={quote(target_date.isoformat())}"
        f"&open_day=1{slot_query}"
    )


def _build_staff_adjustments_link(*, venue_id: int, adjustment_id: int, tab: str | None = None) -> str:
    suffix = f"&tab={quote(str(tab))}" if tab else ""
    return f"{_frontend_base_url()}/staff-adjustments.html?venue_id={int(venue_id)}&open={int(adjustment_id)}{suffix}"


def _build_owner_adjustments_link(*, venue_id: int, adjustment_id: int, tab: str | None = None) -> str:
    suffix = f"&tab={quote(str(tab))}" if tab else ""
    return f"{_frontend_base_url()}/app-adjustments.html?venue_id={int(venue_id)}&open={int(adjustment_id)}{suffix}"


def _display_user_name(user: User | None) -> str:
    if user is None:
        return "Сотрудник"
    return (user.short_name or user.full_name or (user.tg_username or str(user.id))).strip()


def _collect_adjustment_manager_recipients(db: Session, *, venue_id: int) -> list[User]:
    owners = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
            VenueMember.venue_role == "OWNER",
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).scalars().all()

    mgr_rows = db.execute(
        select(User)
        .join(VenuePosition, VenuePosition.member_user_id == User.id)
        .where(
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.is_active.is_(True),
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).scalars().all()

    uniq: dict[int, User] = {int(u.id): u for u in owners if getattr(u, "tg_user_id", None) is not None}
    for candidate in mgr_rows:
        if getattr(candidate, "tg_user_id", None) is None:
            continue
        if has_venue_permission(db, venue_id=venue_id, user=candidate, permission_code="ADJUSTMENTS_MANAGE"):
            uniq.setdefault(int(candidate.id), candidate)
    return list(uniq.values())


def _deliver_user_notification(
    db: Session,
    *,
    notification_type: str,
    recipient: User,
    venue_id: int,
    idempotency_key: str,
    text: str,
    url: str | None = None,
    button_text: str | None = None,
    shift_id: int | None = None,
    shift_assignment_id: int | None = None,
) -> tuple[bool, bool]:
    lock_notification_idempotency_key(db, idempotency_key)
    if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
        return True, False

    planned_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    pending_log = log_notification_attempt(
        db,
        notification_type=notification_type,
        status="pending",
        user_id=int(recipient.id),
        venue_id=int(venue_id),
        shift_id=int(shift_id) if shift_id is not None else None,
        shift_assignment_id=int(shift_assignment_id) if shift_assignment_id is not None else None,
        planned_at=planned_at,
        idempotency_key=idempotency_key,
        payload_preview=text[:2000],
    )
    db.flush()
    db.commit()

    result = tg_notify.notify_result(
        chat_id=int(recipient.tg_user_id),
        text=text,
        url=url,
        button_text=button_text,
    )
    ok = bool(result.get("ok"))
    retryable = bool(result.get("retryable"))
    try:
        pending_log.status = "sent" if ok else "failed"
        pending_log.sent_at = datetime.utcnow().replace(tzinfo=timezone.utc) if ok else None
        pending_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
        db.add(pending_log)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ok, (retryable and not ok)
