from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.daily_report import DailyReport
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.daily_report_audit import DailyReportAudit
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.venue import Venue
from app.services.integrations.credentials import IntegrationCredentialError, decrypt_credential
from app.services.integrations.quickresto import (
    QUICKRESTO_OBJECT_TYPES,
    QuickRestoClient,
    QuickRestoConfig,
    QuickRestoError,
)
from app.services.integrations.quickresto_normalize import (
    QuickRestoDataError,
    aggregate_normalized_shifts,
    business_date_for_shift,
    normalize_closed_shift,
    shift_slot_for_shift,
)
from app.services.integrations.quickresto_issues import (
    ACTIVE_ISSUE_STATUSES,
    classify_quickresto_failure,
    connection_group_key,
    ignored_issue_matches_snapshots,
    open_source_snapshot,
    report_group_key,
    resolve_group_issue,
    snapshots_for_group,
    source_group_key,
    transition_issue,
    upsert_import_issue,
    upsert_source_snapshot,
)
from app.services.integrations.quickresto_notifications import enqueue_quickresto_import_notification
from app.services.integrations.quickresto_snapshot import (
    QuickRestoSnapshotError,
    seal_quickresto_source_snapshot,
)
from app.services.integrations.quickresto_scope import (
    QuickRestoLocationScopeError,
    QuickRestoScopeError,
    activate_pending_quickresto_scope,
    ensure_quickresto_scope_ready,
    evaluate_quickresto_shift_scope,
    load_quickresto_pending_scope_index,
    load_quickresto_scope_index,
    payment_type_is_applicable,
    pending_quickresto_scope,
    refresh_quickresto_catalog,
    selected_sale_place_ids,
    selected_store_ids,
)


_INTEGRATION_COMMENT_PREFIX = "Импортировано из QuickResto:"
_SYNC_LEASE_TIMEOUT = timedelta(minutes=30)
_STALE_SYNC_MESSAGE = "Предыдущий импорт QuickResto не завершился и был автоматически восстановлен."


