from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.integrations.canonical.report_projector import ReportProjector, ShadowProjectionCandidate
from app.integrations.canonical.order_items import attribution_minor_for_item
from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.base.dto import ProviderRecord
from app.integrations.feature_flags import feature_flags_for
from app.integrations.raw.storage import record_raw_object
from app.models.daily_report_value import DailyReportValue
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_connection import IntegrationConnection
from app.models.integration_import_batch import IntegrationImportBatch
from app.models.integration_import_chunk import IntegrationImportChunk
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.integration_sync_job import IntegrationSyncJob
from app.models.integration_sync_run import IntegrationSyncRun
from app.models.pos_canonical import (
    POSBusinessShift,
    POSOrder,
    POSOrderDiscount,
    POSOrderEvent,
    POSOrderItem,
    POSPayment,
    POSPaymentType,
    POSProduct,
    POSProductGroup,
    POSRefund,
    POSTerminal,
    POSVenue,
    POSWarehouse,
)
from app.models.pos_mapping import (
    POSGroupDepartmentAllocation,
    POSGroupDepartmentMapping,
    POSPaymentTypeMapping,
    POSProductKpiMapping,
)
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_dish_category_path import QuickRestoDishCategoryPath
from app.models.quickresto_external_venue import QuickRestoExternalVenue
from app.models.quickresto_import_batch import QuickRestoImportBatch
from app.models.quickresto_kpi_product_mapping import QuickRestoKpiProductMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_sale_place_scope import QuickRestoSalePlaceScope
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.quickresto_store_scope import QuickRestoStoreScope
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.venue import Venue
from app.services.integrations.quickresto_department_distribution import (
    allocate_integer_total,
    mapping_department_distribution,
)
from app.services.integrations.quickresto_issues import open_source_snapshot
from app.services.integrations.quickresto_normalize import (
    _allocate_minor_to_rubles,
    _money_minor,
    normalize_closed_shift,
    stable_payload_hash,
)


NORMALIZATION_VERSION = "quickresto-acdm-v1"
CAPABILITY = Capability.BUSINESS_SHIFTS.value
_RAW_ALLOWLIST = {"schema_version", "shift", "orders", "scope"}


@dataclass(slots=True)
class QuickRestoCanonicalContext:
    connection: IntegrationConnection
    run: IntegrationSyncRun
    enabled: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _category_title(value: Any, external_id: int) -> str:
    title = str(value or "").strip()
    return title or f"Категория QuickResto #{int(external_id)}"


def _money(value: Any) -> Decimal:
    return (Decimal(str(value or 0))).quantize(Decimal("0.0001"))


