from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import base64
import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.finance_entry import FinanceEntry
from app.models.payroll_run import PayrollRun
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.venue import Venue
from app.services.integrations.quickresto_issues import open_source_snapshot, transition_issue
from app.services.integrations.quickresto_normalize import normalize_closed_shift
from app.services.integrations.quickresto_scope import (
    activate_pending_quickresto_scope,
    evaluate_quickresto_shift_scope,
    load_quickresto_scope_index,
    pending_quickresto_scope,
)
from app.services.integrations.quickresto_sync import (
    QuickRestoSyncError,
    _rebuild_imported_report_keys,
    _scope_resolution_requires_review,
    _upsert_normalized_shift,
    _utcnow,
    quickresto_sync_is_active,
    reclaim_stale_quickresto_sync_state,
)


_ALLOWED_ACTIONS = {"KEEP_CURRENT", "EXCLUDE_CURRENT", "MOVE_TO_CONNECTED"}
_PREVIEW_TTL = timedelta(minutes=15)
_TOKEN_CONTEXT = b"axelio:quickresto:scope-reconciliation-preview:v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _token_key() -> bytes:
    root = str(settings.EXPORT_LINK_SECRET or settings.JWT_SECRET).encode("utf-8")
    return hmac.new(root, _TOKEN_CONTEXT, hashlib.sha256).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _issue_generation(issue: QuickRestoImportIssue, connection: QuickRestoConnection) -> int:
    details = issue.details_json if isinstance(issue.details_json, dict) else {}
    return int(details.get("scope_generation") or connection.scope_generation or 1)


def _normalize_decisions(decisions: dict[int, str]) -> dict[int, str]:
    normalized = {int(key): str(value or "").strip().upper() for key, value in decisions.items()}
    if not normalized or any(value not in _ALLOWED_ACTIONS for value in normalized.values()):
        raise QuickRestoSyncError("Для каждой исторической смены выберите допустимое решение")
    return dict(sorted(normalized.items()))


def _decisions_payload(decisions: dict[int, str]) -> list[dict[str, Any]]:
    return [{"shift_import_id": int(key), "action": value} for key, value in sorted(decisions.items())]


def _issue_snapshot(
    db: Session,
    *,
    issue_id: int,
    connection_id: int,
    for_update: bool,
) -> QuickRestoImportIssue:
    statement = select(QuickRestoImportIssue).where(
        QuickRestoImportIssue.id == int(issue_id),
        QuickRestoImportIssue.connection_id == int(connection_id),
    )
    if for_update:
        statement = statement.with_for_update()
    issue = db.execute(statement.execution_options(populate_existing=True)).scalar_one_or_none()
    if issue is None:
        raise QuickRestoSyncError("QuickResto import issue was not found")
    if str(issue.error_code or "").upper() != "PREVIOUS_SCOPE_MISMATCH":
        raise QuickRestoSyncError("Эта проблема не относится к исторической области QuickResto")
    if str(issue.status or "").upper() not in {"OPEN", "RETRY_PENDING"}:
        raise QuickRestoSyncError("Проблема уже обрабатывается или закрыта")
    return issue


