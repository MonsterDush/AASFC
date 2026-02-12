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


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_user_id": user.tg_user_id,
        "tg_username": user.tg_username,
        "system_role": user.system_role,
    }


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
        select(User.id, User.tg_user_id, User.tg_username, VenueMember.venue_role)
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
    flags = {"can_make_reports": False, "can_edit_schedule": False}
    if pos is not None:
        position_obj = {
            "id": pos.id,
            "title": pos.title,
            "rate": pos.rate,
            "percent": pos.percent,
            "can_make_reports": bool(pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
            "is_active": bool(pos.is_active),
        }
        flags = {
            "can_make_reports": bool(pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
        }

    return {
        "venue_id": venue_id,
        "role": vm.venue_role,
        "permissions": list(codes),
        "position": position_obj,
        "position_flags": flags,
    }
