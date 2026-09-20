from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import require_venue_permission
from app.core.db import get_db
from app.integrations.feature_flags import feature_flags_for
from app.integrations.quality import assess_capability_freshness
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_connection import IntegrationConnection
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.user import User
from app.schemas.pos_integrations import POSIntegrationCapabilityOut, POSIntegrationConnectionOut


venue_router = APIRouter()
router = APIRouter()


def _require_view(db: Session, *, venue_id: int, user: User) -> None:
    require_venue_permission(
        db,
        venue_id=venue_id,
        user=user,
        permission_code="INTEGRATIONS_VIEW",
    )


@venue_router.get("/{venue_id}/pos-integrations", response_model=list[POSIntegrationConnectionOut])
def list_pos_integrations(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_view(db, venue_id=venue_id, user=user)
    connections = db.execute(
        select(IntegrationConnection)
        .where(IntegrationConnection.venue_id == venue_id)
        .order_by(IntegrationConnection.provider.asc(), IntegrationConnection.id.asc())
    ).scalars()
    return [
        {
            "id": row.id,
            "venue_id": row.venue_id,
            "provider": row.provider,
            "status": row.status,
            "external_organization_id": row.external_organization_id,
            "external_venue_id": row.external_venue_id,
            "read_mode": row.read_mode,
            "coverage_start": row.coverage_start,
            "coverage_end_exclusive": row.coverage_end_exclusive,
            "last_sync_at": row.last_sync_at,
            "last_successful_sync_at": row.last_successful_sync_at,
            "flags": feature_flags_for(row.provider),
        }
        for row in connections
    ]


@router.get(
    "/pos-integrations/{connection_id}/capabilities",
    response_model=list[POSIntegrationCapabilityOut],
)
def list_pos_integration_capabilities(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="POS integration connection not found")
    _require_view(db, venue_id=connection.venue_id, user=user)
    capability_states = (
        db.execute(
            select(IntegrationCapabilityState)
            .where(IntegrationCapabilityState.connection_id == connection_id)
            .order_by(IntegrationCapabilityState.capability.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "capability": row.capability,
            "state": row.state,
            "checked_at": row.checked_at,
            "last_success_at": row.last_success_at,
            "last_error_code": row.last_error_code,
            "evidence_summary": row.evidence_summary,
            "freshness_seconds": row.freshness_seconds,
        }
        for row in capability_states
    ]


@router.get("/pos-integrations/{connection_id}/quality-summary")
def get_pos_integration_quality_summary(
    connection_id: int,
    stale_after_seconds: int = Query(default=21_600, ge=60, le=604_800),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="POS integration connection not found")
    _require_view(db, venue_id=connection.venue_id, user=user)
    capability_states = list(
        db.execute(
            select(IntegrationCapabilityState).where(IntegrationCapabilityState.connection_id == connection_id)
        ).scalars()
    )
    active_issues = list(
        db.execute(
            select(IntegrationQuarantine).where(
                IntegrationQuarantine.connection_id == connection_id,
                IntegrationQuarantine.status.in_(("OPEN", "RETRY_PENDING", "PROCESSING")),
            )
        ).scalars()
    )
    freshness = assess_capability_freshness(
        capability_states,
        stale_after_seconds=stale_after_seconds,
    )
    stale_count = sum(item.freshness in {"STALE", "NO_DATA"} for item in freshness)
    critical_count = sum(row.severity == "CRITICAL" for row in active_issues)
    if critical_count:
        health = "FAILED"
    elif active_issues or stale_count:
        health = "DEGRADED"
    else:
        health = "HEALTHY"
    return {
        "connection_id": connection_id,
        "health": health,
        "active_issue_count": len(active_issues),
        "critical_issue_count": critical_count,
        "stale_capability_count": stale_count,
        "capabilities": [
            {
                "capability": item.capability,
                "state": item.state,
                "freshness": item.freshness,
                "age_seconds": item.age_seconds,
            }
            for item in freshness
        ],
    }


def _quality_issue_out(row: IntegrationQuarantine) -> dict:
    return {
        "id": int(row.id),
        "connection_id": int(row.connection_id),
        "raw_object_id": row.raw_object_id,
        "sync_run_id": row.sync_run_id,
        "entity_type": row.entity_type,
        "external_id": row.external_id,
        "error_class": row.error_class,
        "error_code": row.error_code,
        "severity": row.severity,
        "status": row.status,
        "user_summary": row.user_summary,
        "affected_report_keys": row.affected_report_keys_json or [],
        "opened_at": row.opened_at,
        "updated_at": row.updated_at,
        "resolved_at": row.resolved_at,
    }


@router.get("/pos-integrations/{connection_id}/quality-issues")
def list_pos_integration_quality_issues(
    connection_id: int,
    status: str = Query(default="active", max_length=24),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="POS integration connection not found")
    _require_view(db, venue_id=connection.venue_id, user=user)
    statement = select(IntegrationQuarantine).where(IntegrationQuarantine.connection_id == connection_id)
    normalized = str(status or "active").upper()
    if normalized == "ACTIVE":
        statement = statement.where(IntegrationQuarantine.status.in_(("OPEN", "RETRY_PENDING", "PROCESSING")))
    elif normalized != "ALL":
        if normalized not in {"OPEN", "RETRY_PENDING", "PROCESSING", "RESOLVED", "IGNORED"}:
            raise HTTPException(status_code=422, detail="Unknown quality issue status")
        statement = statement.where(IntegrationQuarantine.status == normalized)
    rows = list(
        db.execute(
            statement.order_by(IntegrationQuarantine.updated_at.desc(), IntegrationQuarantine.id.desc()).limit(limit)
        ).scalars()
    )
    return {"items": [_quality_issue_out(row) for row in rows]}


@router.get("/pos-integrations/{connection_id}/quality-issues/{issue_id}")
def get_pos_integration_quality_issue(
    connection_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="POS integration connection not found")
    _require_view(db, venue_id=connection.venue_id, user=user)
    row = db.execute(
        select(IntegrationQuarantine).where(
            IntegrationQuarantine.id == issue_id,
            IntegrationQuarantine.connection_id == connection_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="POS integration quality issue not found")
    return _quality_issue_out(row)


@router.get("/pos-integrations/{connection_id}/reconciliations/{reconciliation_id}")
def get_pos_integration_reconciliation(
    connection_id: int,
    reconciliation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    connection = db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="POS integration connection not found")
    _require_view(db, venue_id=connection.venue_id, user=user)
    row = db.execute(
        select(IntegrationReconciliationRun).where(
            IntegrationReconciliationRun.id == reconciliation_id,
            IntegrationReconciliationRun.connection_id == connection_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="POS integration reconciliation not found")
    return {
        "id": int(row.id),
        "connection_id": int(row.connection_id),
        "sync_run_id": row.sync_run_id,
        "capability": row.capability,
        "period_start": row.period_start,
        "period_end_exclusive": row.period_end_exclusive,
        "status": row.status,
        "source_amount": row.source_amount,
        "canonical_amount": row.canonical_amount,
        "amount_delta": row.amount_delta,
        "counts": row.counts_json,
        "discrepancies": row.discrepancies_json,
        "summary": row.summary,
    }
