from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.services.billing.access import BILLING_ACCESS_FULL, get_user_billing_access
from app.services.setup import (
    build_setup_summary,
    complete_setup_step,
    finish_extra_setup,
    finish_prepare_setup,
    patch_setup_state,
    reset_setup_step,
    skip_setup_step,
    start_setup,
)

router = APIRouter(prefix="/venues", tags=["setup"])


class SetupPatchIn(BaseModel):
    current_step_key: str | None = Field(default=None, max_length=64)
    phase: str | None = Field(default=None, max_length=16)
    step_meta: dict[str, Any] | None = None


class SetupStepActionIn(BaseModel):
    step_key: str = Field(..., max_length=64)


class SetupVenueNameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


def _require_setup_owner_or_admin(db: Session, *, venue_id: int, user: User) -> None:
    if user.system_role in {"SUPER_ADMIN", "MODERATOR"}:
        return
    membership = db.execute(
        select(VenueMember.venue_role).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id == int(user.id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    role_upper = str(membership or "").upper()
    if role_upper != "OWNER":
        raise HTTPException(status_code=403, detail="Forbidden")
    access = get_user_billing_access(db, venue_id=int(venue_id), user=user, membership_role=role_upper)
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        raise HTTPException(
            status_code=403,
            detail=access.get("billing_restricted_reason") or "Доступ к заведению ограничен из-за статуса подписки",
        )


@router.get("/{venue_id}/setup")
def get_venue_setup(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    return build_setup_summary(db, venue_id=venue_id, create_missing=True)


@router.post("/{venue_id}/setup/start")
def start_venue_setup(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    summary = start_setup(db, venue_id=venue_id, seen_by_user=user)
    db.commit()
    return summary


@router.patch("/{venue_id}/setup")
def patch_venue_setup(
    venue_id: int,
    payload: SetupPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = patch_setup_state(
            db,
            venue_id=venue_id,
            current_step_key=payload.current_step_key,
            phase=payload.phase,
            step_meta=payload.step_meta,
            seen_by_user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary


@router.post("/{venue_id}/setup/complete-step")
def complete_venue_setup_step(
    venue_id: int,
    payload: SetupStepActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = complete_setup_step(db, venue_id=venue_id, step_key=payload.step_key, seen_by_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary


@router.post("/{venue_id}/setup/skip-step")
def skip_venue_setup_step(
    venue_id: int,
    payload: SetupStepActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = skip_setup_step(db, venue_id=venue_id, step_key=payload.step_key, seen_by_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary


@router.post("/{venue_id}/setup/reset-step")
def reset_venue_setup_step(
    venue_id: int,
    payload: SetupStepActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = reset_setup_step(db, venue_id=venue_id, step_key=payload.step_key, seen_by_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary


@router.post("/{venue_id}/setup/finish-prepare")
def finish_prepare_venue_setup(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = finish_prepare_setup(db, venue_id=venue_id, seen_by_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary


@router.patch("/{venue_id}/setup/venue")
def patch_setup_venue_name(
    venue_id: int,
    payload: SetupVenueNameIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название заведения не может быть пустым")
    venue.name = name
    db.commit()
    return {"id": int(venue.id), "name": str(venue.name or "")}


@router.post("/{venue_id}/setup/finish-extra")
def finish_extra_venue_setup(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_setup_owner_or_admin(db, venue_id=venue_id, user=user)
    try:
        summary = finish_extra_setup(db, venue_id=venue_id, seen_by_user=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return summary
