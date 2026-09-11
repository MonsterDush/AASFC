from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_batch import QuickRestoImportBatch
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.services.integrations.quickresto import QuickRestoClient
from app.services.integrations.quickresto_notifications import enqueue_quickresto_import_notification
from app.services.integrations.quickresto_scope import QuickRestoScopeError, ensure_quickresto_scope_ready
from app.services.integrations.quickresto_sync import (
    QuickRestoSyncError,
    build_quickresto_client,
    quickresto_sync_is_active,
    reclaim_stale_quickresto_sync_state,
    sync_quickresto_connection,
)


ACTIVE_BATCH_STATUSES = frozenset({"PENDING", "RUNNING"})
_BATCH_LEASE_TIMEOUT = timedelta(minutes=30)
_STALE_BATCH_MESSAGE = "Предыдущий обработчик месячного импорта остановился. Очередь восстановлена с текущего месяца."
_TOTAL_FIELDS = (
    "shifts_seen",
    "shifts_imported",
    "reports_created",
    "reports_updated",
    "reports_unchanged",
    "issue_count",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_month_boundary(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def monthly_periods_count(period_start: date, period_end_exclusive: date) -> int:
    if period_end_exclusive <= period_start:
        raise ValueError("QuickResto import period end must be later than its start")
    count = 0
    cursor = period_start
    while cursor < period_end_exclusive:
        count += 1
        cursor = min(_next_month_boundary(cursor), period_end_exclusive)
    return count


def _empty_totals() -> dict[str, int]:
    return {field: 0 for field in _TOTAL_FIELDS}


def _batch_totals(batch: QuickRestoImportBatch) -> dict[str, int]:
    summary = batch.summary_json if isinstance(batch.summary_json, dict) else {}
    source = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    return {field: int(source.get(field) or 0) for field in _TOTAL_FIELDS}


def serialize_quickresto_import_batch(batch: QuickRestoImportBatch) -> dict[str, Any]:
    return {
        "id": int(batch.id),
        "trigger": str(batch.trigger),
        "force_full": bool(batch.force_full),
        "status": str(batch.status),
        "period_start": batch.period_start.isoformat(),
        "period_end_exclusive": batch.period_end_exclusive.isoformat(),
        "next_period_start": batch.next_period_start.isoformat(),
        "current_period_start": batch.current_period_start.isoformat() if batch.current_period_start else None,
        "current_period_end_exclusive": (
            batch.current_period_end_exclusive.isoformat() if batch.current_period_end_exclusive else None
        ),
        "total_periods": int(batch.total_periods),
        "completed_periods": int(batch.completed_periods),
        "partial_periods": int(batch.partial_periods),
        "retry_count": int(batch.retry_count),
        "last_sync_run_id": batch.last_sync_run_id,
        "error": batch.error_message,
        "summary": batch.summary_json,
        "created_at": batch.created_at.isoformat(),
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def latest_quickresto_import_batch(db: Session, *, connection_id: int) -> QuickRestoImportBatch | None:
    return db.execute(
        select(QuickRestoImportBatch)
        .where(QuickRestoImportBatch.connection_id == int(connection_id))
        .order_by(QuickRestoImportBatch.created_at.desc(), QuickRestoImportBatch.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def active_quickresto_import_batch(db: Session, *, connection_id: int) -> QuickRestoImportBatch | None:
    return db.execute(
        select(QuickRestoImportBatch)
        .where(
            QuickRestoImportBatch.connection_id == int(connection_id),
            QuickRestoImportBatch.status.in_(ACTIVE_BATCH_STATUSES),
        )
        .order_by(QuickRestoImportBatch.created_at.asc(), QuickRestoImportBatch.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def quickresto_import_batch_is_active(db: Session, *, connection_id: int) -> bool:
    return active_quickresto_import_batch(db, connection_id=connection_id) is not None


def create_quickresto_import_batch(
    db: Session,
    *,
    connection: QuickRestoConnection,
    requested_by_user_id: int | None,
    force_full: bool,
    today: date | None = None,
) -> QuickRestoImportBatch:
    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.id == int(connection.id))
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
    if active_quickresto_import_batch(db, connection_id=int(connection.id)) is not None:
        db.rollback()
        raise QuickRestoSyncError("Помесячный импорт QuickResto уже поставлен в очередь")
    if not connection.is_active:
        db.rollback()
        raise QuickRestoSyncError("QuickResto connection is disabled")
    try:
        ensure_quickresto_scope_ready(connection)
    except QuickRestoScopeError as exc:
        db.rollback()
        raise QuickRestoSyncError(str(exc)) from exc

    target_today = today or now.date()
    historical = bool(force_full or connection.last_full_reconciliation_at is None)
    if historical:
        period_start = connection.sync_from_date
        if period_start is None:
            db.rollback()
            raise QuickRestoSyncError("Укажите дату «Импортировать начиная с» перед историческим импортом")
    else:
        cursor = connection.incremental_cursor_closed_at
        if cursor is None:
            overlap_start = target_today
        elif cursor.tzinfo is None:
            overlap_start = cursor.date() - timedelta(days=2)
        else:
            overlap_start = cursor.astimezone(timezone.utc).date() - timedelta(days=2)
        period_start = max(connection.sync_from_date or overlap_start, overlap_start)
    if period_start > target_today:
        db.rollback()
        raise QuickRestoSyncError("Дата начала импорта находится в будущем")

    period_end_exclusive = target_today + timedelta(days=1)
    batch = QuickRestoImportBatch(
        connection_id=int(connection.id),
        requested_by_user_id=requested_by_user_id,
        trigger="FULL" if force_full else "MANUAL",
        force_full=historical,
        status="PENDING",
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        next_period_start=period_start,
        total_periods=monthly_periods_count(period_start, period_end_exclusive),
        completed_periods=0,
        partial_periods=0,
        retry_count=0,
        summary_json={"totals": _empty_totals(), "periods": [], "issue_ids": []},
    )
    connection.last_sync_status = "QUEUED"
    connection.last_sync_error = None
    db.add(batch)
    db.add(connection)
    db.commit()
    db.refresh(batch)
    return batch


def retry_quickresto_import_batch(
    db: Session,
    *,
    batch: QuickRestoImportBatch,
) -> QuickRestoImportBatch:
    locked = db.execute(
        select(QuickRestoImportBatch)
        .where(QuickRestoImportBatch.id == int(batch.id))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto import batch no longer exists")
    if str(locked.status).upper() != "FAILED":
        db.rollback()
        raise QuickRestoSyncError("Повторить можно только упавший помесячный импорт")
    if locked.next_period_start >= locked.period_end_exclusive:
        db.rollback()
        raise QuickRestoSyncError("В этом импорте не осталось необработанных месяцев")
    if active_quickresto_import_batch(db, connection_id=int(locked.connection_id)) is not None:
        db.rollback()
        raise QuickRestoSyncError("Другой помесячный импорт QuickResto уже выполняется")

    locked.status = "PENDING"
    locked.retry_count = int(locked.retry_count) + 1
    locked.error_message = None
    locked.finished_at = None
    locked.current_period_start = None
    locked.current_period_end_exclusive = None
    locked.updated_at = _utcnow()
    connection = db.get(QuickRestoConnection, int(locked.connection_id))
    if connection is not None:
        connection.last_sync_status = "QUEUED"
        connection.last_sync_error = None
        db.add(connection)
    db.add(locked)
    db.commit()
    db.refresh(locked)
    return locked


def _run_counts(run: QuickRestoSyncRun) -> dict[str, int]:
    summary = run.summary_json if isinstance(run.summary_json, dict) else {}
    return {
        "shifts_seen": int(run.shifts_seen or 0),
        "shifts_imported": int(run.shifts_imported or 0),
        "reports_created": int(run.reports_created or 0),
        "reports_updated": int(run.reports_updated or 0),
        "reports_unchanged": int(run.reports_unchanged or 0),
        "issue_count": int(summary.get("issue_count") or 0),
    }


def _run_issue_ids(run: QuickRestoSyncRun) -> list[int]:
    summary = run.summary_json if isinstance(run.summary_json, dict) else {}
    values = summary.get("issue_ids")
    if not isinstance(values, list):
        return []
    output: list[int] = []
    for value in values:
        try:
            issue_id = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if issue_id > 0:
            output.append(issue_id)
    return output


def _merge_run_into_batch_summary(
    batch: QuickRestoImportBatch,
    *,
    run: QuickRestoSyncRun,
    period_start: date,
    period_end_exclusive: date,
) -> None:
    summary = dict(batch.summary_json) if isinstance(batch.summary_json, dict) else {}
    totals = _batch_totals(batch)
    counts = _run_counts(run)
    for field in _TOTAL_FIELDS:
        totals[field] += counts[field]

    periods = list(summary.get("periods")) if isinstance(summary.get("periods"), list) else []
    periods.append(
        {
            "period_start": period_start.isoformat(),
            "period_end_exclusive": period_end_exclusive.isoformat(),
            "run_id": int(run.id),
            "status": str(run.status),
            "error": run.error_message,
            **counts,
        }
    )
    issue_ids: set[int] = set()
    for value in summary.get("issue_ids") or []:
        try:
            issue_ids.add(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    issue_ids.update(_run_issue_ids(run))
    summary.update(
        {
            "totals": totals,
            "periods": periods,
            "issue_ids": sorted(issue_id for issue_id in issue_ids if issue_id > 0),
        }
    )
    batch.summary_json = summary


def _latest_connection_run(db: Session, *, connection_id: int) -> QuickRestoSyncRun | None:
    return db.execute(
        select(QuickRestoSyncRun)
        .where(QuickRestoSyncRun.connection_id == int(connection_id))
        .order_by(QuickRestoSyncRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _mark_batch_failed(
    db: Session,
    *,
    batch_id: int,
    connection_id: int,
    error: str,
) -> QuickRestoImportBatch:
    batch = db.get(QuickRestoImportBatch, int(batch_id))
    if batch is None:
        raise QuickRestoSyncError("QuickResto import batch no longer exists")
    last_run = _latest_connection_run(db, connection_id=connection_id)
    if last_run is not None:
        batch.last_sync_run_id = int(last_run.id)
    batch.status = "FAILED"
    batch.error_message = str(error)[:4000]
    batch.finished_at = _utcnow()
    batch.current_period_start = None
    batch.current_period_end_exclusive = None
    connection = db.get(QuickRestoConnection, int(connection_id))
    if connection is not None:
        connection.last_sync_status = "FAILED"
        connection.last_sync_error = batch.error_message
        db.add(connection)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _enqueue_batch_notification(
    db: Session,
    *,
    batch: QuickRestoImportBatch,
    connection: QuickRestoConnection,
) -> None:
    if batch.last_sync_run_id is None:
        return
    totals = _batch_totals(batch)
    enqueue_quickresto_import_notification(
        db,
        venue_id=int(connection.venue_id),
        connection_id=int(connection.id),
        run_id=int(batch.last_sync_run_id),
        status=str(batch.status),
        shifts_seen=totals["shifts_seen"],
        shifts_imported=totals["shifts_imported"],
        reports_created=totals["reports_created"],
        reports_updated=totals["reports_updated"],
        reports_unchanged=totals["reports_unchanged"],
        issue_count=totals["issue_count"],
        report_import_mode=str(connection.report_import_mode or "CLOSED"),
        technical_summary=(
            f"Помесячный импорт: обработано {int(batch.completed_periods)} из {int(batch.total_periods)} периодов"
        ),
        correlation_id=f"quickresto-import-batch-{int(batch.id)}",
    )


def process_quickresto_import_batch(
    db: Session,
    *,
    batch_id: int,
    client: QuickRestoClient | None = None,
) -> QuickRestoImportBatch:
    batch = db.execute(
        select(QuickRestoImportBatch)
        .where(QuickRestoImportBatch.id == int(batch_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if batch is None:
        db.rollback()
        raise QuickRestoSyncError("QuickResto import batch no longer exists")
    if str(batch.status).upper() != "PENDING":
        db.rollback()
        return batch

    connection = db.get(QuickRestoConnection, int(batch.connection_id))
    if connection is None:
        return _mark_batch_failed(
            db,
            batch_id=int(batch.id),
            connection_id=int(batch.connection_id),
            error="QuickResto connection no longer exists",
        )
    now = _utcnow()
    batch.status = "RUNNING"
    batch.error_message = None
    batch.finished_at = None
    batch.started_at = batch.started_at or now
    batch.updated_at = now
    db.add(batch)
    db.commit()
    db.refresh(batch)

    quickresto_client = client or build_quickresto_client(connection)
    while batch.next_period_start < batch.period_end_exclusive:
        period_start = batch.next_period_start
        period_end_exclusive = min(_next_month_boundary(period_start), batch.period_end_exclusive)
        period_index = int(batch.completed_periods) + 1
        batch.current_period_start = period_start
        batch.current_period_end_exclusive = period_end_exclusive
        batch.updated_at = _utcnow()
        db.add(batch)
        db.commit()

        try:
            run = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=batch.requested_by_user_id,
                trigger="MONTHLY_IMPORT",
                client=quickresto_client,
                force_full=bool(batch.force_full),
                period_start=period_start,
                period_end_exclusive=period_end_exclusive,
                include_undated_sources=period_start == batch.period_start,
                finalize_full_reconciliation=False,
                refresh_catalog=period_start == batch.period_start,
                batch_id=int(batch.id),
                batch_period_index=period_index,
                batch_period_total=int(batch.total_periods),
                notify_result=False,
            )
        except QuickRestoSyncError as exc:
            return _mark_batch_failed(
                db,
                batch_id=int(batch.id),
                connection_id=int(batch.connection_id),
                error=str(exc),
            )

        refreshed_batch = db.get(QuickRestoImportBatch, int(batch.id))
        refreshed_connection = db.get(QuickRestoConnection, int(batch.connection_id))
        if refreshed_batch is None or refreshed_connection is None:
            raise QuickRestoSyncError("QuickResto monthly import state disappeared")
        batch = refreshed_batch
        connection = refreshed_connection
        _merge_run_into_batch_summary(
            batch,
            run=run,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
        )
        batch.last_sync_run_id = int(run.id)
        batch.completed_periods = int(batch.completed_periods) + 1
        if str(run.status).upper() == "PARTIAL":
            batch.partial_periods = int(batch.partial_periods) + 1
        batch.next_period_start = period_end_exclusive
        batch.current_period_start = None
        batch.current_period_end_exclusive = None
        batch.updated_at = _utcnow()
        connection.last_sync_status = "QUEUED"
        connection.last_sync_error = None
        db.add(batch)
        db.add(connection)
        db.commit()

    batch = db.get(QuickRestoImportBatch, int(batch.id))
    connection = db.get(QuickRestoConnection, int(batch.connection_id))
    if batch is None or connection is None:
        raise QuickRestoSyncError("QuickResto monthly import state disappeared")
    batch.status = "PARTIAL" if int(batch.partial_periods) > 0 else "SUCCEEDED"
    batch.finished_at = _utcnow()
    batch.current_period_start = None
    batch.current_period_end_exclusive = None
    batch.error_message = None
    if batch.force_full:
        connection.last_full_reconciliation_at = batch.finished_at
    connection.last_sync_status = batch.status
    connection.last_sync_error = None
    _enqueue_batch_notification(db, batch=batch, connection=connection)
    db.add(batch)
    db.add(connection)
    db.commit()
    db.refresh(batch)
    return batch


def reclaim_stale_quickresto_import_batches(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    timestamp = now or _utcnow()
    cutoff = timestamp - _BATCH_LEASE_TIMEOUT
    stale_batches = list(
        db.execute(
            select(QuickRestoImportBatch)
            .where(
                QuickRestoImportBatch.status == "RUNNING",
                QuickRestoImportBatch.updated_at <= cutoff,
            )
            .with_for_update()
        ).scalars()
    )
    reclaimed = 0
    for batch in stale_batches:
        connection = db.get(QuickRestoConnection, int(batch.connection_id))
        if connection is not None and quickresto_sync_is_active(connection, now=timestamp):
            continue
        batch.status = "PENDING"
        batch.error_message = _STALE_BATCH_MESSAGE
        batch.current_period_start = None
        batch.current_period_end_exclusive = None
        batch.finished_at = None
        batch.updated_at = timestamp
        if connection is not None:
            reclaim_stale_quickresto_sync_state(db, connection=connection, now=timestamp)
            connection.last_sync_status = "QUEUED"
            connection.last_sync_error = None
            db.add(connection)
        db.add(batch)
        reclaimed += 1
    return reclaimed


def run_quickresto_import_batch_worker(batch_id: int) -> None:
    with SessionLocal() as db:
        try:
            process_quickresto_import_batch(db, batch_id=int(batch_id))
        except Exception as exc:
            db.rollback()
            batch = db.get(QuickRestoImportBatch, int(batch_id))
            if batch is not None and str(batch.status).upper() in ACTIVE_BATCH_STATUSES:
                _mark_batch_failed(
                    db,
                    batch_id=int(batch.id),
                    connection_id=int(batch.connection_id),
                    error=str(exc) or exc.__class__.__name__,
                )
            raise
