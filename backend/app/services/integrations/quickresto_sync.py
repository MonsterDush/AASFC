from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.venue import Venue
from app.services.integrations.credentials import decrypt_credential
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
)


_INTEGRATION_COMMENT_PREFIX = "Импортировано из QuickResto:"


class QuickRestoSyncError(RuntimeError):
    """Raised when a QuickResto sync cannot complete safely."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    payment_rows = _object_rows(client, "payment_types")
    department_rows = _object_rows(client, "dish_categories")
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
    known_department_titles = {_normalize_label(item.title) for item in active_departments if _normalize_label(item.title)}
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

    for row in payment_rows:
        external_id = int(row.get("id") or 0)
        if external_id <= 0:
            continue
        name = str(row.get("name") or row.get("itemTitle") or f"#{external_id}").strip()
        operation_type = str(row.get("operationType") or "").strip().lower()
        mechanism = str(row.get("paymentMechanismWeb") or "").strip().lower() or None
        excluded = operation_type == "writeoff"
        mapping = existing_payments.get(external_id)
        catalog_title = _catalog_title(name)
        title_key = _normalize_label(catalog_title)
        auto_match = payment_by_title.get(title_key)
        needs_payment_target = mapping is None or mapping.payment_method_id is None
        if (not excluded and needs_payment_target and auto_match is None and title_key not in known_payment_titles):
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
                updated_at=_utcnow(),
            )
            db.add(mapping)
            existing_payments[external_id] = mapping
        else:
            mapping.external_name = _mapping_title(name)
            mapping.operation_type = operation_type
            mapping.payment_mechanism = mechanism
            mapping.excluded_from_revenue = excluded
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
        "payment_types_seen": len(payment_rows),
        "departments_seen": len(department_rows),
        "payment_methods_created": payment_methods_created,
        "departments_created": departments_created,
        "unmapped_payment_type_ids": sorted(
            item.external_id
            for item in existing_payments.values()
            if not item.excluded_from_revenue and item.payment_method_id is None
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
    for external_id, value in (aggregate.get("payments_external") or {}).items():
        if not int(value or 0):
            continue
        mapping = payment_mappings.get(str(external_id))
        if mapping is None or (mapping.payment_method_id is None and not mapping.excluded_from_revenue):
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
    report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == connection.venue_id,
            DailyReport.date == business_date,
            DailyReport.shift_slot == "DAY",
        )
    ).scalar_one_or_none()
    source = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == connection.id,
            QuickRestoReportImport.business_date == business_date,
            QuickRestoReportImport.shift_slot == "DAY",
        )
    ).scalar_one_or_none()

    created = False
    auto_close = str(connection.report_import_mode or "CLOSED").upper() == "CLOSED"
    if report is None:
        report = DailyReport(
            venue_id=connection.venue_id,
            date=business_date,
            shift_slot="DAY",
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
    payment_methods = {
        int(item.id): str(item.code or "")
        for item in db.execute(select(PaymentMethod).where(PaymentMethod.venue_id == connection.venue_id)).scalars()
    }
    report.cash = sum(
        int(value) for ref_id, value in aggregate["payments_internal"].items() if payment_methods.get(ref_id) == "cash"
    )
    report.cashless = sum(
        int(value)
        for ref_id, value in aggregate["payments_internal"].items()
        if payment_methods.get(ref_id) == "cashless"
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
            shift_slot="DAY",
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


def _perform_sync(
    db: Session,
    *,
    connection: QuickRestoConnection,
    run: QuickRestoSyncRun,
    actor_user_id: int,
    client: QuickRestoClient,
) -> dict[str, Any]:
    mapping_summary = refresh_quickresto_mappings(db, connection=connection, client=client)
    shift_rows = _object_rows(client, "shifts")
    order_rows = _object_rows(client, "orders")
    closed_shifts = [row for row in shift_rows if str(row.get("status") or "").upper() == "CLOSED"]
    if connection.sync_from_date is not None:
        closed_shifts = [
            row
            for row in closed_shifts
            if business_date_for_shift(row, cutoff_hour=connection.business_day_cutoff_hour)
            >= connection.sync_from_date
        ]
    closed_shift_ids = {str(row.get("frontId") or row.get("_id") or "") for row in closed_shifts}
    relevant_order_rows = [row for row in order_rows if str(row.get("shiftId") or "") in closed_shift_ids]
    order_details_by_shift: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in relevant_order_rows:
        object_id = int(row.get("id") or 0)
        if object_id <= 0:
            raise QuickRestoDataError("QuickResto order identifier is missing")
        detail = _object_detail(client, "orders", object_id)
        order_details_by_shift[str(detail.get("shiftId") or "")].append(detail)

    changed_dates: set[date] = set()
    shifts_imported = 0
    normalized_rows: list[dict[str, Any]] = []
    for shift in closed_shifts:
        shift_id = str(shift.get("frontId") or shift.get("_id") or "")
        normalized = normalize_closed_shift(
            shift,
            order_details_by_shift.get(shift_id, []),
            cutoff_hour=connection.business_day_cutoff_hour,
        )
        normalized_rows.append(normalized)
        business_date = date.fromisoformat(normalized["business_date"])
        existing = db.execute(
            select(QuickRestoShiftImport).where(
                QuickRestoShiftImport.connection_id == connection.id,
                QuickRestoShiftImport.external_shift_id == shift_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = QuickRestoShiftImport(
                connection_id=connection.id,
                external_shift_id=shift_id,
                external_shift_pk=int(normalized["external_shift_pk"]),
                source_version=int(normalized["source_version"]),
                business_date=business_date,
                local_closed_at=datetime.fromisoformat(normalized["local_closed_at"]),
                payload_hash=str(normalized["payload_hash"]),
                normalized_json=normalized,
                first_imported_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(existing)
            shifts_imported += 1
            changed_dates.add(business_date)
        elif existing.payload_hash != normalized["payload_hash"]:
            changed_dates.add(existing.business_date)
            changed_dates.add(business_date)
            existing.external_shift_pk = int(normalized["external_shift_pk"])
            existing.source_version = int(normalized["source_version"])
            existing.business_date = business_date
            existing.local_closed_at = datetime.fromisoformat(normalized["local_closed_at"])
            existing.payload_hash = str(normalized["payload_hash"])
            existing.normalized_json = normalized
            existing.updated_at = _utcnow()
            shifts_imported += 1
        else:
            changed_dates.add(business_date)
    db.flush()

    result_counts = {"created": 0, "updated": 0, "unchanged": 0}
    conflicts: list[dict[str, str]] = []
    report_ids: list[int] = []
    for target_date in sorted(changed_dates):
        stored_shifts = (
            db.execute(
                select(QuickRestoShiftImport).where(
                    QuickRestoShiftImport.connection_id == connection.id,
                    QuickRestoShiftImport.business_date == target_date,
                )
            )
            .scalars()
            .all()
        )
        aggregate = aggregate_normalized_shifts(item.normalized_json for item in stored_shifts)
        try:
            mapped = _mapped_aggregate(db, connection=connection, aggregate=aggregate)
            outcome, report = _upsert_draft_report(
                db,
                connection=connection,
                aggregate=mapped,
                run=run,
                actor_user_id=actor_user_id,
            )
            result_counts[outcome] += 1
            report_ids.append(int(report.id))
            for item in stored_shifts:
                item.daily_report_id = report.id
        except QuickRestoDataError as exc:
            conflicts.append({"business_date": target_date.isoformat(), "error": str(exc)})

    return {
        **mapping_summary,
        "shifts_seen": len(closed_shifts),
        "shifts_imported": shifts_imported,
        "reports_created": result_counts["created"],
        "reports_updated": result_counts["updated"],
        "reports_unchanged": result_counts["unchanged"],
        "report_ids": sorted(set(report_ids)),
        "conflicts": conflicts,
    }


def sync_quickresto_connection(
    db: Session,
    *,
    connection: QuickRestoConnection,
    requested_by_user_id: int | None,
    trigger: str,
    client: QuickRestoClient | None = None,
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
    if (
        connection.last_sync_status == "RUNNING"
        and connection.last_sync_started_at is not None
        and _ensure_utc(connection.last_sync_started_at) > now - timedelta(minutes=30)
    ):
        db.rollback()
        raise QuickRestoSyncError("QuickResto sync is already running")
    if not connection.is_active:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection is disabled")

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

    managed_client = client is None
    active_client = client or build_quickresto_client(connection)
    context = active_client if managed_client else nullcontext(active_client)
    try:
        with context as current_client:
            summary = _perform_sync(
                db,
                connection=connection,
                run=run,
                actor_user_id=actor_user_id,
                client=current_client,
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
        db.refresh(run)
        return run
    except (QuickRestoError, QuickRestoDataError, QuickRestoSyncError, ValueError) as exc:
        _record_failed_run(
            db,
            run_id=run.id,
            connection_id=connection.id,
            message=str(exc),
        )
        raise QuickRestoSyncError(str(exc)) from exc
    except Exception as exc:
        message = "Unexpected QuickResto sync failure"
        _record_failed_run(
            db,
            run_id=run.id,
            connection_id=connection.id,
            message=message,
        )
        raise QuickRestoSyncError(message) from exc