def _lock_connection(db: Session, *, connection_id: int) -> QuickRestoConnection:
    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.id == int(connection_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if connection is None:
        raise QuickRestoSyncError("QuickResto connection no longer exists")
    now = _utcnow()
    if quickresto_sync_is_active(connection, now=now):
        raise QuickRestoSyncError("QuickResto sync is already running")
    reclaim_stale_quickresto_sync_state(db, connection=connection, now=now)
    if not connection.is_active:
        raise QuickRestoSyncError("QuickResto connection is disabled")
    return connection


def _validate_generation(connection: QuickRestoConnection, *, target_generation: int) -> None:
    pending = pending_quickresto_scope(connection)
    if pending is not None:
        if int(pending["scope_generation"]) != int(target_generation):
            raise QuickRestoSyncError(
                "Ожидающая область QuickResto изменилась. Обновите проблему и выберите решения заново."
            )
        return
    if int(connection.scope_generation or 1) != int(target_generation):
        raise QuickRestoSyncError("Версия области QuickResto изменилась. Запустите полную сверку заново.")


def _load_issue_shifts(
    db: Session,
    *,
    issue: QuickRestoImportIssue,
    connection_id: int,
    target_generation: int,
    decisions: dict[int, str],
    for_update: bool,
) -> tuple[list[QuickRestoImportIssueShift], list[QuickRestoShiftImport]]:
    item_statement = select(QuickRestoImportIssueShift).where(QuickRestoImportIssueShift.issue_id == int(issue.id))
    if for_update:
        item_statement = item_statement.with_for_update()
    issue_items = list(db.execute(item_statement).scalars())
    expected_ids = {int(item.shift_import_id) for item in issue_items if item.shift_import_id is not None}
    if not expected_ids or len(expected_ids) != len(issue_items):
        raise QuickRestoSyncError(
            "Исторические смены не привязаны к сохранённым импортам. Запустите полную синхронизацию."
        )
    if set(decisions) != expected_ids:
        raise QuickRestoSyncError("Список исторических смен изменился. Обновите проблему и выберите решение заново.")

    shift_statement = select(QuickRestoShiftImport).where(
        QuickRestoShiftImport.connection_id == int(connection_id),
        QuickRestoShiftImport.id.in_(sorted(expected_ids)),
        _scope_resolution_requires_review(target_generation),
    )
    if for_update:
        shift_statement = shift_statement.with_for_update()
    shift_imports = list(db.execute(shift_statement).scalars())
    if len(shift_imports) != len(expected_ids):
        raise QuickRestoSyncError("По части исторических смен уже принято решение. Обновите страницу.")
    shift_imports.sort(key=lambda row: int(row.id))
    return issue_items, shift_imports


def _snapshot_for_item(
    db: Session,
    *,
    source_connection_id: int,
    item: QuickRestoImportIssueShift,
    shift_import: QuickRestoShiftImport,
) -> QuickRestoSourceSnapshot | None:
    if item.source_snapshot_id is not None:
        snapshot = db.get(QuickRestoSourceSnapshot, int(item.source_snapshot_id))
        if (
            snapshot is not None
            and int(snapshot.connection_id) == int(source_connection_id)
            and (
                snapshot.source_version is None or int(snapshot.source_version) == int(shift_import.source_version or 0)
            )
        ):
            return snapshot
    return db.execute(
        select(QuickRestoSourceSnapshot)
        .where(
            QuickRestoSourceSnapshot.connection_id == int(source_connection_id),
            QuickRestoSourceSnapshot.external_shift_id == str(shift_import.external_shift_id),
            QuickRestoSourceSnapshot.source_version == int(shift_import.source_version or 0),
        )
        .order_by(QuickRestoSourceSnapshot.updated_at.desc(), QuickRestoSourceSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _matching_move_destinations(
    db: Session,
    *,
    source_connection: QuickRestoConnection,
    source_payload: dict[str, Any],
    lock_candidates: bool = False,
) -> list[QuickRestoConnection]:
    shift = source_payload.get("shift") if isinstance(source_payload, dict) else None
    if not isinstance(shift, dict):
        raise QuickRestoSyncError("Для переноса смены отсутствует сохранённый снимок QuickResto")
    statement = (
        select(QuickRestoConnection)
        .where(
            QuickRestoConnection.id != int(source_connection.id),
            QuickRestoConnection.cloud == source_connection.cloud,
            QuickRestoConnection.is_active.is_(True),
            QuickRestoConnection.scope_status == "READY",
            QuickRestoConnection.external_venue_id.is_not(None),
            QuickRestoConnection.pending_external_venue_id.is_(None),
        )
        .order_by(QuickRestoConnection.id.asc())
    )
    if lock_candidates:
        statement = statement.with_for_update()
    candidates = list(db.execute(statement.execution_options(populate_existing=True)).scalars())
    matches: list[QuickRestoConnection] = []
    for candidate in candidates:
        scope = load_quickresto_scope_index(db, connection=candidate)
        decision = evaluate_quickresto_shift_scope(shift, scope=scope)
        if decision.action == "IMPORT":
            matches.append(candidate)
    return matches


def _copy_snapshot_to_target(
    db: Session,
    *,
    source_snapshot: QuickRestoSourceSnapshot,
    target_connection_id: int,
    normalized: dict[str, Any],
) -> QuickRestoSourceSnapshot:
    target = db.execute(
        select(QuickRestoSourceSnapshot).where(
            QuickRestoSourceSnapshot.connection_id == int(target_connection_id),
            QuickRestoSourceSnapshot.source_fingerprint == source_snapshot.source_fingerprint,
        )
    ).scalar_one_or_none()
    if target is None:
        target = QuickRestoSourceSnapshot(
            connection_id=int(target_connection_id),
            source_fingerprint=source_snapshot.source_fingerprint,
            payload_hash=source_snapshot.payload_hash,
            encrypted_payload=source_snapshot.encrypted_payload,
            encryption_key_version=source_snapshot.encryption_key_version,
            external_shift_id=source_snapshot.external_shift_id,
            external_shift_pk=source_snapshot.external_shift_pk,
            source_version=source_snapshot.source_version,
            business_date=date.fromisoformat(str(normalized["business_date"])),
            shift_slot=str(normalized.get("shift_slot") or "DAY").upper(),
            local_opened_at=source_snapshot.local_opened_at,
            local_closed_at=source_snapshot.local_closed_at,
            retention_expires_at=source_snapshot.retention_expires_at,
            sync_run_id=None,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(target)
        return target
    target.payload_hash = source_snapshot.payload_hash
    target.encrypted_payload = source_snapshot.encrypted_payload
    target.encryption_key_version = source_snapshot.encryption_key_version
    target.external_shift_id = source_snapshot.external_shift_id
    target.external_shift_pk = source_snapshot.external_shift_pk
    target.source_version = source_snapshot.source_version
    target.business_date = date.fromisoformat(str(normalized["business_date"]))
    target.shift_slot = str(normalized.get("shift_slot") or "DAY").upper()
    target.local_opened_at = source_snapshot.local_opened_at
    target.local_closed_at = source_snapshot.local_closed_at
    target.retention_expires_at = source_snapshot.retention_expires_at
    target.updated_at = _utcnow()
    return target


def _report_values(db: Session, report_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(DailyReportValue)
            .where(
                DailyReportValue.report_id == int(report_id),
                DailyReportValue.kind.in_(("PAYMENT", "DEPT", "KPI")),
            )
            .order_by(DailyReportValue.kind.asc(), DailyReportValue.ref_id.asc(), DailyReportValue.id.asc())
        ).scalars()
    )
    return [{"kind": str(row.kind), "ref_id": int(row.ref_id), "value": int(row.value_numeric or 0)} for row in rows]


def _report_snapshot(
    db: Session,
    *,
    connection: QuickRestoConnection,
    target_date: date,
    shift_slot: str,
    normalize_new_id: bool = False,
) -> dict[str, Any] | None:
    report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == int(connection.venue_id),
            DailyReport.date == target_date,
            DailyReport.shift_slot == str(shift_slot).upper(),
        )
    ).scalar_one_or_none()
    if report is None:
        return None
    source = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == int(connection.id),
            QuickRestoReportImport.business_date == target_date,
            QuickRestoReportImport.shift_slot == str(shift_slot).upper(),
        )
    ).scalar_one_or_none()
    ledger_minor = int(
        db.execute(
            select(func.coalesce(func.sum(FinanceEntry.amount_minor), 0)).where(
                FinanceEntry.source_type == "daily_report",
                FinanceEntry.source_id == int(report.id),
                FinanceEntry.kind == "REVENUE",
                FinanceEntry.direction == "INCOME",
            )
        ).scalar_one()
        or 0
    )
    return {
        "report_id": None if normalize_new_id else int(report.id),
        "status": str(report.status or "").upper(),
        "revenue_total": int(report.revenue_total or 0),
        "cash": int(report.cash or 0),
        "cashless": int(report.cashless or 0),
        "tips_total": int(report.tips_total or 0),
        "comment": str(report.comment or ""),
        "values": _report_values(db, int(report.id)),
        "ledger_revenue_minor": ledger_minor,
        "source_aggregate_hash": str(source.aggregate_hash) if source is not None else None,
        "source_shift_count": int(source.shift_count or 0) if source is not None else 0,
    }


