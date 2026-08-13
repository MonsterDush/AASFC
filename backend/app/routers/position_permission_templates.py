from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.core.permission_codes import normalize_known_permission_codes
from app.models.position_permission_template import PositionPermissionTemplate
from app.models.user import User
from app.services.position_permission_templates import ensure_default_templates, next_sort_order, serialize_template

public_router = APIRouter(tags=["position-permission-templates"])
router = APIRouter(prefix="/admin", tags=["admin-position-permission-templates"])


class TemplateCreateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] = Field(default_factory=list)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool = True


class TemplateUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class TemplateArchiveIn(BaseModel):
    is_active: bool = False


class SeedDefaultsIn(BaseModel):
    reactivate: bool = True


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_code(raw: str | None, *, fallback_title: str | None = None) -> str:
    value = str(raw or "").strip().lower()
    if not value and fallback_title:
        value = str(fallback_title).strip().lower()
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    code = "".join(out).strip("-")
    while "--" in code:
        code = code.replace("--", "-")
    return code[:80] or "template"


def _load_row(db: Session, template_id: int) -> PositionPermissionTemplate:
    row = db.execute(
        select(PositionPermissionTemplate).where(
            PositionPermissionTemplate.id == int(template_id),
            PositionPermissionTemplate.scope == "GLOBAL",
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return row


@public_router.get("/position-permission-templates")
def list_position_permission_templates(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    del user
    ensure_default_templates(db)
    db.commit()
    stmt = select(PositionPermissionTemplate).where(PositionPermissionTemplate.scope == "GLOBAL")
    if not include_inactive:
        stmt = stmt.where(PositionPermissionTemplate.is_active.is_(True))
    rows = (
        db.execute(stmt.order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc()))
        .scalars()
        .all()
    )
    return {"items": [serialize_template(row) for row in rows]}


@router.get("/position-permission-templates")
def admin_list_position_permission_templates(
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    ensure_default_templates(db, actor_user_id=int(user.id))
    db.commit()
    stmt = select(PositionPermissionTemplate).where(PositionPermissionTemplate.scope == "GLOBAL")
    if not include_inactive:
        stmt = stmt.where(PositionPermissionTemplate.is_active.is_(True))
    rows = (
        db.execute(stmt.order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc()))
        .scalars()
        .all()
    )
    return {"items": [serialize_template(row) for row in rows]}


@router.post("/position-permission-templates/seed-defaults")
def admin_seed_position_permission_templates(
    payload: SeedDefaultsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    result = ensure_default_templates(db, actor_user_id=int(user.id), reactivate=bool(payload.reactivate))
    db.commit()
    rows = (
        db.execute(
            select(PositionPermissionTemplate)
            .where(PositionPermissionTemplate.scope == "GLOBAL")
            .order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc())
        )
        .scalars()
        .all()
    )
    return {**result, "items": [serialize_template(row) for row in rows]}


@router.post("/position-permission-templates")
def admin_create_position_permission_template(
    payload: TemplateCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    code = _normalize_code(payload.code, fallback_title=payload.title)
    existing = db.execute(
        select(PositionPermissionTemplate).where(
            PositionPermissionTemplate.code == code,
            PositionPermissionTemplate.scope == "GLOBAL",
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Template code already exists")
    row = PositionPermissionTemplate(
        code=code,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        permission_codes_json=normalize_known_permission_codes(db, payload.permission_codes or []),
        sort_order=int(payload.sort_order) if payload.sort_order is not None else next_sort_order(db),
        is_active=bool(payload.is_active),
        is_system=False,
        scope="GLOBAL",
        created_by_user_id=int(user.id),
        updated_by_user_id=int(user.id),
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_template(row)


@router.patch("/position-permission-templates/{template_id}")
def admin_update_position_permission_template(
    template_id: int,
    payload: TemplateUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    row = _load_row(db, template_id)
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "code" in fields_set and payload.code is not None:
        code = _normalize_code(payload.code, fallback_title=row.title)
        existing = db.execute(
            select(PositionPermissionTemplate).where(
                PositionPermissionTemplate.code == code,
                PositionPermissionTemplate.scope == "GLOBAL",
                PositionPermissionTemplate.id != row.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Template code already exists")
        row.code = code
    if "title" in fields_set and payload.title is not None:
        row.title = payload.title.strip()
    if "description" in fields_set:
        row.description = (payload.description or "").strip() or None
    if "permission_codes" in fields_set and payload.permission_codes is not None:
        row.permission_codes_json = normalize_known_permission_codes(db, payload.permission_codes or [])
    if "sort_order" in fields_set and payload.sort_order is not None:
        row.sort_order = int(payload.sort_order)
    if "is_active" in fields_set and payload.is_active is not None:
        row.is_active = bool(payload.is_active)
    row.updated_by_user_id = int(user.id)
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return serialize_template(row)


@router.post("/position-permission-templates/{template_id}/archive")
def admin_archive_position_permission_template(
    template_id: int,
    payload: TemplateArchiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    row = _load_row(db, template_id)
    row.is_active = bool(payload.is_active)
    row.updated_by_user_id = int(user.id)
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    return serialize_template(row)
