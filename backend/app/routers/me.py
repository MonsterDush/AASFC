from __future__ import annotations

from fastapi import APIRouter, Depends
from app.auth.deps import get_current_user
from app.models import User

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.models import VenueMember, Permission, RolePermissionDefault


router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_user_id": user.tg_user_id,
        "tg_username": user.tg_username,
        "system_role": user.system_role,
    }

@router.get("/me/venues/{venue_id}/permissions")
def my_venue_permissions(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 1) Супер-админ: все активные permissions
    if user.system_role == "SUPER_ADMIN":
        codes = db.scalars(select(Permission.code).where(Permission.is_active.is_(True))).all()
        return {"venue_id": venue_id, "role": "SUPER_ADMIN", "permissions": list(codes)}

    # 2) Модератор: права из матрицы для MODERATOR
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
        return {"venue_id": venue_id, "role": "MODERATOR", "permissions": list(codes)}

    # 3) Обычный юзер: ищем membership
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        # можно 403, можно 404 — я бы делал 403
        return {"venue_id": venue_id, "role": None, "permissions": []}

    defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
    if not defaults_role:
        return {"venue_id": venue_id, "role": vm.venue_role, "permissions": []}

    codes = db.scalars(
        select(RolePermissionDefault.permission_code)
        .join(Permission, Permission.code == RolePermissionDefault.permission_code)
        .where(
            RolePermissionDefault.role == defaults_role,
            RolePermissionDefault.is_granted_by_default.is_(True),
            Permission.is_active.is_(True),
        )
    ).all()

    return {"venue_id": venue_id, "role": vm.venue_role, "permissions": list(codes)}
