from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.core.metrics import increment
from app.integrations.base import POSCapability, POSProviderCode, normalize_provider_code
from app.integrations.normalization import IikoP0Normalizer, QuickRestoP0Normalizer
from app.integrations.providers import register_p0_providers
from app.integrations.reconciliation import reconcile_raw_to_canonical
from app.integrations.registry import provider_registry
from app.integrations.sync.p0 import ALL_SYNC_ORDER, historical_backfill, persist_capability_audit, synchronize_capability
from app.models.integration_connection import IntegrationConnection
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.integration_sync_job import IntegrationSyncJob


@dataclass(frozen=True)
class SyncSchedule:
    every_minutes: int
    queue: str


SYNC_SCHEDULES = {
    POSCapability.SALES: SyncSchedule(5, "CRITICAL"),
    POSCapability.STOCK_BALANCES: SyncSchedule(30, "NORMAL"),
    POSCapability.STOCK_MOVEMENTS: SyncSchedule(30, "NORMAL"),
    POSCapability.PURCHASES: SyncSchedule(30, "NORMAL"),
    POSCapability.WRITEOFFS: SyncSchedule(30, "NORMAL"),
    POSCapability.INVENTORY: SyncSchedule(30, "NORMAL"),
    POSCapability.EMPLOYEE_ATTENDANCE: SyncSchedule(60, "NORMAL"),
    POSCapability.EMPLOYEES: SyncSchedule(360, "NORMAL"),
    POSCapability.PRODUCT_GROUPS: SyncSchedule(360, "NORMAL"),
    POSCapability.PRODUCTS: SyncSchedule(360, "NORMAL"),
    POSCapability.RECIPES: SyncSchedule(360, "NORMAL"),
    POSCapability.WAREHOUSES: SyncSchedule(360, "NORMAL"),
    POSCapability.SUPPLIERS: SyncSchedule(360, "NORMAL"),
    POSCapability.VENUES: SyncSchedule(360, "NORMAL"),
    POSCapability.TERMINALS: SyncSchedule(360, "NORMAL"),
}


def enqueue_due_jobs(db: Session, *, now: datetime | None = None) -> int:
    observed_at = _utc(now)
    created = 0
    connections = db.execute(
        select(IntegrationConnection).where(IntegrationConnection.status.in_(("ACTIVE", "DEGRADED")))
    ).scalars()
    for connection in connections:
        # Stage-two QuickResto shadow rows created before credential mirroring are
        # intentionally inert. The legacy importer remains authoritative until
        # the owner explicitly re-enables shadow mode and credentials are copied.
        if not connection.credentials_encrypted:
            continue
        available = _available_capabilities(connection)
        cursors = {
            row.capability: row
            for row in db.execute(
                select(IntegrationSyncCursor).where(
                    IntegrationSyncCursor.integration_connection_id == int(connection.id)
                )
            ).scalars()
        }
        for capability, schedule in SYNC_SCHEDULES.items():
            if capability not in available:
                continue
            if connection.provider == POSProviderCode.QUICK_RESTO.value and connection.shadow_sync_enabled:
                if capability in {
                    POSCapability.SALES,
                    POSCapability.EMPLOYEES,
                    POSCapability.PRODUCT_GROUPS,
                    POSCapability.PRODUCTS,
                    POSCapability.VENUES,
                    POSCapability.TERMINALS,
                }:
                    continue
            cursor = cursors.get(capability.value)
            last_success = _utc(cursor.last_successful_at) if cursor and cursor.last_successful_at else None
            if last_success is not None and observed_at - last_success < timedelta(minutes=schedule.every_minutes):
                continue
            created += int(
                enqueue_job(
                    db,
                    connection_id=int(connection.id),
                    job_type="CAPABILITY_SYNC",
                    queue=schedule.queue,
                    capability=capability,
                    run_after=observed_at,
                    bucket_seconds=schedule.every_minutes * 60,
                )
                is not None
            )
        created += int(
            enqueue_job(
                db,
                connection_id=int(connection.id),
                job_type="CONNECTION_HEALTH",
                queue="CRITICAL",
                run_after=observed_at,
                bucket_seconds=15 * 60,
            )
            is not None
        )
        if POSCapability.SALES in available:
            created += int(
                enqueue_job(
                    db,
                    connection_id=int(connection.id),
                    job_type="NIGHT_RECONCILIATION",
                    queue="BULK",
                    payload={"days": 30},
                    run_after=observed_at,
                    bucket_seconds=24 * 60 * 60,
                )
                is not None
            )
    db.commit()
    return created


