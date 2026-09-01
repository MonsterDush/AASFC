from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
import uuid
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_audit import QuickRestoImportIssueAudit
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.services.integrations.credentials import IntegrationCredentialError
from app.services.integrations.quickresto import (
    QuickRestoAuthenticationError,
    QuickRestoError,
    QuickRestoHTTPError,
)
from app.services.integrations.quickresto_normalize import QuickRestoDataError
from app.services.integrations.quickresto_redaction import (
    generic_quickresto_exception_summary,
    redact_quickresto_correlation_id,
    redact_quickresto_technical_summary,
)
from app.services.integrations.quickresto_snapshot import (
    QuickRestoSnapshotError,
    SealedQuickRestoSnapshot,
    open_quickresto_source_snapshot,
)
from app.services.integrations.quickresto_scope import QuickRestoLocationScopeError, QuickRestoScopeError


ACTIVE_ISSUE_STATUSES = ("OPEN", "RETRY_PENDING", "PROCESSING")
_SNAPSHOT_RETENTION_DAYS = 90


@dataclass(frozen=True)
class QuickRestoFailure:
    error_code: str
    error_category: str
    user_summary: str
    technical_summary: str
    details: dict[str, Any]
    correlation_id: str

    @property
    def fingerprint(self) -> str:
        basis = f"{self.error_category}:{self.error_code}:{self.technical_summary}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mapping_details(message: str) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for source, target in (
        ("payments", "missing_payment_type_ids"),
        ("departments", "missing_department_ids"),
    ):
        match = re.search(rf"{source}=\[([^]]*)\]", message)
        if not match:
            continue
        values = sorted({int(raw) for raw in re.findall(r"\d+", match.group(1)) if int(raw) > 0})
        details[target] = values
    return details


def classify_quickresto_failure(
    exc: BaseException,
    *,
    correlation_id: str | None = None,
) -> QuickRestoFailure:
    technical = redact_quickresto_technical_summary(exc, max_length=2000) or "QuickResto import failed"
    details: dict[str, Any] = {}
    if isinstance(exc, QuickRestoAuthenticationError):
        code = "AUTHENTICATION_REJECTED"
        category = "AUTH"
        user_summary = "QuickResto отклонил API-логин или пароль. Проверьте данные подключения."
    elif isinstance(exc, QuickRestoHTTPError):
        code = f"HTTP_{int(exc.status_code)}"
        category = "TRANSPORT"
        details["http_status"] = int(exc.status_code)
        user_summary = "QuickResto временно недоступен. Axelio повторит запрос автоматически."
    elif isinstance(exc, QuickRestoError):
        code = "TRANSPORT_FAILURE"
        category = "TRANSPORT"
        user_summary = "Не удалось получить данные QuickResto. Проверьте соединение и повторите импорт."
    elif isinstance(exc, (QuickRestoSnapshotError, IntegrationCredentialError)):
        code = "SOURCE_SNAPSHOT_FAILURE"
        category = "STORAGE"
        user_summary = "Не удалось безопасно сохранить данные смены. Импорт остановлен без потери контроля."
    elif isinstance(exc, QuickRestoLocationScopeError):
        code = exc.error_code
        category = "SCOPE"
        details.update(exc.details)
        user_summary = exc.user_summary
    elif isinstance(exc, QuickRestoScopeError):
        code = "LOCATION_SCOPE_INVALID"
        category = "SCOPE"
        user_summary = "Выбор заведения или мест реализации QuickResto требует обновления."
    elif isinstance(exc, QuickRestoDataError):
        lowered = technical.casefold()
        if "mappings are incomplete" in lowered:
            code = "MAPPING_INCOMPLETE"
            category = "MAPPING"
            details.update(_mapping_details(technical))
            user_summary = "Не сопоставлены типы оплат или группы блюд. Исправьте сопоставления и повторите импорт."
        elif "axelio report" in lowered or "could not be closed" in lowered:
            code = "REPORT_CONFLICT"
            category = "REPORT"
            report_match = re.search(r"Axelio report\s+(\d+)", technical, flags=re.IGNORECASE)
            if report_match:
                details["report_id"] = int(report_match.group(1))
            user_summary = (
                "Отчёт Axelio содержит изменения или конфликтует с импортом. Проверьте его и повторите импорт."
            )
        elif "reconcile" in lowered or "do not match" in lowered:
            code = "SOURCE_RECONCILIATION_FAILED"
            category = "SOURCE_DATA"
            user_summary = "Суммы смены QuickResto не прошли сверку. Проверьте смену и повторите импорт."
        elif "identifier" in lowered or "no dish category" in lowered or "payment type id" in lowered:
            code = "SOURCE_REFERENCE_MISSING"
            category = "SOURCE_DATA"
            user_summary = "В смене QuickResto не хватает обязательной ссылки на справочник. Проверьте данные смены."
        else:
            code = "SOURCE_DATA_INVALID"
            category = "SOURCE_DATA"
            user_summary = "Данные смены QuickResto не прошли проверку. Проверьте смену и повторите импорт."
    else:
        code = "INTERNAL_ERROR"
        category = "INTERNAL"
        technical = generic_quickresto_exception_summary(exc)
        user_summary = "Импорт не завершён из-за внутренней ошибки. Команда Axelio получила техническую причину."
    return QuickRestoFailure(
        error_code=code,
        error_category=category,
        user_summary=user_summary,
        technical_summary=technical,
        details=details,
        correlation_id=(redact_quickresto_correlation_id(correlation_id) or uuid.uuid4().hex)[:64],
    )