def _report_precondition(
    db: Session,
    *,
    connection: QuickRestoConnection,
    target_date: date,
    shift_slot: str,
) -> dict[str, Any] | None:
    report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == int(connection.venue_id),
            DailyReport.date == target_date,
            DailyReport.shift_slot == str(shift_slot).upper(),
        )
    ).scalar_one_or_none()
    if report is None:
        return None
    source = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == int(connection.id),
            QuickRestoReportImport.business_date == target_date,
            QuickRestoReportImport.shift_slot == str(shift_slot).upper(),
        )
    ).scalar_one_or_none()
    return {
        "report_id": int(report.id),
        "updated_at": report.updated_at.isoformat() if report.updated_at is not None else None,
        "closed_at": report.closed_at.isoformat() if report.closed_at is not None else None,
        "source_updated_at": (
            source.updated_at.isoformat() if source is not None and source.updated_at is not None else None
        ),
        "source_aggregate_hash": str(source.aggregate_hash) if source is not None else None,
    }


def _payroll_snapshot(db: Session, *, venue_id: int, month: str) -> dict[str, Any]:
    year, month_number = (int(value) for value in month.split("-"))
    period_month = date(year, month_number, 1)
    run = db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == int(venue_id),
            PayrollRun.period_month == period_month,
        )
    ).scalar_one_or_none()
    if run is None:
        return {
            "venue_id": int(venue_id),
            "month": month,
            "total_amount_minor": 0,
            "lines_count": 0,
            "ledger_payroll_minor": 0,
        }
    ledger_minor = int(
        db.execute(
            select(func.coalesce(func.sum(FinanceEntry.amount_minor), 0)).where(
                FinanceEntry.source_type == "payroll_run",
                FinanceEntry.source_id == int(run.id),
                FinanceEntry.kind == "PAYROLL",
                FinanceEntry.direction == "EXPENSE",
            )
        ).scalar_one()
        or 0
    )
    return {
        "venue_id": int(venue_id),
        "month": month,
        "total_amount_minor": int(run.total_amount_minor or 0),
        "lines_count": int(run.lines_count or 0),
        "ledger_payroll_minor": ledger_minor,
    }


def _report_plan_row(
    *,
    connection: QuickRestoConnection,
    target_date: date,
    shift_slot: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    precondition: dict[str, Any] | None,
) -> dict[str, Any]:
    if before is None and after is None:
        action = "UNCHANGED"
    elif before is None:
        action = "CREATE"
    elif after is None:
        action = "DELETE"
    elif before == after:
        action = "UNCHANGED"
    else:
        action = "UPDATE"
    before_revenue = int((before or {}).get("revenue_total") or 0)
    after_revenue = int((after or {}).get("revenue_total") or 0)
    before_ledger = int((before or {}).get("ledger_revenue_minor") or 0)
    after_ledger = int((after or {}).get("ledger_revenue_minor") or 0)
    return {
        "connection_id": int(connection.id),
        "venue_id": int(connection.venue_id),
        "business_date": target_date.isoformat(),
        "shift_slot": str(shift_slot).upper(),
        "action": action,
        "precondition": precondition,
        "before": before,
        "after": after,
        "revenue_delta": after_revenue - before_revenue,
        "ledger_revenue_delta_minor": after_ledger - before_ledger,
    }


def _payroll_plan_row(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_id": int(before["venue_id"]),
        "month": str(before["month"]),
        "before_total_amount_minor": int(before["total_amount_minor"]),
        "after_total_amount_minor": int(after["total_amount_minor"]),
        "delta_amount_minor": int(after["total_amount_minor"]) - int(before["total_amount_minor"]),
        "before_ledger_payroll_minor": int(before["ledger_payroll_minor"]),
        "after_ledger_payroll_minor": int(after["ledger_payroll_minor"]),
        "delta_ledger_payroll_minor": int(after["ledger_payroll_minor"]) - int(before["ledger_payroll_minor"]),
    }