class QuickRestoSyncError(RuntimeError):
    """Raised when a QuickResto sync cannot complete safely."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def quickresto_sync_is_active(
    connection: QuickRestoConnection,
    *,
    now: datetime | None = None,
) -> bool:
    if str(connection.last_sync_status or "").upper() != "RUNNING":
        return False
    started_at = connection.last_sync_started_at
    if started_at is None:
        return False
    return _ensure_utc(started_at) > (now or _utcnow()) - _SYNC_LEASE_TIMEOUT


def reclaim_stale_quickresto_sync_state(
    db: Session,
    *,
    connection: QuickRestoConnection,
    now: datetime | None = None,
) -> bool:
    """Recover runs/issues left RUNNING after a worker process died.

    The caller must hold the connection row lock. A fresh lease is never
    modified; stale work is made retryable without incrementing attempts.
    """

    timestamp = now or _utcnow()
    if quickresto_sync_is_active(connection, now=timestamp):
        return False
    cutoff = timestamp - _SYNC_LEASE_TIMEOUT
    changed = False
    stale_runs = list(
        db.execute(
            select(QuickRestoSyncRun)
            .where(
                QuickRestoSyncRun.connection_id == int(connection.id),
                QuickRestoSyncRun.status == "RUNNING",
                QuickRestoSyncRun.started_at <= cutoff,
            )
            .with_for_update()
        ).scalars()
    )
    for stale_run in stale_runs:
        stale_run.status = "FAILED"
        stale_run.finished_at = timestamp
        stale_run.error_message = _STALE_SYNC_MESSAGE
        changed = True

    stale_issues = list(
        db.execute(
            select(QuickRestoImportIssue)
            .where(
                QuickRestoImportIssue.connection_id == int(connection.id),
                QuickRestoImportIssue.status == "PROCESSING",
                (
                    QuickRestoImportIssue.processing_started_at.is_(None)
                    | (QuickRestoImportIssue.processing_started_at <= cutoff)
                ),
            )
            .with_for_update()
        ).scalars()
    )
    for stale_issue in stale_issues:
        transition_issue(
            db,
            issue=stale_issue,
            status="OPEN",
            event_type="PROCESSING_LEASE_EXPIRED",
            resolution_code="LEASE_EXPIRED",
            resolution_note=_STALE_SYNC_MESSAGE,
        )
        changed = True

    if str(connection.last_sync_status or "").upper() == "RUNNING":
        connection.last_sync_status = "FAILED"
        connection.last_sync_completed_at = timestamp
        connection.last_sync_error = _STALE_SYNC_MESSAGE
        changed = True
    if changed:
        db.flush()
    return changed


def _classify_snapshot_group_failure(exc: BaseException):
    """Classify one report-group failure and report unexpected defects.

    Expected source/mapping/storage failures are operational states. Unexpected
    exceptions are still converted into a durable issue for the affected
    shifts, but also go to Sentry so the underlying defect can be fixed.
    """

    correlation_id = None
    if not isinstance(
        exc,
        (
            QuickRestoError,
            QuickRestoDataError,
            QuickRestoSnapshotError,
            IntegrationCredentialError,
            ValueError,
        ),
    ):
        try:
            import sentry_sdk

            correlation_id = sentry_sdk.capture_exception(exc)
        except Exception:
            correlation_id = None
    return classify_quickresto_failure(exc, correlation_id=correlation_id)


def _record_failed_run(
    db: Session,
    *,
    run_id: int,
    connection_id: int,
    message: str,
) -> None:
    db.rollback()
    run = db.get(QuickRestoSyncRun, run_id)
    connection = db.get(QuickRestoConnection, connection_id)
    finished_at = _utcnow()
    if run is not None:
        run.status = "FAILED"
        run.finished_at = finished_at
        run.error_message = message[:1000]
    if connection is not None:
        connection.last_sync_completed_at = finished_at
        connection.last_sync_status = "FAILED"
        connection.last_sync_error = message[:1000]
    db.commit()


def _enqueue_sync_notification_safely(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    issue_count: int,
    technical_summary: str | None = None,
    correlation_id: str | None = None,
    force: bool = False,
) -> None:
    """Queue the aggregate result without ever rolling back a completed sync."""

    should_notify = bool(
        force
        or str(run.status or "").upper() in {"PARTIAL", "FAILED"}
        or int(run.shifts_imported or 0) > 0
        or int(run.reports_created or 0) > 0
        or int(run.reports_updated or 0) > 0
    )
    if not should_notify:
        return
    try:
        enqueue_quickresto_import_notification(
            db,
            venue_id=int(connection.venue_id),
            connection_id=int(connection.id),
            run_id=int(run.id),
            status=str(run.status or "FAILED"),
            shifts_seen=int(run.shifts_seen or 0),
            shifts_imported=int(run.shifts_imported or 0),
            reports_created=int(run.reports_created or 0),
            reports_updated=int(run.reports_updated or 0),
            reports_unchanged=int(run.reports_unchanged or 0),
            issue_count=max(int(issue_count or 0), 0),
            report_import_mode=str(connection.report_import_mode or "CLOSED"),
            technical_summary=technical_summary,
            correlation_id=correlation_id,
        )
        db.commit()
    except Exception as exc:
        # Notification delivery is explicitly outside the accounting
        # transaction. Record the queueing failure for operators, but never
        # turn an already committed report import into a failed sync.
        db.rollback()
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except Exception:
            pass


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _unique_title_map(items: list[Any]) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        key = _normalize_label(getattr(item, "title", ""))
        if key:
            grouped[key].append(item)
    return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}


def _catalog_code(prefix: str, external_id: int, used_codes: set[str]) -> str:
    base = f"quickresto-{prefix}-{external_id}"[:64]
    candidate = base
    suffix = 2
    while candidate in used_codes:
        marker = f"-{suffix}"
        candidate = f"{base[: 64 - len(marker)]}{marker}"
        suffix += 1
    used_codes.add(candidate)
    return candidate


def _catalog_title(value: str) -> str:
    return value[:120]


def _mapping_title(value: str) -> str:
    return value[:160]


def _object_rows(client: QuickRestoClient, key: str) -> list[dict[str, Any]]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES[key]
    return client.list_all_objects(module_name=module_name, class_name=class_name)


def _object_detail(client: QuickRestoClient, key: str, object_id: int) -> dict[str, Any]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES[key]
    return client.read_object(module_name=module_name, class_name=class_name, object_id=object_id)


def _object_rows_with_details(
    client: QuickRestoClient,
    key: str,
    *,
    required_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in _object_rows(client, key):
        object_id = int(row.get("id") or 0)
        if object_id > 0 and any(field not in row for field in required_fields):
            detail = _object_detail(client, key, object_id)
            if isinstance(detail, dict):
                row = detail
        output.append(row)
    return output


def build_quickresto_client(connection: QuickRestoConnection) -> QuickRestoClient:
    return QuickRestoClient(
        QuickRestoConfig(
            cloud=connection.cloud,
            login=decrypt_credential(connection.api_login_encrypted),
            password=decrypt_credential(connection.api_password_encrypted),
        )
    )


def refresh_quickresto_mappings(
    db: Session,
    *,
    connection: QuickRestoConnection,
    client: QuickRestoClient,
) -> dict[str, Any]:
    payment_rows = _object_rows_with_details(
        client,
        "payment_types",
        required_fields=("allowedSalePlacesWeb",),
    )
    department_rows = _object_rows(client, "dish_categories")
    selected_sale_ids = selected_sale_place_ids(db, connection_id=int(connection.id))
    scope_filter_enabled = bool(
        str(getattr(connection, "scope_status", "") or "").upper() == "READY"
        and getattr(connection, "external_venue_id", None)
    )
    db.execute(
        select(QuickRestoConnection.id).where(QuickRestoConnection.id == connection.id).with_for_update()
    ).scalar_one()
    internal_payments = (
        db.execute(select(PaymentMethod).where(PaymentMethod.venue_id == connection.venue_id)).scalars().all()
    )
    internal_departments = (
        db.execute(select(Department).where(Department.venue_id == connection.venue_id)).scalars().all()
    )
    active_payments = [item for item in internal_payments if item.is_active]
    active_departments = [item for item in internal_departments if item.is_active]
    payment_by_title = _unique_title_map(active_payments)
    department_by_title = _unique_title_map(active_departments)
    known_payment_titles = {_normalize_label(item.title) for item in active_payments if _normalize_label(item.title)}
    known_department_titles = {
        _normalize_label(item.title) for item in active_departments if _normalize_label(item.title)
    }
    used_payment_codes = {str(item.code) for item in internal_payments}
    used_department_codes = {str(item.code) for item in internal_departments}
    next_payment_sort = max((int(item.sort_order or 0) for item in internal_payments), default=0) + 1
    next_department_sort = max((int(item.sort_order or 0) for item in internal_departments), default=0) + 1
    payment_methods_created = 0
    departments_created = 0

    existing_payments = {
        int(item.external_id): item
        for item in db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == connection.id)
        ).scalars()
    }
    existing_departments = {
        int(item.external_id): item
        for item in db.execute(
            select(QuickRestoDepartmentMapping).where(QuickRestoDepartmentMapping.connection_id == connection.id)
        ).scalars()
    }
    for mapping in existing_payments.values():
        mapping.is_available = False
        mapping.is_applicable = False

    for row in payment_rows:
        external_id = int(row.get("id") or 0)
        if external_id <= 0:
            continue
        name = str(row.get("name") or row.get("itemTitle") or f"#{external_id}").strip()
        operation_type = str(row.get("operationType") or "").strip().lower()
        mechanism = str(row.get("paymentMechanismWeb") or "").strip().lower() or None
        allowed_sale_place_ids = sorted(
            {
                int(item.get("id"))
                for item in (row.get("allowedSalePlacesWeb") or ())
                if isinstance(item, dict) and int(item.get("id") or 0) > 0
            }
        )
        applicable = (
            payment_type_is_applicable(
                allowed_sale_place_ids=allowed_sale_place_ids,
                selected_ids=selected_sale_ids,
            )
            if scope_filter_enabled
            else True
        )
        excluded = operation_type == "writeoff"
        mapping = existing_payments.get(external_id)
        catalog_title = _catalog_title(name)
        title_key = _normalize_label(catalog_title)
        auto_match = payment_by_title.get(title_key)
        needs_payment_target = applicable and (mapping is None or mapping.payment_method_id is None)
        if not excluded and needs_payment_target and auto_match is None and title_key not in known_payment_titles:
            auto_match = PaymentMethod(
                venue_id=connection.venue_id,
                code=_catalog_code("payment", external_id, used_payment_codes),
                title=catalog_title,
                is_active=True,
                sort_order=next_payment_sort,
            )
            next_payment_sort += 1
            db.add(auto_match)
            db.flush()
            internal_payments.append(auto_match)
            known_payment_titles.add(title_key)
            payment_by_title[title_key] = auto_match
            payment_methods_created += 1
        if mapping is None:
            mapping = QuickRestoPaymentMapping(
                connection_id=connection.id,
                external_id=external_id,
                external_name=_mapping_title(name),
                operation_type=operation_type,
                payment_mechanism=mechanism,
                payment_method_id=None if excluded or auto_match is None else int(auto_match.id),
                excluded_from_revenue=excluded,
                is_applicable=applicable,
                is_available=True,
                allowed_sale_place_ids_json=allowed_sale_place_ids,
                last_seen_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(mapping)
            existing_payments[external_id] = mapping
        else:
            mapping.external_name = _mapping_title(name)
            mapping.operation_type = operation_type
            mapping.payment_mechanism = mechanism
            mapping.excluded_from_revenue = excluded
            mapping.is_applicable = applicable
            mapping.is_available = True
            mapping.allowed_sale_place_ids_json = allowed_sale_place_ids
            mapping.last_seen_at = _utcnow()
            if excluded:
                mapping.payment_method_id = None
            elif mapping.payment_method_id is None:
                if auto_match is not None:
                    mapping.payment_method_id = int(auto_match.id)
            mapping.updated_at = _utcnow()

    for row in department_rows:
        external_id = int(row.get("id") or 0)
        if external_id <= 0:
            continue
        name = str(row.get("name") or row.get("itemTitle") or f"#{external_id}").strip()
        mapping = existing_departments.get(external_id)
        catalog_title = _catalog_title(name)
        title_key = _normalize_label(catalog_title)
        auto_match = department_by_title.get(title_key)
        needs_department_target = mapping is None or mapping.department_id is None
        if needs_department_target and auto_match is None and title_key not in known_department_titles:
            auto_match = Department(
                venue_id=connection.venue_id,
                code=_catalog_code("department", external_id, used_department_codes),
                title=catalog_title,
                is_active=True,
                sort_order=next_department_sort,
            )
            next_department_sort += 1
            db.add(auto_match)
            db.flush()
            internal_departments.append(auto_match)
            known_department_titles.add(title_key)
            department_by_title[title_key] = auto_match
            departments_created += 1
        if mapping is None:
            mapping = QuickRestoDepartmentMapping(
                connection_id=connection.id,
                external_id=external_id,
                external_name=_mapping_title(name),
                department_id=int(auto_match.id) if auto_match is not None else None,
                updated_at=_utcnow(),
            )
            db.add(mapping)
            existing_departments[external_id] = mapping
        else:
            mapping.external_name = _mapping_title(name)
            if mapping.department_id is None:
                if auto_match is not None:
                    mapping.department_id = int(auto_match.id)
            mapping.updated_at = _utcnow()

    db.flush()
    return {
        "payment_types_seen": sum(int(item.is_applicable) for item in existing_payments.values()),
        "payment_types_available": len(payment_rows),
        "departments_seen": len(department_rows),
        "payment_methods_created": payment_methods_created,
        "departments_created": departments_created,
        "unmapped_payment_type_ids": sorted(
            item.external_id
            for item in existing_payments.values()
            if item.is_applicable and not item.excluded_from_revenue and item.payment_method_id is None
        ),
        "unmapped_department_ids": sorted(
            item.external_id for item in existing_departments.values() if item.department_id is None
        ),
    }


def _mapped_aggregate(
    db: Session,
    *,
    connection: QuickRestoConnection,
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    payment_mappings = {
        str(item.external_id): item
        for item in db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == connection.id)
        ).scalars()
    }
    department_mappings = {
        str(item.external_id): item
        for item in db.execute(
            select(QuickRestoDepartmentMapping).where(QuickRestoDepartmentMapping.connection_id == connection.id)
        ).scalars()
    }

    payments_internal: dict[int, int] = defaultdict(int)
    departments_internal: dict[int, int] = defaultdict(int)
    missing_payments: list[int] = []
    missing_departments: list[int] = []
    scope_filter_enabled = bool(
        str(getattr(connection, "scope_status", "") or "").upper() == "READY"
        and getattr(connection, "external_venue_id", None)
    )
    for external_id, value in (aggregate.get("payments_external") or {}).items():
        if not int(value or 0):
            continue
        mapping = payment_mappings.get(str(external_id))
        if (
            mapping is None
            or (scope_filter_enabled and (not mapping.is_available or not mapping.is_applicable))
            or (mapping.payment_method_id is None and not mapping.excluded_from_revenue)
        ):
            missing_payments.append(int(external_id))
            continue
        if mapping.excluded_from_revenue:
            continue
        payments_internal[int(mapping.payment_method_id)] += int(value)

    for external_id, value in (aggregate.get("departments_external") or {}).items():
        if not int(value or 0):
            continue
        mapping = department_mappings.get(str(external_id))
        if mapping is None or mapping.department_id is None:
            missing_departments.append(int(external_id))
            continue
        departments_internal[int(mapping.department_id)] += int(value)

    if missing_payments or missing_departments:
        raise QuickRestoDataError(
            "QuickResto mappings are incomplete"
            f" (payments={sorted(missing_payments)}, departments={sorted(missing_departments)})"
        )
    payment_total = sum(payments_internal.values())
    department_total = sum(departments_internal.values())
    expected = int(aggregate.get("revenue_total") or 0)
    if payment_total != expected or department_total != expected:
        raise QuickRestoDataError("Mapped QuickResto totals do not reconcile")
    return {
        **aggregate,
        "payments_internal": dict(sorted(payments_internal.items())),
        "departments_internal": dict(sorted(departments_internal.items())),
    }


def _report_values(db: Session, report_id: int, kind: str) -> dict[int, int]:
    return {
        int(row.ref_id): int(row.value_numeric or 0)
        for row in db.execute(
            select(DailyReportValue).where(
                DailyReportValue.report_id == report_id,
                DailyReportValue.kind == kind,
            )
        ).scalars()
    }


def _aggregate_values(aggregate: dict[str, Any], key: str) -> dict[int, int]:
    return {int(ref_id): int(value or 0) for ref_id, value in (aggregate.get(key) or {}).items()}


def _report_values_match(db: Session, report: DailyReport, aggregate: dict[str, Any]) -> bool:
    return (
        int(report.revenue_total or 0) == int(aggregate["revenue_total"])
        and _report_values(db, report.id, "PAYMENT") == _aggregate_values(aggregate, "payments_internal")
        and _report_values(db, report.id, "DEPT") == _aggregate_values(aggregate, "departments_internal")
    )


def _report_matches(db: Session, report: DailyReport, aggregate: dict[str, Any]) -> bool:
    return str(report.status or "").upper() == "DRAFT" and _report_values_match(db, report, aggregate)


def _report_is_empty_draft(db: Session, report: DailyReport) -> bool:
    return (
        str(report.status or "").upper() == "DRAFT"
        and int(report.revenue_total or 0) == 0
        and int(report.cash or 0) == 0
        and int(report.cashless or 0) == 0
        and not _report_values(db, report.id, "PAYMENT")
        and not _report_values(db, report.id, "DEPT")
    )


def _legacy_payment_totals(
    db: Session,
    *,
    venue_id: int,
    aggregate: dict[str, Any],
) -> tuple[int, int]:
    payment_methods = {
        int(item.id): str(item.code or "")
        for item in db.execute(select(PaymentMethod).where(PaymentMethod.venue_id == venue_id)).scalars()
    }
    cash = sum(
        int(value)
        for ref_id, value in aggregate["payments_internal"].items()
        if payment_methods.get(int(ref_id)) == "cash"
    )
    cashless = sum(
        int(value)
        for ref_id, value in aggregate["payments_internal"].items()
        if payment_methods.get(int(ref_id)) == "cashless"
    )
    return cash, cashless


def _remove_empty_imported_report(
    db: Session,
    *,
    connection: QuickRestoConnection,
    business_date: date,
    shift_slot: str,
    actor_user_id: int,
) -> bool:
    source = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == connection.id,
            QuickRestoReportImport.business_date == business_date,
            QuickRestoReportImport.shift_slot == shift_slot,
        )
    ).scalar_one_or_none()
    if source is None:
        return False

    report = db.get(DailyReport, int(source.daily_report_id))
    if report is None:
        raise QuickRestoDataError("QuickResto report source points to a missing Axelio report")
    if (
        int(report.venue_id) != int(connection.venue_id)
        or report.date != business_date
        or str(report.shift_slot or "DAY").upper() != shift_slot
    ):
        raise QuickRestoDataError("QuickResto report source points to another Axelio report key")
    if str(report.status or "").upper() not in {"DRAFT", "CLOSED"}:
        raise QuickRestoDataError(f"Axelio report {report.id} cannot be regrouped by QuickResto")
    if not str(report.comment or "").startswith(_INTEGRATION_COMMENT_PREFIX):
        raise QuickRestoDataError(f"Axelio report {report.id} has a manual comment and cannot be regrouped")
    if not _report_values_match(db, report, source.summary_json):
        raise QuickRestoDataError(f"Axelio report {report.id} was edited and cannot be regrouped")
    expected_cash, expected_cashless = _legacy_payment_totals(
        db,
        venue_id=int(connection.venue_id),
        aggregate=source.summary_json,
    )
    if (
        int(report.cash or 0) != expected_cash
        or int(report.cashless or 0) != expected_cashless
        or int(report.tips_total or 0) != 0
    ):
        raise QuickRestoDataError(f"Axelio report {report.id} has manual totals and cannot be regrouped")
    has_manual_values = db.execute(
        select(DailyReportValue.id)
        .where(DailyReportValue.report_id == report.id, DailyReportValue.kind == "KPI")
        .limit(1)
    ).scalar_one_or_none()
    has_audit = db.execute(
        select(DailyReportAudit.id).where(DailyReportAudit.report_id == report.id).limit(1)
    ).scalar_one_or_none()
    has_attachment = db.execute(
        select(DailyReportAttachment.id)
        .where(
            DailyReportAttachment.venue_id == connection.venue_id,
            DailyReportAttachment.report_date == business_date,
            DailyReportAttachment.shift_slot == shift_slot,
            DailyReportAttachment.is_active.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if has_manual_values is not None or has_audit is not None or has_attachment is not None:
        raise QuickRestoDataError(f"Axelio report {report.id} contains manual data and cannot be regrouped")

    was_closed = str(report.status or "").upper() == "CLOSED"
    if was_closed:
        from app.routers.venue_payroll_support import _recalculate_payroll_for_dates
        from app.routers.venue_reports import _sync_recurring_accruals_after_report_reopen
        from app.services.finance.revenue import delete_revenue_entries_for_report

        report.status = "DRAFT"
        report.closed_by_user_id = None
        report.closed_at = None
        delete_revenue_entries_for_report(db=db, report_id=int(report.id))
        db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == report.id))
        db.flush()
        _sync_recurring_accruals_after_report_reopen(db, report=report)
        _recalculate_payroll_for_dates(
            db,
            venue_id=int(connection.venue_id),
            target_dates=[business_date],
            calculated_by_user_id=int(actor_user_id),
            force=True,
            trigger_reason="quickresto_regroup",
            details={
                "source": "quickresto",
                "connection_id": int(connection.id),
                "removed_report_id": int(report.id),
            },
        )

    db.execute(
        update(QuickRestoShiftImport)
        .where(QuickRestoShiftImport.daily_report_id == report.id)
        .values(daily_report_id=None)
    )
    db.delete(source)
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == report.id))
    db.execute(delete(DailyReportAudit).where(DailyReportAudit.report_id == report.id))
    db.execute(delete(DailyReportValue).where(DailyReportValue.report_id == report.id))
    db.flush()
    db.delete(report)
    db.flush()
    return True


def _replace_report_values(db: Session, report: DailyReport, aggregate: dict[str, Any]) -> None:
    db.execute(
        delete(DailyReportValue).where(
            DailyReportValue.report_id == report.id,
            DailyReportValue.kind.in_(["PAYMENT", "DEPT"]),
        )
    )
    for kind, key in (("PAYMENT", "payments_internal"), ("DEPT", "departments_internal")):
        for ref_id, value in aggregate[key].items():
            if int(value or 0):
                db.add(
                    DailyReportValue(
                        report_id=report.id,
                        kind=kind,
                        ref_id=int(ref_id),
                        value_numeric=int(value),
                    )
                )


def _close_imported_report(
    db: Session,
    *,
    connection: QuickRestoConnection,
    report: DailyReport,
    aggregate: dict[str, Any],
    actor_user_id: int,
) -> None:
    # Import locally so the integration service can reuse the exact same
    # accounting and notification transition as the report API without a
    # module-import cycle during application startup.
    from app.routers.venue_reports import _close_daily_report_record

    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        raise QuickRestoDataError("Axelio venue no longer exists")
    try:
        _close_daily_report_record(
            db,
            report=report,
            venue=venue,
            actor_user_id=int(actor_user_id),
            comment=report.comment,
            trigger_reason="quickresto_import",
            notification_event_key=(
                f"quickresto:connection:{int(connection.id)}:report:{int(report.id)}:{str(aggregate['aggregate_hash'])}"
            ),
            recalculation_details={
                "source": "quickresto",
                "connection_id": int(connection.id),
                "report_id": int(report.id),
            },
        )
    except ValueError as exc:
        raise QuickRestoDataError(f"QuickResto report could not be closed: {exc}") from exc


def _upsert_draft_report(
    db: Session,
    *,
    connection: QuickRestoConnection,
    aggregate: dict[str, Any],
    run: QuickRestoSyncRun,
    actor_user_id: int,
) -> tuple[str, DailyReport]:
    business_date = date.fromisoformat(str(aggregate["business_date"]))
    shift_slot = str(aggregate.get("shift_slot") or "DAY").upper()
    if shift_slot not in {"DAY", "NIGHT"}:
        raise QuickRestoDataError("QuickResto report has an invalid shift slot")
    report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == connection.venue_id,
            DailyReport.date == business_date,
            DailyReport.shift_slot == shift_slot,
        )
    ).scalar_one_or_none()
    source = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == connection.id,
            QuickRestoReportImport.business_date == business_date,
            QuickRestoReportImport.shift_slot == shift_slot,
        )
    ).scalar_one_or_none()

    created = False
    auto_close = str(connection.report_import_mode or "CLOSED").upper() == "CLOSED"
    if report is None:
        report = DailyReport(
            venue_id=connection.venue_id,
            date=business_date,
            shift_slot=shift_slot,
            cash=0,
            cashless=0,
            revenue_total=0,
            tips_total=0,
            status="DRAFT",
            comment=(
                f"{_INTEGRATION_COMMENT_PREFIX} {int(aggregate['shift_count'])} закрытых смен; "
                f"списания {int(aggregate['writeoff_total'])} ₽ исключены из выручки."
            ),
            created_by_user_id=actor_user_id,
        )
        db.add(report)
        db.flush()
        created = True
    elif source is None and not (_report_matches(db, report, aggregate) or _report_is_empty_draft(db, report)):
        raise QuickRestoDataError(
            f"Axelio report {report.id} already exists and is neither empty nor an exact QuickResto draft"
        )

    if source is not None and int(source.daily_report_id) != int(report.id):
        raise QuickRestoDataError("QuickResto report source points to another Axelio report")
    if source is not None and source.aggregate_hash == aggregate["aggregate_hash"]:
        if str(report.status or "").upper() == "DRAFT":
            if not auto_close:
                return "unchanged", report
            if not _report_matches(db, report, aggregate):
                raise QuickRestoDataError(
                    f"Axelio report {report.id} was reopened and now differs from its QuickResto import"
                )
            _close_imported_report(
                db,
                connection=connection,
                report=report,
                aggregate=aggregate,
                actor_user_id=actor_user_id,
            )
            source.last_sync_run_id = run.id
            source.updated_at = _utcnow()
            db.flush()
            return "updated", report
        return "unchanged", report
    report_status = str(report.status or "").upper()
    if report_status == "CLOSED":
        if not auto_close or source is None or not _report_values_match(db, report, source.summary_json):
            raise QuickRestoDataError(f"Axelio report {report.id} is closed and cannot be changed by QuickResto")
        # A venue can close several till shifts on the same business day. If
        # Axelio already auto-closed the imported report, safely reopen only
        # its integration-owned values and immediately close it again below.
        # The aggregate hash in the notification key keeps repeated runs
        # idempotent while a genuinely new shift produces a fresh event.
        report.status = "DRAFT"
        report.closed_by_user_id = None
        report.closed_at = None
    elif report_status != "DRAFT":
        raise QuickRestoDataError(f"Axelio report {report.id} cannot be changed by QuickResto")
    if source is not None and not _report_matches(db, report, source.summary_json):
        raise QuickRestoDataError(
            f"Axelio report {report.id} was edited and cannot be overwritten by a changed QuickResto import"
        )

    _replace_report_values(db, report, aggregate)
    report.revenue_total = int(aggregate["revenue_total"])
    report.cash, report.cashless = _legacy_payment_totals(
        db,
        venue_id=int(connection.venue_id),
        aggregate=aggregate,
    )
    report.updated_by_user_id = actor_user_id
    report.updated_at = _utcnow()
    if not report.comment or str(report.comment).startswith(_INTEGRATION_COMMENT_PREFIX):
        report.comment = (
            f"{_INTEGRATION_COMMENT_PREFIX} {int(aggregate['shift_count'])} закрытых смен; "
            f"списания {int(aggregate['writeoff_total'])} ₽ исключены из выручки."
        )

    if source is None:
        source = QuickRestoReportImport(
            connection_id=connection.id,
            daily_report_id=report.id,
            business_date=business_date,
            shift_slot=shift_slot,
            aggregate_hash=str(aggregate["aggregate_hash"]),
            shift_count=int(aggregate["shift_count"]),
            writeoff_total=int(aggregate["writeoff_total"]),
            discount_total=int(aggregate["discount_total"]),
            summary_json=aggregate,
            last_sync_run_id=run.id,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(source)
    else:
        source.aggregate_hash = str(aggregate["aggregate_hash"])
        source.shift_count = int(aggregate["shift_count"])
        source.writeoff_total = int(aggregate["writeoff_total"])
        source.discount_total = int(aggregate["discount_total"])
        source.summary_json = aggregate
        source.last_sync_run_id = run.id
        source.updated_at = _utcnow()
    if auto_close:
        _close_imported_report(
            db,
            connection=connection,
            report=report,
            aggregate=aggregate,
            actor_user_id=actor_user_id,
        )
    db.flush()
    return "created" if created else "updated", report


def _remote_closed_at(shift: dict[str, Any]) -> datetime | None:
    for field in ("closed", "localClosedTime"):
        raw = str(shift.get(field) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        return _ensure_utc(parsed)
    return None


def _list_closed_shift_rows(
    client: QuickRestoClient,
    *,
    closed_since: datetime | None,
) -> list[dict[str, Any]]:
    if hasattr(client, "list_closed_shifts"):
        rows = client.list_closed_shifts(closed_since=closed_since)
    else:
        rows = _object_rows(client, "shifts")
    output = [row for row in rows if str(row.get("status") or "").upper() == "CLOSED"]
    if closed_since is not None and not hasattr(client, "list_closed_shifts"):
        output = [row for row in output if (closed_at := _remote_closed_at(row)) is None or closed_at >= closed_since]
    return output


def _list_order_rows_for_shifts(
    client: QuickRestoClient,
    *,
    shift_ids: set[str],
) -> list[dict[str, Any]]:
    if not shift_ids:
        return []
    if hasattr(client, "list_orders_for_shift_ids"):
        return client.list_orders_for_shift_ids(shift_ids)
    return [row for row in _object_rows(client, "orders") if str(row.get("shiftId") or "") in shift_ids]


def _scope_resolution_requires_review(scope_generation: int):
    target_generation = int(scope_generation)
    return or_(
        QuickRestoShiftImport.scope_resolution_action.is_(None),
        QuickRestoShiftImport.scope_resolution_generation.is_(None),
        QuickRestoShiftImport.scope_resolution_generation != target_generation,
    )


def _sync_previous_scope_mismatch_issue(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    mismatch_external_ids: set[str],
    scope_generation: int | None = None,
    selected_external_venue_id: int | None = None,
) -> QuickRestoImportIssue | None:
    target_generation = int(scope_generation or connection.scope_generation or 1)
    group_key = connection_group_key("PREVIOUS_SCOPE_MISMATCH")
    existing = db.execute(
        select(QuickRestoImportIssue).where(
            QuickRestoImportIssue.connection_id == int(connection.id),
            QuickRestoImportIssue.group_key == group_key,
        )
    ).scalar_one_or_none()
    normalized_ids = sorted(str(value) for value in mismatch_external_ids if str(value))
    if not normalized_ids:
        if existing is not None and str(existing.status or "").upper() in ACTIVE_ISSUE_STATUSES:
            transition_issue(
                db,
                issue=existing,
                status="RESOLVED",
                event_type="SCOPE_RECONCILED",
                actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
                sync_run_id=int(run.id),
                resolution_code="CURRENT_SCOPE_VERIFIED",
                resolution_note="Историческая сверка не обнаружила смен вне текущей области QuickResto.",
            )
        return None
    shift_imports = list(
        db.execute(
            select(QuickRestoShiftImport)
            .where(
                QuickRestoShiftImport.connection_id == int(connection.id),
                QuickRestoShiftImport.external_shift_id.in_(normalized_ids),
                _scope_resolution_requires_review(target_generation),
            )
            .order_by(
                QuickRestoShiftImport.business_date.asc(),
                QuickRestoShiftImport.shift_slot.asc(),
                QuickRestoShiftImport.id.asc(),
            )
        ).scalars()
    )
    normalized_ids = [str(item.external_shift_id) for item in shift_imports]
    if not normalized_ids:
        if existing is not None and str(existing.status or "").upper() in ACTIVE_ISSUE_STATUSES:
            transition_issue(
                db,
                issue=existing,
                status="RESOLVED",
                event_type="SCOPE_RECONCILED",
                actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
                sync_run_id=int(run.id),
                resolution_code="HISTORICAL_DECISIONS_RECORDED",
                resolution_note="Для всех исторических смен уже сохранено явное решение.",
            )
        return None
    affected_report_ids = sorted({int(item.daily_report_id) for item in shift_imports if item.daily_report_id})
    scope_error = QuickRestoLocationScopeError(
        error_code="PREVIOUS_SCOPE_MISMATCH",
        user_summary=(
            "Ранее импортированные смены не соответствуют текущей области QuickResto. "
            "Проверьте историю — Axelio не изменяет старые отчёты автоматически."
        ),
        technical_summary="Historical QuickResto imports contain shifts outside the confirmed current scope",
        details={
            "selected_external_venue_id": selected_external_venue_id or int(connection.external_venue_id or 0) or None,
            "scope_generation": target_generation,
            "legacy_shift_count": len(normalized_ids),
            "legacy_external_shift_ids": normalized_ids[:100],
            "affected_report_ids": affected_report_ids,
        },
    )
    failure = classify_quickresto_failure(scope_error)
    issue = upsert_import_issue(
        db,
        connection_id=int(connection.id),
        sync_run_id=int(run.id),
        group_key=group_key,
        business_date=None,
        shift_slot=None,
        failure=failure,
        actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
    )
    now = _utcnow()
    latest_snapshots: dict[str, QuickRestoSourceSnapshot] = {}
    snapshots = list(
        db.execute(
            select(QuickRestoSourceSnapshot)
            .where(
                QuickRestoSourceSnapshot.connection_id == int(connection.id),
                QuickRestoSourceSnapshot.external_shift_id.in_(normalized_ids),
            )
            .order_by(QuickRestoSourceSnapshot.updated_at.desc(), QuickRestoSourceSnapshot.id.desc())
        ).scalars()
    )
    for snapshot in snapshots:
        latest_snapshots.setdefault(str(snapshot.external_shift_id), snapshot)

    existing_items = {int(item.shift_import_id): item for item in issue.shifts if item.shift_import_id is not None}
    keep_shift_import_ids: set[int] = set()
    for shift_import in shift_imports:
        shift_import_id = int(shift_import.id)
        keep_shift_import_ids.add(shift_import_id)
        item = existing_items.get(shift_import_id)
        if item is None:
            item = QuickRestoImportIssueShift(
                source_key=f"historical:{shift_import_id}",
                created_at=now,
            )
            issue.shifts.append(item)
        snapshot = latest_snapshots.get(str(shift_import.external_shift_id))
        normalized = shift_import.normalized_json if isinstance(shift_import.normalized_json, dict) else {}
        raw_opened_at = normalized.get("local_opened_at")
        local_opened_at = None
        if raw_opened_at:
            try:
                local_opened_at = datetime.fromisoformat(str(raw_opened_at))
            except ValueError:
                local_opened_at = None
        item.source_snapshot_id = int(snapshot.id) if snapshot is not None else None
        item.shift_import_id = shift_import_id
        item.external_shift_id = shift_import.external_shift_id
        item.external_shift_pk = int(shift_import.external_shift_pk)
        item.source_version = int(shift_import.source_version)
        item.source_fingerprint = snapshot.source_fingerprint if snapshot is not None else None
        item.local_opened_at = snapshot.local_opened_at if snapshot is not None else local_opened_at
        item.local_closed_at = shift_import.local_closed_at
        item.item_status = "READY"
        item.error_code = "PREVIOUS_SCOPE_MISMATCH"
        item.user_summary = "Выберите, оставить смену в текущем отчёте или исключить из этого заведения."
        item.technical_summary = None
        item.updated_at = now
    for item in list(issue.shifts):
        if item.shift_import_id is None or int(item.shift_import_id) not in keep_shift_import_ids:
            db.delete(item)
    db.flush()
    return issue


def _stage_quickresto_sources(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    venue: Venue,
    client: QuickRestoClient,
    force_full: bool,
) -> tuple[list[QuickRestoSourceSnapshot], bool, dict[str, Any], list[dict[str, Any]]]:
    now = _utcnow()
    pending_scope = pending_quickresto_scope(connection)
    last_full = connection.last_full_reconciliation_at
    full_reconciliation = bool(
        pending_scope or force_full or last_full is None or _ensure_utc(last_full) <= now - timedelta(days=30)
    )
    closed_since = None
    if not full_reconciliation and connection.incremental_cursor_closed_at is not None:
        closed_since = _ensure_utc(connection.incremental_cursor_closed_at) - timedelta(hours=48)
    closed_shifts = _list_closed_shift_rows(client, closed_since=closed_since)
    cloud_closed_shifts_seen = len(closed_shifts)
    if connection.sync_from_date is not None:
        filtered: list[dict[str, Any]] = []
        for shift in closed_shifts:
            try:
                target_date = business_date_for_shift(
                    shift,
                    cutoff_hour=connection.business_day_cutoff_hour,
                )
            except (QuickRestoDataError, ValueError):
                # Keep malformed rows visible so they become durable issues.
                filtered.append(shift)
                continue
            if target_date >= connection.sync_from_date:
                filtered.append(shift)
        closed_shifts = filtered

    scope_index = load_quickresto_scope_index(db, connection=connection)
    historical_scope_index = (
        load_quickresto_pending_scope_index(db, connection=connection) if pending_scope is not None else scope_index
    )
    historical_scope_generation = int(
        pending_scope["scope_generation"] if pending_scope is not None else connection.scope_generation or 1
    )
    historical_imports = (
        list(
            db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == int(connection.id),
                    _scope_resolution_requires_review(historical_scope_generation),
                )
            ).scalars()
        )
        if full_reconciliation
        else []
    )
    historical_imports_by_external_id = {str(item.external_shift_id): item for item in historical_imports}
    historical_scope_mismatch_ids: set[str] = set()
    for item in historical_imports:
        if (
            item.scope_resolution_action is not None
            and int(item.scope_resolution_generation or 0) != historical_scope_generation
        ):
            # A decision belongs to the generation in which it was made. A
            # later scope must explicitly review it again even when the shift
            # would still be importable under the proposed scope.
            historical_scope_mismatch_ids.add(str(item.external_shift_id))

    if full_reconciliation:
        for shift in closed_shifts:
            external_shift_id = str(shift.get("frontId") or shift.get("_id") or "").strip()
            if not external_shift_id or external_shift_id not in historical_imports_by_external_id:
                continue
            historical_decision = evaluate_quickresto_shift_scope(shift, scope=historical_scope_index)
            if historical_decision.action != "IMPORT":
                historical_scope_mismatch_ids.add(external_shift_id)

    historical_scope_issue = None
    if full_reconciliation:
        historical_scope_issue = _sync_previous_scope_mismatch_issue(
            db,
            connection=connection,
            run=run,
            mismatch_external_ids=historical_scope_mismatch_ids,
            scope_generation=historical_scope_generation,
            selected_external_venue_id=(int(pending_scope["external_venue_id"]) if pending_scope is not None else None),
        )
    pending_scope_activated = False
    if pending_scope is not None and historical_scope_issue is None:
        activate_pending_quickresto_scope(
            db,
            connection=connection,
            actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
            expected_generation=historical_scope_generation,
        )
        pending_scope_activated = True
        scope_index = load_quickresto_scope_index(db, connection=connection)

    scope_decisions: dict[int, Any] = {}
    scoped_shifts: list[dict[str, Any]] = []
    scope_counts = {
        "cloud_closed_shifts_seen": cloud_closed_shifts_seen,
        "shifts_in_scope": 0,
        "shifts_skipped_other_venue": 0,
        "shifts_skipped_unselected_sale_place": 0,
        "shifts_blocked_by_scope": 0,
        "historical_scope_generation": historical_scope_generation,
        "pending_scope_generation": int(pending_scope["scope_generation"]) if pending_scope is not None else None,
        "pending_scope_activated": pending_scope_activated,
    }
    for shift in closed_shifts:
        decision = evaluate_quickresto_shift_scope(shift, scope=scope_index)
        external_shift_id = str(shift.get("frontId") or shift.get("_id") or "").strip()
        if decision.action == "SKIP_OTHER_VENUE":
            scope_counts["shifts_skipped_other_venue"] += 1
            continue
        if decision.action == "SKIP_UNSELECTED_SALE_PLACE":
            scope_counts["shifts_skipped_unselected_sale_place"] += 1
            continue
        object_id = int(shift.get("id") or 0)
        if object_id > 0:
            scope_decisions[object_id] = decision
        scoped_shifts.append(shift)
        if decision.action == "IMPORT":
            scope_counts["shifts_in_scope"] += 1
        else:
            scope_counts["shifts_blocked_by_scope"] += 1
    scope_counts["historical_scope_mismatch_count"] = len(historical_scope_mismatch_ids)
    scope_counts["historical_scope_mismatch_issue_id"] = (
        int(historical_scope_issue.id) if historical_scope_issue is not None else None
    )
    closed_shifts = scoped_shifts

    shift_ids = {
        str(row.get("frontId") or row.get("_id") or "").strip()
        for row in closed_shifts
        if str(row.get("frontId") or row.get("_id") or "").strip()
    }
    order_rows = _list_order_rows_for_shifts(client, shift_ids=shift_ids)
    order_details_by_shift: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in order_rows:
        object_id = int(row.get("id") or 0)
        if object_id <= 0:
            raise QuickRestoDataError("QuickResto order identifier is missing")
        detail = _object_detail(client, "orders", object_id)
        order_details_by_shift[str(detail.get("shiftId") or "")].append(detail)

    night_split = bool(connection.night_shift_split_enabled and venue.night_shifts_enabled)
    snapshot_store_ids = selected_store_ids(db, connection_id=int(connection.id))
    sealed_rows = []
    scope_errors_by_fingerprint: dict[str, Any] = {}
    first_snapshot_error: QuickRestoSnapshotError | None = None
    for index, shift in enumerate(closed_shifts):
        shift_id = str(shift.get("frontId") or shift.get("_id") or "").strip()
        try:
            target_date = business_date_for_shift(
                shift,
                cutoff_hour=connection.business_day_cutoff_hour,
            )
            target_slot = shift_slot_for_shift(
                shift,
                cutoff_hour=connection.business_day_cutoff_hour,
                night_shift_split_enabled=night_split,
                night_shift_start_hour=connection.night_shift_start_hour,
            )
        except (QuickRestoDataError, ValueError):
            target_date = None
            target_slot = None
        try:
            sealed = seal_quickresto_source_snapshot(
                shift=shift,
                orders=order_details_by_shift.get(shift_id, []),
                business_date=target_date,
                shift_slot=target_slot,
                source_key=f"row:{index}:pk:{int(shift.get('id') or 0)}",
                scope_store_ids=snapshot_store_ids,
            )
            sealed_rows.append(sealed)
            decision = scope_decisions.get(int(shift.get("id") or 0))
            if decision is not None and decision.error is not None:
                scope_errors_by_fingerprint[sealed.source_fingerprint] = decision.error
        except QuickRestoSnapshotError as exc:
            first_snapshot_error = first_snapshot_error or exc

    if first_snapshot_error is not None:
        failure = classify_quickresto_failure(first_snapshot_error)
        upsert_import_issue(
            db,
            connection_id=int(connection.id),
            sync_run_id=int(run.id),
            group_key=connection_group_key(failure.error_code),
            business_date=None,
            shift_slot=None,
            failure=failure,
            actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
        )
        db.commit()
        raise first_snapshot_error

    all_snapshots = [
        upsert_source_snapshot(
            db,
            connection_id=int(connection.id),
            sync_run_id=int(run.id),
            sealed=sealed,
            now=now,
        )
        for sealed in sealed_rows
    ]
    scope_conflicts: list[dict[str, Any]] = []
    snapshots: list[QuickRestoSourceSnapshot] = []
    for snapshot in all_snapshots:
        scope_error = scope_errors_by_fingerprint.get(snapshot.source_fingerprint)
        if scope_error is None:
            snapshots.append(snapshot)
            continue
        failure = classify_quickresto_failure(scope_error)
        issue = upsert_import_issue(
            db,
            connection_id=int(connection.id),
            sync_run_id=int(run.id),
            group_key=source_group_key(snapshot.source_fingerprint),
            business_date=snapshot.business_date,
            shift_slot=snapshot.shift_slot,
            failure=failure,
            snapshots=[snapshot],
            failed_source_fingerprints={snapshot.source_fingerprint},
            actor_user_id=int(run.requested_by_user_id) if run.requested_by_user_id else None,
        )
        scope_conflicts.append(
            {
                "issue_id": int(issue.id),
                "error_code": failure.error_code,
                "user_summary": failure.user_summary,
            }
        )
    cursor_candidates = [value for shift in closed_shifts if (value := _remote_closed_at(shift)) is not None]
    if cursor_candidates:
        newest = max(cursor_candidates)
        current = connection.incremental_cursor_closed_at
        if current is None or newest > _ensure_utc(current):
            connection.incremental_cursor_closed_at = newest
    if full_reconciliation:
        connection.last_full_reconciliation_at = now
    # This commit is intentional: encrypted allowlisted source data must survive
    # any later normalization or report conflict in the same synchronization.
    db.commit()
    db.refresh(run)
    db.refresh(connection)
    for row in snapshots:
        db.refresh(row)
    return snapshots, full_reconciliation, scope_counts, scope_conflicts


def _upsert_normalized_shift(
    db: Session,
    *,
    connection: QuickRestoConnection,
    normalized: dict[str, Any],
) -> tuple[bool, set[tuple[date, str]]]:
    shift_id = str(normalized["external_shift_id"])
    target_date = date.fromisoformat(str(normalized["business_date"]))
    target_slot = str(normalized.get("shift_slot") or "DAY").upper()
    next_key = (target_date, target_slot)
    existing = db.execute(
        select(QuickRestoShiftImport).where(
            QuickRestoShiftImport.connection_id == connection.id,
            QuickRestoShiftImport.external_shift_id == shift_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            QuickRestoShiftImport(
                connection_id=connection.id,
                external_shift_id=shift_id,
                external_shift_pk=int(normalized["external_shift_pk"]),
                source_version=int(normalized["source_version"]),
                business_date=target_date,
                shift_slot=target_slot,
                local_closed_at=datetime.fromisoformat(str(normalized["local_closed_at"])),
                payload_hash=str(normalized["payload_hash"]),
                normalized_json=normalized,
                first_imported_at=_utcnow(),
                updated_at=_utcnow(),
            )
        )
        return True, {next_key}

    previous_key = (
        existing.business_date,
        str(getattr(existing, "shift_slot", None) or "DAY").upper(),
    )
    payload_changed = existing.payload_hash != normalized["payload_hash"]
    key_changed = previous_key != next_key
    stale_scope_resolution = bool(
        existing.scope_resolution_action is not None
        and int(existing.scope_resolution_generation or 0) != int(connection.scope_generation or 1)
    )
    scope_resolution_cleared = bool(
        existing.scope_resolution_action is not None and (payload_changed or key_changed or stale_scope_resolution)
    )
    changed = payload_changed or key_changed or stale_scope_resolution
    if changed:
        if key_changed:
            existing.daily_report_id = None
        existing.external_shift_pk = int(normalized["external_shift_pk"])
        existing.source_version = int(normalized["source_version"])
        existing.business_date = target_date
        existing.shift_slot = target_slot
        existing.local_closed_at = datetime.fromisoformat(str(normalized["local_closed_at"]))
        existing.payload_hash = str(normalized["payload_hash"])
        existing.normalized_json = normalized
        existing.updated_at = _utcnow()
        if scope_resolution_cleared:
            existing.scope_resolution_action = None
            existing.scope_resolution_generation = None
            existing.scope_resolved_by_user_id = None
            existing.scope_resolved_at = None
            existing.scope_resolution_note = None
    return changed, {previous_key, next_key}


def _rebuild_imported_report_keys(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    actor_user_id: int,
    affected_keys: set[tuple[date, str]],
) -> tuple[dict[str, int], list[int]]:
    """Rebuild only reports owned by this integration from active shift imports."""

    counts = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    report_ids: list[int] = []
    for target_date, target_slot in sorted(affected_keys):
        stored_shifts = list(
            db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == connection.id,
                    QuickRestoShiftImport.business_date == target_date,
                    QuickRestoShiftImport.shift_slot == target_slot,
                    or_(
                        QuickRestoShiftImport.scope_resolution_action.is_(None),
                        QuickRestoShiftImport.scope_resolution_action != "EXCLUDE_CURRENT",
                        QuickRestoShiftImport.scope_resolution_generation.is_(None),
                        QuickRestoShiftImport.scope_resolution_generation != int(connection.scope_generation or 1),
                    ),
                )
            ).scalars()
        )
        if not stored_shifts:
            if _remove_empty_imported_report(
                db,
                connection=connection,
                business_date=target_date,
                shift_slot=target_slot,
                actor_user_id=actor_user_id,
            ):
                counts["removed"] += 1
            continue
        aggregate = aggregate_normalized_shifts(item.normalized_json for item in stored_shifts)
        mapped = _mapped_aggregate(db, connection=connection, aggregate=aggregate)
        outcome, report = _upsert_draft_report(
            db,
            connection=connection,
            aggregate=mapped,
            run=run,
            actor_user_id=actor_user_id,
        )
        counts[outcome] += 1
        report_ids.append(int(report.id))
        for item in stored_shifts:
            item.daily_report_id = report.id
    return counts, report_ids


def _process_snapshot_group(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    venue: Venue,
    actor_user_id: int,
    snapshots: list[QuickRestoSourceSnapshot],
) -> dict[str, Any]:
    night_split = bool(connection.night_shift_split_enabled and venue.night_shifts_enabled)
    scope_index = load_quickresto_scope_index(db, connection=connection)
    normalized_rows: list[dict[str, Any]] = []
    failed_fingerprints: set[str] = set()
    first_error: BaseException | None = None
    for snapshot in snapshots:
        try:
            source = open_source_snapshot(snapshot)
            scope_decision = evaluate_quickresto_shift_scope(source["shift"], scope=scope_index)
            if scope_decision.action != "IMPORT":
                if scope_decision.error is not None:
                    raise scope_decision.error
                raise QuickRestoLocationScopeError(
                    error_code="LOCATION_OUTSIDE_SCOPE",
                    user_summary="Смена QuickResto не входит в подтверждённую область импорта.",
                    technical_summary="QuickResto shift is outside the selected venue scope",
                    details={
                        "selected_external_venue_id": scope_index.external_venue_id,
                        "shift_external_venue_id": scope_decision.external_venue_id,
                        "sale_place_id": scope_decision.sale_place_id,
                    },
                )
            normalized_rows.append(
                normalize_closed_shift(
                    source["shift"],
                    source["orders"],
                    cutoff_hour=connection.business_day_cutoff_hour,
                    night_shift_split_enabled=night_split,
                    night_shift_start_hour=connection.night_shift_start_hour,
                )
            )
        except Exception as exc:
            first_error = first_error or exc
            failed_fingerprints.add(snapshot.source_fingerprint)

    business_date = snapshots[0].business_date if snapshots else None
    shift_slot = snapshots[0].shift_slot if snapshots else None
    group_key = (
        report_group_key(business_date, shift_slot)
        if business_date is not None and shift_slot is not None
        else source_group_key(snapshots[0].source_fingerprint)
    )
    if first_error is not None:
        failure = _classify_snapshot_group_failure(first_error)
        issue = upsert_import_issue(
            db,
            connection_id=int(connection.id),
            sync_run_id=int(run.id),
            group_key=group_key,
            business_date=business_date,
            shift_slot=shift_slot,
            failure=failure,
            snapshots=snapshots,
            failed_source_fingerprints=failed_fingerprints,
            actor_user_id=actor_user_id,
        )
        return {
            "shifts_imported": 0,
            "counts": {"created": 0, "updated": 0, "unchanged": 0, "removed": 0},
            "report_ids": [],
            "conflict": {
                "issue_id": int(issue.id),
                "business_date": business_date.isoformat() if business_date else None,
                "shift_slot": shift_slot,
                "error_code": failure.error_code,
                "error": failure.user_summary,
            },
        }

    local_counts = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    local_report_ids: list[int] = []
    imported = 0
    try:
        with db.begin_nested():
            affected_keys: set[tuple[date, str]] = set()
            for normalized in normalized_rows:
                changed, keys = _upsert_normalized_shift(
                    db,
                    connection=connection,
                    normalized=normalized,
                )
                imported += int(changed)
                affected_keys.update(keys)
            db.flush()
            local_counts, local_report_ids = _rebuild_imported_report_keys(
                db,
                connection=connection,
                run=run,
                actor_user_id=actor_user_id,
                affected_keys=affected_keys,
            )
    except Exception as exc:
        failure = _classify_snapshot_group_failure(exc)
        issue_snapshots = snapshots
        if business_date is not None and shift_slot is not None:
            issue_snapshots = (
                snapshots_for_group(
                    db,
                    connection_id=int(connection.id),
                    business_date=business_date,
                    shift_slot=shift_slot,
                )
                or snapshots
            )
        issue = upsert_import_issue(
            db,
            connection_id=int(connection.id),
            sync_run_id=int(run.id),
            group_key=group_key,
            business_date=business_date,
            shift_slot=shift_slot,
            failure=failure,
            snapshots=issue_snapshots,
            failed_source_fingerprints={item.source_fingerprint for item in issue_snapshots},
            actor_user_id=actor_user_id,
        )
        return {
            "shifts_imported": 0,
            "counts": {"created": 0, "updated": 0, "unchanged": 0, "removed": 0},
            "report_ids": [],
            "conflict": {
                "issue_id": int(issue.id),
                "business_date": business_date.isoformat() if business_date else None,
                "shift_slot": shift_slot,
                "error_code": failure.error_code,
                "error": failure.user_summary,
            },
        }

    if business_date is not None and shift_slot is not None:
        resolve_group_issue(
            db,
            connection_id=int(connection.id),
            business_date=business_date,
            shift_slot=shift_slot,
            actor_user_id=actor_user_id,
            sync_run_id=int(run.id),
        )
    return {
        "shifts_imported": imported,
        "counts": local_counts,
        "report_ids": local_report_ids,
        "conflict": None,
    }


def _perform_sync(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    actor_user_id: int,
    client: QuickRestoClient,
    force_full: bool = False,
) -> dict[str, Any]:
    catalog_summary = refresh_quickresto_catalog(db, connection=connection, client=client)
    ensure_quickresto_scope_ready(connection)
    mapping_summary = refresh_quickresto_mappings(db, connection=connection, client=client)
    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        raise QuickRestoDataError("Axelio venue no longer exists")
    snapshots, full_reconciliation, scope_counts, scope_conflicts = _stage_quickresto_sources(
        db,
        connection=connection,
        run=run,
        venue=venue,
        client=client,
        force_full=force_full,
    )
    grouped: dict[tuple[date | None, str | None, str], list[QuickRestoSourceSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        discriminator = (
            report_group_key(snapshot.business_date, snapshot.shift_slot)
            if snapshot.business_date is not None and snapshot.shift_slot is not None
            else source_group_key(snapshot.source_fingerprint)
        )
        grouped[(snapshot.business_date, snapshot.shift_slot, discriminator)].append(snapshot)

    totals = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    shifts_imported = 0
    report_ids: list[int] = []
    conflicts: list[dict[str, Any]] = list(scope_conflicts)
    historical_issue_id = scope_counts.get("historical_scope_mismatch_issue_id")
    if historical_issue_id:
        historical_issue = db.get(QuickRestoImportIssue, int(historical_issue_id))
        if historical_issue is not None and str(historical_issue.status or "").upper() in ACTIVE_ISSUE_STATUSES:
            conflicts.append(
                {
                    "issue_id": int(historical_issue.id),
                    "business_date": None,
                    "shift_slot": None,
                    "error_code": historical_issue.error_code,
                    "error": historical_issue.user_summary,
                }
            )
    ignored_groups = 0
    for _key, group_snapshots in sorted(
        grouped.items(),
        key=lambda item: (item[0][0] or date.min, item[0][1] or "", item[0][2]),
    ):
        if ignored_issue_matches_snapshots(
            db,
            connection_id=int(connection.id),
            group_key=_key[2],
            snapshots=group_snapshots,
        ):
            ignored_groups += 1
            continue
        result = _process_snapshot_group(
            db,
            connection=connection,
            run=run,
            venue=venue,
            actor_user_id=actor_user_id,
            snapshots=group_snapshots,
        )
        shifts_imported += int(result["shifts_imported"])
        for name in totals:
            totals[name] += int(result["counts"][name])
        report_ids.extend(result["report_ids"])
        if result["conflict"] is not None:
            conflicts.append(result["conflict"])

    return {
        **catalog_summary,
        **mapping_summary,
        **scope_counts,
        "sync_mode": "FULL_RECONCILIATION" if full_reconciliation else "INCREMENTAL",
        "source_snapshots_staged": len(snapshots) + len(scope_conflicts),
        "shifts_seen": len(snapshots) + len(scope_conflicts),
        "shifts_imported": shifts_imported,
        "reports_created": totals["created"],
        "reports_updated": totals["updated"],
        "reports_unchanged": totals["unchanged"],
        "reports_removed": totals["removed"],
        "report_ids": sorted(set(report_ids)),
        "conflicts": conflicts,
        "issue_count": len(conflicts),
        "ignored_groups": ignored_groups,
    }


def reconcile_quickresto_historical_scope_issue(
    db: Session,
    *,
    connection: QuickRestoConnection,
    issue_id: int,
    decisions: dict[int, str],
    note: str,
    requested_by_user_id: int,
) -> QuickRestoSyncRun:
    """Apply explicit keep/exclude decisions and atomically rebuild affected reports."""

    connection_id = int(connection.id)
    actor_user_id = int(requested_by_user_id)
    normalized_decisions = {int(key): str(value or "").upper() for key, value in decisions.items()}
    if not normalized_decisions or any(
        value not in {"KEEP_CURRENT", "EXCLUDE_CURRENT"} for value in normalized_decisions.values()
    ):
        raise QuickRestoSyncError("Для каждой исторической смены выберите допустимое решение")

    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if connection is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection no longer exists")
    now = _utcnow()
    if quickresto_sync_is_active(connection, now=now):
        db.rollback()
        raise QuickRestoSyncError("QuickResto sync is already running")
    reclaim_stale_quickresto_sync_state(db, connection=connection, now=now)
    if not connection.is_active:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection is disabled")

    issue = db.execute(
        select(QuickRestoImportIssue)
        .where(
            QuickRestoImportIssue.id == int(issue_id),
            QuickRestoImportIssue.connection_id == connection_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if issue is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto import issue was not found")
    if str(issue.error_code or "").upper() != "PREVIOUS_SCOPE_MISMATCH":
        db.rollback()
        raise QuickRestoSyncError("Эта проблема не относится к исторической области QuickResto")
    if str(issue.status or "").upper() not in {"OPEN", "RETRY_PENDING"}:
        db.rollback()
        raise QuickRestoSyncError("Проблема уже обрабатывается или закрыта")
    issue_details = issue.details_json if isinstance(issue.details_json, dict) else {}
    target_generation = int(issue_details.get("scope_generation") or connection.scope_generation or 1)
    pending_scope = pending_quickresto_scope(connection)
    if pending_scope is not None:
        if int(pending_scope["scope_generation"]) != target_generation:
            db.rollback()
            raise QuickRestoSyncError(
                "Ожидающая область QuickResto изменилась. Обновите проблему и выберите решения заново."
            )
    elif target_generation != int(connection.scope_generation or 1):
        db.rollback()
        raise QuickRestoSyncError("Версия области QuickResto изменилась. Запустите полную сверку заново.")

    issue_items = list(
        db.execute(
            select(QuickRestoImportIssueShift)
            .where(QuickRestoImportIssueShift.issue_id == int(issue.id))
            .with_for_update()
        ).scalars()
    )
    expected_ids = {int(item.shift_import_id) for item in issue_items if item.shift_import_id is not None}
    if not expected_ids or len(expected_ids) != len(issue_items):
        db.rollback()
        raise QuickRestoSyncError(
            "Исторические смены не привязаны к сохранённым импортам. Запустите полную синхронизацию."
        )
    if set(normalized_decisions) != expected_ids:
        db.rollback()
        raise QuickRestoSyncError("Список исторических смен изменился. Обновите проблему и выберите решение заново.")

    shift_imports = list(
        db.execute(
            select(QuickRestoShiftImport)
            .where(
                QuickRestoShiftImport.connection_id == connection_id,
                QuickRestoShiftImport.id.in_(sorted(expected_ids)),
                _scope_resolution_requires_review(target_generation),
            )
            .with_for_update()
        ).scalars()
    )
    if len(shift_imports) != len(expected_ids):
        db.rollback()
        raise QuickRestoSyncError("По части исторических смен уже принято решение. Обновите страницу.")

    run = QuickRestoSyncRun(
        connection_id=connection_id,
        requested_by_user_id=actor_user_id,
        trigger="SCOPE_RECONCILIATION",
        status="RUNNING",
        started_at=now,
    )
    db.add(run)
    db.flush()
    transition_issue(
        db,
        issue=issue,
        status="PROCESSING",
        event_type="HISTORICAL_SCOPE_RECONCILIATION_STARTED",
        actor_user_id=actor_user_id,
        sync_run_id=int(run.id),
    )
    connection.last_sync_started_at = now
    connection.last_sync_status = "RUNNING"
    connection.last_sync_error = None
    db.commit()
    run_id = int(run.id)

    try:
        connection = db.execute(
            select(QuickRestoConnection)
            .where(QuickRestoConnection.id == connection_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        issue = db.execute(
            select(QuickRestoImportIssue)
            .where(QuickRestoImportIssue.id == int(issue_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        shift_imports = list(
            db.execute(
                select(QuickRestoShiftImport)
                .where(
                    QuickRestoShiftImport.connection_id == connection_id,
                    QuickRestoShiftImport.id.in_(sorted(expected_ids)),
                    _scope_resolution_requires_review(target_generation),
                )
                .with_for_update()
            ).scalars()
        )
        if len(shift_imports) != len(expected_ids):
            raise QuickRestoSyncError("По части исторических смен уже принято решение. Обновите страницу.")

        current_pending_scope = pending_quickresto_scope(connection)
        pending_scope_activated = False
        if current_pending_scope is not None:
            if int(current_pending_scope["scope_generation"]) != target_generation:
                raise QuickRestoSyncError("Ожидающая область QuickResto изменилась. Обновите проблему.")
            activate_pending_quickresto_scope(
                db,
                connection=connection,
                actor_user_id=actor_user_id,
                expected_generation=target_generation,
            )
            pending_scope_activated = True
        elif int(connection.scope_generation or 1) != target_generation:
            raise QuickRestoSyncError("Версия области QuickResto изменилась. Запустите полную сверку заново.")

        timestamp = _utcnow()
        affected_keys: set[tuple[date, str]] = set()
        kept_count = 0
        excluded_count = 0
        decision_audit: list[dict[str, Any]] = []
        for shift_import in shift_imports:
            action = normalized_decisions[int(shift_import.id)]
            affected_keys.add((shift_import.business_date, str(shift_import.shift_slot or "DAY").upper()))
            before_report_id = int(shift_import.daily_report_id) if shift_import.daily_report_id is not None else None
            shift_import.scope_resolution_action = action
            shift_import.scope_resolution_generation = target_generation
            shift_import.scope_resolved_by_user_id = actor_user_id
            shift_import.scope_resolved_at = timestamp
            shift_import.scope_resolution_note = str(note).strip()
            shift_import.updated_at = timestamp
            if action == "EXCLUDE_CURRENT":
                excluded_count += 1
                shift_import.daily_report_id = None
            else:
                kept_count += 1
            decision_audit.append(
                {
                    "shift_import_id": int(shift_import.id),
                    "external_shift_id": str(shift_import.external_shift_id),
                    "action": action,
                    "business_date": shift_import.business_date.isoformat(),
                    "shift_slot": str(shift_import.shift_slot or "DAY").upper(),
                    "daily_report_id_before": before_report_id,
                }
            )
        db.flush()

        counts, report_ids = _rebuild_imported_report_keys(
            db,
            connection=connection,
            run=run,
            actor_user_id=actor_user_id,
            affected_keys=affected_keys,
        )
        shift_by_id = {int(item.id): item for item in shift_imports}
        for row in decision_audit:
            resolved_shift = shift_by_id[int(row["shift_import_id"])]
            row["daily_report_id_after"] = (
                int(resolved_shift.daily_report_id) if resolved_shift.daily_report_id is not None else None
            )
        details = dict(issue.details_json) if isinstance(issue.details_json, dict) else {}
        details.update(
            {
                "scope_generation": target_generation,
                "historical_decisions_kept": kept_count,
                "historical_decisions_excluded": excluded_count,
                "reconciled_report_ids": sorted(set(report_ids)),
            }
        )
        issue.details_json = details
        transition_issue(
            db,
            issue=issue,
            status="RESOLVED",
            event_type="HISTORICAL_SCOPE_RECONCILED",
            actor_user_id=actor_user_id,
            sync_run_id=run_id,
            resolution_code="SHIFT_DECISIONS_APPLIED",
            resolution_note=str(note).strip(),
            audit_metadata={
                "scope_generation": target_generation,
                "pending_scope_activated": pending_scope_activated,
                "decisions": decision_audit,
                "reconciled_report_ids": sorted(set(report_ids)),
            },
        )
        for item in issue.shifts:
            action = normalized_decisions.get(int(item.shift_import_id or 0))
            item.user_summary = (
                "Смена исключена из текущего заведения; импортированные отчёты пересчитаны."
                if action == "EXCLUDE_CURRENT"
                else "Смена подтверждена как историческая часть текущего заведения."
            )

        finished_at = _utcnow()
        run.status = "SUCCEEDED"
        run.finished_at = finished_at
        run.shifts_seen = len(shift_imports)
        run.shifts_imported = 0
        run.reports_created = int(counts["created"])
        run.reports_updated = int(counts["updated"])
        run.reports_unchanged = int(counts["unchanged"])
        run.summary_json = {
            "sync_mode": "HISTORICAL_SCOPE_RECONCILIATION",
            "reconciled_issue_id": int(issue_id),
            "scope_generation": target_generation,
            "pending_scope_activated": pending_scope_activated,
            "shifts_seen": len(shift_imports),
            "shifts_kept": kept_count,
            "shifts_excluded": excluded_count,
            "reports_created": int(counts["created"]),
            "reports_updated": int(counts["updated"]),
            "reports_unchanged": int(counts["unchanged"]),
            "reports_removed": int(counts["removed"]),
            "report_ids": sorted(set(report_ids)),
            "issue_count": 0,
        }
        connection.last_sync_completed_at = finished_at
        connection.last_sync_status = "SUCCEEDED"
        connection.last_sync_error = None
        db.commit()
        db.refresh(run)
        _enqueue_sync_notification_safely(
            db,
            connection=connection,
            run=run,
            issue_count=0,
            force=True,
        )
        db.refresh(run)
        return run
    except Exception as exc:
        correlation_id = None
        if not isinstance(exc, (QuickRestoDataError, QuickRestoSyncError, ValueError)):
            try:
                import sentry_sdk

                correlation_id = sentry_sdk.capture_exception(exc)
            except Exception:
                correlation_id = None
        failure = classify_quickresto_failure(exc, correlation_id=correlation_id)
        _record_failed_run(
            db,
            run_id=run_id,
            connection_id=connection_id,
            message=failure.user_summary,
        )
        current_issue = db.get(QuickRestoImportIssue, int(issue_id))
        if current_issue is not None:
            transition_issue(
                db,
                issue=current_issue,
                status="OPEN",
                event_type="HISTORICAL_SCOPE_RECONCILIATION_FAILED",
                actor_user_id=actor_user_id,
                sync_run_id=run_id,
                resolution_code=failure.error_code,
                resolution_note=failure.user_summary,
            )
            db.commit()
        failed_run = db.get(QuickRestoSyncRun, run_id)
        failed_connection = db.get(QuickRestoConnection, connection_id)
        if failed_run is not None and failed_connection is not None:
            _enqueue_sync_notification_safely(
                db,
                connection=failed_connection,
                run=failed_run,
                issue_count=1,
                technical_summary=failure.technical_summary,
                correlation_id=failure.correlation_id,
                force=True,
            )
        raise QuickRestoSyncError(failure.user_summary) from exc


def sync_quickresto_connection(
    db: Session,
    *,
    connection: QuickRestoConnection,
    requested_by_user_id: int | None,
    trigger: str,
    client: QuickRestoClient | None = None,
    force_full: bool = False,
) -> QuickRestoSyncRun:
    connection_id = int(connection.id)
    locked_connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked_connection is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection no longer exists")
    connection = locked_connection
    now = _utcnow()
    if quickresto_sync_is_active(connection, now=now):
        db.rollback()
        raise QuickRestoSyncError("QuickResto sync is already running")
    reclaim_stale_quickresto_sync_state(db, connection=connection, now=now)
    if not connection.is_active:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection is disabled")
    try:
        ensure_quickresto_scope_ready(connection)
    except QuickRestoScopeError as exc:
        db.rollback()
        raise QuickRestoSyncError(str(exc)) from exc

    actor_user_id = int(requested_by_user_id or connection.created_by_user_id)
    run = QuickRestoSyncRun(
        connection_id=connection.id,
        requested_by_user_id=requested_by_user_id,
        trigger=str(trigger or "MANUAL").upper(),
        status="RUNNING",
        started_at=now,
    )
    db.add(run)
    connection.last_sync_started_at = now
    connection.last_sync_status = "RUNNING"
    connection.last_sync_error = None
    db.commit()
    db.refresh(run)
    db.refresh(connection)

    try:
        managed_client = client is None
        active_client = client or build_quickresto_client(connection)
        context = active_client if managed_client else nullcontext(active_client)
        with context as current_client:
            summary = _perform_sync(
                db,
                connection=connection,
                run=run,
                actor_user_id=actor_user_id,
                client=current_client,
                force_full=force_full,
            )
        finished_at = _utcnow()
        run.status = "PARTIAL" if summary["conflicts"] else "SUCCEEDED"
        run.finished_at = finished_at
        run.shifts_seen = int(summary["shifts_seen"])
        run.shifts_imported = int(summary["shifts_imported"])
        run.reports_created = int(summary["reports_created"])
        run.reports_updated = int(summary["reports_updated"])
        run.reports_unchanged = int(summary["reports_unchanged"])
        run.summary_json = summary
        connection.last_sync_completed_at = finished_at
        connection.last_sync_status = run.status
        connection.last_sync_error = None if run.status == "SUCCEEDED" else "Some report dates need attention"
        db.commit()
        diagnostic_issue = None
        if summary["conflicts"]:
            diagnostic_issue = db.get(QuickRestoImportIssue, int(summary["conflicts"][0]["issue_id"]))
        _enqueue_sync_notification_safely(
            db,
            connection=connection,
            run=run,
            issue_count=int(summary.get("issue_count") or 0),
            technical_summary=diagnostic_issue.technical_summary if diagnostic_issue is not None else None,
            correlation_id=diagnostic_issue.correlation_id if diagnostic_issue is not None else None,
        )
        db.refresh(run)
        return run
    except (
        QuickRestoError,
        QuickRestoDataError,
        QuickRestoSnapshotError,
        QuickRestoSyncError,
        IntegrationCredentialError,
        ValueError,
    ) as exc:
        failure = classify_quickresto_failure(exc)
        _record_failed_run(
            db,
            run_id=run.id,
            connection_id=connection.id,
            message=failure.user_summary,
        )
        issue = upsert_import_issue(
            db,
            connection_id=connection_id,
            sync_run_id=int(run.id),
            group_key=connection_group_key(failure.error_code),
            business_date=None,
            shift_slot=None,
            failure=failure,
            actor_user_id=requested_by_user_id,
        )
        db.commit()
        failed_run = db.get(QuickRestoSyncRun, int(run.id))
        failed_connection = db.get(QuickRestoConnection, connection_id)
        if failed_run is not None and failed_connection is not None:
            _enqueue_sync_notification_safely(
                db,
                connection=failed_connection,
                run=failed_run,
                issue_count=1,
                technical_summary=issue.technical_summary,
                correlation_id=issue.correlation_id,
                force=True,
            )
        raise QuickRestoSyncError(failure.user_summary) from exc
    except Exception as exc:
        correlation_id = None
        try:
            import sentry_sdk

            correlation_id = sentry_sdk.capture_exception(exc)
        except Exception:
            correlation_id = None
        failure = classify_quickresto_failure(exc, correlation_id=correlation_id)
        _record_failed_run(
            db,
            run_id=run.id,
            connection_id=connection.id,
            message=failure.user_summary,
        )
        issue = upsert_import_issue(
            db,
            connection_id=connection_id,
            sync_run_id=int(run.id),
            group_key=connection_group_key(failure.error_code),
            business_date=None,
            shift_slot=None,
            failure=failure,
            actor_user_id=requested_by_user_id,
        )
        db.commit()
        failed_run = db.get(QuickRestoSyncRun, int(run.id))
        failed_connection = db.get(QuickRestoConnection, connection_id)
        if failed_run is not None and failed_connection is not None:
            _enqueue_sync_notification_safely(
                db,
                connection=failed_connection,
                run=failed_run,
                issue_count=1,
                technical_summary=issue.technical_summary,
                correlation_id=issue.correlation_id,
                force=True,
            )
        raise QuickRestoSyncError(failure.user_summary) from exc


def retry_quickresto_import_issue(
    db: Session,
    *,
    connection: QuickRestoConnection,
    issue_id: int,
    requested_by_user_id: int,
) -> QuickRestoSyncRun:
    """Retry one durable issue from encrypted snapshots without calling QuickResto."""

    connection_id = int(connection.id)
    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.id == connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if connection is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection no longer exists")
    now = _utcnow()
    if quickresto_sync_is_active(connection, now=now):
        db.rollback()
        raise QuickRestoSyncError("QuickResto sync is already running")
    reclaim_stale_quickresto_sync_state(db, connection=connection, now=now)
    issue = db.execute(
        select(QuickRestoImportIssue)
        .where(
            QuickRestoImportIssue.id == int(issue_id),
            QuickRestoImportIssue.connection_id == connection_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if issue is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto import issue was not found")
    if str(issue.status or "").upper() not in {"OPEN", "RETRY_PENDING"}:
        db.rollback()
        raise QuickRestoSyncError("QuickResto import issue is not waiting for a retry")
    if not connection.is_active:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection is disabled")

    snapshots = list(
        db.execute(
            select(QuickRestoSourceSnapshot)
            .join(
                QuickRestoImportIssueShift,
                QuickRestoImportIssueShift.source_snapshot_id == QuickRestoSourceSnapshot.id,
            )
            .where(
                QuickRestoImportIssueShift.issue_id == int(issue.id),
                QuickRestoSourceSnapshot.connection_id == connection_id,
            )
            .order_by(
                QuickRestoSourceSnapshot.local_opened_at.asc(),
                QuickRestoSourceSnapshot.id.asc(),
            )
        ).scalars()
    )
    if not snapshots or len(snapshots) != len(issue.shifts):
        db.rollback()
        raise QuickRestoSyncError("Сохранённые данные смены уже недоступны. Запустите полную синхронизацию QuickResto.")

    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        db.rollback()
        raise QuickRestoSyncError("Axelio venue no longer exists")
    run = QuickRestoSyncRun(
        connection_id=connection_id,
        requested_by_user_id=int(requested_by_user_id),
        trigger="ISSUE_RETRY",
        status="RUNNING",
        started_at=now,
    )
    db.add(run)
    db.flush()
    transition_issue(
        db,
        issue=issue,
        status="PROCESSING",
        event_type="USER_RETRY_STARTED",
        actor_user_id=int(requested_by_user_id),
        sync_run_id=int(run.id),
    )
    connection.last_sync_started_at = now
    connection.last_sync_status = "RUNNING"
    connection.last_sync_error = None
    db.commit()
    db.refresh(run)
    db.refresh(connection)
    for snapshot in snapshots:
        db.refresh(snapshot)

    try:
        result = _process_snapshot_group(
            db,
            connection=connection,
            run=run,
            venue=venue,
            actor_user_id=int(requested_by_user_id),
            snapshots=snapshots,
        )
        finished_at = _utcnow()
        conflict = result["conflict"]
        run.status = "PARTIAL" if conflict is not None else "SUCCEEDED"
        run.finished_at = finished_at
        run.shifts_seen = len(snapshots)
        run.shifts_imported = int(result["shifts_imported"])
        run.reports_created = int(result["counts"]["created"])
        run.reports_updated = int(result["counts"]["updated"])
        run.reports_unchanged = int(result["counts"]["unchanged"])
        run.error_message = conflict["error"] if conflict is not None else None
        run.summary_json = {
            "sync_mode": "STORED_RETRY",
            "source_snapshots_staged": 0,
            "shifts_seen": len(snapshots),
            "shifts_imported": int(result["shifts_imported"]),
            "reports_created": int(result["counts"]["created"]),
            "reports_updated": int(result["counts"]["updated"]),
            "reports_unchanged": int(result["counts"]["unchanged"]),
            "reports_removed": int(result["counts"]["removed"]),
            "report_ids": sorted(set(result["report_ids"])),
            "conflicts": [conflict] if conflict is not None else [],
            "issue_count": int(conflict is not None),
            "retried_issue_id": int(issue_id),
        }
        if conflict is None:
            current_issue = db.get(QuickRestoImportIssue, int(issue_id))
            if current_issue is not None and str(current_issue.status) in ACTIVE_ISSUE_STATUSES:
                transition_issue(
                    db,
                    issue=current_issue,
                    status="RESOLVED",
                    event_type="IMPORT_SUCCEEDED",
                    actor_user_id=int(requested_by_user_id),
                    sync_run_id=int(run.id),
                    resolution_code="RETRY_SUCCEEDED",
                    resolution_note="Сохранённые смены успешно импортированы после повторной обработки.",
                )
        connection.last_sync_completed_at = finished_at
        connection.last_sync_status = run.status
        connection.last_sync_error = None if conflict is None else conflict["error"]
        db.commit()

        diagnostic_issue = db.get(
            QuickRestoImportIssue,
            int(conflict["issue_id"]) if conflict is not None else int(issue_id),
        )
        _enqueue_sync_notification_safely(
            db,
            connection=connection,
            run=run,
            issue_count=int(conflict is not None),
            technical_summary=(
                diagnostic_issue.technical_summary if conflict is not None and diagnostic_issue is not None else None
            ),
            correlation_id=(
                diagnostic_issue.correlation_id if conflict is not None and diagnostic_issue is not None else None
            ),
            force=True,
        )
        db.refresh(run)
        return run
    except Exception as exc:
        correlation_id = None
        if not isinstance(
            exc,
            (
                QuickRestoError,
                QuickRestoDataError,
                QuickRestoSnapshotError,
                QuickRestoSyncError,
                IntegrationCredentialError,
                ValueError,
            ),
        ):
            try:
                import sentry_sdk

                correlation_id = sentry_sdk.capture_exception(exc)
            except Exception:
                correlation_id = None
        failure = classify_quickresto_failure(exc, correlation_id=correlation_id)
        _record_failed_run(
            db,
            run_id=int(run.id),
            connection_id=connection_id,
            message=failure.user_summary,
        )
        failed_issue = upsert_import_issue(
            db,
            connection_id=connection_id,
            sync_run_id=int(run.id),
            group_key=str(issue.group_key),
            business_date=issue.business_date,
            shift_slot=issue.shift_slot,
            failure=failure,
            snapshots=snapshots,
            failed_source_fingerprints={item.source_fingerprint for item in snapshots},
            actor_user_id=int(requested_by_user_id),
        )
        db.commit()
        failed_run = db.get(QuickRestoSyncRun, int(run.id))
        failed_connection = db.get(QuickRestoConnection, connection_id)
        if failed_run is not None and failed_connection is not None:
            _enqueue_sync_notification_safely(
                db,
                connection=failed_connection,
                run=failed_run,
                issue_count=1,
                technical_summary=failed_issue.technical_summary,
                correlation_id=failed_issue.correlation_id,
                force=True,
            )
        raise QuickRestoSyncError(failure.user_summary) from exc
