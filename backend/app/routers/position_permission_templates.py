from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.core.permission_codes import normalize_known_permission_codes, parse_permission_codes
from app.models.position_permission_template import PositionPermissionTemplate
from app.models.user import User

public_router = APIRouter(tags=["position-permission-templates"])
router = APIRouter(prefix="/admin", tags=["admin-position-permission-templates"])


class TemplateCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] = Field(default_factory=list)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool = True


class TemplateUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class TemplateArchiveIn(BaseModel):
    is_active: bool = False


def _utcnow() -> datetime:
    return datetime.utcnow()


def _serialize_template(row: PositionPermissionTemplate) -> dict:
    return {
        "id": int(row.id),
        "title": str(row.title or "").strip(),
        "description": str(row.description or "").strip() or None,
        "permission_codes": parse_permission_codes(getattr(row, "permission_codes_json", None)),
        "sort_order": int(getattr(row, "sort_order", 0) or 0),
        "is_active": bool(getattr(row, "is_active", True)),
        "scope": str(getattr(row, "scope", "GLOBAL") or "GLOBAL").upper(),
        "created_by_user_id": int(row.created_by_user_id) if getattr(row, "created_by_user_id", None) is not None else None,
        "updated_by_user_id": int(row.updated_by_user_id) if getattr(row, "updated_by_user_id", None) is not None else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
    }


def _next_sort_order(db: Session) -> int:
    current = db.execute(select(func.max(PositionPermissionTemplate.sort_order))).scalar_one_or_none()
    base = int(current or 0)
    return base + 10 if base >= 0 else 10


@public_router.get("/position-permission-templates")
def list_position_permission_templates(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    del user
    stmt = select(PositionPermissionTemplate).where(PositionPermissionTemplate.scope == "GLOBAL")
    if not include_inactive:
        stmt = stmt.where(PositionPermissionTemplate.is_active.is_(True))
    rows = db.execute(
        stmt.order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc())
    ).scalars().all()
    return {"items": [_serialize_template(row) for row in rows]}


@router.get("/position-permission-templates")
def admin_list_position_permission_templates(
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    del user
    stmt = select(PositionPermissionTemplate).where(PositionPermissionTemplate.scope == "GLOBAL")
    if not include_inactive:
        stmt = stmt.where(PositionPermissionTemplate.is_active.is_(True))
    rows = db.execute(
        stmt.order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc())
    ).scalars().all()
    return {"items": [_serialize_template(row) for row in rows]}


@router.post("/position-permission-templates")
def admin_create_position_permission_template(
    payload: TemplateCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    norm_codes = normalize_known_permission_codes(db, payload.permission_codes or [])
    row = PositionPermissionTemplate(
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        permission_codes_json=norm_codes,
        sort_order=int(payload.sort_order) if payload.sort_order is not None else _next_sort_order(db),
        is_active=bool(payload.is_active),
        scope="GLOBAL",
        created_by_user_id=int(user.id),
        updated_by_user_id=int(user.id),
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_template(row)


@router.patch("/position-permission-templates/{template_id}")
def admin_update_position_permission_template(
    template_id: int,
    payload: TemplateUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    row = db.execute(
        select(PositionPermissionTemplate).where(PositionPermissionTemplate.id == int(template_id), PositionPermissionTemplate.scope == "GLOBAL")
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")

    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    if 'title' in fields_set and payload.title is not None:
        row.title = payload.title.strip()
    if 'description' in fields_set:
        row.description = (payload.description or '').strip() or None
    if 'permission_codes' in fields_set and payload.permission_codes is not None:
        row.permission_codes_json = normalize_known_permission_codes(db, payload.permission_codes or [])
    if 'sort_order' in fields_set and payload.sort_order is not None:
        row.sort_order = int(payload.sort_order)
    if 'is_active' in fields_set and payload.is_active is not None:
        row.is_active = bool(payload.is_active)
    row.updated_by_user_id = int(user.id)
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return _serialize_template(row)


@router.post("/position-permission-templates/{template_id}/archive")
def admin_archive_position_permission_template(
    template_id: int,
    payload: TemplateArchiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    row = db.execute(
        select(PositionPermissionTemplate).where(PositionPermissionTemplate.id == int(template_id), PositionPermissionTemplate.scope == "GLOBAL")
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    row.is_active = bool(payload.is_active)
    row.updated_by_user_id = int(user.id)
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return _serialize_template(row)