def _target_normalized_payload(
    db: Session,
    *,
    target_connection: QuickRestoConnection,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    target_venue = db.get(Venue, int(target_connection.venue_id))
    if target_venue is None:
        raise QuickRestoSyncError("Целевое заведение Axelio больше не существует")
    shift = source_payload.get("shift") if isinstance(source_payload, dict) else None
    orders = source_payload.get("orders") if isinstance(source_payload, dict) else None
    if not isinstance(shift, dict) or not isinstance(orders, list):
        raise QuickRestoSyncError("Для переноса смены отсутствует полный сохранённый снимок QuickResto")
    return normalize_closed_shift(
        shift,
        orders,
        cutoff_hour=int(target_connection.business_day_cutoff_hour or 0),
        night_shift_split_enabled=bool(
            target_connection.night_shift_split_enabled and target_venue.night_shifts_enabled
        ),
        night_shift_start_hour=int(target_connection.night_shift_start_hour or 22),
    )


def _prepare_context(
    db: Session,
    *,
    source_connection_id: int,
    issue_id: int,
    decisions: dict[int, str],
    allowed_target_venue_ids: set[int] | None,
    for_update: bool,
) -> dict[str, Any]:
    connection = (
        _lock_connection(db, connection_id=source_connection_id)
        if for_update
        else db.get(QuickRestoConnection, int(source_connection_id))
    )
    if connection is None:
        raise QuickRestoSyncError("QuickResto connection no longer exists")
    if not for_update:
        if not connection.is_active:
            raise QuickRestoSyncError("QuickResto connection is disabled")
        if quickresto_sync_is_active(connection):
            raise QuickRestoSyncError("QuickResto sync is already running")
    issue = _issue_snapshot(
        db,
        issue_id=issue_id,
        connection_id=int(connection.id),
        for_update=for_update,
    )
    target_generation = _issue_generation(issue, connection)
    _validate_generation(connection, target_generation=target_generation)
    issue_items, shift_imports = _load_issue_shifts(
        db,
        issue=issue,
        connection_id=int(connection.id),
        target_generation=target_generation,
        decisions=decisions,
        for_update=for_update,
    )
    item_by_shift_id = {int(item.shift_import_id): item for item in issue_items if item.shift_import_id is not None}
    snapshot_by_shift_id: dict[int, QuickRestoSourceSnapshot | None] = {}
    payload_by_shift_id: dict[int, dict[str, Any]] = {}
    target_by_shift_id: dict[int, QuickRestoConnection] = {}
    normalized_target_by_shift_id: dict[int, dict[str, Any]] = {}
    target_existing_state_by_shift_id: dict[int, dict[str, Any] | None] = {}

    for shift_import in shift_imports:
        shift_id = int(shift_import.id)
        item = item_by_shift_id[shift_id]
        snapshot = _snapshot_for_item(
            db,
            source_connection_id=int(connection.id),
            item=item,
            shift_import=shift_import,
        )
        snapshot_by_shift_id[shift_id] = snapshot
        if decisions[shift_id] != "MOVE_TO_CONNECTED":
            continue
        if snapshot is None:
            raise QuickRestoSyncError(
                f"Для смены QuickResto {shift_import.external_shift_id} нет сохранённого снимка "
                "для безопасного переноса"
            )
        payload = open_source_snapshot(snapshot)
        payload_by_shift_id[shift_id] = payload
        matches = _matching_move_destinations(
            db,
            source_connection=connection,
            source_payload=payload,
            lock_candidates=for_update,
        )
        if len(matches) != 1:
            if not matches:
                raise QuickRestoSyncError(
                    f"Для смены QuickResto {shift_import.external_shift_id} не найдено подключённое "
                    "целевое заведение; "
                    "выберите явное исключение или исправьте область интеграции"
                )
            raise QuickRestoSyncError(
                f"Для смены QuickResto {shift_import.external_shift_id} найдено несколько целевых заведений; "
                "перенос без однозначного назначения запрещён"
            )
        target = matches[0]
        if allowed_target_venue_ids is not None and int(target.venue_id) not in allowed_target_venue_ids:
            raise QuickRestoSyncError("Недостаточно прав для переноса смены в целевое заведение Axelio")
        if for_update:
            now = _utcnow()
            if quickresto_sync_is_active(target, now=now):
                raise QuickRestoSyncError("Целевое подключение QuickResto сейчас синхронизируется")
            reclaim_stale_quickresto_sync_state(db, connection=target, now=now)
            if not target.is_active or str(target.scope_status or "").upper() != "READY":
                raise QuickRestoSyncError("Целевое подключение QuickResto больше не готово к переносу")
        target_by_shift_id[shift_id] = target
        normalized_target_by_shift_id[shift_id] = _target_normalized_payload(
            db,
            target_connection=target,
            source_payload=payload,
        )

    source_state_by_shift_id = {
        int(shift.id): {
            "payload_hash": str(shift.payload_hash),
            "source_version": int(shift.source_version or 0),
            "business_date": shift.business_date.isoformat(),
            "shift_slot": str(shift.shift_slot or "DAY").upper(),
            "daily_report_id": int(shift.daily_report_id) if shift.daily_report_id is not None else None,
            "scope_resolution_action": shift.scope_resolution_action,
            "scope_resolution_generation": shift.scope_resolution_generation,
            "updated_at": shift.updated_at.isoformat() if shift.updated_at is not None else None,
        }
        for shift in shift_imports
    }
    source_keys = {(shift.business_date, str(shift.shift_slot or "DAY").upper()) for shift in shift_imports}
    target_keys_by_connection: dict[int, set[tuple[date, str]]] = defaultdict(set)
    for shift_import in shift_imports:
        shift_id = int(shift_import.id)
        if decisions[shift_id] != "MOVE_TO_CONNECTED":
            continue
        target = target_by_shift_id[shift_id]
        normalized = normalized_target_by_shift_id[shift_id]
        new_key = (
            date.fromisoformat(str(normalized["business_date"])),
            str(normalized.get("shift_slot") or "DAY").upper(),
        )
        target_keys_by_connection[int(target.id)].add(new_key)
        existing_target = db.execute(
            select(QuickRestoShiftImport).where(
                QuickRestoShiftImport.connection_id == int(target.id),
                QuickRestoShiftImport.external_shift_id == str(shift_import.external_shift_id),
            )
        ).scalar_one_or_none()
        if existing_target is not None:
            target_keys_by_connection[int(target.id)].add(
                (existing_target.business_date, str(existing_target.shift_slot or "DAY").upper())
            )
            target_existing_state_by_shift_id[shift_id] = {
                "shift_import_id": int(existing_target.id),
                "payload_hash": str(existing_target.payload_hash),
                "source_version": int(existing_target.source_version or 0),
                "business_date": existing_target.business_date.isoformat(),
                "shift_slot": str(existing_target.shift_slot or "DAY").upper(),
                "daily_report_id": (
                    int(existing_target.daily_report_id) if existing_target.daily_report_id is not None else None
                ),
                "scope_resolution_action": existing_target.scope_resolution_action,
                "scope_resolution_generation": existing_target.scope_resolution_generation,
                "updated_at": (
                    existing_target.updated_at.isoformat() if existing_target.updated_at is not None else None
                ),
                "target_scope_generation": int(target.scope_generation or 1),
                "target_external_venue_id": int(target.external_venue_id or 0) or None,
            }
        else:
            target_existing_state_by_shift_id[shift_id] = None

    if for_update:
        all_target_ids = sorted({int(target.id) for target in target_by_shift_id.values()})
        if all_target_ids:
            # Lock existing target shift rows and report rows before the confirm re-check.
            list(
                db.execute(
                    select(QuickRestoShiftImport)
                    .where(
                        QuickRestoShiftImport.connection_id.in_(all_target_ids),
                        QuickRestoShiftImport.external_shift_id.in_(
                            sorted({str(row.external_shift_id) for row in shift_imports})
                        ),
                    )
                    .with_for_update()
                ).scalars()
            )
        report_filters = []
        for target_date, slot in source_keys:
            report_filters.append((int(connection.venue_id), target_date, slot))
        for target_id, keys in target_keys_by_connection.items():
            target = next(value for value in target_by_shift_id.values() if int(value.id) == target_id)
            for target_date, slot in keys:
                report_filters.append((int(target.venue_id), target_date, slot))
        for venue_id, target_date, slot in sorted(set(report_filters)):
            list(
                db.execute(
                    select(DailyReport)
                    .where(
                        DailyReport.venue_id == venue_id,
                        DailyReport.date == target_date,
                        DailyReport.shift_slot == slot,
                    )
                    .with_for_update()
                ).scalars()
            )

    return {
        "connection": connection,
        "issue": issue,
        "target_generation": target_generation,
        "shift_imports": shift_imports,
        "item_by_shift_id": item_by_shift_id,
        "snapshot_by_shift_id": snapshot_by_shift_id,
        "payload_by_shift_id": payload_by_shift_id,
        "target_by_shift_id": target_by_shift_id,
        "normalized_target_by_shift_id": normalized_target_by_shift_id,
        "target_existing_state_by_shift_id": target_existing_state_by_shift_id,
        "source_state_by_shift_id": source_state_by_shift_id,
        "source_keys": source_keys,
        "target_keys_by_connection": target_keys_by_connection,
    }


def _apply_mutations(
    db: Session,
    *,
    context: dict[str, Any],
    decisions: dict[int, str],
    note: str,
    actor_user_id: int,
    run: QuickRestoSyncRun,
) -> dict[str, Any]:
    source: QuickRestoConnection = context["connection"]
    generation = int(context["target_generation"])
    if pending_quickresto_scope(source) is not None:
        activate_pending_quickresto_scope(
            db,
            connection=source,
            actor_user_id=int(actor_user_id),
            expected_generation=generation,
        )

    timestamp = _utcnow()
    source_keys: set[tuple[date, str]] = set(context["source_keys"])
    target_keys_by_connection: dict[int, set[tuple[date, str]]] = defaultdict(set)
    decision_audit: list[dict[str, Any]] = []
    counts_by_action = {"KEEP_CURRENT": 0, "EXCLUDE_CURRENT": 0, "MOVE_TO_CONNECTED": 0}

    for shift_import in context["shift_imports"]:
        shift_id = int(shift_import.id)
        action = decisions[shift_id]
        counts_by_action[action] += 1
        source_report_before = int(shift_import.daily_report_id) if shift_import.daily_report_id is not None else None
        target_connection = context["target_by_shift_id"].get(shift_id)
        target_report_before = None
        target_shift_id = None

        shift_import.scope_resolution_action = action
        shift_import.scope_resolution_generation = generation
        shift_import.scope_resolved_by_user_id = int(actor_user_id)
        shift_import.scope_resolved_at = timestamp
        shift_import.scope_resolution_note = str(note).strip()
        shift_import.updated_at = timestamp

        if action == "EXCLUDE_CURRENT":
            shift_import.daily_report_id = None
        elif action == "MOVE_TO_CONNECTED":
            if target_connection is None:
                raise QuickRestoSyncError("Целевое заведение для переноса больше не определено")
            source_snapshot = context["snapshot_by_shift_id"].get(shift_id)
            if source_snapshot is None:
                raise QuickRestoSyncError("Сохранённый снимок QuickResto для переноса больше не доступен")
            normalized = context["normalized_target_by_shift_id"][shift_id]
            existing_target = db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == int(target_connection.id),
                    QuickRestoShiftImport.external_shift_id == str(shift_import.external_shift_id),
                )
            ).scalar_one_or_none()
            if existing_target is not None:
                target_report_before = (
                    int(existing_target.daily_report_id) if existing_target.daily_report_id is not None else None
                )
            _copy_snapshot_to_target(
                db,
                source_snapshot=source_snapshot,
                target_connection_id=int(target_connection.id),
                normalized=normalized,
            )
            _changed, affected = _upsert_normalized_shift(
                db,
                connection=target_connection,
                normalized=normalized,
            )
            db.flush()
            target_shift = db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == int(target_connection.id),
                    QuickRestoShiftImport.external_shift_id == str(shift_import.external_shift_id),
                )
            ).scalar_one()
            # A prior target-side EXCLUDE/MOVE decision must never survive an
            # explicitly confirmed transfer. The target becomes the active owner.
            target_shift.scope_resolution_action = None
            target_shift.scope_resolution_generation = None
            target_shift.scope_resolved_by_user_id = None
            target_shift.scope_resolved_at = None
            target_shift.scope_resolution_note = None
            target_shift.updated_at = timestamp
            target_shift_id = int(target_shift.id)
            target_keys_by_connection[int(target_connection.id)].update(affected)
            shift_import.daily_report_id = None

        decision_audit.append(
            {
                "shift_import_id": shift_id,
                "external_shift_id": str(shift_import.external_shift_id),
                "action": action,
                "scope_generation": generation,
                "source_connection_id": int(source.id),
                "source_venue_id": int(source.venue_id),
                "source_report_id_before": source_report_before,
                "target_connection_id": int(target_connection.id) if target_connection is not None else None,
                "target_venue_id": int(target_connection.venue_id) if target_connection is not None else None,
                "target_shift_import_id": target_shift_id,
                "target_report_id_before": target_report_before,
                "target_state_before": context["target_existing_state_by_shift_id"].get(shift_id),
            }
        )

    db.flush()
    report_counts = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    source_counts, source_report_ids = _rebuild_imported_report_keys(
        db,
        connection=source,
        run=run,
        actor_user_id=int(actor_user_id),
        affected_keys=source_keys,
    )
    for key, value in source_counts.items():
        report_counts[key] += int(value)
    report_ids = list(source_report_ids)

    target_connections = {int(value.id): value for value in context["target_by_shift_id"].values()}
    for target_connection_id, keys in target_keys_by_connection.items():
        target = target_connections[target_connection_id]
        local_counts, local_report_ids = _rebuild_imported_report_keys(
            db,
            connection=target,
            run=run,
            actor_user_id=int(actor_user_id),
            affected_keys=keys,
        )
        for key, value in local_counts.items():
            report_counts[key] += int(value)
        report_ids.extend(local_report_ids)

    db.flush()
    source_shift_by_id = {int(row.id): row for row in context["shift_imports"]}
    for row in decision_audit:
        source_shift = source_shift_by_id[int(row["shift_import_id"])]
        row["source_report_id_after"] = (
            int(source_shift.daily_report_id) if source_shift.daily_report_id is not None else None
        )
        target_connection_id = row.get("target_connection_id")
        if target_connection_id is not None:
            target_shift = db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == int(target_connection_id),
                    QuickRestoShiftImport.external_shift_id == row["external_shift_id"],
                )
            ).scalar_one()
            row["target_report_id_after"] = (
                int(target_shift.daily_report_id) if target_shift.daily_report_id is not None else None
            )
        else:
            row["target_report_id_after"] = None

    return {
        "counts_by_action": counts_by_action,
        "report_counts": report_counts,
        "report_ids": sorted(set(int(value) for value in report_ids)),
        "decision_audit": decision_audit,
        "source_keys": source_keys,
        "target_keys_by_connection": target_keys_by_connection,
    }


