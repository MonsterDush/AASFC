from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_scope_audit import QuickRestoScopeAudit
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.auth.deps import get_current_user
from app.auth.venue_permissions import has_venue_permission, require_venue_permission
from app.schemas.quickresto import (
    QuickRestoConnectionUpsertIn,
    QuickRestoIssueResolveIn,
    QuickRestoMappingsUpdateIn,
    QuickRestoScopeUpdateIn,
)
from app.services.integrations.credentials import (
    IntegrationCredentialError,
    decrypt_credential,
    encrypt_credential,
)
from app.services.integrations.quickresto import QuickRestoConfig, QuickRestoError
from app.services.integrations.quickresto_sync import (
    QuickRestoSyncError,
    build_quickresto_client,
    quickresto_sync_is_active,
    reclaim_stale_quickresto_sync_state,
    refresh_quickresto_mappings,
    retry_quickresto_import_issue,
    sync_quickresto_connection,
)
from app.services.integrations.quickresto_issues import (
    ACTIVE_ISSUE_STATUSES,
    issue_counters,
    serialize_issue,
    transition_issue,
)
from app.services.integrations.quickresto_scope import (
    QuickRestoScopeConflictError,
    QuickRestoScopeError,
    apply_quickresto_scope,
    ensure_quickresto_scope_ready,
    refresh_quickresto_catalog,
    serialize_quickresto_catalog,
)
from app.services.integrations.pos_provider_selection import (
    POSProviderSelectionError,
    acquire_pos_provider,
    active_pos_provider,
    release_pos_provider,
)


router = APIRouter()
QUICKRESTO_PROVIDER = "QUICKRESTO"


def _require_quickresto_view(db: Session, *, venue_id: int, user: User) -> None:
    require_venue_permission(
        db,
        venue_id=venue_id,
        user=user,
        permission_code="INTEGRATIONS_VIEW",
    )


def _require_quickresto_manage(db: Session, *, venue_id: int, user: User) -> None:
    require_venue_permission(
        db,
        venue_id=venue_id,
        user=user,
        permission_code="INTEGRATIONS_MANAGE",
    )


def _can_manage_quickresto(db: Session, *, venue_id: int, user: User) -> bool:
    return has_venue_permission(
        db,
        venue_id=venue_id,
        user=user,
        permission_code="INTEGRATIONS_MANAGE",
    )


def _is_super_admin(user: User) -> bool:
    return str(getattr(user, "system_role", "") or "").upper() == "SUPER_ADMIN"


def _connection_or_404(db: Session, venue_id: int) -> QuickRestoConnection:
    connection = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="QuickResto connection is not configured")
    return connection


def _connection_for_update_or_404(db: Session, venue_id: int) -> QuickRestoConnection:
    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.venue_id == venue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="QuickResto connection is not configured")
    return connection


def _require_quickresto_idle(db: Session, connection: QuickRestoConnection) -> None:
    if quickresto_sync_is_active(connection):
        raise HTTPException(
            status_code=409,
            detail="QuickResto import is running. Wait for it to finish before changing the integration.",
        )
    reclaim_stale_quickresto_sync_state(db, connection=connection)


def _serialize_connection(
    connection: QuickRestoConnection,
    *,
    venue_night_shifts_enabled: bool,
) -> dict:
    return {
        "id": int(connection.id),
        "venue_id": int(connection.venue_id),
        "cloud": connection.cloud,
        "external_venue_id": connection.external_venue_id,
        "external_venue_name": connection.external_venue_name,
        "external_venue_version": connection.external_venue_version,
        "scope_status": str(connection.scope_status or "NEEDS_SELECTION"),
        "scope_generation": int(connection.scope_generation or 1),
        "scope_confirmed_at": (connection.scope_confirmed_at.isoformat() if connection.scope_confirmed_at else None),
        "scope_confirmed_by_user_id": connection.scope_confirmed_by_user_id,
        "credentials_configured": bool(connection.api_login_encrypted and connection.api_password_encrypted),
        "is_active": bool(connection.is_active),
        "auto_sync_enabled": bool(connection.auto_sync_enabled),
        "report_import_mode": str(connection.report_import_mode or "CLOSED").upper(),
        "business_day_cutoff_hour": int(connection.business_day_cutoff_hour or 0),
        "night_shift_split_enabled": bool(connection.night_shift_split_enabled),
        "night_shift_start_hour": int(connection.night_shift_start_hour),
        "venue_night_shifts_enabled": bool(venue_night_shifts_enabled),
        "sync_from_date": connection.sync_from_date.isoformat() if connection.sync_from_date else None,
        "last_sync_started_at": (
            connection.last_sync_started_at.isoformat() if connection.last_sync_started_at else None
        ),
        "last_sync_completed_at": (
            connection.last_sync_completed_at.isoformat() if connection.last_sync_completed_at else None
        ),
        "last_sync_status": connection.last_sync_status,
        "last_sync_error": connection.last_sync_error,
        "incremental_cursor_closed_at": (
            getattr(connection, "incremental_cursor_closed_at", None).isoformat()
            if getattr(connection, "incremental_cursor_closed_at", None)
            else None
        ),
        "last_full_reconciliation_at": (
            getattr(connection, "last_full_reconciliation_at", None).isoformat()
            if getattr(connection, "last_full_reconciliation_at", None)
            else None
        ),
    }


