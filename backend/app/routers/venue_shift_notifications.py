from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification_job import NotificationJob
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.shift_comment import ShiftComment
from app.models.shift_comment_mention import ShiftCommentMention
from app.models.shift_interval import ShiftInterval
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.routers.venue_common import (
    _NOTIFICATION_JOB_MAX_ATTEMPTS,
    _NOTIFICATION_JOB_STATUS_PENDING,
    _NOTIFICATION_JOB_STATUS_PROCESSING,
    _NOTIFICATION_JOB_STATUS_SENT,
    _NOTIFICATION_JOB_TYPE_SHIFT_COMMENT,
)
from app.routers.venue_notification_common import (
    NotificationDeliveryError,
    _deliver_user_notification,
    _display_user_name,
    _frontend_base_url,
    _should_notify_user,
)
from app.routers.venue_permissions import _is_shift_comments_allowed
from app.services.notification_logs import notification_dedupe_scope
from app.services.shifts.slots import normalize_shift_slot


_RU_MONTHS_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _enqueue_shift_comment_job(db: Session, *, venue_id: int, comment_id: int) -> NotificationJob:
    idempotency_key = f"job:shift_comment:{int(comment_id)}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SHIFT_COMMENT,
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
        job_type=_NOTIFICATION_JOB_TYPE_SHIFT_COMMENT,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {"venue_id": int(venue_id), "comment_id": int(comment_id)},
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


def _comment_preview(value: str | None, limit: int = 300) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _shift_comment_link(*, venue_id: int, shift: Shift, comment_id: int) -> str:
    month_value = shift.date.strftime("%Y-%m")
    shift_slot = normalize_shift_slot(getattr(shift, "shift_slot", None))
    return (
        f"{_frontend_base_url()}/staff-shifts.html?venue_id={int(venue_id)}"
        f"&month={quote(month_value)}&date={quote(shift.date.isoformat())}"
        f"&shift_slot={quote(shift_slot)}"
        f"&open_shift={int(shift.id)}&comment={int(comment_id)}"
    )


def _shift_date_label(shift: Shift, interval: ShiftInterval) -> str:
    month = _RU_MONTHS_GENITIVE.get(int(shift.date.month), str(shift.date.month))
    start_time = interval.start_time.strftime("%H:%M")
    slot_label = "Ночь" if normalize_shift_slot(getattr(shift, "shift_slot", None)) == "NIGHT" else "День"
    return f"{shift.date.day} {month} · {slot_label} · {start_time}"


def _send_shift_comment_notifications(db: Session, *, venue_id: int, comment_id: int) -> None:
    row = db.execute(
        select(ShiftComment, Shift, ShiftInterval, Venue, User)
        .join(Shift, Shift.id == ShiftComment.shift_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .join(Venue, Venue.id == Shift.venue_id)
        .join(User, User.id == ShiftComment.author_user_id)
        .where(
            ShiftComment.id == int(comment_id),
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
        )
    ).first()
    if row is None:
        return

    comment, shift, interval, venue, author = row
    recipients: dict[int, dict] = {}

    assignment_rows = db.execute(
        select(ShiftAssignment, User)
        .join(User, User.id == ShiftAssignment.member_user_id)
        .where(ShiftAssignment.shift_id == int(shift.id))
        .order_by(ShiftAssignment.id.asc())
    ).all()
    for assignment, recipient in assignment_rows:
        entry = recipients.setdefault(
            int(recipient.id),
            {"user": recipient, "reasons": set(), "assignment_id": int(assignment.id)},
        )
        entry["reasons"].add("assigned")
        if entry.get("assignment_id") is None:
            entry["assignment_id"] = int(assignment.id)

    mention_rows = db.execute(
        select(ShiftCommentMention, User)
        .join(User, User.id == ShiftCommentMention.mentioned_user_id)
        .join(
            VenueMember,
            (VenueMember.user_id == User.id)
            & (VenueMember.venue_id == int(venue_id))
            & VenueMember.is_active.is_(True),
        )
        .where(ShiftCommentMention.comment_id == int(comment.id))
        .order_by(ShiftCommentMention.id.asc())
    ).all()
    for _, recipient in mention_rows:
        entry = recipients.setdefault(
            int(recipient.id),
            {"user": recipient, "reasons": set(), "assignment_id": None},
        )
        entry["reasons"].add("mention")

    if comment.parent_comment_id is not None:
        reply_recipient = db.execute(
            select(User)
            .join(ShiftComment, ShiftComment.author_user_id == User.id)
            .where(
                ShiftComment.id == int(comment.parent_comment_id),
                ShiftComment.shift_id == int(shift.id),
            )
        ).scalar_one_or_none()
        if reply_recipient is not None and _is_shift_comments_allowed(
            db,
            venue_id=venue_id,
            shift_id=int(shift.id),
            user=reply_recipient,
        ):
            entry = recipients.setdefault(
                int(reply_recipient.id),
                {"user": reply_recipient, "reasons": set(), "assignment_id": None},
            )
            entry["reasons"].add("reply")

    recipients.pop(int(author.id), None)
    if not recipients:
        return

    author_name = _display_user_name(author)
    date_label = _shift_date_label(shift, interval)
    comment_text = _comment_preview(comment.text)
    link = _shift_comment_link(venue_id=venue_id, shift=shift, comment_id=int(comment.id))
    seen_chat_ids: set[int] = set()
    had_failure = False
    had_retryable_error = False

    for item in recipients.values():
        recipient: User = item["user"]
        if not getattr(recipient, "tg_user_id", None):
            continue
        if not _should_notify_user(recipient, "shift_comments"):
            continue
        chat_id = int(recipient.tg_user_id)
        if chat_id in seen_chat_ids:
            continue
        seen_chat_ids.add(chat_id)

        reasons = item["reasons"]
        if "reply" in reasons and "mention" in reasons:
            title = "Вас упомянули в ответе к смене"
        elif "reply" in reasons:
            title = "Вам ответили в комментариях к смене"
        elif "mention" in reasons:
            title = "Вас упомянули в комментарии к смене"
        else:
            title = "Новый комментарий к вашей смене"
        text = f"{title} в «{venue.name}»\n{date_label}\nОт: {author_name}\n\n{comment_text}"

        ok, retryable_error = _deliver_user_notification(
            db,
            notification_type="shift_comment",
            recipient=recipient,
            venue_id=venue_id,
            idempotency_key=f"shift_comment:{int(comment.id)}:{notification_dedupe_scope(recipient)}",
            text=text,
            url=link,
            button_text="Открыть комментарий",
            shift_id=int(shift.id),
            shift_assignment_id=item.get("assignment_id"),
        )
        had_failure = had_failure or not ok
        had_retryable_error = had_retryable_error or retryable_error

    if had_failure:
        raise NotificationDeliveryError(
            "shift comment delivery failed",
            retryable=had_retryable_error,
        )