def report_group_key(business_date: date, shift_slot: str) -> str:
    return f"report:{business_date.isoformat()}:{str(shift_slot or 'DAY').upper()}"


def source_group_key(source_fingerprint: str) -> str:
    return f"source:{str(source_fingerprint or '')[:64]}"


def connection_group_key(error_code: str) -> str:
    return f"connection:{str(error_code or 'UNKNOWN').upper()[:64]}"


def upsert_source_snapshot(
    db: Session,
    *,
    connection_id: int,
    sync_run_id: int | None,
    sealed: SealedQuickRestoSnapshot,
    now: datetime | None = None,
) -> QuickRestoSourceSnapshot:
    timestamp = now or utcnow()
    row = db.execute(
        select(QuickRestoSourceSnapshot).where(
            QuickRestoSourceSnapshot.connection_id == int(connection_id),
            QuickRestoSourceSnapshot.source_fingerprint == sealed.source_fingerprint,
        )
    ).scalar_one_or_none()
    if row is None:
        row = QuickRestoSourceSnapshot(
            connection_id=int(connection_id),
            source_fingerprint=sealed.source_fingerprint,
            created_at=timestamp,
        )
        db.add(row)
    row.sync_run_id = int(sync_run_id) if sync_run_id is not None else None
    row.payload_hash = sealed.payload_hash
    row.encrypted_payload = sealed.encrypted_payload
    row.encryption_key_version = sealed.encryption_key_version
    row.external_shift_id = sealed.external_shift_id
    row.external_shift_pk = sealed.external_shift_pk
    row.source_version = sealed.source_version
    row.business_date = sealed.business_date
    row.shift_slot = sealed.shift_slot
    row.local_opened_at = sealed.local_opened_at
    row.local_closed_at = sealed.local_closed_at
    row.retention_expires_at = timestamp + timedelta(days=_SNAPSHOT_RETENTION_DAYS)
    row.updated_at = timestamp
    db.flush()
    return row


def open_source_snapshot(row: QuickRestoSourceSnapshot) -> dict[str, Any]:
    return open_quickresto_source_snapshot(
        encrypted_payload=row.encrypted_payload,
        expected_payload_hash=row.payload_hash,
        expected_key_version=row.encryption_key_version,
    )


def purge_expired_source_snapshots(db: Session, *, now: datetime | None = None) -> int:
    result = db.execute(
        delete(QuickRestoSourceSnapshot).where(QuickRestoSourceSnapshot.retention_expires_at < (now or utcnow()))
    )
    return int(result.rowcount or 0)


def snapshots_for_group(
    db: Session,
    *,
    connection_id: int,
    business_date: date,
    shift_slot: str,
) -> list[QuickRestoSourceSnapshot]:
    return list(
        db.execute(
            select(QuickRestoSourceSnapshot)
            .where(
                QuickRestoSourceSnapshot.connection_id == int(connection_id),
                QuickRestoSourceSnapshot.business_date == business_date,
                QuickRestoSourceSnapshot.shift_slot == str(shift_slot).upper(),
            )
            .order_by(
                QuickRestoSourceSnapshot.local_opened_at.asc(),
                QuickRestoSourceSnapshot.id.asc(),
            )
        ).scalars()
    )