def _serialize_run(run: QuickRestoSyncRun) -> dict:
    return {
        "id": int(run.id),
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "summary": run.summary_json,
        "error": run.error_message,
    }


def _serialized_issue_counters(db: Session, *, connection_id: int) -> dict:
    counters = issue_counters(db, connection_id=connection_id)
    oldest = counters.get("oldest_failed_at")
    return {
        **counters,
        "oldest_failed_at": oldest.isoformat() if oldest else None,
    }


def _issue_or_404(
    db: Session,
    *,
    connection_id: int,
    issue_id: int,
    for_update: bool = False,
) -> QuickRestoImportIssue:
    statement = select(QuickRestoImportIssue).where(
        QuickRestoImportIssue.id == int(issue_id),
        QuickRestoImportIssue.connection_id == int(connection_id),
    )
    if for_update:
        statement = statement.with_for_update()
    issue = db.execute(statement).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="QuickResto import issue not found")
    return issue


def _venue_or_404(db: Session, venue_id: int) -> Venue:
    venue = db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


def _venue_for_update_or_404(db: Session, venue_id: int) -> Venue:
    venue = db.execute(select(Venue).where(Venue.id == venue_id).with_for_update()).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


def _validate_night_shift_split(payload: QuickRestoConnectionUpsertIn, *, venue: Venue) -> None:
    if not payload.night_shift_split_enabled:
        return
    if not venue.night_shifts_enabled:
        raise HTTPException(
            status_code=400,
            detail="Night shift split requires night shifts to be enabled for the venue",
        )
    if payload.night_shift_start_hour <= payload.business_day_cutoff_hour:
        raise HTTPException(
            status_code=400,
            detail="Night shift start hour must be greater than business day cutoff hour",
        )


def _serialize_mappings(db: Session, connection: QuickRestoConnection) -> dict:
    payments = (
        db.execute(
            select(QuickRestoPaymentMapping)
            .where(QuickRestoPaymentMapping.connection_id == connection.id)
            .order_by(QuickRestoPaymentMapping.external_name, QuickRestoPaymentMapping.external_id)
        )
        .scalars()
        .all()
    )
    departments = (
        db.execute(
            select(QuickRestoDepartmentMapping)
            .where(QuickRestoDepartmentMapping.connection_id == connection.id)
            .order_by(QuickRestoDepartmentMapping.external_name, QuickRestoDepartmentMapping.external_id)
        )
        .scalars()
        .all()
    )
    return {
        "payments": [
            {
                "external_id": int(item.external_id),
                "external_name": item.external_name,
                "operation_type": item.operation_type,
                "payment_mechanism": item.payment_mechanism,
                "payment_method_id": int(item.payment_method_id) if item.payment_method_id else None,
                "excluded_from_revenue": bool(item.excluded_from_revenue),
                "is_applicable": bool(item.is_applicable),
                "is_available": bool(item.is_available),
                "allowed_sale_place_ids": sorted(int(value) for value in item.allowed_sale_place_ids_json or ()),
            }
            for item in payments
        ],
        "departments": [
            {
                "external_id": int(item.external_id),
                "external_name": item.external_name,
                "department_id": int(item.department_id) if item.department_id else None,
            }
            for item in departments
        ],
    }