def _quantity(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


def _minor_to_money(value: int) -> Decimal:
    return (Decimal(int(value)) / Decimal(100)).quantize(Decimal("0.0001"))


def _money_to_minor(value: Any) -> int:
    return int((Decimal(str(value or 0)) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _aware_local(value: Any, timezone_name: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def ensure_quickresto_integration_connection(
    db: Session,
    *,
    connection: QuickRestoConnection,
) -> IntegrationConnection:
    canonical = (
        db.get(IntegrationConnection, int(connection.integration_connection_id))
        if connection.integration_connection_id
        else None
    )
    if canonical is None:
        canonical = db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.venue_id == int(connection.venue_id),
                IntegrationConnection.provider == "QUICKRESTO",
            )
        ).scalar_one_or_none()
    flags = feature_flags_for("QUICKRESTO")
    if canonical is None:
        canonical = IntegrationConnection(
            venue_id=int(connection.venue_id),
            provider="QUICKRESTO",
            status="ACTIVE" if connection.is_active else "PAUSED",
            external_venue_id=str(connection.external_venue_id) if connection.external_venue_id else None,
            shadow_sync_enabled=flags.shadow_write_enabled,
            read_mode="LEGACY",
            coverage_start=connection.sync_from_date,
            provider_limits_json={"max_page_size": 1000, "max_pages": 100, "package": "CALENDAR_MONTH"},
        )
        db.add(canonical)
        db.flush()
    canonical.status = "ACTIVE" if connection.is_active else "PAUSED"
    canonical.external_venue_id = str(connection.external_venue_id) if connection.external_venue_id else None
    canonical.shadow_sync_enabled = flags.shadow_write_enabled
    # Operations owns the per-connection rollout gate. Synchronization
    # refreshes health and coverage but must not silently undo POS_CANONICAL.
    canonical.coverage_start = connection.sync_from_date
    canonical.updated_at = _utcnow()
    connection.integration_connection_id = int(canonical.id)
    db.add_all([canonical, connection])
    db.flush()
    return canonical


def _next_month_boundary(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _monthly_periods(period_start: date, period_end_exclusive: date) -> list[tuple[date, date]]:
    periods: list[tuple[date, date]] = []
    cursor = period_start
    while cursor < period_end_exclusive:
        chunk_end = min(_next_month_boundary(cursor), period_end_exclusive)
        periods.append((cursor, chunk_end))
        cursor = chunk_end
    return periods


def ensure_quickresto_canonical_import_batch(
    db: Session,
    *,
    connection: QuickRestoConnection,
    batch: QuickRestoImportBatch,
) -> IntegrationImportBatch | None:
    if not feature_flags_for("QUICKRESTO").provider_rollout_enabled:
        return None
    canonical_connection = ensure_quickresto_integration_connection(db, connection=connection)
    canonical_batch = (
        db.get(IntegrationImportBatch, int(batch.integration_import_batch_id))
        if batch.integration_import_batch_id
        else None
    )
    if canonical_batch is None:
        canonical_batch = IntegrationImportBatch(
            connection_id=int(canonical_connection.id),
            requested_by_user_id=batch.requested_by_user_id,
            trigger=str(batch.trigger),
            mode="FULL" if batch.force_full else "INCREMENTAL",
            status=str(batch.status),
            active_guard=1 if str(batch.status) in {"PENDING", "RUNNING"} else None,
            period_start=batch.period_start,
            period_end_exclusive=batch.period_end_exclusive,
            next_period_start=batch.next_period_start,
            total_chunks=int(batch.total_periods),
            completed_chunks=int(batch.completed_periods),
            partial_chunks=int(batch.partial_periods),
            retry_count=int(batch.retry_count),
            counters_json=dict((batch.summary_json or {}).get("totals") or {}),
            created_at=batch.created_at,
            started_at=batch.started_at,
            finished_at=batch.finished_at,
            updated_at=batch.updated_at or _utcnow(),
        )
        db.add(canonical_batch)
        db.flush()
    batch.integration_import_batch_id = int(canonical_batch.id)
    db.add(batch)

    expected_periods = _monthly_periods(batch.period_start, batch.period_end_exclusive)
    existing = {
        int(row.sequence): row
        for row in db.execute(
            select(IntegrationImportChunk).where(IntegrationImportChunk.batch_id == int(canonical_batch.id))
        ).scalars()
    }
    for sequence, (period_start, period_end_exclusive) in enumerate(expected_periods, start=1):
        chunk = existing.get(sequence)
        if chunk is None:
            db.add(
                IntegrationImportChunk(
                    batch_id=int(canonical_batch.id),
                    sequence=sequence,
                    period_start=period_start,
                    period_end_exclusive=period_end_exclusive,
                    status="PENDING",
                )
            )
        elif chunk.period_start != period_start or chunk.period_end_exclusive != period_end_exclusive:
            raise ValueError("QuickResto canonical import chunks do not match the legacy batch range")
    if len(existing) > len(expected_periods):
        raise ValueError("QuickResto canonical import batch contains unexpected chunks")
    db.flush()
    return canonical_batch


def _canonical_chunk_for_period(
    db: Session,
    *,
    canonical_batch_id: int,
    period_start: date,
    period_end_exclusive: date | None = None,
) -> IntegrationImportChunk | None:
    statement = select(IntegrationImportChunk).where(
        IntegrationImportChunk.batch_id == int(canonical_batch_id),
        IntegrationImportChunk.period_start == period_start,
    )
    if period_end_exclusive is not None:
        statement = statement.where(IntegrationImportChunk.period_end_exclusive == period_end_exclusive)
    return db.execute(statement).scalar_one_or_none()


def _refresh_canonical_batch_progress(
    db: Session,
    *,
    canonical_batch: IntegrationImportBatch,
    legacy_batch: QuickRestoImportBatch,
) -> None:
    chunks = list(
        db.execute(
            select(IntegrationImportChunk)
            .where(IntegrationImportChunk.batch_id == int(canonical_batch.id))
            .order_by(IntegrationImportChunk.sequence)
        ).scalars()
    )
    completed = [row for row in chunks if str(row.status) in {"SUCCEEDED", "PARTIAL"}]
    canonical_batch.completed_chunks = len(completed)
    canonical_batch.partial_chunks = sum(str(row.status) == "PARTIAL" for row in completed)
    canonical_batch.total_chunks = len(chunks)
    canonical_batch.next_period_start = legacy_batch.next_period_start
    canonical_batch.retry_count = int(legacy_batch.retry_count)
    canonical_batch.current_chunk_sequence = next(
        (
            int(row.sequence)
            for row in chunks
            if legacy_batch.current_period_start is not None
            and row.period_start == legacy_batch.current_period_start
            and row.period_end_exclusive == legacy_batch.current_period_end_exclusive
        ),
        None,
    )
    canonical_batch.coverage_start = min((row.period_start for row in completed), default=None)
    canonical_batch.coverage_end_exclusive = max((row.period_end_exclusive for row in completed), default=None)
    canonical_batch.counters_json = dict((legacy_batch.summary_json or {}).get("totals") or {})
    canonical_batch.error_code = "QUICKRESTO_IMPORT_FAILED" if legacy_batch.error_message else None
    canonical_batch.error_message = legacy_batch.error_message
    canonical_batch.started_at = legacy_batch.started_at
    canonical_batch.finished_at = legacy_batch.finished_at
    canonical_batch.updated_at = _utcnow()

    legacy_status = str(legacy_batch.status)
    if legacy_status in {"PENDING", "RUNNING", "FAILED", "CANCELLED"}:
        canonical_status = legacy_status
    elif any(str(row.status) == "FAILED" for row in chunks):
        canonical_status = "FAILED"
    elif any(str(row.status) == "PARTIAL" for row in chunks):
        canonical_status = "PARTIAL"
    else:
        canonical_status = legacy_status
    canonical_batch.status = canonical_status
    canonical_batch.active_guard = 1 if canonical_status in {"PENDING", "RUNNING"} else None
    db.add(canonical_batch)


def ensure_quickresto_import_job(
    db: Session,
    *,
    connection: QuickRestoConnection,
    batch: QuickRestoImportBatch,
) -> IntegrationSyncJob | None:
    if not feature_flags_for("QUICKRESTO").provider_rollout_enabled:
        return None
    canonical = ensure_quickresto_integration_connection(db, connection=connection)
    canonical_batch = ensure_quickresto_canonical_import_batch(db, connection=connection, batch=batch)
    job = db.get(IntegrationSyncJob, int(batch.integration_sync_job_id)) if batch.integration_sync_job_id else None
    if job is None:
        job = db.execute(
            select(IntegrationSyncJob).where(
                IntegrationSyncJob.idempotency_key == f"quickresto-import-batch:{int(batch.id)}"
            )
        ).scalar_one_or_none()
    payload = {
        "legacy_batch_id": int(batch.id),
        "period_start": batch.period_start.isoformat(),
        "period_end_exclusive": batch.period_end_exclusive.isoformat(),
        "package": "CALENDAR_MONTH",
        "overlap_seconds": 172800,
        "queue_owner": "quickresto_import_batches",
    }
    if job is None:
        job = IntegrationSyncJob(
            connection_id=int(canonical.id),
            job_type="HISTORICAL_IMPORT" if batch.force_full else "INCREMENTAL_IMPORT",
            capability=CAPABILITY,
            queue="normal",
            priority=100,
            status=str(batch.status),
            idempotency_key=f"quickresto-import-batch:{int(batch.id)}",
            job_payload_json=payload,
            max_attempts=5,
        )
        db.add(job)
        db.flush()
    job.status = str(batch.status)
    job.job_payload_json = payload
    job.updated_at = _utcnow()
    batch.integration_sync_job_id = int(job.id)
    if canonical_batch is not None:
        canonical_batch.sync_job_id = int(job.id)
        db.add(canonical_batch)
    db.add_all([job, batch])
    db.flush()
    return job


def mirror_quickresto_import_job(
    db: Session,
    *,
    batch: QuickRestoImportBatch,
    connection: QuickRestoConnection,
    error: str | None = None,
) -> IntegrationSyncJob | None:
    if not feature_flags_for("QUICKRESTO").provider_rollout_enabled:
        return None
    job = ensure_quickresto_import_job(db, connection=connection, batch=batch)
    if job is None:
        return None
    canonical_batch = ensure_quickresto_canonical_import_batch(db, connection=connection, batch=batch)
    if canonical_batch is not None:
        if str(batch.status) == "FAILED":
            failed_chunk = _canonical_chunk_for_period(
                db,
                canonical_batch_id=int(canonical_batch.id),
                period_start=batch.next_period_start,
            )
            if failed_chunk is not None and str(failed_chunk.status) not in {"SUCCEEDED", "PARTIAL"}:
                failed_chunk.status = "FAILED"
                failed_chunk.error_code = "QUICKRESTO_IMPORT_FAILED"
                failed_chunk.error_message = str(error or batch.error_message or "")[:4000] or None
                failed_chunk.finished_at = _utcnow()
                failed_chunk.updated_at = _utcnow()
                db.add(failed_chunk)
        elif str(batch.status) == "PENDING":
            retry_chunk = _canonical_chunk_for_period(
                db,
                canonical_batch_id=int(canonical_batch.id),
                period_start=batch.next_period_start,
            )
            if retry_chunk is not None and str(retry_chunk.status) in {"FAILED", "RUNNING"}:
                retry_chunk.status = "PENDING"
                retry_chunk.error_code = None
                retry_chunk.error_message = None
                retry_chunk.finished_at = None
                retry_chunk.updated_at = _utcnow()
                db.add(retry_chunk)
        _refresh_canonical_batch_progress(db, canonical_batch=canonical_batch, legacy_batch=batch)
        canonical_batch.sync_job_id = int(job.id)
        job.status = str(canonical_batch.status)
        db.add(canonical_batch)
    else:
        job.status = str(batch.status)
    job.last_error_code = "QUICKRESTO_IMPORT_FAILED" if error else None
    job.last_error_message = str(error)[:4000] if error else None
    job.heartbeat_at = _utcnow() if str(batch.status) == "RUNNING" else job.heartbeat_at
    job.lease_expires_at = None if str(batch.status) not in {"PENDING", "RUNNING"} else job.lease_expires_at
    payload = dict(job.job_payload_json or {})
    payload.update(
        {
            "next_period_start": batch.next_period_start.isoformat(),
            "completed_periods": int(batch.completed_periods),
            "partial_periods": int(batch.partial_periods),
            "total_periods": int(batch.total_periods),
            "retry_count": int(batch.retry_count),
        }
    )
    job.job_payload_json = payload
    job.updated_at = _utcnow()
    db.add(job)
    db.flush()
    return job


def start_quickresto_canonical_run(
    db: Session,
    *,
    connection: QuickRestoConnection,
    legacy_run: QuickRestoSyncRun,
    period_start: date | None,
    period_end_exclusive: date | None,
    batch: QuickRestoImportBatch | None = None,
) -> QuickRestoCanonicalContext | None:
    if not feature_flags_for("QUICKRESTO").provider_rollout_enabled:
        return None
    canonical = ensure_quickresto_integration_connection(db, connection=connection)
    run = (
        db.get(IntegrationSyncRun, int(legacy_run.integration_sync_run_id))
        if legacy_run.integration_sync_run_id
        else None
    )
    if run is None:
        run = IntegrationSyncRun(
            connection_id=int(canonical.id),
            capability=CAPABILITY,
            trigger=str(legacy_run.trigger),
            status="RUNNING",
            started_at=legacy_run.started_at,
            cursor_before=(
                connection.incremental_cursor_closed_at.isoformat()
                if connection.incremental_cursor_closed_at is not None
                else None
            ),
            summary_json={
                "legacy_sync_run_id": int(legacy_run.id),
                "period_start": period_start.isoformat() if period_start else None,
                "period_end_exclusive": period_end_exclusive.isoformat() if period_end_exclusive else None,
                "read_mode": "LEGACY",
            },
        )
        db.add(run)
        db.flush()
    legacy_run.integration_sync_run_id = int(run.id)
    if batch is not None:
        canonical_batch = ensure_quickresto_canonical_import_batch(db, connection=connection, batch=batch)
        if canonical_batch is not None and period_start is not None and period_end_exclusive is not None:
            chunk = _canonical_chunk_for_period(
                db,
                canonical_batch_id=int(canonical_batch.id),
                period_start=period_start,
                period_end_exclusive=period_end_exclusive,
            )
            if chunk is None:
                raise ValueError("QuickResto sync range has no canonical import chunk")
            if str(chunk.status) in {"SUCCEEDED", "PARTIAL"}:
                raise ValueError("QuickResto canonical import chunk was already completed")
            if chunk.sync_run_id != int(run.id):
                chunk.attempts = int(chunk.attempts) + 1
            chunk.status = "RUNNING"
            chunk.sync_run_id = int(run.id)
            chunk.error_code = None
            chunk.error_message = None
            chunk.started_at = _utcnow()
            chunk.finished_at = None
            chunk.updated_at = _utcnow()
            canonical_batch.current_chunk_sequence = int(chunk.sequence)
            canonical_batch.last_sync_run_id = int(run.id)
            db.add_all([canonical_batch, chunk])
        job = ensure_quickresto_import_job(db, connection=connection, batch=batch)
        if job is not None:
            job.sync_run_id = int(run.id)
            db.add(job)
    db.add(legacy_run)
    db.flush()
    return QuickRestoCanonicalContext(connection=canonical, run=run, enabled=bool(canonical.shadow_sync_enabled))


def finish_quickresto_canonical_run(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    legacy_run: QuickRestoSyncRun,
    summary: dict[str, Any],
    failed: bool = False,
) -> None:
    now = _utcnow()
    canonical_summary = dict(summary.get("canonical") or {})
    statuses = {str(item.get("status") or "") for item in canonical_summary.get("groups") or []}
    if failed:
        status = "FAILED"
    elif not context.enabled:
        status = "SUCCEEDED"
        canonical_summary = {"enabled": False, "reason": "feature_flag_disabled", "read_mode": "LEGACY"}
    elif statuses.intersection({"FAILED", "PARTIAL", "MISMATCH", "INCOMPLETE"}):
        status = "PARTIAL"
    else:
        status = "SUCCEEDED"
    context.run.status = status
    context.run.finished_at = now
    context.run.records_seen = int(canonical_summary.get("records_seen") or legacy_run.shifts_seen or 0)
    context.run.records_persisted = int(canonical_summary.get("records_persisted") or 0)
    context.run.records_quarantined = int(canonical_summary.get("records_quarantined") or 0)
    context.run.cursor_after = (
        legacy_run.connection.incremental_cursor_closed_at.isoformat()
        if getattr(legacy_run, "connection", None) is not None
        and legacy_run.connection.incremental_cursor_closed_at is not None
        else None
    )
    context.run.summary_json = {**canonical_summary, "legacy_sync_run_id": int(legacy_run.id)}
    context.run.error_code = "CANONICAL_SHADOW_FAILED" if failed else None
    context.run.error_message = legacy_run.error_message if failed else None
    context.connection.last_sync_at = now
    if status in {"SUCCEEDED", "PARTIAL"}:
        context.connection.last_successful_sync_at = now
    db.add_all([context.run, context.connection])

    chunk = db.execute(
        select(IntegrationImportChunk).where(IntegrationImportChunk.sync_run_id == int(context.run.id))
    ).scalar_one_or_none()
    if chunk is not None:
        chunk.status = status
        chunk.error_code = context.run.error_code
        chunk.error_message = context.run.error_message
        chunk.counters_json = {
            "shifts_seen": int(legacy_run.shifts_seen or 0),
            "shifts_imported": int(legacy_run.shifts_imported or 0),
            "reports_created": int(legacy_run.reports_created or 0),
            "reports_updated": int(legacy_run.reports_updated or 0),
            "reports_unchanged": int(legacy_run.reports_unchanged or 0),
            "records_persisted": int(context.run.records_persisted or 0),
            "records_quarantined": int(context.run.records_quarantined or 0),
        }
        chunk.provenance_json = {
            "legacy_sync_run_id": int(legacy_run.id),
            "canonical_sync_run_id": int(context.run.id),
            "reconciliation_ids": [
                int((group.get("compare") or {}).get("reconciliation_id"))
                for group in canonical_summary.get("groups") or []
                if (group.get("compare") or {}).get("reconciliation_id")
            ],
            "quarantine_ids": sorted(
                {
                    int(issue_id)
                    for group in canonical_summary.get("groups") or []
                    for issue_id in ((group.get("write") or {}).get("quarantine_ids") or [])
                }
            ),
        }
        chunk.finished_at = now
        chunk.updated_at = now
        db.add(chunk)

    if status in {"SUCCEEDED", "PARTIAL"} and context.enabled:
        cursor = db.execute(
            select(IntegrationSyncCursor).where(
                IntegrationSyncCursor.connection_id == int(context.connection.id),
                IntegrationSyncCursor.capability == CAPABILITY,
            )
        ).scalar_one_or_none()
        if cursor is None:
            cursor = IntegrationSyncCursor(
                connection_id=int(context.connection.id), capability=CAPABILITY, overlap_seconds=172800
            )
            db.add(cursor)
        cursor.cursor_token = context.run.cursor_after
        cursor.watermark_at = now
        cursor.last_confirmed_run_id = int(context.run.id)
        cursor.updated_at = now
        db.add(cursor)


def fail_quickresto_canonical_run(db: Session, *, integration_sync_run_id: int | None, error: str) -> None:
    if not integration_sync_run_id:
        return
    run = db.get(IntegrationSyncRun, int(integration_sync_run_id))
    if run is None:
        return
    run.status = "FAILED"
    run.finished_at = _utcnow()
    run.error_code = "QUICKRESTO_SYNC_FAILED"
    run.error_message = str(error)[:4000]
    chunk = db.execute(
        select(IntegrationImportChunk).where(IntegrationImportChunk.sync_run_id == int(run.id))
    ).scalar_one_or_none()
    if chunk is not None:
        chunk.status = "FAILED"
        chunk.error_code = run.error_code
        chunk.error_message = run.error_message
        chunk.finished_at = run.finished_at
        chunk.updated_at = run.finished_at
        db.add(chunk)
    connection = db.get(IntegrationConnection, int(run.connection_id))
    if connection is not None:
        connection.last_sync_at = run.finished_at
        db.add(connection)
    db.add(run)
    db.commit()


def record_observed_capabilities(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    fallback_diagnostics: Iterable[dict[str, Any]],
) -> None:
    if not context.enabled:
        return
    now = _utcnow()
    diagnostics = [dict(item) for item in fallback_diagnostics]
    observed = {
        Capability.EXTERNAL_VENUES,
        Capability.SALE_PLACES,
        Capability.STORES,
        Capability.PAYMENTS,
        Capability.PRODUCTS,
        Capability.PRODUCT_GROUPS,
        Capability.BUSINESS_SHIFTS,
        Capability.ORDERS,
    }
    derived = {
        Capability.SALES,
        Capability.ORDER_ITEMS,
        Capability.ORDER_EVENTS,
        Capability.RETURNS,
        Capability.DISCOUNTS,
    }
    states: dict[Capability, CapabilityState] = {item: CapabilityState.SUPPORTED for item in observed}
    states.update({item: CapabilityState.DERIVED for item in derived})
    states[Capability.SERVER_TIME_FILTER] = CapabilityState.DEGRADED if diagnostics else CapabilityState.SUPPORTED
    unavailable = {
        Capability.EMPLOYEES,
        Capability.EMPLOYEE_ATTENDANCE,
        Capability.EMPLOYEE_ROLES,
        Capability.INVENTORY,
        Capability.PURCHASES,
        Capability.SUPPLIERS,
    }
    states.update({item: CapabilityState.UNAVAILABLE for item in unavailable})
    snapshot: dict[str, str] = {}
    for capability, state in states.items():
        row = db.execute(
            select(IntegrationCapabilityState).where(
                IntegrationCapabilityState.connection_id == int(context.connection.id),
                IntegrationCapabilityState.capability == capability.value,
            )
        ).scalar_one_or_none()
        if row is None:
            row = IntegrationCapabilityState(connection_id=int(context.connection.id), capability=capability.value)
            db.add(row)
        row.state = state.value
        row.checked_at = now
        row.last_success_at = now if state in {CapabilityState.SUPPORTED, CapabilityState.DERIVED} else None
        row.evidence_summary = (
            "Observed in the completed QuickResto read-only sync"
            if state in {CapabilityState.SUPPORTED, CapabilityState.DERIVED}
            else "No verified QuickResto read-only source"
        )
        row.details_json = {"fallback": diagnostics} if capability is Capability.SERVER_TIME_FILTER else None
        row.updated_at = now
        snapshot[capability.value] = state.value
    context.connection.capabilities_snapshot = snapshot
    db.add(context.connection)


def _upsert_external(db: Session, model, *, connection_id: int, external_id: str, values: dict[str, Any]):
    row = db.execute(
        select(model).where(model.connection_id == int(connection_id), model.external_id == str(external_id))
    ).scalar_one_or_none()
    if row is None:
        row = model(connection_id=int(connection_id), external_id=str(external_id), **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    row.synced_at = _utcnow()
    row.is_deleted = False
    row.deleted_at = None
    db.flush()
    return row


def mirror_quickresto_catalog_and_mappings(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    connection: QuickRestoConnection,
    venue: Venue,
) -> dict[str, int]:
    if not context.enabled:
        return {}
    now = _utcnow()
    canonical_id = int(context.connection.id)
    external_venue = None
    if connection.external_venue_id:
        external_venue = db.execute(
            select(QuickRestoExternalVenue).where(
                QuickRestoExternalVenue.connection_id == int(connection.id),
                QuickRestoExternalVenue.external_id == int(connection.external_venue_id),
            )
        ).scalar_one_or_none()
    pos_venue = _upsert_external(
        db,
        POSVenue,
        connection_id=canonical_id,
        external_id=str(connection.external_venue_id or f"venue:{venue.id}"),
        values={
            "venue_id": int(venue.id),
            "name": str(connection.external_venue_name or getattr(external_venue, "external_name", None) or venue.name),
            "address": getattr(external_venue, "address_label", None),
            "timezone": str(getattr(venue, "timezone", None) or "Europe/Moscow"),
            "source_version": (
                str(connection.external_venue_version) if connection.external_venue_version is not None else None
            ),
            "payload_hash": _json_hash(
                {"external_id": connection.external_venue_id, "name": connection.external_venue_name}
            ),
            "is_active": bool(connection.is_active),
        },
    )
    for source in db.execute(
        select(QuickRestoSalePlaceScope).where(QuickRestoSalePlaceScope.connection_id == int(connection.id))
    ).scalars():
        _upsert_external(
            db,
            POSTerminal,
            connection_id=canonical_id,
            external_id=str(source.external_id),
            values={
                "venue_id": int(venue.id),
                "pos_venue_id": int(pos_venue.id),
                "sale_place_external_id": str(source.external_id),
                "name": str(source.external_name),
                "source_metadata_json": {"selected": bool(source.is_selected), "confirmed": bool(source.is_confirmed)},
                "payload_hash": _json_hash({"name": source.external_name, "available": source.is_available}),
                "is_active": bool(source.is_available and source.is_selected),
            },
        )
    for source in db.execute(
        select(QuickRestoStoreScope).where(QuickRestoStoreScope.connection_id == int(connection.id))
    ).scalars():
        _upsert_external(
            db,
            POSWarehouse,
            connection_id=canonical_id,
            external_id=str(source.external_id),
            values={
                "venue_id": int(venue.id),
                "name": str(source.external_name),
                "warehouse_type": "STORE",
                "payload_hash": _json_hash({"name": source.external_name, "available": source.is_available}),
                "is_active": bool(source.is_available and source.is_selected),
            },
        )

    group_sources: dict[int, tuple[str, int | None]] = {}
    for source in db.execute(
        select(QuickRestoDishCategoryPath).where(QuickRestoDishCategoryPath.connection_id == int(connection.id))
    ).scalars():
        external_id = int(source.external_id)
        group_sources[external_id] = (_category_title(source.external_name, external_id), source.parent_external_id)
    legacy_groups = list(
        db.execute(
            select(QuickRestoDepartmentMapping)
            .where(QuickRestoDepartmentMapping.connection_id == int(connection.id))
            .options(selectinload(QuickRestoDepartmentMapping.allocations))
        ).scalars()
    )
    for source in legacy_groups:
        external_id = int(source.external_id)
        group_sources.setdefault(external_id, (_category_title(source.external_name, external_id), None))
    groups: dict[int, POSProductGroup] = {}
    for external_id, (name, _parent_id) in sorted(group_sources.items()):
        groups[external_id] = _upsert_external(
            db,
            POSProductGroup,
            connection_id=canonical_id,
            external_id=str(external_id),
            values={"name": name, "kind": "CATEGORY", "payload_hash": _json_hash({"name": name}), "is_active": True},
        )
    for external_id, (_name, parent_external_id) in group_sources.items():
        if parent_external_id and parent_external_id in groups:
            groups[external_id].parent_id = int(groups[parent_external_id].id)

    products: dict[int, POSProduct] = {}
    legacy_products = list(
        db.execute(
            select(QuickRestoKpiProductMapping).where(QuickRestoKpiProductMapping.connection_id == int(connection.id))
        ).scalars()
    )
    for source in legacy_products:
        group = groups.get(int(source.external_group_id or 0))
        products[int(source.external_product_id)] = _upsert_external(
            db,
            POSProduct,
            connection_id=canonical_id,
            external_id=str(source.external_product_id),
            values={
                "group_id": int(group.id) if group else None,
                "category_id": int(group.id) if group else None,
                "name": str(source.external_name),
                "payload_hash": _json_hash({"name": source.external_name, "group": source.external_group_id}),
                "is_active": True,
            },
        )

    payment_types: dict[int, POSPaymentType] = {}
    legacy_payments = list(
        db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == int(connection.id))
        ).scalars()
    )
    for source in legacy_payments:
        payment_types[int(source.external_id)] = _upsert_external(
            db,
            POSPaymentType,
            connection_id=canonical_id,
            external_id=str(source.external_id),
            values={
                "name": str(source.external_name),
                "source_operation_type": str(source.operation_type),
                "canonical_hint": str(source.payment_mechanism or "") or None,
                "payload_hash": _json_hash(
                    {
                        "name": source.external_name,
                        "operation": source.operation_type,
                        "mechanism": source.payment_mechanism,
                    }
                ),
                "is_active": bool(source.is_available),
                "last_seen_at": source.last_seen_at,
            },
        )

    for source in legacy_payments:
        canonical_source = payment_types[int(source.external_id)]
        mapping = db.execute(
            select(POSPaymentTypeMapping).where(
                POSPaymentTypeMapping.connection_id == canonical_id,
                POSPaymentTypeMapping.canonical_source_id == int(canonical_source.id),
            )
        ).scalar_one_or_none()
        if mapping is None:
            mapping = POSPaymentTypeMapping(
                connection_id=canonical_id,
                canonical_source_id=int(canonical_source.id),
                target_type="PAYMENT_METHOD",
                source_name_snapshot=str(source.external_name),
            )
            db.add(mapping)
        mapping.target_id = int(source.payment_method_id) if source.payment_method_id else None
        mapping.status = (
            "EXCLUDED" if source.excluded_from_revenue else "MAPPED" if source.payment_method_id else "UNMAPPED"
        )
        mapping.source_name_snapshot = str(source.external_name)
        mapping.last_seen_at = source.last_seen_at or now
        mapping.updated_at = now

    legacy_groups_by_id = {int(item.external_id): item for item in legacy_groups}
    category_roots = {
        int(item.external_id): int(item.root_external_id)
        for item in db.execute(
            select(QuickRestoDishCategoryPath).where(QuickRestoDishCategoryPath.connection_id == int(connection.id))
        ).scalars()
    }
    for external_id, canonical_source in groups.items():
        source = legacy_groups_by_id.get(external_id) or legacy_groups_by_id.get(category_roots.get(external_id, 0))
        mapping = db.execute(
            select(POSGroupDepartmentMapping).where(
                POSGroupDepartmentMapping.connection_id == canonical_id,
                POSGroupDepartmentMapping.canonical_source_id == int(canonical_source.id),
            )
        ).scalar_one_or_none()
        if mapping is None:
            mapping = POSGroupDepartmentMapping(
                connection_id=canonical_id,
                canonical_source_id=int(canonical_source.id),
                target_type="DEPARTMENT",
                source_name_snapshot=str(canonical_source.name),
            )
            db.add(mapping)
            db.flush()
        distribution = mapping_department_distribution(source)
        mapping.target_id = int(source.department_id) if source and source.department_id and distribution else None
        mapping.status = "MAPPED" if distribution else "UNMAPPED"
        mapping.source_name_snapshot = str(canonical_source.name)
        mapping.last_seen_at = now
        mapping.updated_at = now
        db.execute(delete(POSGroupDepartmentAllocation).where(POSGroupDepartmentAllocation.mapping_id == mapping.id))
        if distribution:
            for department_id, share_percent in distribution.items():
                db.add(
                    POSGroupDepartmentAllocation(
                        mapping_id=int(mapping.id),
                        department_id=int(department_id),
                        share_percent=Decimal(str(share_percent)),
                        updated_at=now,
                    )
                )

    for source in legacy_products:
        canonical_source = products[int(source.external_product_id)]
        mapping = db.execute(
            select(POSProductKpiMapping).where(
                POSProductKpiMapping.connection_id == canonical_id,
                POSProductKpiMapping.canonical_source_id == int(canonical_source.id),
            )
        ).scalar_one_or_none()
        if mapping is None:
            mapping = POSProductKpiMapping(
                connection_id=canonical_id,
                canonical_source_id=int(canonical_source.id),
                target_type="KPI_METRIC",
                source_name_snapshot=str(source.external_name),
            )
            db.add(mapping)
        mapping.target_id = int(source.kpi_metric_id) if source.kpi_metric_id else None
        mapping.status = "MAPPED" if source.kpi_metric_id else "UNMAPPED"
        mapping.exclude_from_percentage_base = bool(source.exclude_from_percentage_base)
        mapping.source_name_snapshot = str(source.external_name)
        mapping.last_seen_at = source.last_seen_at
        mapping.updated_at = now
    db.flush()
    return {
        "venues": 1,
        "terminals": int(
            db.scalar(select(func.count(POSTerminal.id)).where(POSTerminal.connection_id == canonical_id)) or 0
        ),
        "payment_types": len(payment_types),
        "product_groups": len(groups),
        "products": len(products),
    }


def _quarantine(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    raw: IntegrationRawObject | None,
    entity_type: str,
    external_id: str | None,
    code: str,
    summary: str,
    technical: str | None = None,
) -> IntegrationQuarantine:
    issue_key = _json_hash({"entity_type": entity_type, "external_id": external_id, "code": code})
    row = db.execute(
        select(IntegrationQuarantine).where(
            IntegrationQuarantine.connection_id == int(context.connection.id),
            IntegrationQuarantine.issue_key == issue_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationQuarantine(
            connection_id=int(context.connection.id),
            issue_key=issue_key,
            entity_type=entity_type,
            external_id=external_id,
            error_class="MAPPING" if "MAPPING" in code else "NORMALIZATION",
            error_code=code,
            severity="ERROR",
            status="OPEN",
            user_summary=summary,
        )
        db.add(row)
    row.raw_object_id = int(raw.id) if raw else None
    row.sync_run_id = int(context.run.id)
    row.status = "OPEN"
    row.resolved_at = None
    row.technical_summary = technical
    row.updated_at = _utcnow()
    return row


def _terminal_for_shift(db: Session, *, connection_id: int, shift: dict[str, Any]) -> POSTerminal | None:
    for key in ("salePlace", "createTerminalSalePlace"):
        reference = shift.get(key)
        if isinstance(reference, dict) and int(reference.get("id") or 0) > 0:
            return db.execute(
                select(POSTerminal).where(
                    POSTerminal.connection_id == connection_id,
                    POSTerminal.external_id == str(int(reference["id"])),
                )
            ).scalar_one_or_none()
    return None


def _soft_delete_missing(
    db: Session, model, *, connection_id: int, parent_field, parent_id: int, seen: set[str]
) -> None:
    rows = db.execute(
        select(model).where(model.connection_id == connection_id, parent_field == int(parent_id))
    ).scalars()
    now = _utcnow()
    for row in rows:
        if row.external_id not in seen:
            row.is_deleted = True
            row.deleted_at = now


def shadow_write_snapshot_group(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    connection: QuickRestoConnection,
    venue: Venue,
    snapshots: list[QuickRestoSourceSnapshot],
) -> dict[str, Any]:
    if not context.enabled:
        return {"enabled": False, "status": "SKIPPED", "records_seen": len(snapshots), "records_persisted": 0}
    counts = defaultdict(int)
    quarantines: list[int] = []
    raw_ids: list[int] = []
    canonical_shift_ids: list[int] = []
    timezone_name = str(getattr(venue, "timezone", None) or "Europe/Moscow")
    for snapshot in snapshots:
        source = open_source_snapshot(snapshot)
        record = ProviderRecord(
            external_id=str(snapshot.external_shift_id or snapshot.external_shift_pk or snapshot.source_fingerprint),
            payload=source,
            source_version=str(snapshot.source_version) if snapshot.source_version is not None else None,
        )
        raw = record_raw_object(
            db,
            connection_id=int(context.connection.id),
            entity_type="SHIFT_BUNDLE",
            record=record,
            allowed_fields=_RAW_ALLOWLIST,
            import_run_id=int(context.run.id),
            expires_at=snapshot.retention_expires_at,
        )
        raw_ids.append(int(raw.id))
        counts["records_seen"] += 1
        try:
            normalized = normalize_closed_shift(
                source["shift"],
                source["orders"],
                cutoff_hour=int(connection.business_day_cutoff_hour),
                night_shift_split_enabled=bool(connection.night_shift_split_enabled and venue.night_shifts_enabled),
                night_shift_start_hour=int(connection.night_shift_start_hour),
            )
            shift_source = source["shift"]
            opened_at = _aware_local(shift_source.get("localOpenedTime") or shift_source.get("opened"), timezone_name)
            closed_at = _aware_local(shift_source.get("localClosedTime") or shift_source.get("closed"), timezone_name)
            terminal = _terminal_for_shift(db, connection_id=int(context.connection.id), shift=shift_source)
            business_date = date.fromisoformat(str(normalized["business_date"]))
            shift = _upsert_external(
                db,
                POSBusinessShift,
                connection_id=int(context.connection.id),
                external_id=str(normalized["external_shift_id"]),
                values={
                    "venue_id": int(venue.id),
                    "terminal_id": int(terminal.id) if terminal else None,
                    "shift_number": str(shift_source.get("shiftNumber") or "") or None,
                    "business_date": business_date,
                    "calendar_date": (
                        opened_at.astimezone(ZoneInfo(timezone_name)).date() if opened_at else business_date
                    ),
                    "shift_slot": str(normalized.get("shift_slot") or "DAY"),
                    "opened_at": opened_at,
                    "closed_at": closed_at,
                    "status": "CLOSED",
                    "orders_count": int(normalized.get("orders_count") or 0),
                    "revenue_amount": _minor_to_money(int(normalized.get("revenue_total_minor") or 0)),
                    "refund_amount": _minor_to_money(
                        sum(
                            _money_minor(order.get("frontTotalPrice"), field="frontTotalPrice")
                            for order in source["orders"]
                            if bool(order.get("returned"))
                        )
                    ),
                    "writeoff_amount": _minor_to_money(int(normalized.get("writeoff_total_minor") or 0)),
                    "currency": "RUB",
                    "source_version": str(snapshot.source_version or 0),
                    "payload_hash": str(normalized["payload_hash"]),
                    "source_timezone": timezone_name,
                    "source_metadata_json": {
                        "raw_object_id": int(raw.id),
                        "source_fingerprint": snapshot.source_fingerprint,
                    },
                },
            )
            canonical_shift_ids.append(int(shift.id))
            counts["shifts"] += 1
            seen_orders: set[str] = set()
            for order_source in source["orders"]:
                order_external_id = str(order_source.get("id") or "").strip()
                if not order_external_id:
                    raise ValueError("QuickResto canonical order has no stable id")
                seen_orders.add(order_external_id)
                payments = [item for item in order_source.get("payments") or [] if isinstance(item, dict)]
                items = [item for item in order_source.get("orderItemList") or [] if isinstance(item, dict)]
                payment_total_minor = sum(_money_minor(item.get("amount"), field="payment.amount") for item in payments)
                net_minor = _money_minor(order_source.get("frontTotalPrice"), field="frontTotalPrice")
                discount_minor = _money_minor(
                    order_source.get("frontTotalAbsoluteDiscount"), field="frontTotalAbsoluteDiscount"
                )
                operation_types = {
                    str(item.get("operationType") or (item.get("paymentType") or {}).get("operationType") or "").lower()
                    for item in payments
                }
                is_writeoff = bool(operation_types) and operation_types == {"writeoff"}
                returned = bool(order_source.get("returned"))
                order = _upsert_external(
                    db,
                    POSOrder,
                    connection_id=int(context.connection.id),
                    external_id=order_external_id,
                    values={
                        "venue_id": int(venue.id),
                        "business_shift_id": int(shift.id),
                        "terminal_id": int(terminal.id) if terminal else None,
                        "external_number": order_external_id,
                        "business_date": business_date,
                        "opened_at": opened_at,
                        "closed_at": closed_at,
                        "status": "REFUNDED" if returned else "CLOSED",
                        "gross_amount": _minor_to_money(net_minor + discount_minor),
                        "discount_amount": _minor_to_money(discount_minor),
                        "net_amount": _minor_to_money(net_minor),
                        "payment_amount": _minor_to_money(payment_total_minor),
                        "refund_amount": _minor_to_money(net_minor if returned else 0),
                        "currency": "RUB",
                        "source_version": str(order_source.get("version") or 0),
                        "payload_hash": stable_payload_hash(order_source),
                        "source_timezone": timezone_name,
                        "source_metadata_json": {
                            "raw_object_id": int(raw.id),
                            "is_writeoff": is_writeoff,
                            "returned": returned,
                        },
                    },
                )
                counts["orders"] += 1
                seen_items: set[str] = set()
                for index, item_source in enumerate(items):
                    item_external_id = f"{order_external_id}:item:{index}:{stable_payload_hash(item_source)[:12]}"
                    seen_items.add(item_external_id)
                    product_ref = item_source.get("product") if isinstance(item_source.get("product"), dict) else {}
                    product_external_id = str(int(product_ref.get("id") or 0))
                    product = db.execute(
                        select(POSProduct).where(
                            POSProduct.connection_id == int(context.connection.id),
                            POSProduct.external_id == product_external_id,
                        )
                    ).scalar_one_or_none()
                    if product is None:
                        issue = _quarantine(
                            db,
                            context=context,
                            raw=raw,
                            entity_type="PRODUCT",
                            external_id=product_external_id,
                            code="PRODUCT_MAPPING_UNKNOWN",
                            summary="Товар QuickResto не найден в каноническом каталоге.",
                        )
                        db.flush()
                        quarantines.append(int(issue.id))
                    total_minor = _money_minor(item_source.get("totalPrice"), field="orderItem.totalPrice")
                    item_discount_minor = _money_minor(
                        item_source.get("totalAbsoluteDiscount"), field="orderItem.totalAbsoluteDiscount"
                    )
                    charge_minor = _money_minor(
                        item_source.get("totalAbsoluteCharge"), field="orderItem.totalAbsoluteCharge"
                    )
                    _upsert_external(
                        db,
                        POSOrderItem,
                        connection_id=int(context.connection.id),
                        external_id=item_external_id,
                        values={
                            "order_id": int(order.id),
                            "product_id": int(product.id) if product else None,
                            "source_line_number": str(index + 1),
                            "item_role": "PRODUCT",
                            "component_role": None,
                            "product_name_snapshot": str(
                                product.name if product else f"QuickResto #{product_external_id}"
                            ),
                            "group_name_snapshot": (
                                str(product.group.name) if product and product.group is not None else None
                            ),
                            "quantity": _quantity(item_source.get("amount")),
                            "gross_amount": _minor_to_money(total_minor + charge_minor),
                            "discount_amount": _minor_to_money(item_discount_minor),
                            "net_amount": _minor_to_money(total_minor - item_discount_minor + charge_minor),
                            "attributed_net_amount": None,
                            "included_in_parent": False,
                            "is_modifier": False,
                            "is_refund": returned,
                            "currency": "RUB",
                            "payload_hash": stable_payload_hash(item_source),
                            "source_metadata_json": {"raw_object_id": int(raw.id)},
                        },
                    )
                    counts["order_items"] += 1
                _soft_delete_missing(
                    db,
                    POSOrderItem,
                    connection_id=int(context.connection.id),
                    parent_field=POSOrderItem.order_id,
                    parent_id=int(order.id),
                    seen=seen_items,
                )

                seen_payments: set[str] = set()
                payment_rows: list[POSPayment] = []
                for index, payment_source in enumerate(payments):
                    payment_external_id = (
                        f"{order_external_id}:payment:{index}:{stable_payload_hash(payment_source)[:12]}"
                    )
                    seen_payments.add(payment_external_id)
                    payment_ref = (
                        payment_source.get("paymentType") if isinstance(payment_source.get("paymentType"), dict) else {}
                    )
                    payment_type_external_id = str(int(payment_ref.get("id") or 0))
                    payment_type = db.execute(
                        select(POSPaymentType).where(
                            POSPaymentType.connection_id == int(context.connection.id),
                            POSPaymentType.external_id == payment_type_external_id,
                        )
                    ).scalar_one_or_none()
                    if payment_type is None:
                        issue = _quarantine(
                            db,
                            context=context,
                            raw=raw,
                            entity_type="PAYMENT_TYPE",
                            external_id=payment_type_external_id,
                            code="PAYMENT_MAPPING_UNKNOWN",
                            summary="Тип оплаты QuickResto не сопоставлен.",
                        )
                        db.flush()
                        quarantines.append(int(issue.id))
                    payment = _upsert_external(
                        db,
                        POSPayment,
                        connection_id=int(context.connection.id),
                        external_id=payment_external_id,
                        values={
                            "order_id": int(order.id),
                            "payment_type_id": int(payment_type.id) if payment_type else None,
                            "canonical_type": (
                                str(payment_type.canonical_hint or payment_type.source_operation_type or "") or None
                                if payment_type
                                else None
                            ),
                            "amount": _minor_to_money(
                                _money_minor(payment_source.get("amount"), field="payment.amount")
                            ),
                            "paid_at": closed_at,
                            "currency": "RUB",
                            "payload_hash": stable_payload_hash(payment_source),
                            "source_metadata_json": {"raw_object_id": int(raw.id), "returned": returned},
                        },
                    )
                    payment_rows.append(payment)
                    counts["payments"] += 1
                _soft_delete_missing(
                    db,
                    POSPayment,
                    connection_id=int(context.connection.id),
                    parent_field=POSPayment.order_id,
                    parent_id=int(order.id),
                    seen=seen_payments,
                )

                discount_external_id = f"{order_external_id}:discount"
                seen_discounts: set[str] = set()
                if discount_minor:
                    seen_discounts.add(discount_external_id)
                    _upsert_external(
                        db,
                        POSOrderDiscount,
                        connection_id=int(context.connection.id),
                        external_id=discount_external_id,
                        values={
                            "order_id": int(order.id),
                            "source_discount_name": "QuickResto absolute discount",
                            "canonical_type": "ORDER",
                            "amount": _minor_to_money(discount_minor),
                            "currency": "RUB",
                            "payload_hash": _json_hash({"order": order_external_id, "amount_minor": discount_minor}),
                            "source_metadata_json": {"raw_object_id": int(raw.id)},
                        },
                    )
                    counts["discounts"] += 1
                _soft_delete_missing(
                    db,
                    POSOrderDiscount,
                    connection_id=int(context.connection.id),
                    parent_field=POSOrderDiscount.order_id,
                    parent_id=int(order.id),
                    seen=seen_discounts,
                )

                refund_external_id = f"{order_external_id}:refund"
                seen_refunds: set[str] = set()
                if returned:
                    seen_refunds.add(refund_external_id)
                    _upsert_external(
                        db,
                        POSRefund,
                        connection_id=int(context.connection.id),
                        external_id=refund_external_id,
                        values={
                            "order_id": int(order.id),
                            "payment_id": int(payment_rows[0].id) if payment_rows else None,
                            "amount": _minor_to_money(net_minor),
                            "reason": "QuickResto returned order",
                            "refunded_at": closed_at or _utcnow(),
                            "currency": "RUB",
                            "payload_hash": _json_hash({"order": order_external_id, "amount_minor": net_minor}),
                            "source_metadata_json": {"raw_object_id": int(raw.id)},
                        },
                    )
                    counts["refunds"] += 1
                _soft_delete_missing(
                    db,
                    POSRefund,
                    connection_id=int(context.connection.id),
                    parent_field=POSRefund.order_id,
                    parent_id=int(order.id),
                    seen=seen_refunds,
                )
                event_external_id = f"{order_external_id}:event:{'REFUNDED' if returned else 'CLOSED'}"
                _upsert_external(
                    db,
                    POSOrderEvent,
                    connection_id=int(context.connection.id),
                    external_id=event_external_id,
                    values={
                        "order_id": int(order.id),
                        "event_type": "RETURNED" if returned else "CLOSED",
                        "canonical_event_type": "REFUNDED" if returned else "CLOSED",
                        "occurred_at": closed_at or _utcnow(),
                        "details_json": {"raw_object_id": int(raw.id)},
                        "payload_hash": _json_hash({"order": order_external_id, "returned": returned}),
                    },
                )
                counts["order_events"] += 1
            _soft_delete_missing(
                db,
                POSOrder,
                connection_id=int(context.connection.id),
                parent_field=POSOrder.business_shift_id,
                parent_id=int(shift.id),
                seen=seen_orders,
            )
            raw.normalization_version = NORMALIZATION_VERSION
            raw.normalized_at = _utcnow()
            raw.canonical_identity = f"POSBusinessShift:{int(shift.id)}"
            counts["records_persisted"] += 1
            db.add(raw)
            db.commit()
        except Exception as exc:
            db.rollback()
            raw = db.get(IntegrationRawObject, int(raw.id))
            issue = _quarantine(
                db,
                context=context,
                raw=raw,
                entity_type="SHIFT_BUNDLE",
                external_id=record.external_id,
                code="CANONICAL_NORMALIZATION_FAILED",
                summary="Данные QuickResto сохранены, но не нормализованы в канонический формат.",
                technical=str(exc)[:1000],
            )
            db.commit()
            quarantines.append(int(issue.id))
            counts["records_quarantined"] += 1
    return {
        "enabled": True,
        "status": "PARTIAL" if quarantines else "SUCCEEDED",
        **{key: int(value) for key, value in counts.items()},
        "raw_object_ids": sorted(set(raw_ids)),
        "canonical_shift_ids": sorted(set(canonical_shift_ids)),
        "quarantine_ids": sorted(set(quarantines)),
    }


def _canonical_aggregate(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    legacy_connection: QuickRestoConnection,
    business_date: date,
    shift_slot: str,
) -> dict[str, Any]:
    shift_external_ids = {
        str(row.external_shift_id)
        for row in db.execute(
            select(QuickRestoShiftImport).where(
                QuickRestoShiftImport.connection_id == int(legacy_connection.id),
                QuickRestoShiftImport.business_date == business_date,
                QuickRestoShiftImport.shift_slot == shift_slot,
            )
        ).scalars()
        if str(row.scope_resolution_action or "") not in {"EXCLUDE_CURRENT", "MOVE_TO_CONNECTED"}
    }
    shifts = list(
        db.execute(
            select(POSBusinessShift).where(
                POSBusinessShift.connection_id == int(context.connection.id),
                POSBusinessShift.external_id.in_(shift_external_ids),
                POSBusinessShift.is_deleted.is_(False),
            )
        ).scalars()
    )
    shift_ids = [int(row.id) for row in shifts]
    orders = (
        list(
            db.execute(
                select(POSOrder).where(POSOrder.business_shift_id.in_(shift_ids), POSOrder.is_deleted.is_(False))
            ).scalars()
        )
        if shift_ids
        else []
    )
    order_ids = [int(row.id) for row in orders]
    report_orders = [row for row in orders if str(row.status) != "REFUNDED"]
    report_order_ids = {int(row.id) for row in report_orders}
    normal_orders = [row for row in report_orders if not bool((row.source_metadata_json or {}).get("is_writeoff"))]
    normal_order_ids = {int(row.id) for row in normal_orders}
    items = (
        list(
            db.execute(
                select(POSOrderItem).where(POSOrderItem.order_id.in_(order_ids), POSOrderItem.is_deleted.is_(False))
            ).scalars()
        )
        if order_ids
        else []
    )
    compound_parent_ids = {
        int(row.parent_item_id) for row in items if row.parent_item_id is not None and not bool(row.is_deleted)
    }
    payments = (
        list(
            db.execute(
                select(POSPayment).where(POSPayment.order_id.in_(order_ids), POSPayment.is_deleted.is_(False))
            ).scalars()
        )
        if order_ids
        else []
    )
    refunds = (
        list(
            db.execute(
                select(POSRefund).where(POSRefund.order_id.in_(order_ids), POSRefund.is_deleted.is_(False))
            ).scalars()
        )
        if order_ids
        else []
    )
    discounts = (
        list(
            db.execute(
                select(POSOrderDiscount).where(
                    POSOrderDiscount.order_id.in_(order_ids), POSOrderDiscount.is_deleted.is_(False)
                )
            ).scalars()
        )
        if order_ids
        else []
    )

    payment_mappings = {
        int(row.canonical_source_id): row
        for row in db.execute(
            select(POSPaymentTypeMapping).where(POSPaymentTypeMapping.connection_id == int(context.connection.id))
        ).scalars()
    }
    payment_minor: dict[str, int] = defaultdict(int)
    for payment in payments:
        if int(payment.order_id) not in normal_order_ids or payment.payment_type_id is None:
            continue
        mapping = payment_mappings.get(int(payment.payment_type_id))
        if mapping and mapping.status == "MAPPED" and mapping.target_id:
            payment_minor[str(mapping.target_id)] += _money_to_minor(payment.amount)
    payments_internal = _allocate_minor_to_rubles(payment_minor)

    group_mappings = {
        int(row.canonical_source_id): row
        for row in db.execute(
            select(POSGroupDepartmentMapping)
            .where(POSGroupDepartmentMapping.connection_id == int(context.connection.id))
            .options(selectinload(POSGroupDepartmentMapping.allocations))
        ).scalars()
    }
    product_mappings = {
        int(row.canonical_source_id): row
        for row in db.execute(
            select(POSProductKpiMapping).where(POSProductKpiMapping.connection_id == int(context.connection.id))
        ).scalars()
    }
    products = {
        int(row.id): row
        for row in db.execute(
            select(POSProduct).where(POSProduct.connection_id == int(context.connection.id))
        ).scalars()
    }
    kpis_internal: dict[int, int] = defaultdict(int)
    excluded_by_group_minor: dict[int, int] = defaultdict(int)
    department_by_group_minor: dict[int, int] = defaultdict(int)
    for item in items:
        if int(item.order_id) not in normal_order_ids or item.product_id is None:
            continue
        product = products.get(int(item.product_id))
        if product is None or product.category_id is None:
            continue
        # A compound dish owns the financial charge once. Providers may map
        # that charge onto component rows through attributed_net_amount; a
        # component included in its parent contributes zero by default.
        item_minor = attribution_minor_for_item(item)
        product_mapping = product_mappings.get(int(product.id))
        if product_mapping and product_mapping.status == "MAPPED" and product_mapping.target_id:
            quantity = Decimal(str(item.quantity or 0))
            is_expanded_compound = str(item.item_role or "PRODUCT") == "COMPOUND" and int(item.id) in (
                compound_parent_ids
            )
            if not is_expanded_compound and quantity == quantity.to_integral_value():
                kpis_internal[int(product_mapping.target_id)] += int(quantity)
            if product_mapping.exclude_from_percentage_base:
                excluded_by_group_minor[int(product.category_id)] += item_minor
                continue
        department_by_group_minor[int(product.category_id)] += item_minor

    combined_minor = {
        **{f"D:{key}": value for key, value in department_by_group_minor.items()},
        **{f"K:{key}": value for key, value in excluded_by_group_minor.items()},
    }
    combined_rubles = _allocate_minor_to_rubles(combined_minor)
    departments_internal: dict[int, int] = defaultdict(int)
    for key, value in combined_rubles.items():
        if not key.startswith("D:") or not int(value):
            continue
        mapping = group_mappings.get(int(key.removeprefix("D:")))
        if mapping is None or mapping.status != "MAPPED":
            continue
        distribution = {
            int(allocation.department_id): int(Decimal(allocation.share_percent)) for allocation in mapping.allocations
        }
        if not distribution and mapping.target_id:
            distribution = {int(mapping.target_id): 100}
        for department_id, amount in allocate_integer_total(int(value), distribution).items():
            departments_internal[int(department_id)] += int(amount)

    return {
        "business_date": business_date.isoformat(),
        "shift_slot": shift_slot,
        "shift_count": len(shifts),
        "orders_count": len(report_orders),
        "returned_orders_count": sum(1 for row in orders if str(row.status) == "REFUNDED"),
        "revenue_total": _allocate_minor_to_rubles(
            {"total": sum(_money_to_minor(row.revenue_amount) for row in shifts)}
        ).get("total", 0),
        "writeoff_total": _allocate_minor_to_rubles(
            {"total": sum(_money_to_minor(row.writeoff_amount) for row in shifts)}
        ).get("total", 0),
        "refund_total": _allocate_minor_to_rubles({"total": sum(_money_to_minor(row.amount) for row in refunds)}).get(
            "total", 0
        ),
        "discount_total": _allocate_minor_to_rubles(
            {"total": sum(_money_to_minor(row.amount) for row in discounts if int(row.order_id) in report_order_ids)}
        ).get("total", 0),
        "payments_internal": dict(
            sorted((int(key), int(value)) for key, value in payments_internal.items() if int(value))
        ),
        "departments_internal": dict(sorted(departments_internal.items())),
        "kpis_internal": dict(sorted(kpis_internal.items())),
        "unallocated_revenue_total": sum(value for key, value in combined_rubles.items() if key.startswith("K:")),
        "canonical_ids": {
            "shifts": shift_ids,
            "orders": order_ids,
            "items": [int(row.id) for row in items],
            "payments": [int(row.id) for row in payments],
            "refunds": [int(row.id) for row in refunds],
            "discounts": [int(row.id) for row in discounts],
        },
    }


def shadow_compare_snapshot_group(
    db: Session,
    *,
    context: QuickRestoCanonicalContext,
    connection: QuickRestoConnection,
    business_date: date | None,
    shift_slot: str | None,
) -> dict[str, Any]:
    if not context.enabled:
        return {"enabled": False, "status": "SKIPPED"}
    if business_date is None or shift_slot is None:
        return {"enabled": True, "status": "INCOMPLETE", "reason": "source_has_no_business_date"}
    legacy = db.execute(
        select(QuickRestoReportImport).where(
            QuickRestoReportImport.connection_id == int(connection.id),
            QuickRestoReportImport.business_date == business_date,
            QuickRestoReportImport.shift_slot == shift_slot,
        )
    ).scalar_one_or_none()
    if legacy is None:
        return {"enabled": True, "status": "INCOMPLETE", "reason": "legacy_projection_missing"}
    canonical = _canonical_aggregate(
        db,
        context=context,
        legacy_connection=connection,
        business_date=business_date,
        shift_slot=shift_slot,
    )
    legacy_summary = dict(legacy.summary_json or {})
    invariant_errors: dict[str, dict[str, int]] = {}
    payment_total = sum(int(value) for value in canonical["payments_internal"].values())
    if payment_total != int(canonical["revenue_total"]):
        invariant_errors["payment_total"] = {
            "expected": int(canonical["revenue_total"]),
            "actual": payment_total,
        }
    department_total = sum(int(value) for value in canonical["departments_internal"].values())
    department_total += int(canonical["unallocated_revenue_total"])
    if department_total != int(canonical["revenue_total"]):
        invariant_errors["department_total"] = {
            "expected": int(canonical["revenue_total"]),
            "actual": department_total,
        }
    legacy_report = legacy.daily_report
    expected_report_status = str(connection.report_import_mode or "CLOSED").upper()
    comparisons = {
        "shift_count": (int(legacy_summary.get("shift_count") or 0), int(canonical["shift_count"])),
        "orders_count": (int(legacy_summary.get("orders_count") or 0), int(canonical["orders_count"])),
        "returned_orders_count": (
            int(legacy_summary.get("returned_orders_count") or 0),
            int(canonical["returned_orders_count"]),
        ),
        "revenue_total": (int(legacy_summary.get("revenue_total") or 0), int(canonical["revenue_total"])),
        "writeoff_total": (int(legacy_summary.get("writeoff_total") or 0), int(canonical["writeoff_total"])),
        "discount_total": (int(legacy_summary.get("discount_total") or 0), int(canonical["discount_total"])),
        "payments_internal": (
            {int(k): int(v) for k, v in (legacy_summary.get("payments_internal") or {}).items()},
            canonical["payments_internal"],
        ),
        "departments_internal": (
            {int(k): int(v) for k, v in (legacy_summary.get("departments_internal") or {}).items()},
            canonical["departments_internal"],
        ),
        "kpis_internal": (
            {int(k): int(v) for k, v in (legacy_summary.get("kpis_internal") or {}).items()},
            canonical["kpis_internal"],
        ),
        "unallocated_revenue_total": (
            int(legacy_summary.get("department_unallocated_total") or 0),
            int(canonical["unallocated_revenue_total"]),
        ),
        "business_date": (str(legacy.business_date), str(canonical["business_date"])),
        "shift_slot": (str(legacy.shift_slot), str(canonical["shift_slot"])),
        "report_status": (str(legacy_report.status).upper(), expected_report_status),
    }
    discrepancies = {
        key: {"legacy": expected, "canonical": actual}
        for key, (expected, actual) in comparisons.items()
        if expected != actual
    }
    if invariant_errors:
        discrepancies["financial_invariants"] = invariant_errors
    status = "FAILED" if invariant_errors else "MISMATCH" if discrepancies else "MATCHED"
    coverage = {
        "raw_object_ids": [
            int(row.id)
            for row in db.execute(
                select(IntegrationRawObject).where(
                    IntegrationRawObject.integration_connection_id == int(context.connection.id),
                    IntegrationRawObject.import_run_id == int(context.run.id),
                )
            ).scalars()
        ],
        **canonical["canonical_ids"],
    }
    quality_issue_id = None
    if invariant_errors:
        issue = _quarantine(
            db,
            context=context,
            raw=None,
            entity_type="REPORT_PROJECTION",
            external_id=f"{business_date.isoformat()}:{shift_slot}",
            code="PROJECTION_FINANCIAL_INVARIANT",
            summary="Каноническая проекция QuickResto нарушает финансовый инвариант.",
            technical=json.dumps(invariant_errors, ensure_ascii=False, sort_keys=True),
        )
        issue.affected_report_keys_json = [{"business_date": business_date.isoformat(), "shift_slot": shift_slot}]
        db.flush()
        quality_issue_id = int(issue.id)
    else:
        issue_key = _json_hash(
            {
                "entity_type": "REPORT_PROJECTION",
                "external_id": f"{business_date.isoformat()}:{shift_slot}",
                "code": "PROJECTION_FINANCIAL_INVARIANT",
            }
        )
        resolved_issue = db.execute(
            select(IntegrationQuarantine).where(
                IntegrationQuarantine.connection_id == int(context.connection.id),
                IntegrationQuarantine.issue_key == issue_key,
                IntegrationQuarantine.status.in_({"OPEN", "RETRY_PENDING", "PROCESSING"}),
            )
        ).scalar_one_or_none()
        if resolved_issue is not None:
            resolved_issue.status = "RESOLVED"
            resolved_issue.resolved_at = _utcnow()
            resolved_issue.updated_at = resolved_issue.resolved_at
            db.add(resolved_issue)
    summary = {
        "legacy": {key: value[0] for key, value in comparisons.items()},
        "canonical": {key: value[1] for key, value in comparisons.items()},
        "discrepancies": discrepancies,
        "provenance": coverage,
        "normalization_version": NORMALIZATION_VERSION,
        "read_mode": "LEGACY",
    }
    candidate_hash = _json_hash(canonical)
    coverage_hash = _json_hash(coverage)
    projection_result = ReportProjector().persist_shadow(
        db,
        candidate=ShadowProjectionCandidate(
            daily_report_id=int(legacy.daily_report_id),
            connection_id=int(context.connection.id),
            business_date=business_date,
            shift_slot=shift_slot,
            sync_run_id=int(context.run.id),
            status=status,
            aggregate_hash=candidate_hash,
            mapping_version=1,
            policy_version=1,
            shift_count=int(canonical["shift_count"]),
            canonical_coverage_hash=coverage_hash,
            summary_json=summary,
            facts=canonical,
        ),
    )
    projection = projection_result.projection
    reconciliation = IntegrationReconciliationRun(
        connection_id=int(context.connection.id),
        sync_run_id=int(context.run.id),
        capability="REPORT_FACTS",
        period_start=business_date,
        period_end_exclusive=date.fromordinal(business_date.toordinal() + 1),
        status="FAILED" if invariant_errors else "WARNING" if discrepancies else "SUCCEEDED",
        source_amount=Decimal(str(comparisons["revenue_total"][0])),
        canonical_amount=Decimal(str(comparisons["revenue_total"][1])),
        amount_delta=Decimal(str(comparisons["revenue_total"][1] - comparisons["revenue_total"][0])),
        counts_json={
            "legacy_shifts": comparisons["shift_count"][0],
            "canonical_shifts": comparisons["shift_count"][1],
            "canonical_documents": {key: len(value) for key, value in canonical["canonical_ids"].items()},
        },
        discrepancies_json={"fields": discrepancies, "provenance": coverage},
        summary="Canonical shadow projection matches the current report path"
        if not discrepancies
        else "Canonical shadow projection differs from the current report path",
        started_at=_utcnow(),
        finished_at=_utcnow(),
    )
    db.add(reconciliation)
    db.flush()
    return {
        "enabled": True,
        "status": status,
        "projection_id": int(projection.id),
        "reconciliation_id": int(reconciliation.id),
        "discrepancy_fields": sorted(discrepancies),
        "quality_issue_id": quality_issue_id,
        "projection_updated": projection_result.updated,
        "provenance": coverage,
    }


def current_daily_report_values(db: Session, report_id: int) -> dict[str, dict[int, int]]:
    """Read-only diagnostic helper; never used as an ACDM input."""
    output: dict[str, dict[int, int]] = defaultdict(dict)
    for row in db.execute(select(DailyReportValue).where(DailyReportValue.report_id == int(report_id))).scalars():
        output[str(row.kind)][int(row.ref_id)] = int(row.value_numeric or 0)
    return dict(output)
