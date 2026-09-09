from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import has_venue_permission, require_venue_permission
from app.core.db import get_db
from app.integrations.base import (
    POSAuthenticationError,
    POSCapability,
    POSCapabilityUnavailableError,
    decrypt_credentials,
    encrypt_credentials,
)
from app.integrations.canonical import canonical_sales_metrics
from app.integrations.normalization import IikoP0Normalizer
from app.integrations.normalization import QuickRestoP0Normalizer
from app.integrations.providers.iiko import IikoConfig, IikoError, IikoPOSProvider
from app.integrations.freshness import capability_freshness
from app.integrations.providers import register_p0_providers
from app.integrations.registry import provider_registry
from app.integrations.reconciliation import (
    CanonicalReadSwitchError,
    SourceReconciliationMetrics,
    enable_canonical_reads,
    reconcile_connection,
    rollback_to_legacy_reads,
)
from app.integrations.sync import (
    historical_backfill,
    incremental_sync,
    persist_capability_audit,
    synchronize_capability,
)
from app.integrations.sync.jobs import enqueue_historical_backfill_job
from app.integrations.sync.p0 import ALL_SYNC_ORDER, P0_SYNC_ORDER
from app.models.integration_connection import IntegrationConnection
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.integration_sync_job import IntegrationSyncJob
from app.models.quickresto_connection import QuickRestoConnection
from app.models.pos_canonical import POSEmployee, POSEmployeeMapping
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.schemas.pos_integrations import (
    IikoConnectionUpsertIn,
    POSEmployeeMappingConfirmIn,
    POSHistoricalSyncIn,
    POSReconciliationIn,
    POSQuarantineStatusIn,
    QuickRestoCanonicalConfigIn,
)
from app.services.integrations.pos_provider_selection import (
    POSProviderSelectionError,
    acquire_pos_provider,
    active_pos_provider,
    release_pos_provider,
)
from app.services.integrations.credentials import IntegrationCredentialError, decrypt_credential


router = APIRouter()


def _require_view(db: Session, *, venue_id: int, user: User) -> None:
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="INTEGRATIONS_VIEW")


def _require_manage(db: Session, *, venue_id: int, user: User) -> None:
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="INTEGRATIONS_MANAGE")


def _venue_or_404(db: Session, venue_id: int) -> Venue:
    venue = db.get(Venue, int(venue_id))
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


