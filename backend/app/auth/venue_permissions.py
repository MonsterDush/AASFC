from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permission_codes import parse_permission_codes
from app.core.permission_policy import (
    expand_permission_codes,
    get_default_permission_codes_for_role,
    normalize_permission_code,
)
from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.models import Permission, RolePermissionDefault, User, Venue, VenueMember, VenuePosition
from app.services.billing.access import BILLING_ACCESS_FULL, get_user_billing_access


def _raise_billing_forbidden(access: dict) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=access.get("billing_restricted_reason") or "Доступ к заведению ограничен из-за статуса подписки",
    )


def require_venue_permission(
    db: Session,
    *,
    venue_id: int,
    user: User,
    permission_code: str,
) -> None:
    """Raises 403 if user doesn't have given permission for the venue.

    Checks order:
    1) permission / role access
    2) billing-gate for the venue
    """

    requested_code = normalize_permission_code(permission_code)
    if not requested_code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    # system roles
    if user.system_role == "SUPER_ADMIN":
        return

    def _has_default(role: str) -> bool:
        role_defaults = get_default_permission_codes_for_role(role)
        if requested_code in role_defaults:
            return True
        return bool(
            db.execute(
                select(RolePermissionDefault)
                .join(Permission, Permission.code == RolePermissionDefault.permission_code)
                .where(
                    RolePermissionDefault.role == role,
                    RolePermissionDefault.permission_code == requested_code,
                    RolePermissionDefault.is_granted_by_default.is_(True),
                    Permission.is_active.is_(True),
                )
            ).scalar_one_or_none()
        )

    if user.system_role == "MODERATOR":
        if _has_default("MODERATOR"):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a venue member")

    venue_is_archived = bool(db.execute(select(Venue.is_archived).where(Venue.id == venue_id)).scalar_one_or_none())

    role_upper = str(vm.venue_role or "").upper()

    if venue_is_archived and role_upper != "OWNER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Заведение сейчас не активно")

    if role_upper == "OWNER":
        access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=role_upper)
        if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
            _raise_billing_forbidden(access)
        return

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()

    raw_perm = getattr(pos, "permission_codes", None) if pos is not None else None
    pos_codes = expand_permission_codes(parse_permission_codes(raw_perm)) if pos is not None else set()
    allowed = requested_code in pos_codes

    if not allowed:
        defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
        if not defaults_role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        allowed = _has_default(defaults_role)

    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=role_upper)
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        _raise_billing_forbidden(access)


def has_venue_permission(
    db: Session,
    *,
    venue_id: int,
    user: User,
    permission_code: str,
) -> bool:
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code=permission_code)
        return True
    except HTTPException:
        return False