def enqueue_job(
    db: Session,
    *,
    connection_id: int,
    job_type: str,
    queue: str,
    run_after: datetime,
    capability: POSCapability | None = None,
    payload: dict | None = None,
    bucket_seconds: int | None = None,
) -> IntegrationSyncJob | None:
    normalized_run_after = _utc(run_after)
    bucket = int(normalized_run_after.timestamp()) // max(1, int(bucket_seconds or 1))
    capability_code = capability.value if capability is not None else "none"
    key = f"pos:{int(connection_id)}:{job_type}:{capability_code}:{bucket}"
    capability_filter = (
        IntegrationSyncJob.capability == capability.value
        if capability is not None
        else IntegrationSyncJob.capability.is_(None)
    )
    open_job = db.execute(
        select(IntegrationSyncJob.id).where(
            IntegrationSyncJob.integration_connection_id == int(connection_id),
            IntegrationSyncJob.job_type == str(job_type),
            capability_filter,
            IntegrationSyncJob.status.in_(("PENDING", "RUNNING")),
        )
    ).first()
    if open_job is not None:
        return None
    existing = db.execute(
        select(IntegrationSyncJob.id).where(IntegrationSyncJob.idempotency_key == key)
    ).first()
    if existing is not None:
        return None
    job = IntegrationSyncJob(
        integration_connection_id=int(connection_id),
        job_type=str(job_type),
        queue=str(queue),
        capability=capability.value if capability is not None else None,
        payload_json=dict(payload or {}),
        idempotency_key=key,
        run_after=normalized_run_after,
    )
    db.add(job)
    db.flush()
    return job


def enqueue_historical_backfill_job(
    db: Session,
    *,
    connection_id: int,
    months: int,
    now: datetime | None = None,
) -> IntegrationSyncJob:
    if not 1 <= int(months) <= 24:
        raise ValueError("Historical backfill must cover between 1 and 24 months")
    observed_at = _utc(now)
    job = enqueue_job(
        db,
        connection_id=connection_id,
        job_type="HISTORICAL_BACKFILL",
        queue="BULK",
        payload={"months": int(months)},
        run_after=observed_at,
        bucket_seconds=1,
    )
    if job is None:
        raise ValueError("Historical backfill job is already queued")
    db.commit()
    return job


def requeue_stale_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    lease_minutes: int = 30,
) -> int:
    """Release jobs left RUNNING after a worker crash or forced restart."""
    if not 5 <= int(lease_minutes) <= 24 * 60:
        raise ValueError("POS sync job lease must be between 5 minutes and 24 hours")
    observed_at = _utc(now)
    cutoff = observed_at - timedelta(minutes=int(lease_minutes))
    stale = list(
        db.execute(
            select(IntegrationSyncJob).where(
                IntegrationSyncJob.status == "RUNNING",
                IntegrationSyncJob.locked_at.is_not(None),
                IntegrationSyncJob.locked_at <= cutoff,
            )
        ).scalars()
    )
    for job in stale:
        job.locked_at = None
        job.last_error = "worker_lease_expired"
        if int(job.attempts or 0) >= int(job.max_attempts or 1):
            job.status = "FAILED"
            job.completed_at = observed_at
        else:
            job.status = "PENDING"
            job.run_after = observed_at
    if stale:
        db.commit()
    return len(stale)


