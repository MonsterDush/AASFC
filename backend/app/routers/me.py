from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.models import (
    User,
    Venue,
    VenueMember,
    Permission,
    RolePermissionDefault,
    VenuePosition,
)


router = APIRouter(tags=["me"])


from pydantic import BaseModel, Field

class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)





class NotificationSettingsIn(BaseModel):
    notify_enabled: bool | None = None
    notify_adjustments: bool | None = None
    notify_shifts: bool | None = None

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_user_id": user.tg_user_id,
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
        "system_role": user.system_role,
        "notify_enabled": user.notify_enabled,
        "notify_adjustments": user.notify_adjustments,
        "notify_shifts": user.notify_shifts,
    }



@router.get("/me/profile")
def get_profile(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
    }


@router.patch("/me/profile")
def update_profile(
    payload: ProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # пустые строки считаем как None
    if payload.full_name is not None:
        v = payload.full_name.strip()
        user.full_name = v or None
    if payload.short_name is not None:
        v = payload.short_name.strip()
        user.short_name = v or None
    db.commit()
    return {"ok": True}


@router.get("/me/notification-settings")
def get_notification_settings(user: User = Depends(get_current_user)):
    return {
        "notify_enabled": user.notify_enabled,
        "notify_adjustments": user.notify_adjustments,
        "notify_shifts": user.notify_shifts,
    }


@router.patch("/me/notification-settings")
def update_notification_settings(
    payload: NotificationSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.notify_enabled is not None:
        user.notify_enabled = bool(payload.notify_enabled)
    if payload.notify_adjustments is not None:
        user.notify_adjustments = bool(payload.notify_adjustments)
    if payload.notify_shifts is not None:
        user.notify_shifts = bool(payload.notify_shifts)
    db.commit()
    return {"ok": True}


@router.get("/me/venues")
def my_venues(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Venue.id, Venue.name, VenueMember.venue_role)
        .join(VenueMember, VenueMember.venue_id == Venue.id)
        .where(
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
        .order_by(Venue.id.desc())
    ).all()

    return [{"id": r.id, "name": r.name, "my_role": r.venue_role} for r in rows]


@router.get("/me/venues/{venue_id}/members")
def my_venue_members(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # доступ: любой активный member этого venue
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None and user.system_role not in ("SUPER_ADMIN", "MODERATOR"):
        # можно 403 — так правильнее
        return {"venue_id": venue_id, "members": []}

    rows = db.execute(
        select(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == venue_id,
            VenueMember.is_active.is_(True),
        )
        .order_by(VenueMember.venue_role.asc(), User.id.asc())
    ).all()

    return {
        "venue_id": venue_id,
        "members": [
            {
                "user_id": r.id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
            }
            for r in rows
        ],
    }


@router.get("/me/venues/{venue_id}/permissions")
def my_venue_permissions(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return permissions + venue role + position flags for current user.

    Position flags are used for MVP UI gating:
    - can_make_reports
    - can_edit_schedule
    """

    # ---- system roles ----
    if user.system_role == "SUPER_ADMIN":
        codes = db.scalars(select(Permission.code).where(Permission.is_active.is_(True))).all()
        return {
            "venue_id": venue_id,
            "role": "SUPER_ADMIN",
            "permissions": list(codes),
            "position": None,
            "position_flags": {"can_make_reports": True, "can_edit_schedule": True},
        }

    if user.system_role == "MODERATOR":
        codes = db.scalars(
            select(RolePermissionDefault.permission_code)
            .join(Permission, Permission.code == RolePermissionDefault.permission_code)
            .where(
                RolePermissionDefault.role == "MODERATOR",
                RolePermissionDefault.is_granted_by_default.is_(True),
                Permission.is_active.is_(True),
            )
        ).all()
        return {
            "venue_id": venue_id,
            "role": "MODERATOR",
            "permissions": list(codes),
            "position": None,
            "position_flags": {"can_make_reports": True, "can_edit_schedule": True},
        }

    # ---- venue membership ----
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        return {
            "venue_id": venue_id,
            "role": None,
            "permissions": [],
            "position": None,
            "position_flags": {"can_make_reports": False, "can_edit_schedule": False},
        }

    defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
    if not defaults_role:
        codes = []
    else:
        codes = db.scalars(
            select(RolePermissionDefault.permission_code)
            .join(Permission, Permission.code == RolePermissionDefault.permission_code)
            .where(
                RolePermissionDefault.role == defaults_role,
                RolePermissionDefault.is_granted_by_default.is_(True),
                Permission.is_active.is_(True),
            )
        ).all()

    # ---- position flags (MVP) ----
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()

    position_obj = None
    flags = {"can_make_reports": False, "can_edit_schedule": False, "can_view_adjustments": False, "can_manage_adjustments": False}
    if pos is not None:
        position_obj = {
            "id": pos.id,
            "title": pos.title,
            "rate": pos.rate,
            "percent": pos.percent,
            "can_make_reports": bool(pos.can_make_reports),
            "can_view_reports": bool(pos.can_view_reports or pos.can_make_reports),
            "can_view_revenue": bool(pos.can_view_revenue or pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
            "can_view_adjustments": bool(getattr(pos, "can_view_adjustments", False)),
            "can_manage_adjustments": bool(getattr(pos, "can_manage_adjustments", False)),
            "is_active": bool(pos.is_active),
        }
        flags = {
            "can_make_reports": bool(pos.can_make_reports),
            "can_view_reports": bool(pos.can_view_reports or pos.can_make_reports),
            "can_view_revenue": bool(pos.can_view_revenue or pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
            "can_view_adjustments": bool(getattr(pos, "can_view_adjustments", False)),
            "can_manage_adjustments": bool(getattr(pos, "can_manage_adjustments", False)),
        }

    return {
        "venue_id": venue_id,
        "role": vm.venue_role,
        "permissions": list(codes),
        "position": position_obj,
        "position_flags": flags,
    }
