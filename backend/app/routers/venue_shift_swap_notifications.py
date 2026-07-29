from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.notification_job import NotificationJob
from app.models.shift import Shift
from app.models.shift_interval import ShiftInterval
from app.models.shift_swap_request import ShiftSwapRequest
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.routers.venue_common import (
    _NOTIFICATION_JOB_MAX_ATTEMPTS,
    _NOTIFICATION_JOB_STATUS_PENDING,
    _NOTIFICATION_JOB_STATUS_PROCESSING,
    _NOTIFICATION_JOB_STATUS_SENT,
    _NOTIFICATION_JOB_TYPE_SHIFT_SWAP,
)
from app.routers.venue_notification_common import (
    NotificationDeliveryError,
    _deliver_user_notification,
    _display_user_name,
    _frontend_base_url,
    _should_notify_user,
)
from app.routers.venue_permissions import _is_schedule_editor
from app.services.notification_logs import notification_dedupe_scope
from app.services.shifts.slots import normalize_shift_slot


def _enqueue_shift_swap_job(
    db: Session,
    *,
    request_id: int,
    event_kind: str,
) -> NotificationJob:
    normalized_event = str(event_kind or "").strip().lower()
    idempotency_key = f"job:shift_swap:{int(request_id)}:{normalized_event}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SHIFT_SWAP,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_(
                [
                    _NOTIFICATION_JOB_STATUS_PENDING,
                    _NOTIFICATION_JOB_STATUS_PROCESSING,
                    _NOTIFICATION_JOB_STATUS_SENT,
                ]
            ),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SHIFT_SWAP,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {"request_id": int(request_id), "event_kind": normalized_event},
            ensure_ascii=False,
        ),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _shift_swap_link(*, venue_id: int, shift: Shift) -> str:
    return (
        f"{_frontend_base_url()}/staff-shifts.html?venue_id={int(venue_id)}"
        f"&month={quote(shift.date.strftime('%Y-%m'))}"
        f"&date={quote(shift.date.isoformat())}"
        f"&shift_slot={quote(normalize_shift_slot(shift.shift_slot))}"
        f"&open_shift={int(shift.id)}"
    )


def _shift_label(shift: Shift, interval: ShiftInterval) -> str:
    slot = "Ночь" if normalize_shift_slot(shift.shift_slot) == "NIGHT" else "День"
    start = interval.start_time.strftime("%H:%M")
    end = interval.end_time.strftime("%H:%M")
    return f"{shift.date.strftime('%d.%m.%Y')} · {slot} · {start}–{end}"


def _manager_recipients(db: Session, *, venue_id: int) -> list[User]:
    members = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
        )
        .order_by(User.id.asc())
    ).scalars().all()
    return [
        candidate
        for candidate in members
        if getattr(candidate, "tg_user_id", None)
        and _is_schedule_editor(db, venue_id=venue_id, user=candidate)
    ]


def _send_shift_swap_notifications(
    db: Session,
    *,
    request_id: int,
    event_kind: str,
) -> None:
    replacement_alias = aliased(User)
    row = db.execute(
        select(ShiftSwapRequest, Shift, ShiftInterval, Venue, User, replacement_alias)
        .join(Shift, Shift.id == ShiftSwapRequest.shift_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .join(Venue, Venue.id == ShiftSwapRequest.venue_id)
        .join(User, User.id == ShiftSwapRequest.requester_user_id)
        .outerjoin(replacement_alias, replacement_alias.id == ShiftSwapRequest.replacement_user_id)
        .where(ShiftSwapRequest.id == int(request_id))
    ).first()
    if row is None:
        return
    request, shift, interval, venue, requester, replacement = row
    event = str(event_kind or "").strip().lower()
    requester_name = _display_user_name(requester)
    replacement_name = _display_user_name(replacement) if replacement is not None else "не выбрана"
    shift_label = _shift_label(shift, interval)
    link = _shift_swap_link(venue_id=int(venue.id), shift=shift)

    recipients: dict[int, tuple[User, str, str]] = {}
    if event in {"created", "cancelled"}:
        title = (
            "Новый запрос на обмен сменой"
            if event == "created"
            else "Запрос на обмен сменой отменён"
        )
        for manager in _manager_recipients(db, venue_id=int(venue.id)):
            if int(manager.id) == int(requester.id):
                continue
            text = (
                f"{title}\n"
                f"Заведение: {venue.name}\n"
                f"Сотрудник: {requester_name}\n"
                f"Смена: {shift_label}\n"
                f"Предложенная замена: {replacement_name}"
            )
            recipients[int(manager.id)] = (manager, text, "Открыть запрос")
    elif event in {"approved", "rejected"}:
        approved = event == "approved"
        title = "Обмен сменой подтверждён" if approved else "Обмен сменой отклонён"
        manager_note = str(request.manager_comment or "").strip()
        requester_text = (
            f"{title}\n"
            f"Заведение: {venue.name}\n"
            f"Смена: {shift_label}\n"
            f"Замена: {replacement_name}"
        )
        if manager_note:
            requester_text += f"\nКомментарий: {manager_note}"
        recipients[int(requester.id)] = (requester, requester_text, "Открыть график")
        if approved and replacement is not None:
            replacement_text = (
                f"Вам передали смену\n"
                f"Заведение: {venue.name}\n"
                f"Смена: {shift_label}\n"
                f"От сотрудника: {requester_name}"
            )
            recipients[int(replacement.id)] = (
                replacement,
                replacement_text,
                "Открыть график",
            )
    else:
        return

    had_failure = False
    had_retryable_error = False
    for recipient, text, button_text in recipients.values():
        if not getattr(recipient, "tg_user_id", None) or not _should_notify_user(recipient, "shifts"):
            continue
        dedupe_scope = notification_dedupe_scope(recipient)
        ok, retryable = _deliver_user_notification(
            db,
            notification_type=f"shift_swap_{event}",
            recipient=recipient,
            venue_id=int(venue.id),
            shift_id=int(shift.id),
            shift_assignment_id=int(request.assignment_id) if request.assignment_id is not None else None,
            idempotency_key=f"shift_swap:{int(request.id)}:{event}:{dedupe_scope}",
            text=text,
            url=link,
            button_text=button_text,
        )
        if not ok:
            had_failure = True
            had_retryable_error = had_retryable_error or retryable
    if had_failure:
        raise NotificationDeliveryError(
            "One or more shift swap notifications failed",
            retryable=had_retryable_error,
        )
