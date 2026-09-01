from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any, Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.venue_permissions import has_venue_permission
from app.core.i18n import localized, user_locale
from app.models.notification_delivery_log import NotificationDeliveryLog
from app.models.notification_job import NotificationJob
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.services import tg_notify
from app.services.notification_logs import (
    lock_notification_idempotency_key,
    log_notification_attempt,
    notification_delivery_exists,
)
from app.services.integrations.quickresto_redaction import (
    redact_quickresto_correlation_id,
    redact_quickresto_technical_summary,
)
from app.settings import settings


QUICKRESTO_IMPORT_JOB_TYPE = "quickresto_import"

_JOB_STATUS_PENDING = "pending"
_KNOWN_IMPORT_STATUSES = frozenset({"SUCCEEDED", "PARTIAL", "FAILED"})
_KNOWN_REPORT_IMPORT_MODES = frozenset({"DRAFT", "CLOSED"})
_MAX_COUNT = 1_000_000_000
_MAX_JOB_ATTEMPTS = max(int(os.getenv("NOTIFICATION_JOB_MAX_ATTEMPTS", "5") or 5), 1)
_DELIVERY_PENDING_LEASE = timedelta(minutes=10)


class QuickRestoNotificationDeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = bool(retryable)


class QuickRestoNotificationPayloadError(ValueError):
    retryable = False


@dataclass(frozen=True)
class _AdminRecipient:
    chat_id: int
    user: User | None = None

    @property
    def locale(self) -> str:
        return user_locale(self.user) if self.user is not None else "ru"

    @property
    def user_id(self) -> int | None:
        return int(self.user.id) if self.user is not None else None