def process_next_job(db: Session, *, now: datetime | None = None) -> IntegrationSyncJob | None:
    observed_at = _utc(now)
    requeue_stale_jobs(db, now=observed_at)
    queue_order = case((IntegrationSyncJob.queue == "CRITICAL", 0), (IntegrationSyncJob.queue == "NORMAL", 1), else_=2)
    job = db.execute(
        select(IntegrationSyncJob)
        .where(
            IntegrationSyncJob.status == "PENDING",
            IntegrationSyncJob.run_after <= observed_at,
        )
        .order_by(queue_order, IntegrationSyncJob.run_after.asc(), IntegrationSyncJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "RUNNING"
    job.locked_at = observed_at
    job.started_at = observed_at
    job.attempts = int(job.attempts or 0) + 1
    db.commit()

    try:
        partial = _execute_job(db, job, observed_at=observed_at)
        job = db.get(IntegrationSyncJob, int(job.id))
        job.status = "PARTIAL" if partial else "SUCCEEDED"
        job.last_error = None
        job.completed_at = datetime.now(timezone.utc)
        job.locked_at = None
        db.commit()
        increment("axelio_pos_sync_jobs_total", provider=job.connection.provider, job_type=job.job_type, status=job.status)
        return job
    except Exception as exc:
        db.rollback()
        job = db.get(IntegrationSyncJob, int(job.id))
        job.last_error = type(exc).__name__[:255]
        job.locked_at = None
        if int(job.attempts or 0) < int(job.max_attempts or 1):
            job.status = "PENDING"
            job.run_after = datetime.now(timezone.utc) + timedelta(minutes=min(60, 2 ** int(job.attempts or 1)))
        else:
            job.status = "FAILED"
            job.completed_at = datetime.now(timezone.utc)
        connection = db.get(IntegrationConnection, int(job.integration_connection_id))
        if connection is not None:
            connection.status = "DEGRADED"
        db.commit()
        increment(
            "axelio_pos_sync_jobs_total",
            provider=connection.provider if connection is not None else "UNKNOWN",
            job_type=job.job_type,
            status=job.status,
        )
        return job


def _execute_job(db: Session, job: IntegrationSyncJob, *, observed_at: datetime) -> bool:
    register_p0_providers()
    connection = db.get(IntegrationConnection, int(job.integration_connection_id))
    if connection is None:
        raise ValueError("Integration connection no longer exists")
    provider = provider_registry.create(connection.provider, connection)
    normalizer = _normalizer(connection.provider)
    if job.job_type == "CONNECTION_HEALTH":
        health = provider.health_check()
        persist_capability_audit(db, connection, provider)
        connection.status = "ACTIVE" if health.ok else "DEGRADED"
        db.commit()
        if not health.ok:
            raise RuntimeError("POS provider health check failed")
        return False
    if job.job_type == "CAPABILITY_SYNC":
        capability = POSCapability(str(job.capability))
        result = synchronize_capability(
            db,
            connection=connection,
            provider=provider,
            normalizer=normalizer,
            capability=capability,
        )
        return bool(result.quarantined_records)
    if job.job_type == "HISTORICAL_BACKFILL":
        available = tuple(capability for capability in ALL_SYNC_ORDER if capability in _available_capabilities(connection))
        if POSCapability.SALES not in available:
            raise ValueError("Historical backfill requires SALES capability")
        results = historical_backfill(
            db,
            connection=connection,
            provider=provider,
            normalizer=normalizer,
            months=int((job.payload_json or {}).get("months") or 12),
            capabilities=available,
        )
        return any(result.quarantined_records for result in results)
    if job.job_type == "NIGHT_RECONCILIATION":
        days = max(14, min(30, int((job.payload_json or {}).get("days") or 30)))
        result = synchronize_capability(
            db,
            connection=connection,
            provider=provider,
            normalizer=normalizer,
            capability=POSCapability.SALES,
            updated_since=observed_at - timedelta(days=days),
        )
        period_end = observed_at.date()
        run = reconcile_raw_to_canonical(
            db,
            connection=connection,
            normalizer=normalizer,
            period_start=period_end - timedelta(days=days),
            period_end=period_end,
        )
        db.commit()
        return bool(result.quarantined_records or run.status != "OK")
    raise ValueError(f"Unsupported POS sync job type: {job.job_type}")


def _available_capabilities(connection: IntegrationConnection) -> set[POSCapability]:
    output = set()
    for raw_capability, details in (connection.capabilities or {}).items():
        try:
            capability = POSCapability(str(raw_capability))
        except ValueError:
            continue
        if isinstance(details, dict) and details.get("status") in {"AVAILABLE", "DEGRADED"}:
            output.add(capability)
    return output


def _normalizer(provider: str):
    code = normalize_provider_code(provider)
    if code == POSProviderCode.IIKO:
        return IikoP0Normalizer()
    if code == POSProviderCode.QUICK_RESTO:
        return QuickRestoP0Normalizer()
    raise ValueError(f"No normalizer is registered for {code.value}")


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
