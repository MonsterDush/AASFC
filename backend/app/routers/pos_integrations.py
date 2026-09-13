from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import require_venue_permission
from app.core.db import get_db
from app.integrations.feature_flags import feature_flags_for
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_connection import IntegrationConnection
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