def _non_negative_count(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(max(number, 0), _MAX_COUNT)


def _required_positive_id(value: Any, *, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise QuickRestoNotificationPayloadError(f"QuickResto notification {field} is invalid") from exc
    if number <= 0:
        raise QuickRestoNotificationPayloadError(f"QuickResto notification {field} is invalid")
    return number


def _normalized_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    return status if status in _KNOWN_IMPORT_STATUSES else "UNKNOWN"


def _normalized_report_import_mode(value: Any) -> str:
    mode = str(value or "").strip().upper()
    return mode if mode in _KNOWN_REPORT_IMPORT_MODES else "UNKNOWN"


def _safe_payload(
    *,
    venue_id: Any,
    connection_id: Any,
    run_id: Any,
    status: Any,
    shifts_seen: Any = 0,
    shifts_imported: Any = 0,
    reports_created: Any = 0,
    reports_updated: Any = 0,
    reports_unchanged: Any = 0,
    issue_count: Any = 0,
    report_import_mode: Any = "CLOSED",
    technical_summary: Any = None,
    correlation_id: Any = None,
) -> dict[str, Any]:
    return {
        "venue_id": _required_positive_id(venue_id, field="venue_id"),
        "connection_id": _required_positive_id(connection_id, field="connection_id"),
        "run_id": _required_positive_id(run_id, field="run_id"),
        "status": _normalized_status(status),
        "shifts_seen": _non_negative_count(shifts_seen),
        "shifts_imported": _non_negative_count(shifts_imported),
        "reports_created": _non_negative_count(reports_created),
        "reports_updated": _non_negative_count(reports_updated),
        "reports_unchanged": _non_negative_count(reports_unchanged),
        "issue_count": _non_negative_count(issue_count),
        "report_import_mode": _normalized_report_import_mode(report_import_mode),
        "technical_summary": redact_quickresto_technical_summary(technical_summary),
        "correlation_id": redact_quickresto_correlation_id(correlation_id),
    }


def _safe_payload_from_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _safe_payload(
        venue_id=payload.get("venue_id"),
        connection_id=payload.get("connection_id"),
        run_id=payload.get("run_id"),
        status=payload.get("status"),
        shifts_seen=payload.get("shifts_seen"),
        shifts_imported=payload.get("shifts_imported"),
        reports_created=payload.get("reports_created"),
        reports_updated=payload.get("reports_updated"),
        reports_unchanged=payload.get("reports_unchanged"),
        issue_count=payload.get("issue_count"),
        report_import_mode=payload.get("report_import_mode"),
        technical_summary=payload.get("technical_summary"),
        correlation_id=payload.get("correlation_id"),
    )


def enqueue_quickresto_import_notification(
    db: Session,
    *,
    venue_id: int,
    connection_id: int,
    run_id: int,
    status: str,
    shifts_seen: int = 0,
    shifts_imported: int = 0,
    reports_created: int = 0,
    reports_updated: int = 0,
    reports_unchanged: int = 0,
    issue_count: int = 0,
    report_import_mode: str = "CLOSED",
    technical_summary: str | None = None,
    correlation_id: str | None = None,
) -> NotificationJob:
    """Enqueue exactly one aggregate notification job for a completed sync run."""

    payload = _safe_payload(
        venue_id=venue_id,
        connection_id=connection_id,
        run_id=run_id,
        status=status,
        shifts_seen=shifts_seen,
        shifts_imported=shifts_imported,
        reports_created=reports_created,
        reports_updated=reports_updated,
        reports_unchanged=reports_unchanged,
        issue_count=issue_count,
        report_import_mode=report_import_mode,
        technical_summary=technical_summary,
        correlation_id=correlation_id,
    )
    idempotency_key = f"job:{QUICKRESTO_IMPORT_JOB_TYPE}:run:{int(payload['run_id'])}"
    lock_notification_idempotency_key(db, idempotency_key)
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == QUICKRESTO_IMPORT_JOB_TYPE,
            NotificationJob.idempotency_key == idempotency_key,
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=QUICKRESTO_IMPORT_JOB_TYPE,
        status=_JOB_STATUS_PENDING,
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        attempts=0,
        max_attempts=_MAX_JOB_ATTEMPTS,
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _venue_name(db: Session, *, venue_id: int) -> str:
    value = db.execute(select(Venue.name).where(Venue.id == int(venue_id))).scalar_one_or_none()
    return str(value or f"Заведение #{int(venue_id)}")


def _frontend_base_url() -> str:
    return settings.frontend_base_url()


def _configured_super_admin_ids() -> set[int]:
    return {int(value) for value in settings.super_admin_ids()}


def _integration_open_url(*, venue_id: int, show_issues: bool = True) -> str:
    if show_issues:
        return f"{_frontend_base_url()}/owner-integration-issues.html?venue_id={int(venue_id)}&provider=quickresto"
    return f"{_frontend_base_url()}/owner-quickresto.html?venue_id={int(venue_id)}"


def _business_recipients(db: Session, *, venue_id: int) -> list[User]:
    rows = db.execute(
        select(User, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).all()

    recipients: list[User] = []
    seen_chat_ids: set[int] = set()
    for row in rows:
        user = row[0]
        venue_role = str(row[1] or "").strip().upper()
        if not getattr(user, "notify_enabled", True) or not getattr(user, "notify_integrations", True):
            continue
        chat_id = int(user.tg_user_id)
        if chat_id in seen_chat_ids:
            continue
        allowed = venue_role == "OWNER" or has_venue_permission(
            db,
            venue_id=int(venue_id),
            user=user,
            permission_code="INTEGRATIONS_MANAGE",
        )
        if not allowed:
            continue
        recipients.append(user)
        seen_chat_ids.add(chat_id)
    return recipients


def _admin_recipients(db: Session) -> list[_AdminRecipient]:
    configured_ids = _configured_super_admin_ids()
    filters = [User.system_role == "SUPER_ADMIN"]
    if configured_ids:
        filters.append(User.tg_user_id.in_(sorted(configured_ids)))
    users = (
        db.execute(select(User).where(or_(*filters), User.tg_user_id.is_not(None)).order_by(User.id.asc()))
        .scalars()
        .all()
    )

    recipients: list[_AdminRecipient] = []
    known_user_chat_ids: set[int] = set()
    delivered_chat_ids: set[int] = set()
    for user in users:
        chat_id = int(user.tg_user_id)
        known_user_chat_ids.add(chat_id)
        if not getattr(user, "notify_enabled", True) or not getattr(user, "notify_integrations", True):
            continue
        if chat_id in delivered_chat_ids:
            continue
        recipients.append(_AdminRecipient(chat_id=chat_id, user=user))
        delivered_chat_ids.add(chat_id)

    for chat_id in sorted(configured_ids - known_user_chat_ids):
        recipients.append(_AdminRecipient(chat_id=int(chat_id)))
    return recipients


def build_quickresto_import_text(
    *,
    venue_name: str,
    payload: Mapping[str, Any],
    locale: str = "ru",
) -> str:
    safe = _safe_payload_from_mapping(payload)
    status = safe["status"]
    if locale == "en":
        heading = {
            "SUCCEEDED": "✅ QuickResto import completed",
            "PARTIAL": "⚠️ QuickResto import completed with issues",
            "FAILED": "❌ QuickResto import failed",
        }.get(status, "ℹ️ QuickResto import result")
        mode = {"DRAFT": "Draft", "CLOSED": "Closed"}.get(safe["report_import_mode"], "Unknown")
        lines = [
            heading,
            f"Venue: {venue_name}",
            f"Shifts: {safe['shifts_seen']} found · {safe['shifts_imported']} imported",
            (
                f"Reports: {safe['reports_created']} created · {safe['reports_updated']} updated · "
                f"{safe['reports_unchanged']} unchanged"
            ),
            f"Issues: {safe['issue_count']}",
            f"Report mode: {mode}",
        ]
        if safe["issue_count"] or status in {"PARTIAL", "FAILED"}:
            lines.append("Open the integration to review and resolve the issues.")
        return "\n".join(lines)

    heading = {
        "SUCCEEDED": "✅ Импорт QuickResto завершён",
        "PARTIAL": "⚠️ Импорт QuickResto завершён с замечаниями",
        "FAILED": "❌ Импорт QuickResto не завершён",
    }.get(status, "ℹ️ Результат импорта QuickResto")
    mode = {"DRAFT": "Черновики", "CLOSED": "Закрытые"}.get(safe["report_import_mode"], "Неизвестно")
    lines = [
        heading,
        f"Заведение: {venue_name}",
        f"Смены: найдено {safe['shifts_seen']} · импортировано {safe['shifts_imported']}",
        (
            f"Отчёты: создано {safe['reports_created']} · обновлено {safe['reports_updated']} · "
            f"без изменений {safe['reports_unchanged']}"
        ),
        f"Проблемы: {safe['issue_count']}",
        f"Режим отчётов: {mode}",
    ]
    if safe["issue_count"] or status in {"PARTIAL", "FAILED"}:
        lines.append("Откройте интеграцию, чтобы проверить и решить проблемы.")
    return "\n".join(lines)


def build_quickresto_admin_text(*, payload: Mapping[str, Any], locale: str = "ru") -> str:
    safe = _safe_payload_from_mapping(payload)
    if locale == "en":
        lines = [
            f"🛠 QuickResto import · {safe['status']}",
            f"Run ID: {safe['run_id']}",
            f"Connection ID: {safe['connection_id']}",
            f"Issues: {safe['issue_count']}",
            f"Reason: {safe['technical_summary'] or 'not provided'}",
            f"Correlation ID: {safe['correlation_id'] or 'not provided'}",
        ]
    else:
        lines = [
            f"🛠 Импорт QuickResto · {safe['status']}",
            f"Run ID: {safe['run_id']}",
            f"Connection ID: {safe['connection_id']}",
            f"Проблемы: {safe['issue_count']}",
            f"Причина: {safe['technical_summary'] or 'не указана'}",
            f"Correlation ID: {safe['correlation_id'] or 'не указан'}",
        ]
    return "\n".join(lines)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _pending_delivery(db: Session, *, idempotency_key: str) -> NotificationDeliveryLog | None:
    return (
        db.execute(
            select(NotificationDeliveryLog)
            .where(
                NotificationDeliveryLog.idempotency_key == idempotency_key,
                NotificationDeliveryLog.status == "pending",
            )
            .order_by(NotificationDeliveryLog.id.desc())
            .with_for_update()
        )
        .scalars()
        .first()
    )


def _pending_delivery_is_fresh(entry: NotificationDeliveryLog, *, now: datetime) -> bool:
    planned_at = entry.planned_at
    return planned_at is not None and _as_utc(planned_at) > now - _DELIVERY_PENDING_LEASE


def _deliver_once(
    db: Session,
    *,
    recipient_kind: str,
    chat_id: int,
    user_id: int | None,
    venue_id: int,
    run_id: int,
    text: str,
    url: str,
    button_text: str,
) -> tuple[bool, bool, bool]:
    """Return ``(sent, failed, retryable_failure)``.

    A completed delivery is a successful no-op. A fresh pending lease blocks a
    concurrent sender but remains retryable so a worker crash cannot silently
    turn an unsent notification into a completed job.
    """

    idempotency_key = f"{QUICKRESTO_IMPORT_JOB_TYPE}:{recipient_kind}:run:{int(run_id)}:tg:{int(chat_id)}"
    lock_notification_idempotency_key(db, idempotency_key)
    if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("sent",)):
        return False, False, False

    planned_at = datetime.now(timezone.utc)
    entry = _pending_delivery(db, idempotency_key=idempotency_key)
    if entry is not None and _pending_delivery_is_fresh(entry, now=planned_at):
        # Another worker may still be between the durable claim and Telegram.
        # Keep this job retryable: a later attempt becomes a sent no-op or
        # reclaims the claim after the lease expires.
        return False, True, True
    if entry is None:
        entry = log_notification_attempt(
            db,
            notification_type=f"{QUICKRESTO_IMPORT_JOB_TYPE}_{recipient_kind}",
            status="pending",
            user_id=int(user_id) if user_id is not None else None,
            venue_id=int(venue_id),
            planned_at=planned_at,
            idempotency_key=idempotency_key,
            payload_preview=str(text or "")[:1000],
        )
    else:
        entry.notification_type = f"{QUICKRESTO_IMPORT_JOB_TYPE}_{recipient_kind}"
        entry.status = "pending"
        entry.user_id = int(user_id) if user_id is not None else None
        entry.venue_id = int(venue_id)
        entry.planned_at = planned_at
        entry.sent_at = None
        entry.error_text = None
        entry.payload_preview = str(text or "")[:1000]
        db.add(entry)
    db.flush()
    db.commit()

    try:
        result = tg_notify.notify_result(
            chat_id=int(chat_id),
            text=text,
            url=url,
            button_text=button_text,
        )
    except Exception as exc:  # transport normally never raises, but the queue must still be retryable
        result = {"ok": False, "retryable": True, "error": str(exc)}

    ok = bool(result.get("ok"))
    retryable = bool(result.get("retryable")) and not ok
    entry.status = "sent" if ok else "failed"
    entry.sent_at = datetime.now(timezone.utc) if ok else None
    entry.error_text = (
        None if ok else redact_quickresto_technical_summary(result.get("error") or "Telegram delivery failed")
    )
    db.add(entry)
    db.commit()
    return ok, not ok, retryable


def send_quickresto_import_notifications(db: Session, *, payload: Mapping[str, Any]) -> dict[str, int]:
    """Deliver one localized aggregate result plus a separate safe admin diagnostic."""

    safe = _safe_payload_from_mapping(payload)
    venue_id = int(safe["venue_id"])
    run_id = int(safe["run_id"])
    venue_name = _venue_name(db, venue_id=venue_id)
    open_url = _integration_open_url(
        venue_id=venue_id,
        show_issues=bool(safe["issue_count"] or safe["status"] in {"PARTIAL", "FAILED"}),
    )

    sent_business = 0
    sent_admin = 0
    had_failure = False
    had_retryable_failure = False

    for recipient in _business_recipients(db, venue_id=venue_id):
        locale = user_locale(recipient)
        sent, failed, retryable = _deliver_once(
            db,
            recipient_kind="business",
            chat_id=int(recipient.tg_user_id),
            user_id=int(recipient.id),
            venue_id=venue_id,
            run_id=run_id,
            text=build_quickresto_import_text(venue_name=venue_name, payload=safe, locale=locale),
            url=open_url,
            button_text=localized(locale, ru="Открыть интеграцию", en="Open integration"),
        )
        sent_business += int(sent)
        had_failure = had_failure or failed
        had_retryable_failure = had_retryable_failure or retryable

    if safe["status"] in {"PARTIAL", "FAILED"}:
        for recipient in _admin_recipients(db):
            locale = recipient.locale
            sent, failed, retryable = _deliver_once(
                db,
                recipient_kind="admin",
                chat_id=recipient.chat_id,
                user_id=recipient.user_id,
                venue_id=venue_id,
                run_id=run_id,
                text=build_quickresto_admin_text(payload=safe, locale=locale),
                url=open_url,
                button_text=localized(locale, ru="Открыть QuickResto", en="Open QuickResto"),
            )
            sent_admin += int(sent)
            had_failure = had_failure or failed
            had_retryable_failure = had_retryable_failure or retryable

    if had_failure:
        raise QuickRestoNotificationDeliveryError(
            "QuickResto import notification delivery failed",
            retryable=had_retryable_failure,
        )
    return {"business_sent": sent_business, "admin_sent": sent_admin}