def _mapping_readiness(db: Session, connection: QuickRestoConnection) -> dict:
    payments = list(
        db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == connection.id)
        ).scalars()
    )
    departments = list(
        db.execute(
            select(QuickRestoDepartmentMapping).where(QuickRestoDepartmentMapping.connection_id == connection.id)
        ).scalars()
    )
    missing_payments = sorted(
        int(item.external_id)
        for item in payments
        if item.is_available
        and item.is_applicable
        and not item.excluded_from_revenue
        and item.payment_method_id is None
    )
    missing_departments = sorted(int(item.external_id) for item in departments if item.department_id is None)
    discovered = bool(any(item.is_available and item.is_applicable for item in payments) or departments)
    return {
        "ready": bool(
            str(connection.scope_status or "").upper() == "READY"
            and discovered
            and not missing_payments
            and not missing_departments
        ),
        "discovered": discovered,
        "unmapped_payment_type_ids": missing_payments,
        "unmapped_department_ids": missing_departments,
    }


def _serialize_scope_audits(db: Session, *, connection_id: int, limit: int = 20) -> list[dict]:
    rows = list(
        db.execute(
            select(QuickRestoScopeAudit)
            .where(QuickRestoScopeAudit.connection_id == int(connection_id))
            .order_by(QuickRestoScopeAudit.changed_at.desc(), QuickRestoScopeAudit.id.desc())
            .limit(int(limit))
        ).scalars()
    )
    return [
        {
            "id": int(item.id),
            "actor_user_id": item.actor_user_id,
            "scope_generation": int(item.scope_generation),
            "previous_scope": item.previous_scope_json or {},
            "current_scope": item.current_scope_json or {},
            "changes": item.changes_json or {},
            "changed_at": item.changed_at.isoformat() if item.changed_at else None,
        }
        for item in rows
    ]


@router.get("/{venue_id}/integrations/quickresto")
def get_quickresto_connection(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_view(db, venue_id=venue_id, user=user)
    venue = _venue_or_404(db, venue_id)
    connection = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
    ).scalar_one_or_none()
    can_manage = _can_manage_quickresto(db, venue_id=venue_id, user=user)
    selected_provider = active_pos_provider(db, venue_id=venue_id)
    if connection is None:
        return {
            "configured": False,
            "venue_night_shifts_enabled": bool(venue.night_shifts_enabled),
            "connection": None,
            "mappings": {"payments": [], "departments": []},
            "mapping_readiness": {
                "ready": False,
                "discovered": False,
                "unmapped_payment_type_ids": [],
                "unmapped_department_ids": [],
            },
            "scope_audit": [],
            "catalog": {
                "scope_status": "NEEDS_SELECTION",
                "scope_generation": 1,
                "selected_external_venue_id": None,
                "venues": [],
                "sale_places": [],
                "stores": [],
                "payment_types": [],
            },
            "permissions": {"can_view": True, "can_manage": can_manage},
            "active_pos_provider": selected_provider,
            "issues": {"open_count": 0, "affected_shift_count": 0, "oldest_failed_at": None},
        }
    return {
        "configured": True,
        "venue_night_shifts_enabled": bool(venue.night_shifts_enabled),
        "connection": _serialize_connection(
            connection,
            venue_night_shifts_enabled=venue.night_shifts_enabled,
        ),
        "mappings": _serialize_mappings(db, connection),
        "mapping_readiness": _mapping_readiness(db, connection),
        "scope_audit": _serialize_scope_audits(db, connection_id=int(connection.id)),
        "catalog": serialize_quickresto_catalog(db, connection=connection),
        "permissions": {"can_view": True, "can_manage": can_manage},
        "active_pos_provider": selected_provider,
        "issues": _serialized_issue_counters(db, connection_id=int(connection.id)),
    }