def ignored_issue_matches_snapshots(
    db: Session,
    *,
    connection_id: int,
    group_key: str,
    snapshots: Iterable[QuickRestoSourceSnapshot],
) -> bool:
    issue = db.execute(
        select(QuickRestoImportIssue).where(
            QuickRestoImportIssue.connection_id == int(connection_id),
            QuickRestoImportIssue.group_key == str(group_key)[:255],
            QuickRestoImportIssue.status == "IGNORED",
        )
    ).scalar_one_or_none()
    if issue is None or not isinstance(issue.details_json, dict):
        return False
    stored = issue.details_json.get("_ignored_payload_hashes")
    if not isinstance(stored, dict) or not stored:
        return False
    current = {str(snapshot.source_fingerprint): str(snapshot.payload_hash) for snapshot in snapshots}
    return bool(current) and current == {str(key): str(value) for key, value in stored.items()}


def _issue_audit(
    db: Session,
    *,
    issue: QuickRestoImportIssue,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    actor_user_id: int | None = None,
    sync_run_id: int | None = None,
    reason_code: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        QuickRestoImportIssueAudit(
            issue_id=int(issue.id),
            actor_user_id=int(actor_user_id) if actor_user_id is not None else None,
            sync_run_id=int(sync_run_id) if sync_run_id is not None else None,
            event_type=str(event_type)[:64],
            from_status=from_status,
            to_status=to_status,
            reason_code=str(reason_code)[:64] if reason_code else None,
            summary=str(summary)[:1000] if summary else None,
            correlation_id=issue.correlation_id,
            metadata_json=metadata or {},
            created_at=utcnow(),
        )
    )