def _connection(db: Session, *, venue_id: int, provider: str) -> IntegrationConnection | None:
    return db.execute(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.venue_id == int(venue_id),
            IntegrationConnection.provider == provider,
        )
        .order_by(IntegrationConnection.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def _connection_or_404(db: Session, *, venue_id: int, provider: str) -> IntegrationConnection:
    connection = _connection(db, venue_id=venue_id, provider=provider)
    if connection is None:
        raise HTTPException(status_code=404, detail=f"{provider} connection is not configured")
    return connection


def _provider_code(provider: str) -> str:
    code = str(provider or "").strip().upper().replace("QUICKRESTO", "QUICK_RESTO")
    if code not in {"IIKO", "QUICK_RESTO"}:
        raise HTTPException(status_code=404, detail="POS provider is not supported")
    return code


def _iiko_provider(connection: IntegrationConnection) -> IikoPOSProvider:
    try:
        return IikoPOSProvider(connection)
    except (IntegrationCredentialError, POSAuthenticationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Stored iiko connection settings are invalid") from exc


def _require_active_iiko(db: Session, *, venue_id: int) -> None:
    if active_pos_provider(db, venue_id=venue_id) != "IIKO":
        raise HTTPException(status_code=409, detail="iiko must be the active POS integration before synchronization")


def _require_active_provider(db: Session, *, venue_id: int, provider: str) -> None:
    if active_pos_provider(db, venue_id=venue_id) != provider:
        raise HTTPException(status_code=409, detail=f"{provider} must be the active POS integration")


def _provider(connection: IntegrationConnection):
    try:
        register_p0_providers()
        return provider_registry.create(connection.provider, connection)
    except (IntegrationCredentialError, POSAuthenticationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Stored POS connection settings are invalid") from exc


def _normalizer(provider: str):
    return IikoP0Normalizer() if provider == "IIKO" else QuickRestoP0Normalizer()


def _sync_capability(value: str) -> POSCapability:
    try:
        capability = POSCapability(str(value or "").strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="POS capability is not supported") from exc
    if capability not in ALL_SYNC_ORDER:
        raise HTTPException(status_code=409, detail="POS capability is embedded in another synchronization block")
    return capability


def _quickresto_credentials(legacy: QuickRestoConnection, connection: IntegrationConnection | None) -> dict:
    existing = (
        decrypt_credentials(connection.credentials_encrypted)
        if connection is not None and connection.credentials_encrypted
        else {}
    )
    return {
        **existing,
        "cloud": legacy.cloud,
        "login": decrypt_credential(legacy.api_login_encrypted),
        "password": decrypt_credential(legacy.api_password_encrypted),
    }


def _serialize(connection: IntegrationConnection, db: Session) -> dict:
    cursors = list(
        db.execute(
            select(IntegrationSyncCursor)
            .where(IntegrationSyncCursor.integration_connection_id == int(connection.id))
            .order_by(IntegrationSyncCursor.capability.asc())
        ).scalars()
    )
    latest = db.execute(
        select(IntegrationReconciliationRun)
        .where(IntegrationReconciliationRun.integration_connection_id == int(connection.id))
        .order_by(IntegrationReconciliationRun.completed_at.desc(), IntegrationReconciliationRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "id": int(connection.id),
        "provider": connection.provider,
        "status": connection.status,
        "external_organization_id": connection.external_organization_id,
        "external_venue_id": connection.external_venue_id,
        "credentials_configured": bool(connection.credentials_encrypted),
        "capabilities": connection.capabilities or {},
        "shadow_sync_enabled": bool(connection.shadow_sync_enabled),
        "read_mode": connection.read_mode,
        "canonical_read_enabled_at": (
            connection.canonical_read_enabled_at.isoformat() if connection.canonical_read_enabled_at else None
        ),
        "historical_sync_status": connection.historical_sync_status,
        "coverage_start": connection.coverage_start.isoformat() if connection.coverage_start else None,
        "coverage_end": connection.coverage_end.isoformat() if connection.coverage_end else None,
        "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
        "last_successful_sync_at": (
            connection.last_successful_sync_at.isoformat() if connection.last_successful_sync_at else None
        ),
        "cursors": [
            {
                "capability": row.capability,
                "status": row.status,
                "watermark_at": row.watermark_at.isoformat() if row.watermark_at else None,
                "last_successful_at": row.last_successful_at.isoformat() if row.last_successful_at else None,
                "last_error": row.last_error,
            }
            for row in cursors
        ],
        "latest_reconciliation": (
            {
                "id": int(latest.id),
                "status": latest.status,
                "period_start": latest.period_start.isoformat(),
                "period_end": latest.period_end.isoformat(),
                "revenue_difference": str(latest.revenue_difference),
                "refund_difference": str(latest.refund_difference),
                "discrepancies": latest.discrepancies_json,
                "completed_at": latest.completed_at.isoformat(),
            }
            if latest is not None
            else None
        ),
    }


@router.get("/{venue_id}/integrations/iiko")
def get_iiko_connection(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    _venue_or_404(db, venue_id)
    connection = _connection(db, venue_id=venue_id, provider="IIKO")
    return {
        "configured": connection is not None,
        "connection": _serialize(connection, db) if connection is not None else None,
        "active_pos_provider": active_pos_provider(db, venue_id=venue_id),
        "permissions": {
            "can_view": True,
            "can_manage": has_venue_permission(
                db, venue_id=venue_id, user=user, permission_code="INTEGRATIONS_MANAGE"
            ),
        },
    }


@router.put("/{venue_id}/integrations/iiko")
def put_iiko_connection(
    venue_id: int,
    payload: IikoConnectionUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    _venue_or_404(db, venue_id)
    try:
        connection = _connection(db, venue_id=venue_id, provider="IIKO")
        existing = (
            decrypt_credentials(connection.credentials_encrypted)
            if connection and connection.credentials_encrypted
            else {}
        )
        api_login = payload.api_login or existing.get("api_login")
        organization_id = payload.organization_id or existing.get("organization_id")
        if not api_login:
            raise ValueError("iiko apiLogin is required")
        fields_set = payload.model_fields_set
        credentials = {
            "api_login": api_login,
            "organization_id": organization_id,
            "base_url": (
                payload.base_url
                if "base_url" in fields_set
                else existing.get("base_url", payload.base_url)
            ),
            "sales_endpoint": (
                payload.sales_endpoint
                if "sales_endpoint" in fields_set
                else existing.get("sales_endpoint")
            ),
            "employees_endpoint": (
                payload.employees_endpoint
                if "employees_endpoint" in fields_set
                else existing.get("employees_endpoint")
            ),
            "extended_endpoints": (
                payload.extended_endpoints
                if "extended_endpoints" in fields_set
                else existing.get("extended_endpoints", {})
            ),
        }
        IikoConfig(**{key: value for key, value in credentials.items() if key != "organization_id"})
        encrypted = encrypt_credentials(credentials)
        if payload.is_active:
            acquire_pos_provider(db, venue_id=venue_id, provider="IIKO")
        else:
            release_pos_provider(db, venue_id=venue_id, provider="IIKO")
    except (ValueError, IntegrationCredentialError, POSProviderSelectionError) as exc:
        db.rollback()
        raise HTTPException(status_code=409 if isinstance(exc, POSProviderSelectionError) else 400, detail=str(exc)) from exc
    if connection is None:
        connection = IntegrationConnection(
            venue_id=venue_id,
            provider="IIKO",
            status="CONNECTING" if payload.is_active else "PAUSED",
            external_organization_id=organization_id,
            external_venue_id=organization_id,
            credentials_encrypted=encrypted,
        )
        db.add(connection)
    else:
        connection.status = "CONNECTING" if payload.is_active else "PAUSED"
        connection.external_organization_id = organization_id
        connection.external_venue_id = organization_id
        connection.credentials_encrypted = encrypted
        connection.capabilities = {}
        connection.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(connection)
    return {
        "ok": True,
        "connection": _serialize(connection, db),
        "active_pos_provider": active_pos_provider(db, venue_id=venue_id),
    }


@router.post("/{venue_id}/integrations/iiko/probe")
def probe_iiko_connection(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider="IIKO")
    provider = _iiko_provider(connection)
    health = provider.health_check()
    persist_capability_audit(db, connection, provider)
    connection.status = (
        "ACTIVE"
        if health.ok and active_pos_provider(db, venue_id=venue_id) == "IIKO"
        else "PAUSED" if health.ok else "FAILED"
    )
    db.commit()
    return {"ok": health.ok, "health": {"latency_ms": health.latency_ms, "message": health.message}, "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/iiko/sync/historical")
def historical_iiko_sync(
    venue_id: int,
    payload: POSHistoricalSyncIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    _require_active_iiko(db, venue_id=venue_id)
    connection = _connection_or_404(db, venue_id=venue_id, provider="IIKO")
    provider = _iiko_provider(connection)
    audit = provider.detect_capabilities()
    missing = [cap.value for cap in P0_SYNC_ORDER if not audit[cap].available]
    if missing:
        raise HTTPException(status_code=409, detail={"message": "iiko P0 export is incomplete", "missing": missing})
    try:
        results = historical_backfill(
            db,
            connection=connection,
            provider=provider,
            normalizer=IikoP0Normalizer(),
            months=payload.months,
        )
    except (IikoError, POSCapabilityUnavailableError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"iiko synchronization failed: {type(exc).__name__}") from exc
    return {"ok": True, "results": [_sync_result(item) for item in results], "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/iiko/sync/incremental")
def incremental_iiko_sync(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    _require_active_iiko(db, venue_id=venue_id)
    connection = _connection_or_404(db, venue_id=venue_id, provider="IIKO")
    provider = _iiko_provider(connection)
    audit = provider.detect_capabilities()
    available = tuple(capability for capability in P0_SYNC_ORDER if audit[capability].available)
    if POSCapability.SALES not in available:
        raise HTTPException(status_code=409, detail="iiko sales export is unavailable for this connection")
    try:
        results = incremental_sync(
            db,
            connection=connection,
            provider=provider,
            normalizer=IikoP0Normalizer(),
            capabilities=available,
        )
    except (IikoError, POSCapabilityUnavailableError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"iiko synchronization failed: {type(exc).__name__}") from exc
    return {"ok": True, "results": [_sync_result(item) for item in results], "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/{provider}/sync/{capability}")
def synchronize_pos_capability(
    venue_id: int,
    provider: str,
    capability: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    provider_code = _provider_code(provider)
    _require_active_provider(db, venue_id=venue_id, provider=provider_code)
    connection = _connection_or_404(db, venue_id=venue_id, provider=provider_code)
    target = _sync_capability(capability)
    if connection.provider == "QUICK_RESTO" and connection.shadow_sync_enabled and target in P0_SYNC_ORDER:
        raise HTTPException(status_code=409, detail="QuickResto P0 data is owned by the legacy shadow-safe sync")
    adapter = _provider(connection)
    audit = adapter.detect_capabilities()
    persist_capability_audit(db, connection, adapter)
    if target not in audit or not audit[target].available:
        db.commit()
        raise HTTPException(status_code=409, detail=f"{target.value} is unavailable for this connection")
    try:
        result = synchronize_capability(
            db,
            connection=connection,
            provider=adapter,
            normalizer=_normalizer(provider_code),
            capability=target,
        )
    except (POSCapabilityUnavailableError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"POS synchronization failed: {type(exc).__name__}") from exc
    return {"ok": not result.quarantined_records, "result": _sync_result(result), "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/{provider}/sync/historical/enqueue")
def enqueue_pos_historical_sync(
    venue_id: int,
    provider: str,
    payload: POSHistoricalSyncIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    provider_code = _provider_code(provider)
    _require_active_provider(db, venue_id=venue_id, provider=provider_code)
    connection = _connection_or_404(db, venue_id=venue_id, provider=provider_code)
    try:
        job = enqueue_historical_backfill_job(
            db,
            connection_id=int(connection.id),
            months=payload.months,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "job_id": int(job.id), "queue": job.queue, "status": job.status}


@router.get("/{venue_id}/integrations/{provider}/operations")
def get_pos_integration_operations(
    venue_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider=_provider_code(provider))
    quarantine_rows = db.execute(
        select(
            IntegrationQuarantine.severity,
            IntegrationQuarantine.error_code,
            func.count(IntegrationQuarantine.id),
        )
        .where(
            IntegrationQuarantine.integration_connection_id == int(connection.id),
            IntegrationQuarantine.status == "OPEN",
        )
        .group_by(IntegrationQuarantine.severity, IntegrationQuarantine.error_code)
    ).all()
    recent_jobs = list(
        db.execute(
            select(IntegrationSyncJob)
            .where(IntegrationSyncJob.integration_connection_id == int(connection.id))
            .order_by(IntegrationSyncJob.created_at.desc(), IntegrationSyncJob.id.desc())
            .limit(20)
        ).scalars()
    )
    return {
        "connection": _serialize(connection, db),
        "freshness": capability_freshness(db, connection_id=int(connection.id)),
        "quarantine": [
            {"severity": severity, "error_code": error_code, "count": int(count)}
            for severity, error_code, count in quarantine_rows
        ],
        "jobs": [
            {
                "id": int(job.id),
                "job_type": job.job_type,
                "queue": job.queue,
                "capability": job.capability,
                "status": job.status,
                "attempts": int(job.attempts),
                "last_error": job.last_error,
                "run_after": job.run_after.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            for job in recent_jobs
        ],
    }


@router.get("/{venue_id}/integrations/canonical/sales-metrics")
def get_canonical_sales_metrics(
    venue_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    _venue_or_404(db, venue_id)
    try:
        metrics = canonical_sales_metrics(
            db,
            venue_id=venue_id,
            period_start=date_from,
            period_end=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        key: str(value) if isinstance(value, Decimal) else value.isoformat() if isinstance(value, date) else value
        for key, value in metrics.items()
    }


@router.get("/{venue_id}/integrations/{provider}/quarantine")
def get_pos_quarantine(
    venue_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider=_provider_code(provider))
    rows = list(
        db.execute(
            select(IntegrationQuarantine)
            .where(
                IntegrationQuarantine.integration_connection_id == int(connection.id),
                IntegrationQuarantine.status.in_(("OPEN", "RETRYING")),
            )
            .order_by(IntegrationQuarantine.last_seen_at.desc(), IntegrationQuarantine.id.desc())
            .limit(200)
        ).scalars()
    )
    return {
        "items": [
            {
                "id": int(row.id),
                "capability": row.capability,
                "entity_type": row.entity_type,
                "external_id": row.external_id,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "severity": row.severity,
                "status": row.status,
                "attempts": int(row.attempts),
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.put("/{venue_id}/integrations/{provider}/quarantine/{item_id}")
def update_pos_quarantine_status(
    venue_id: int,
    provider: str,
    item_id: int,
    payload: POSQuarantineStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider=_provider_code(provider))
    row = db.get(IntegrationQuarantine, int(item_id))
    if row is None or int(row.integration_connection_id) != int(connection.id):
        raise HTTPException(status_code=404, detail="Quarantine item was not found")
    row.status = payload.status
    row.resolved_at = datetime.now(timezone.utc) if payload.status == "IGNORED" else None
    db.commit()
    return {"ok": True, "id": int(row.id), "status": row.status}


@router.get("/{venue_id}/integrations/{provider}/employee-mappings")
def get_pos_employee_mappings(
    venue_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider=_provider_code(provider))
    employees = list(
        db.execute(
            select(POSEmployee)
            .where(POSEmployee.connection_id == int(connection.id))
            .order_by(POSEmployee.name.asc(), POSEmployee.id.asc())
        ).scalars()
    )
    mappings = {
        int(item.pos_employee_id): item
        for item in db.execute(
            select(POSEmployeeMapping).where(
                POSEmployeeMapping.pos_employee_id.in_([int(employee.id) for employee in employees])
            )
        ).scalars()
    } if employees else {}
    return {
        "items": [
            {
                "pos_employee_id": int(employee.id),
                "external_id": employee.external_id,
                "name": employee.name,
                "position_name": employee.position_name,
                "active": bool(employee.active),
                "mapping": (
                    {
                        "venue_member_id": int(mapping.venue_member_id),
                        "match_type": mapping.match_type,
                        "confidence": str(mapping.confidence),
                        "confirmed": bool(mapping.confirmed),
                    }
                    if (mapping := mappings.get(int(employee.id))) is not None
                    else None
                ),
            }
            for employee in employees
        ],
        "connection": _serialize(connection, db),
    }


@router.put("/{venue_id}/integrations/{provider}/employee-mappings/{pos_employee_id}")
def confirm_pos_employee_mapping(
    venue_id: int,
    provider: str,
    pos_employee_id: int,
    payload: POSEmployeeMappingConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider=_provider_code(provider))
    employee = db.get(POSEmployee, int(pos_employee_id))
    if employee is None or int(employee.connection_id) != int(connection.id):
        raise HTTPException(status_code=404, detail="POS employee was not found for this connection")
    member = db.get(VenueMember, int(payload.venue_member_id))
    if member is None or int(member.venue_id) != int(venue_id) or not member.is_active:
        raise HTTPException(status_code=400, detail="Active venue member is required")
    mapping = db.execute(
        select(POSEmployeeMapping).where(POSEmployeeMapping.pos_employee_id == int(employee.id))
    ).scalar_one_or_none()
    if mapping is None:
        mapping = POSEmployeeMapping(pos_employee_id=int(employee.id), venue_member_id=int(member.id))
        db.add(mapping)
    mapping.venue_member_id = int(member.id)
    mapping.match_type = "MANUAL"
    mapping.confidence = 1
    mapping.confirmed = True
    mapping.confirmed_at = datetime.now(timezone.utc)
    mapping.confirmed_by_user_id = int(user.id)
    db.commit()
    return {
        "ok": True,
        "mapping": {
            "pos_employee_id": int(employee.id),
            "venue_member_id": int(member.id),
            "match_type": mapping.match_type,
            "confidence": str(mapping.confidence),
            "confirmed": True,
        },
    }


@router.post("/{venue_id}/integrations/{provider}/reconcile")
def reconcile_pos_connection(
    venue_id: int,
    provider: str,
    payload: POSReconciliationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    provider_code = _provider_code(provider)
    connection = _connection_or_404(db, venue_id=venue_id, provider=provider_code)
    run = reconcile_connection(
        db,
        connection=connection,
        period_start=payload.period_start,
        period_end=payload.period_end,
        source=SourceReconciliationMetrics(
            revenue=payload.source_revenue,
            refunds=payload.source_refunds,
            counts=payload.source_counts,
            coverage_start=payload.coverage_start,
            coverage_end=payload.coverage_end,
        ),
        note=payload.note,
    )
    db.commit()
    return {"ok": run.status == "OK", "status": run.status, "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/{provider}/read-mode/canonical")
def switch_pos_reads_to_canonical(
    venue_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    provider_code = _provider_code(provider)
    connection = _connection_or_404(db, venue_id=venue_id, provider=provider_code)
    try:
        enable_canonical_reads(db, connection=connection)
    except CanonicalReadSwitchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"ok": True, "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/{provider}/read-mode/legacy")
def switch_pos_reads_to_legacy(
    venue_id: int,
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    provider_code = _provider_code(provider)
    connection = _connection_or_404(db, venue_id=venue_id, provider=provider_code)
    rollback_to_legacy_reads(connection)
    db.commit()
    return {"ok": True, "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/quickresto/canonical-shadow/enable")
def enable_quickresto_canonical_shadow(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    legacy = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if legacy is None:
        raise HTTPException(status_code=404, detail="QuickResto connection is not configured")
    connection = _connection(db, venue_id=venue_id, provider="QUICK_RESTO")
    try:
        encrypted_credentials = encrypt_credentials(_quickresto_credentials(legacy, connection))
    except IntegrationCredentialError as exc:
        raise HTTPException(status_code=400, detail="Stored QuickResto credentials are invalid") from exc
    if connection is None:
        connection = IntegrationConnection(
            venue_id=venue_id,
            provider="QUICK_RESTO",
            status="ACTIVE",
            external_organization_id=legacy.cloud,
            external_venue_id=str(legacy.external_venue_id) if legacy.external_venue_id is not None else None,
            shadow_sync_enabled=True,
            credentials_encrypted=encrypted_credentials,
        )
        db.add(connection)
    else:
        connection.shadow_sync_enabled = True
        connection.status = "ACTIVE"
        connection.external_organization_id = legacy.cloud
        connection.external_venue_id = (
            str(legacy.external_venue_id) if legacy.external_venue_id is not None else None
        )
        connection.credentials_encrypted = encrypted_credentials
    db.commit()
    db.refresh(connection)
    return {"ok": True, "connection": _serialize(connection, db)}


@router.put("/{venue_id}/integrations/quickresto/canonical-config")
def configure_quickresto_canonical_adapter(
    venue_id: int,
    payload: QuickRestoCanonicalConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    legacy = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if legacy is None:
        raise HTTPException(status_code=404, detail="QuickResto connection is not configured")
    connection = _connection(db, venue_id=venue_id, provider="QUICK_RESTO")
    if connection is None:
        connection = IntegrationConnection(
            venue_id=venue_id,
            provider="QUICK_RESTO",
            status="PAUSED",
            external_organization_id=legacy.cloud,
            external_venue_id=str(legacy.external_venue_id) if legacy.external_venue_id is not None else None,
        )
        db.add(connection)
        db.flush()
    try:
        credentials = _quickresto_credentials(legacy, connection)
        credentials["object_types"] = payload.object_types
        connection.credentials_encrypted = encrypt_credentials(credentials)
    except IntegrationCredentialError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Stored QuickResto credentials are invalid") from exc
    connection.capabilities = {}
    connection.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(connection)
    return {"ok": True, "connection": _serialize(connection, db)}


@router.post("/{venue_id}/integrations/quickresto/canonical-shadow/disable")
def disable_quickresto_canonical_shadow(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id=venue_id, provider="QUICK_RESTO")
    connection.shadow_sync_enabled = False
    rollback_to_legacy_reads(connection)
    db.commit()
    return {"ok": True, "connection": _serialize(connection, db)}


def _sync_result(result) -> dict:
    return {
        "capability": result.capability.value,
        "pages": result.pages,
        "records_seen": result.records_seen,
        "records_changed": result.records_changed,
        "canonical_rows": result.canonical_rows,
        "quarantined_records": result.quarantined_records,
        "watermark_at": result.watermark_at.isoformat() if result.watermark_at else None,
    }