@router.put("/{venue_id}/integrations/quickresto")
def put_quickresto_connection(
    venue_id: int,
    payload: QuickRestoConnectionUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    venue = _venue_for_update_or_404(db, venue_id)
    _validate_night_shift_split(payload, venue=venue)
    connection = db.execute(
        select(QuickRestoConnection)
        .where(QuickRestoConnection.venue_id == venue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if connection is not None:
        _require_quickresto_idle(db, connection)
    if connection is None and (not payload.api_login or not payload.api_password):
        raise HTTPException(status_code=400, detail="QuickResto API login and password are required")

    try:
        login = payload.api_login or decrypt_credential(connection.api_login_encrypted)
        password = payload.api_password or decrypt_credential(connection.api_password_encrypted)
        config = QuickRestoConfig(cloud=payload.cloud, login=login, password=password)
        encrypted_login = encrypt_credential(login)
        encrypted_password = encrypt_credential(password)
    except (ValueError, IntegrationCredentialError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.utcnow()
    if connection is None:
        connection = QuickRestoConnection(
            venue_id=venue_id,
            cloud=config.cloud,
            api_login_encrypted=encrypted_login,
            api_password_encrypted=encrypted_password,
            scope_status="NEEDS_SELECTION",
            scope_generation=1,
            is_active=payload.is_active,
            auto_sync_enabled=payload.auto_sync_enabled,
            report_import_mode=payload.report_import_mode or "CLOSED",
            business_day_cutoff_hour=payload.business_day_cutoff_hour,
            night_shift_split_enabled=payload.night_shift_split_enabled,
            night_shift_start_hour=payload.night_shift_start_hour,
            sync_from_date=payload.sync_from_date,
            created_by_user_id=user.id,
            created_at=now,
        )
        db.add(connection)
    else:
        cloud_changed = connection.cloud != config.cloud
        credentials_changed = bool(payload.api_login or payload.api_password)
        connection.cloud = config.cloud
        connection.api_login_encrypted = encrypted_login
        connection.api_password_encrypted = encrypted_password
        connection.is_active = payload.is_active
        connection.auto_sync_enabled = payload.auto_sync_enabled
        if payload.report_import_mode is not None:
            connection.report_import_mode = payload.report_import_mode
        connection.business_day_cutoff_hour = payload.business_day_cutoff_hour
        connection.night_shift_split_enabled = payload.night_shift_split_enabled
        connection.night_shift_start_hour = payload.night_shift_start_hour
        connection.sync_from_date = payload.sync_from_date
        if cloud_changed:
            connection.external_venue_id = None
            connection.external_venue_name = None
            connection.external_venue_version = None
            connection.scope_status = "NEEDS_SELECTION"
            connection.scope_confirmed_at = None
            connection.scope_confirmed_by_user_id = None
            connection.scope_generation = int(connection.scope_generation or 1) + 1
            connection.incremental_cursor_closed_at = None
            connection.last_full_reconciliation_at = None
        elif credentials_changed and connection.scope_status == "READY":
            connection.scope_status = "STALE"
        connection.updated_by_user_id = user.id
        connection.updated_at = now
    try:
        if payload.is_active:
            acquire_pos_provider(
                db,
                venue_id=venue_id,
                provider=QUICKRESTO_PROVIDER,
            )
        else:
            release_pos_provider(
                db,
                venue_id=venue_id,
                provider=QUICKRESTO_PROVIDER,
            )
    except POSProviderSelectionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(connection)
    return {
        "ok": True,
        "venue_night_shifts_enabled": bool(venue.night_shifts_enabled),
        "connection": _serialize_connection(
            connection,
            venue_night_shifts_enabled=venue.night_shifts_enabled,
        ),
        "active_pos_provider": active_pos_provider(db, venue_id=venue_id),
    }


@router.get("/{venue_id}/integrations/quickresto/catalog")
def get_quickresto_catalog(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    return {"ok": True, "catalog": serialize_quickresto_catalog(db, connection=connection)}


@router.post("/{venue_id}/integrations/quickresto/catalog/refresh")
def refresh_quickresto_catalog_route(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_for_update_or_404(db, venue_id)
    _require_quickresto_idle(db, connection)
    try:
        with build_quickresto_client(connection) as client:
            summary = refresh_quickresto_catalog(db, connection=connection, client=client)
        connection.updated_by_user_id = user.id
        connection.updated_at = datetime.utcnow()
        db.commit()
    except (QuickRestoError, IntegrationCredentialError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "summary": summary,
        "catalog": serialize_quickresto_catalog(db, connection=connection),
    }


@router.put("/{venue_id}/integrations/quickresto/scope")
def put_quickresto_scope(
    venue_id: int,
    payload: QuickRestoScopeUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_for_update_or_404(db, venue_id)
    _require_quickresto_idle(db, connection)
    try:
        scope = apply_quickresto_scope(
            db,
            connection=connection,
            external_venue_id=payload.external_venue_id,
            sale_place_ids=payload.sale_place_ids,
            store_ids=payload.store_ids,
            actor_user_id=int(user.id),
        )
        with build_quickresto_client(connection) as client:
            mapping_summary = refresh_quickresto_mappings(db, connection=connection, client=client)
        connection.updated_by_user_id = user.id
        connection.updated_at = datetime.utcnow()
        db.commit()
    except QuickRestoScopeConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuickRestoScopeError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (QuickRestoError, IntegrationCredentialError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "scope": scope,
        "mapping_summary": mapping_summary,
        "connection": _serialize_connection(
            connection,
            venue_night_shifts_enabled=_venue_or_404(db, venue_id).night_shifts_enabled,
        ),
        "catalog": serialize_quickresto_catalog(db, connection=connection),
        "mappings": _serialize_mappings(db, connection),
        "mapping_readiness": _mapping_readiness(db, connection),
        "scope_audit": _serialize_scope_audits(db, connection_id=int(connection.id)),
    }


@router.post("/{venue_id}/integrations/quickresto/discover")
def discover_quickresto_mappings(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_for_update_or_404(db, venue_id)
    _require_quickresto_idle(db, connection)
    try:
        with build_quickresto_client(connection) as client:
            catalog_summary = refresh_quickresto_catalog(db, connection=connection, client=client)
            ensure_quickresto_scope_ready(connection)
            summary = refresh_quickresto_mappings(db, connection=connection, client=client)
        db.commit()
    except QuickRestoScopeError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (QuickRestoError, IntegrationCredentialError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "summary": {**catalog_summary, **summary},
        "catalog": serialize_quickresto_catalog(db, connection=connection),
        "mappings": _serialize_mappings(db, connection),
        "mapping_readiness": _mapping_readiness(db, connection),
    }


@router.put("/{venue_id}/integrations/quickresto/mappings")
def put_quickresto_mappings(
    venue_id: int,
    payload: QuickRestoMappingsUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_for_update_or_404(db, venue_id)
    _require_quickresto_idle(db, connection)
    try:
        ensure_quickresto_scope_ready(connection)
    except QuickRestoScopeError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    valid_payment_ids = set(db.execute(select(PaymentMethod.id).where(PaymentMethod.venue_id == venue_id)).scalars())
    valid_department_ids = set(db.execute(select(Department.id).where(Department.venue_id == venue_id)).scalars())
    payment_mappings = {
        int(item.external_id): item
        for item in db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == connection.id)
        ).scalars()
    }
    department_mappings = {
        int(item.external_id): item
        for item in db.execute(
            select(QuickRestoDepartmentMapping).where(QuickRestoDepartmentMapping.connection_id == connection.id)
        ).scalars()
    }
    for item in payload.payments:
        mapping = payment_mappings.get(item.external_id)
        if mapping is None:
            raise HTTPException(status_code=400, detail=f"Unknown QuickResto payment type {item.external_id}")
        if not mapping.is_available or not mapping.is_applicable:
            raise HTTPException(status_code=400, detail="QuickResto payment type is outside the selected venue scope")
        if item.payment_method_id is not None and item.payment_method_id not in valid_payment_ids:
            raise HTTPException(status_code=400, detail="Payment method does not belong to venue")
        if mapping.operation_type == "writeoff" and not item.excluded_from_revenue:
            raise HTTPException(status_code=400, detail="QuickResto write-off cannot be included in revenue")
        if mapping.operation_type != "writeoff" and item.excluded_from_revenue:
            raise HTTPException(status_code=400, detail="Only QuickResto write-offs can be excluded from revenue")
        mapping.payment_method_id = item.payment_method_id
        mapping.excluded_from_revenue = bool(item.excluded_from_revenue)
        mapping.updated_at = datetime.utcnow()
    for item in payload.departments:
        mapping = department_mappings.get(item.external_id)
        if mapping is None:
            raise HTTPException(status_code=400, detail=f"Unknown QuickResto department {item.external_id}")
        if item.department_id is not None and item.department_id not in valid_department_ids:
            raise HTTPException(status_code=400, detail="Department does not belong to venue")
        mapping.department_id = item.department_id
        mapping.updated_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "mappings": _serialize_mappings(db, connection),
        "mapping_readiness": _mapping_readiness(db, connection),
    }


@router.get("/{venue_id}/integrations/quickresto/issues")
def list_quickresto_issues(
    venue_id: int,
    status: str = Query(default="active", max_length=32),
    business_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    normalized_status = str(status or "active").strip().upper()
    filters = [QuickRestoImportIssue.connection_id == int(connection.id)]
    if business_date is not None:
        filters.append(QuickRestoImportIssue.business_date == business_date)
    if normalized_status == "ACTIVE":
        filters.append(QuickRestoImportIssue.status.in_(ACTIVE_ISSUE_STATUSES))
    elif normalized_status != "ALL":
        if normalized_status not in {"OPEN", "RETRY_PENDING", "PROCESSING", "RESOLVED", "IGNORED"}:
            raise HTTPException(status_code=400, detail="Unsupported QuickResto issue status")
        filters.append(QuickRestoImportIssue.status == normalized_status)
    total = int(db.execute(select(func.count(QuickRestoImportIssue.id)).where(*filters)).scalar_one())
    rows = list(
        db.execute(
            select(QuickRestoImportIssue)
            .where(*filters)
            .order_by(
                QuickRestoImportIssue.last_failed_at.desc(),
                QuickRestoImportIssue.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).scalars()
    )
    counters = _serialized_issue_counters(db, connection_id=int(connection.id))
    return {
        "items": [serialize_issue(item, include_technical=_is_super_admin(user)) for item in rows],
        "total": total,
        **counters,
    }


@router.get("/{venue_id}/integrations/quickresto/issues/{issue_id}")
def get_quickresto_issue(
    venue_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    issue = _issue_or_404(db, connection_id=int(connection.id), issue_id=issue_id)
    return serialize_issue(
        issue,
        include_shifts=True,
        include_technical=_is_super_admin(user),
    )


@router.post("/{venue_id}/integrations/quickresto/issues/{issue_id}/retry")
def post_quickresto_issue_retry(
    venue_id: int,
    issue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    _issue_or_404(db, connection_id=int(connection.id), issue_id=issue_id)
    try:
        run = retry_quickresto_import_issue(
            db,
            connection=connection,
            issue_id=issue_id,
            requested_by_user_id=int(user.id),
        )
    except QuickRestoSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    issue = _issue_or_404(db, connection_id=int(connection.id), issue_id=issue_id)
    return {
        "ok": run.status == "SUCCEEDED",
        "run": _serialize_run(run),
        "issue": serialize_issue(
            issue,
            include_shifts=True,
            include_technical=_is_super_admin(user),
        ),
    }


@router.post("/{venue_id}/integrations/quickresto/issues/{issue_id}/resolve")
def post_quickresto_issue_resolve(
    venue_id: int,
    issue_id: int,
    payload: QuickRestoIssueResolveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_for_update_or_404(db, venue_id)
    _require_quickresto_idle(db, connection)
    issue = _issue_or_404(
        db,
        connection_id=int(connection.id),
        issue_id=issue_id,
        for_update=True,
    )
    if str(issue.status or "").upper() not in {"OPEN", "RETRY_PENDING"}:
        raise HTTPException(status_code=409, detail="QuickResto import issue is not waiting for a resolution")
    transition_issue(
        db,
        issue=issue,
        status="IGNORED",
        event_type="USER_IGNORED",
        actor_user_id=int(user.id),
        resolution_code=payload.action,
        resolution_note=payload.note.strip(),
    )
    db.commit()
    db.refresh(issue)
    return {
        "ok": True,
        "issue": serialize_issue(
            issue,
            include_shifts=True,
            include_technical=_is_super_admin(user),
        ),
    }


@router.post("/{venue_id}/integrations/quickresto/sync")
def post_quickresto_sync(
    venue_id: int,
    full: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_manage(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    try:
        run = sync_quickresto_connection(
            db,
            connection=connection,
            requested_by_user_id=user.id,
            trigger="MANUAL",
            force_full=full,
        )
    except QuickRestoSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": run.status in {"SUCCEEDED", "PARTIAL"},
        "run": _serialize_run(run),
    }


@router.get("/{venue_id}/integrations/quickresto/runs")
def list_quickresto_runs(
    venue_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_quickresto_view(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    rows = (
        db.execute(
            select(QuickRestoSyncRun)
            .where(QuickRestoSyncRun.connection_id == connection.id)
            .order_by(QuickRestoSyncRun.started_at.desc(), QuickRestoSyncRun.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_serialize_run(item) for item in rows]
