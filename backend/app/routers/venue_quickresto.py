from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.auth.deps import get_current_user
from app.routers.venue_access import require_owner_or_super_admin
from app.schemas.quickresto import QuickRestoConnectionUpsertIn, QuickRestoMappingsUpdateIn
from app.services.integrations.credentials import (
    IntegrationCredentialError,
    decrypt_credential,
    encrypt_credential,
)
from app.services.integrations.quickresto import QuickRestoConfig, QuickRestoError
from app.services.integrations.quickresto_sync import (
    QuickRestoSyncError,
    build_quickresto_client,
    refresh_quickresto_mappings,
    sync_quickresto_connection,
)


router = APIRouter()


def _connection_or_404(db: Session, venue_id: int) -> QuickRestoConnection:
    connection = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="QuickResto connection is not configured")
    return connection


def _serialize_connection(connection: QuickRestoConnection) -> dict:
    return {
        "id": int(connection.id),
        "venue_id": int(connection.venue_id),
        "cloud": connection.cloud,
        "credentials_configured": bool(connection.api_login_encrypted and connection.api_password_encrypted),
        "is_active": bool(connection.is_active),
        "auto_sync_enabled": bool(connection.auto_sync_enabled),
        "report_import_mode": str(connection.report_import_mode or "CLOSED").upper(),
        "business_day_cutoff_hour": int(connection.business_day_cutoff_hour or 0),
        "sync_from_date": connection.sync_from_date.isoformat() if connection.sync_from_date else None,
        "last_sync_started_at": (
            connection.last_sync_started_at.isoformat() if connection.last_sync_started_at else None
        ),
        "last_sync_completed_at": (
            connection.last_sync_completed_at.isoformat() if connection.last_sync_completed_at else None
        ),
        "last_sync_status": connection.last_sync_status,
        "last_sync_error": connection.last_sync_error,
    }


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


@router.get("/{venue_id}/integrations/quickresto")
def get_quickresto_connection(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    connection = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
    ).scalar_one_or_none()
    if connection is None:
        return {"configured": False, "connection": None, "mappings": {"payments": [], "departments": []}}
    return {
        "configured": True,
        "connection": _serialize_connection(connection),
        "mappings": _serialize_mappings(db, connection),
    }


@router.put("/{venue_id}/integrations/quickresto")
def put_quickresto_connection(
    venue_id: int,
    payload: QuickRestoConnectionUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    connection = db.execute(
        select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
    ).scalar_one_or_none()
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
            is_active=payload.is_active,
            auto_sync_enabled=payload.auto_sync_enabled,
            report_import_mode=payload.report_import_mode or "CLOSED",
            business_day_cutoff_hour=payload.business_day_cutoff_hour,
            sync_from_date=payload.sync_from_date,
            created_by_user_id=user.id,
            created_at=now,
        )
        db.add(connection)
    else:
        connection.cloud = config.cloud
        connection.api_login_encrypted = encrypted_login
        connection.api_password_encrypted = encrypted_password
        connection.is_active = payload.is_active
        connection.auto_sync_enabled = payload.auto_sync_enabled
        if payload.report_import_mode is not None:
            connection.report_import_mode = payload.report_import_mode
        connection.business_day_cutoff_hour = payload.business_day_cutoff_hour
        connection.sync_from_date = payload.sync_from_date
        connection.updated_by_user_id = user.id
        connection.updated_at = now
    db.commit()
    db.refresh(connection)
    return {"ok": True, "connection": _serialize_connection(connection)}


@router.post("/{venue_id}/integrations/quickresto/discover")
def discover_quickresto_mappings(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    try:
        with build_quickresto_client(connection) as client:
            summary = refresh_quickresto_mappings(db, connection=connection, client=client)
        db.commit()
    except (QuickRestoError, IntegrationCredentialError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "summary": summary, "mappings": _serialize_mappings(db, connection)}


@router.put("/{venue_id}/integrations/quickresto/mappings")
def put_quickresto_mappings(
    venue_id: int,
    payload: QuickRestoMappingsUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
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
    return {"ok": True, "mappings": _serialize_mappings(db, connection)}


@router.post("/{venue_id}/integrations/quickresto/sync")
def post_quickresto_sync(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    connection = _connection_or_404(db, venue_id)
    try:
        run = sync_quickresto_connection(
            db,
            connection=connection,
            requested_by_user_id=user.id,
            trigger="MANUAL",
        )
    except QuickRestoSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": run.status == "SUCCEEDED",
        "run": {
            "id": int(run.id),
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "summary": run.summary_json,
            "error": run.error_message,
        },
    }


@router.get("/{venue_id}/integrations/quickresto/runs")
def list_quickresto_runs(
    venue_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
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
    return [
        {
            "id": int(item.id),
            "trigger": item.trigger,
            "status": item.status,
            "started_at": item.started_at.isoformat(),
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            "summary": item.summary_json,
            "error": item.error_message,
        }
        for item in rows
    ]
