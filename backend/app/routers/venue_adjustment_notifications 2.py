from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
import os
import json
import hashlib
from urllib.parse import quote
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status, UploadFile, File
from sqlalchemy import select, delete, update, func, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.db import SessionLocal, get_db
from app.services import tg_notify
from app.services.notification_logs import (
    log_notification_attempt,
    lock_notification_idempotency_key,
    notification_delivery_exists,
    notification_dedupe_scope,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.routers.venue_access import (
    _has_revenue_view_access,
    _is_active_member_or_admin,
    _is_owner_or_super_admin,
    _is_report_viewer,
    _require_active_member_or_admin,
    _require_owner_or_super_admin,
    _require_report_viewer,
    _require_revenue_viewer,
)
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.notification_job import NotificationJob
from app.models.adjustment import Adjustment
from app.models.adjustment_dispute import AdjustmentDispute
from app.models.adjustment_dispute_comment import AdjustmentDisputeComment
from app.auth.venue_permissions import require_venue_permission, has_venue_permission
from app.settings import settings

from app.routers.venue_common import (
    _NOTIFICATION_JOB_MAX_ATTEMPTS,
    _NOTIFICATION_JOB_RETRY_MINUTES,
    _NOTIFICATION_JOB_STALE_MINUTES,
    _NOTIFICATION_JOB_STATUS_FAILED,
    _NOTIFICATION_JOB_STATUS_PENDING,
    _NOTIFICATION_JOB_STATUS_PROCESSING,
    _NOTIFICATION_JOB_STATUS_SENT,
    _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
    _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
    _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
    _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
    _NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
    log,
)
from app.routers.venue_permissions import _has_adjustments_manage_access

from app.routers.venue_notification_common import (
    _adj_type_label,
    _build_owner_adjustments_link,
    _build_staff_adjustments_link,
    _collect_adjustment_manager_recipients,
    _deliver_user_notification,
    _display_user_name,
    _should_notify_user,
    _venue_name,
)


def _enqueue_adjustment_assigned_job(db: Session, *, venue_id: int, adjustment_id: int) -> NotificationJob:
    idempotency_key = f"job:adjustment_assigned:{int(adjustment_id)}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "adjustment_id": int(adjustment_id)}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _enqueue_adjustment_dispute_event_job(
    db: Session,
    *,
    venue_id: int,
    dispute_id: int,
    comment_id: int,
    event_kind: str,
) -> NotificationJob:
    normalized_kind = str(event_kind or "comment").strip().lower()
    if normalized_kind not in {"opened", "comment"}:
        normalized_kind = "comment"
    idempotency_key = f"job:adjustment_dispute_event:{int(comment_id)}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {
                "venue_id": int(venue_id),
                "dispute_id": int(dispute_id),
                "comment_id": int(comment_id),
                "event_kind": normalized_kind,
            },
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


def _send_adjustment_assigned_notification(db: Session, *, venue_id: int, adjustment_id: int) -> None:
    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == int(adjustment_id),
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None or not getattr(adj, "member_user_id", None):
        return

    recipient = db.execute(select(User).where(User.id == int(adj.member_user_id))).scalar_one_or_none()
    if recipient is None or not getattr(recipient, "tg_user_id", None):
        return
    if not _should_notify_user(recipient, "adjustments"):
        return

    venue_name = _venue_name(db, venue_id)
    label = _adj_type_label(adj.type)
    text = (
        f"{venue_name}: вам добавлен(а) {label} на {adj.date.isoformat()} "
        f"на сумму {adj.amount}. Причина: {(adj.reason or '—')}"
    )
    ok, retryable_error = _deliver_user_notification(
        db,
        notification_type="adjustment_assigned",
        recipient=recipient,
        venue_id=venue_id,
        idempotency_key=f"adjustment_assigned:{int(adj.id)}:{notification_dedupe_scope(recipient)}",
        text=text,
        url=_build_staff_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab=adj.type),
        button_text="Открыть",
    )
    if retryable_error and not ok:
        raise RuntimeError("adjustment assigned delivery failed with retryable error")


def _send_adjustment_dispute_event_notifications(
    db: Session,
    *,
    venue_id: int,
    dispute_id: int,
    comment_id: int,
    event_kind: str,
) -> None:
    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == int(dispute_id),
            AdjustmentDispute.venue_id == int(venue_id),
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        return

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == int(dis.adjustment_id),
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        return

    comment = db.execute(
        select(AdjustmentDisputeComment).where(
            AdjustmentDisputeComment.id == int(comment_id),
            AdjustmentDisputeComment.dispute_id == int(dis.id),
            AdjustmentDisputeComment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if comment is None:
        return

    author = db.execute(select(User).where(User.id == int(comment.author_user_id))).scalar_one_or_none()
    if author is None:
        return

    author_is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=author)
    recipients: list[User] = []
    if author_is_manager:
        if getattr(adj, "member_user_id", None):
            employee = db.execute(
                select(User).where(
                    User.id == int(adj.member_user_id),
                    User.tg_user_id.is_not(None),
                )
            ).scalar_one_or_none()
            if employee is not None:
                recipients.append(employee)
    else:
        recipients.extend(_collect_adjustment_manager_recipients(db, venue_id=venue_id))

    if not recipients:
        return

    venue_name = _venue_name(db, venue_id)
    who = _display_user_name(author)
    label = _adj_type_label(adj.type)
    prefix = "Новый спор" if str(event_kind or "comment").strip().lower() == "opened" else "Новый комментарий"
    message_text = (comment.message or dis.message or "—").strip() or "—"

    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    had_retryable_error = False
    delivered_any = False

    for recipient in recipients:
        if recipient is None or int(recipient.id) == int(author.id):
            continue
        if not getattr(recipient, "tg_user_id", None):
            continue
        if not _should_notify_user(recipient, "adjustments"):
            continue
        recipient_id = int(recipient.id)
        chat_id = int(recipient.tg_user_id)
        if recipient_id in seen_recipient_ids or chat_id in seen_tg_user_ids:
            continue

        recipient_is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=recipient)
        link = (
            _build_owner_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab="disputes")
            if recipient_is_manager
            else _build_staff_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab="disputes")
        )
        if prefix == "Новый спор":
            text = (
                f"{venue_name}: {prefix}. {who} оспорил {label} #{adj.id} на {adj.date.isoformat()} "
                f"(сумма {adj.amount}).\nКомментарий: {message_text}"
            )
        else:
            text = f"{venue_name}: новый комментарий в споре по {label} #{adj.id} от {who}.\n{message_text}"

        ok, retryable_error = _deliver_user_notification(
            db,
            notification_type="adjustment_dispute_event",
            recipient=recipient,
            venue_id=venue_id,
            idempotency_key=f"adjustment_dispute_event:{int(comment.id)}:{notification_dedupe_scope(recipient)}",
            text=text,
            url=link,
            button_text="Открыть спор",
        )
        delivered_any = delivered_any or ok
        had_retryable_error = had_retryable_error or retryable_error
        seen_recipient_ids.add(recipient_id)
        seen_tg_user_ids.add(chat_id)

    if had_retryable_error and not delivered_any:
        raise RuntimeError("adjustment dispute delivery failed with retryable error")