def _build_plan(
    db: Session,
    *,
    context: dict[str, Any],
    decisions: dict[int, str],
    note: str,
    actor_user_id: int,
) -> dict[str, Any]:
    source: QuickRestoConnection = context["connection"]
    target_connections = {int(value.id): value for value in context["target_by_shift_id"].values()}
    report_keys: list[tuple[QuickRestoConnection, date, str]] = [
        (source, target_date, slot) for target_date, slot in sorted(context["source_keys"])
    ]
    for connection_id, keys in sorted(context["target_keys_by_connection"].items()):
        connection = target_connections[connection_id]
        report_keys.extend((connection, target_date, slot) for target_date, slot in sorted(keys))

    before_scope_state = {
        "active_generation": int(source.scope_generation or 1),
        "active_external_venue_id": int(source.external_venue_id or 0) or None,
        "pending_scope": pending_quickresto_scope(source),
    }
    before_reports: dict[tuple[int, str, str], dict[str, Any] | None] = {}
    before_preconditions: dict[tuple[int, str, str], dict[str, Any] | None] = {}
    for connection, target_date, slot in report_keys:
        report_key = (int(connection.id), target_date.isoformat(), slot)
        before_reports[report_key] = _report_snapshot(
            db,
            connection=connection,
            target_date=target_date,
            shift_slot=slot,
        )
        before_preconditions[report_key] = _report_precondition(
            db,
            connection=connection,
            target_date=target_date,
            shift_slot=slot,
        )
    venue_months = {
        (int(connection.venue_id), target_date.strftime("%Y-%m")) for connection, target_date, _slot in report_keys
    }
    before_payroll = {key: _payroll_snapshot(db, venue_id=key[0], month=key[1]) for key in sorted(venue_months)}

    savepoint = db.begin_nested()
    try:
        preview_run = QuickRestoSyncRun(
            connection_id=int(source.id),
            requested_by_user_id=int(actor_user_id),
            trigger="SCOPE_RECONCILIATION",
            status="RUNNING",
            started_at=_utcnow(),
        )
        db.add(preview_run)
        db.flush()
        mutation = _apply_mutations(
            db,
            context=context,
            decisions=decisions,
            note=note,
            actor_user_id=int(actor_user_id),
            run=preview_run,
        )
        db.flush()

        # MOVE may expose a previous target key only after upsert. Merge it into
        # the stable report key set before collecting the projected state.
        merged_target_keys: dict[int, set[tuple[date, str]]] = defaultdict(set)
        for connection_id, keys in context["target_keys_by_connection"].items():
            merged_target_keys[int(connection_id)].update(keys)
        for connection_id, keys in mutation["target_keys_by_connection"].items():
            merged_target_keys[int(connection_id)].update(keys)
        final_report_keys = [(source, target_date, slot) for target_date, slot in sorted(mutation["source_keys"])]
        for connection_id, keys in sorted(merged_target_keys.items()):
            connection = target_connections[connection_id]
            final_report_keys.extend((connection, target_date, slot) for target_date, slot in sorted(keys))

        for connection, target_date, slot in final_report_keys:
            key = (int(connection.id), target_date.isoformat(), slot)
            if key not in before_reports:
                raise QuickRestoSyncError("Набор затрагиваемых отчётов изменился во время предпросмотра")

        report_rows: list[dict[str, Any]] = []
        for connection, target_date, slot in sorted(
            final_report_keys,
            key=lambda row: (int(row[0].venue_id), row[1], row[2], int(row[0].id)),
        ):
            key = (int(connection.id), target_date.isoformat(), slot)
            before = before_reports.get(key)
            after = _report_snapshot(
                db,
                connection=connection,
                target_date=target_date,
                shift_slot=slot,
                normalize_new_id=before is None,
            )
            report_rows.append(
                _report_plan_row(
                    connection=connection,
                    target_date=target_date,
                    shift_slot=slot,
                    before=before,
                    after=after,
                    precondition=before_preconditions.get(key),
                )
            )

        venue_months = {
            (int(connection.venue_id), target_date.strftime("%Y-%m"))
            for connection, target_date, _slot in final_report_keys
        }
        if any(key not in before_payroll for key in venue_months):
            raise QuickRestoSyncError("Набор затрагиваемых периодов ФОТ изменился во время предпросмотра")
        payroll_rows = [
            _payroll_plan_row(
                before_payroll[key],
                _payroll_snapshot(db, venue_id=key[0], month=key[1]),
            )
            for key in sorted(venue_months)
        ]

        shift_rows: list[dict[str, Any]] = []
        for shift in context["shift_imports"]:
            shift_id = int(shift.id)
            target = context["target_by_shift_id"].get(shift_id)
            normalized_target = context["normalized_target_by_shift_id"].get(shift_id)
            shift_rows.append(
                {
                    "shift_import_id": shift_id,
                    "external_shift_id": str(shift.external_shift_id),
                    "action": decisions[shift_id],
                    "revenue_total": int((shift.normalized_json or {}).get("revenue_total") or 0),
                    "source_connection_id": int(source.id),
                    "source_venue_id": int(source.venue_id),
                    "source_report_id": context["source_state_by_shift_id"][shift_id]["daily_report_id"],
                    "source_state": context["source_state_by_shift_id"][shift_id],
                    "target_connection_id": int(target.id) if target is not None else None,
                    "target_venue_id": int(target.venue_id) if target is not None else None,
                    "target_venue_name": (
                        db.get(Venue, int(target.venue_id)).name
                        if target is not None and db.get(Venue, int(target.venue_id)) is not None
                        else None
                    ),
                    "target_business_date": (
                        str(normalized_target.get("business_date")) if normalized_target is not None else None
                    ),
                    "target_shift_slot": (
                        str(normalized_target.get("shift_slot") or "DAY") if normalized_target is not None else None
                    ),
                    "target_state_before": context["target_existing_state_by_shift_id"].get(shift_id),
                }
            )

        report_counts = {name: 0 for name in ("CREATE", "UPDATE", "DELETE", "UNCHANGED")}
        for row in report_rows:
            report_counts[str(row["action"])] += 1
        summary = {
            "shifts_kept": sum(int(row["action"] == "KEEP_CURRENT") for row in shift_rows),
            "shifts_excluded": sum(int(row["action"] == "EXCLUDE_CURRENT") for row in shift_rows),
            "shifts_moved": sum(int(row["action"] == "MOVE_TO_CONNECTED") for row in shift_rows),
            "reports_created": report_counts["CREATE"],
            "reports_updated": report_counts["UPDATE"],
            "reports_removed": report_counts["DELETE"],
            "reports_unchanged": report_counts["UNCHANGED"],
            "revenue_delta": sum(int(row["revenue_delta"]) for row in report_rows),
            "revenue_ledger_delta_minor": sum(int(row["ledger_revenue_delta_minor"]) for row in report_rows),
            "payroll_delta_minor": sum(int(row["delta_amount_minor"]) for row in payroll_rows),
            "payroll_ledger_delta_minor": sum(int(row["delta_ledger_payroll_minor"]) for row in payroll_rows),
        }
        plan = {
            "connection_id": int(source.id),
            "issue_id": int(context["issue"].id),
            "scope_generation": int(context["target_generation"]),
            "scope_state": before_scope_state,
            "decisions": _decisions_payload(decisions),
            "summary": summary,
            "shifts": shift_rows,
            "reports": report_rows,
            "payroll": payroll_rows,
        }
        plan["plan_hash"] = _hash(plan)
        return plan
    finally:
        savepoint.rollback()
        db.expire_all()