def upsert_import_issue(
    db: Session,
    *,
    connection_id: int,
    sync_run_id: int | None,
    group_key: str,
    business_date: date | None,
    shift_slot: str | None,
    failure: QuickRestoFailure,
    snapshots: Iterable[QuickRestoSourceSnapshot] = (),
    failed_source_fingerprints: set[str] | None = None,
    actor_user_id: int | None = None,
) -> QuickRestoImportIssue:
    now = utcnow()
    issue = db.execute(
        select(QuickRestoImportIssue)
        .where(
            QuickRestoImportIssue.connection_id == int(connection_id),
            QuickRestoImportIssue.group_key == str(group_key)[:255],
        )
        .with_for_update()
    ).scalar_one_or_none()
    if issue is None:
        issue = QuickRestoImportIssue(
            connection_id=int(connection_id),
            group_key=str(group_key)[:255],
            status="OPEN",
            error_code=failure.error_code,
            error_category=failure.error_category,
            user_summary=failure.user_summary,
            technical_summary=failure.technical_summary,
            details_json=failure.details,
            failure_fingerprint=failure.fingerprint,
            correlation_id=failure.correlation_id,
            generation=1,
            attempt_count=0,
            lock_version=1,
            first_failed_at=now,
            last_failed_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(issue)
        db.flush()
        previous_status = None
        event_type = "OPENED"
    else:
        previous_status = str(issue.status)
        event_type = "REOPENED" if previous_status in {"RESOLVED", "IGNORED"} else "FAILED_AGAIN"
        if previous_status in {"RESOLVED", "IGNORED"}:
            issue.generation = int(issue.generation or 1) + 1
            issue.first_failed_at = now
        issue.status = "OPEN"
        issue.lock_version = int(issue.lock_version or 1) + 1

    issue.last_sync_run_id = int(sync_run_id) if sync_run_id is not None else None
    issue.business_date = business_date
    issue.shift_slot = str(shift_slot).upper() if shift_slot else None
    issue.error_code = failure.error_code
    issue.error_category = failure.error_category
    issue.user_summary = failure.user_summary
    issue.technical_summary = failure.technical_summary
    issue.details_json = failure.details
    issue.failure_fingerprint = failure.fingerprint
    issue.correlation_id = failure.correlation_id
    issue.attempt_count = int(issue.attempt_count or 0) + 1
    issue.last_failed_at = now
    issue.next_retry_at = None
    issue.processing_started_at = None
    issue.resolved_at = None
    issue.resolved_by_user_id = None
    issue.resolution_code = None
    issue.resolution_note = None
    issue.updated_at = now
    db.flush()

    rows = list(snapshots)
    keep_keys: set[str] = set()
    failed = set(failed_source_fingerprints or set())
    existing_items = {item.source_key: item for item in issue.shifts}
    for snapshot in rows:
        source_key = str(snapshot.external_shift_id or snapshot.source_fingerprint)
        keep_keys.add(source_key)
        item = existing_items.get(source_key)
        if item is None:
            item = QuickRestoImportIssueShift(issue_id=int(issue.id), source_key=source_key, created_at=now)
            db.add(item)
        is_failed = snapshot.source_fingerprint in failed
        item.source_snapshot_id = int(snapshot.id)
        item.external_shift_id = snapshot.external_shift_id
        item.external_shift_pk = snapshot.external_shift_pk
        item.source_version = snapshot.source_version
        item.source_fingerprint = snapshot.source_fingerprint
        item.local_opened_at = snapshot.local_opened_at
        item.local_closed_at = snapshot.local_closed_at
        item.item_status = "FAILED" if is_failed else "BLOCKED"
        item.error_code = failure.error_code if is_failed else "BLOCKED_BY_GROUP"
        item.user_summary = failure.user_summary if is_failed else "Ожидает успешной обработки всей группы смен."
        item.technical_summary = failure.technical_summary if is_failed else None
        item.updated_at = now
        if snapshot.external_shift_id:
            item.shift_import_id = db.execute(
                select(QuickRestoShiftImport.id).where(
                    QuickRestoShiftImport.connection_id == int(connection_id),
                    QuickRestoShiftImport.external_shift_id == snapshot.external_shift_id,
                )
            ).scalar_one_or_none()
    for source_key, item in existing_items.items():
        if source_key not in keep_keys:
            db.delete(item)

    _issue_audit(
        db,
        issue=issue,
        event_type=event_type,
        from_status=previous_status,
        to_status="OPEN",
        actor_user_id=actor_user_id,
        sync_run_id=sync_run_id,
        reason_code=failure.error_code,
        summary=failure.user_summary,
        metadata={"shift_count": len(rows), **failure.details},
    )
    db.flush()
    return issue


def transition_issue(
    db: Session,
    *,
    issue: QuickRestoImportIssue,
    status: str,
    event_type: str,
    actor_user_id: int | None = None,
    sync_run_id: int | None = None,
    resolution_code: str | None = None,
    resolution_note: str | None = None,
) -> None:
    target = str(status or "").upper()
    if target not in {"OPEN", "RETRY_PENDING", "PROCESSING", "RESOLVED", "IGNORED"}:
        raise ValueError("Unsupported QuickResto issue status")
    previous = str(issue.status)
    now = utcnow()
    issue.status = target
    issue.lock_version = int(issue.lock_version or 1) + 1
    issue.updated_at = now
    issue.processing_started_at = now if target == "PROCESSING" else None
    issue.next_retry_at = now if target == "RETRY_PENDING" else None
    if target in {"RESOLVED", "IGNORED"}:
        issue.resolved_at = now
        issue.resolved_by_user_id = int(actor_user_id) if actor_user_id is not None else None
        issue.resolution_code = str(resolution_code or target)[:64]
        issue.resolution_note = str(resolution_note or "")[:1000] or None
        for item in issue.shifts:
            item.item_status = target
            item.updated_at = now
    details = dict(issue.details_json) if isinstance(issue.details_json, dict) else {}
    if target == "IGNORED":
        ignored_hashes = {
            str(item.source_fingerprint): str(item.source_snapshot.payload_hash)
            for item in issue.shifts
            if item.source_fingerprint and item.source_snapshot is not None
        }
        if ignored_hashes:
            details["_ignored_payload_hashes"] = ignored_hashes
    elif target == "RESOLVED":
        details.pop("_ignored_payload_hashes", None)
    issue.details_json = details
    _issue_audit(
        db,
        issue=issue,
        event_type=event_type,
        from_status=previous,
        to_status=target,
        actor_user_id=actor_user_id,
        sync_run_id=sync_run_id,
        reason_code=resolution_code,
        summary=resolution_note,
    )
    db.flush()


def resolve_group_issue(
    db: Session,
    *,
    connection_id: int,
    business_date: date,
    shift_slot: str,
    actor_user_id: int | None,
    sync_run_id: int | None,
) -> QuickRestoImportIssue | None:
    issue = db.execute(
        select(QuickRestoImportIssue).where(
            QuickRestoImportIssue.connection_id == int(connection_id),
            QuickRestoImportIssue.group_key == report_group_key(business_date, shift_slot),
            QuickRestoImportIssue.status.in_((*ACTIVE_ISSUE_STATUSES, "IGNORED")),
        )
    ).scalar_one_or_none()
    if issue is not None:
        transition_issue(
            db,
            issue=issue,
            status="RESOLVED",
            event_type="IMPORT_SUCCEEDED",
            actor_user_id=actor_user_id,
            sync_run_id=sync_run_id,
            resolution_code="RETRY_SUCCEEDED",
            resolution_note="Группа смен успешно импортирована.",
        )
    return issue


def serialize_issue(
    issue: QuickRestoImportIssue,
    *,
    include_shifts: bool = False,
    include_technical: bool = False,
) -> dict[str, Any]:
    status = str(issue.status)
    details = issue.details_json if isinstance(issue.details_json, dict) else {}
    public_details = {
        key: details[key]
        for key in (
            "missing_payment_type_ids",
            "missing_department_ids",
            "report_id",
            "http_status",
            "selected_external_venue_id",
            "shift_external_venue_id",
            "sale_place_id",
            "opening_sale_place_id",
            "resolved_sale_place_venue_id",
            "legacy_shift_count",
            "legacy_external_shift_ids",
        )
        if key in details
    }
    retry_sources_available = bool(issue.shifts) and all(item.source_snapshot_id is not None for item in issue.shifts)
    payload: dict[str, Any] = {
        "id": int(issue.id),
        "status": status,
        "error_code": str(issue.error_code),
        "error_category": str(issue.error_category),
        "user_summary": str(issue.user_summary),
        "business_date": issue.business_date.isoformat() if issue.business_date else None,
        "shift_slot": issue.shift_slot,
        "generation": int(issue.generation or 1),
        "attempt_count": int(issue.attempt_count or 0),
        "first_failed_at": issue.first_failed_at.isoformat() if issue.first_failed_at else None,
        "last_failed_at": issue.last_failed_at.isoformat() if issue.last_failed_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "resolution_note": issue.resolution_note,
        "shift_count": max(len(issue.shifts), int(details.get("legacy_shift_count") or 0)),
        "can_retry": status in {"OPEN", "RETRY_PENDING"} and retry_sources_available,
        "can_ignore": status in {"OPEN", "RETRY_PENDING"},
        "details": public_details,
    }
    if include_technical:
        payload["technical_summary"] = issue.technical_summary
        payload["correlation_id"] = issue.correlation_id
    if include_shifts:
        payload["shifts"] = []
        for item in issue.shifts:
            shift_payload = {
                "id": int(item.id),
                "external_shift_id": item.external_shift_id,
                "external_shift_pk": item.external_shift_pk,
                "source_version": item.source_version,
                "item_status": item.item_status,
                "user_summary": item.user_summary,
                "local_opened_at": item.local_opened_at.isoformat() if item.local_opened_at else None,
                "local_closed_at": item.local_closed_at.isoformat() if item.local_closed_at else None,
            }
            if include_technical:
                shift_payload["technical_summary"] = item.technical_summary
            payload["shifts"].append(shift_payload)
    return payload


def issue_counters(db: Session, *, connection_id: int) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(QuickRestoImportIssue).where(
                QuickRestoImportIssue.connection_id == int(connection_id),
                QuickRestoImportIssue.status.in_(ACTIVE_ISSUE_STATUSES),
            )
        ).scalars()
    )
    return {
        "open_count": len(rows),
        "affected_shift_count": sum(
            max(
                len(row.shifts),
                int(row.details_json.get("legacy_shift_count") or 0) if isinstance(row.details_json, dict) else 0,
            )
            for row in rows
        ),
        "oldest_failed_at": min((row.first_failed_at for row in rows), default=None),
    }