def _sign_preview_token(
    *,
    plan: dict[str, Any],
    actor_user_id: int,
    note: str,
) -> tuple[str, datetime]:
    expires_at = _utcnow() + _PREVIEW_TTL
    payload = {
        "v": 1,
        "actor_user_id": int(actor_user_id),
        "connection_id": int(plan["connection_id"]),
        "issue_id": int(plan["issue_id"]),
        "scope_generation": int(plan["scope_generation"]),
        "decisions_hash": _hash(plan["decisions"]),
        "note_hash": _hash(str(note).strip()),
        "plan_hash": str(plan["plan_hash"]),
        "exp": int(expires_at.timestamp()),
    }
    body = _b64encode(_canonical_json(payload).encode("utf-8"))
    signature = _b64encode(hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}", expires_at


def _verify_preview_token(
    token: str,
    *,
    actor_user_id: int,
    connection_id: int,
    issue_id: int,
    decisions: dict[int, str],
    note: str,
) -> dict[str, Any]:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _b64encode(hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except Exception as exc:
        raise QuickRestoSyncError("Предпросмотр изменений недействителен. Рассчитайте изменения заново.") from exc
    if int(payload.get("exp") or 0) < int(_utcnow().timestamp()):
        raise QuickRestoSyncError("Предпросмотр изменений истёк. Рассчитайте изменения заново.")
    expected_values = {
        "actor_user_id": int(actor_user_id),
        "connection_id": int(connection_id),
        "issue_id": int(issue_id),
        "decisions_hash": _hash(_decisions_payload(decisions)),
        "note_hash": _hash(str(note).strip()),
    }
    for key, expected_value in expected_values.items():
        if payload.get(key) != expected_value:
            raise QuickRestoSyncError("Решения изменились после предпросмотра. Рассчитайте изменения заново.")
    return payload


def preview_quickresto_historical_scope_reconciliation(
    db: Session,
    *,
    connection: QuickRestoConnection,
    issue_id: int,
    decisions: dict[int, str],
    note: str,
    requested_by_user_id: int,
    allowed_target_venue_ids: set[int] | None = None,
) -> dict[str, Any]:
    normalized_decisions = _normalize_decisions(decisions)
    clean_note = str(note or "").strip()
    if len(clean_note) < 3:
        raise QuickRestoSyncError("Добавьте комментарий минимум из 3 символов")
    try:
        context = _prepare_context(
            db,
            source_connection_id=int(connection.id),
            issue_id=int(issue_id),
            decisions=normalized_decisions,
            allowed_target_venue_ids=allowed_target_venue_ids,
            for_update=True,
        )
        plan = _build_plan(
            db,
            context=context,
            decisions=normalized_decisions,
            note=clean_note,
            actor_user_id=int(requested_by_user_id),
        )
        token, expires_at = _sign_preview_token(
            plan=plan,
            actor_user_id=int(requested_by_user_id),
            note=clean_note,
        )
        db.rollback()
        return {
            **plan,
            "preview_token": token,
            "preview_expires_at": expires_at.isoformat(),
            "requires_explicit_confirmation": True,
        }
    except QuickRestoSyncError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise QuickRestoSyncError(
            "Не удалось безопасно рассчитать финансовые изменения. Проверьте отчёты и сопоставления QuickResto."
        ) from exc


def confirm_quickresto_historical_scope_reconciliation(
    db: Session,
    *,
    connection: QuickRestoConnection,
    issue_id: int,
    decisions: dict[int, str],
    note: str,
    preview_token: str,
    requested_by_user_id: int,
    allowed_target_venue_ids: set[int] | None = None,
) -> QuickRestoSyncRun:
    connection_id = int(connection.id)
    actor_user_id = int(requested_by_user_id)
    normalized_decisions = _normalize_decisions(decisions)
    clean_note = str(note or "").strip()
    token_payload = _verify_preview_token(
        preview_token,
        actor_user_id=actor_user_id,
        connection_id=connection_id,
        issue_id=int(issue_id),
        decisions=normalized_decisions,
        note=clean_note,
    )
    try:
        context = _prepare_context(
            db,
            source_connection_id=connection_id,
            issue_id=int(issue_id),
            decisions=normalized_decisions,
            allowed_target_venue_ids=allowed_target_venue_ids,
            for_update=True,
        )
        if int(token_payload.get("scope_generation") or 0) != int(context["target_generation"]):
            raise QuickRestoSyncError("Версия области QuickResto изменилась. Рассчитайте изменения заново.")
        fresh_plan = _build_plan(
            db,
            context=context,
            decisions=normalized_decisions,
            note=clean_note,
            actor_user_id=actor_user_id,
        )
        if not hmac.compare_digest(str(token_payload.get("plan_hash") or ""), str(fresh_plan["plan_hash"])):
            raise QuickRestoSyncError(
                "Данные изменились после предпросмотра. Финансовые изменения не применены; рассчитайте их заново."
            )

        # _build_plan expires ORM state after its SAVEPOINT rollback, so reload
        # the locked context while the outer transaction is still active.
        context = _prepare_context(
            db,
            source_connection_id=connection_id,
            issue_id=int(issue_id),
            decisions=normalized_decisions,
            allowed_target_venue_ids=allowed_target_venue_ids,
            for_update=True,
        )
        run = QuickRestoSyncRun(
            connection_id=connection_id,
            requested_by_user_id=actor_user_id,
            trigger="SCOPE_RECONCILIATION",
            status="RUNNING",
            started_at=_utcnow(),
        )
        db.add(run)
        db.flush()
        mutation = _apply_mutations(
            db,
            context=context,
            decisions=normalized_decisions,
            note=clean_note,
            actor_user_id=actor_user_id,
            run=run,
        )
        db.flush()

        source: QuickRestoConnection = context["connection"]
        issue: QuickRestoImportIssue = context["issue"]
        applied_plan = _build_applied_plan_from_preview(db, preview_plan=fresh_plan)
        details = dict(issue.details_json) if isinstance(issue.details_json, dict) else {}
        details.update(
            {
                "scope_generation": int(context["target_generation"]),
                "historical_decisions_kept": int(mutation["counts_by_action"]["KEEP_CURRENT"]),
                "historical_decisions_excluded": int(mutation["counts_by_action"]["EXCLUDE_CURRENT"]),
                "historical_decisions_moved": int(mutation["counts_by_action"]["MOVE_TO_CONNECTED"]),
                "reconciled_report_ids": mutation["report_ids"],
                "last_reconciliation_plan_hash": str(fresh_plan["plan_hash"]),
            }
        )
        issue.details_json = details
        transition_issue(
            db,
            issue=issue,
            status="RESOLVED",
            event_type="HISTORICAL_SCOPE_RECONCILIATION_CONFIRMED",
            actor_user_id=actor_user_id,
            sync_run_id=int(run.id),
            resolution_code="PREVIEW_CONFIRMED",
            resolution_note=clean_note,
            audit_metadata={
                "scope_generation": int(context["target_generation"]),
                "plan_hash": str(fresh_plan["plan_hash"]),
                "preview_token_hash": hashlib.sha256(str(preview_token).encode("utf-8")).hexdigest(),
                "summary": fresh_plan["summary"],
                "reports": fresh_plan["reports"],
                "payroll": fresh_plan["payroll"],
                "decisions": mutation["decision_audit"],
                "applied_reports": applied_plan,
                "actor_user_id": actor_user_id,
                "comment": clean_note,
            },
        )
        finished_at = _utcnow()
        run.status = "SUCCEEDED"
        run.finished_at = finished_at
        run.shifts_seen = len(context["shift_imports"])
        run.shifts_imported = int(mutation["counts_by_action"]["MOVE_TO_CONNECTED"])
        run.reports_created = int(mutation["report_counts"]["created"])
        run.reports_updated = int(mutation["report_counts"]["updated"])
        run.reports_unchanged = int(mutation["report_counts"]["unchanged"])
        run.summary_json = {
            "sync_mode": "HISTORICAL_SCOPE_RECONCILIATION_CONFIRMED",
            "reconciled_issue_id": int(issue_id),
            "scope_generation": int(context["target_generation"]),
            "plan_hash": str(fresh_plan["plan_hash"]),
            "shifts_seen": len(context["shift_imports"]),
            "shifts_kept": int(mutation["counts_by_action"]["KEEP_CURRENT"]),
            "shifts_excluded": int(mutation["counts_by_action"]["EXCLUDE_CURRENT"]),
            "shifts_moved": int(mutation["counts_by_action"]["MOVE_TO_CONNECTED"]),
            "reports_created": int(mutation["report_counts"]["created"]),
            "reports_updated": int(mutation["report_counts"]["updated"]),
            "reports_unchanged": int(mutation["report_counts"]["unchanged"]),
            "reports_removed": int(mutation["report_counts"]["removed"]),
            "report_ids": mutation["report_ids"],
            "financial_preview": fresh_plan["summary"],
            "issue_count": 0,
        }
        source.last_sync_started_at = run.started_at
        source.last_sync_completed_at = finished_at
        source.last_sync_status = "SUCCEEDED"
        source.last_sync_error = None
        db.commit()
        db.refresh(run)
        return run
    except QuickRestoSyncError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise QuickRestoSyncError(
            "Подтверждённый план не удалось применить безопасно. Финансовые изменения отменены."
        ) from exc


def _build_applied_plan_from_preview(db: Session, *, preview_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Capture report ids/totals after the confirmed mutation for immutable audit metadata."""
    rows: list[dict[str, Any]] = []
    connection_ids = sorted({int(item["connection_id"]) for item in preview_plan.get("reports") or []})
    connections = {
        int(row.id): row
        for row in db.execute(select(QuickRestoConnection).where(QuickRestoConnection.id.in_(connection_ids))).scalars()
    }
    for item in preview_plan.get("reports") or []:
        connection = connections.get(int(item["connection_id"]))
        if connection is None:
            continue
        target_date = date.fromisoformat(str(item["business_date"]))
        slot = str(item["shift_slot"])
        rows.append(
            {
                "connection_id": int(connection.id),
                "venue_id": int(connection.venue_id),
                "business_date": target_date.isoformat(),
                "shift_slot": slot,
                "after": _report_snapshot(
                    db,
                    connection=connection,
                    target_date=target_date,
                    shift_slot=slot,
                ),
            }
        )
    return rows
