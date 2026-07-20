from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.venue_permissions import require_venue_permission
from app.models.user import User
from app.models.venue_member import VenueMember
from app.services.billing import BILLING_ACCESS_FULL, get_user_billing_access


def is_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> bool:
    if user.system_role == "SUPER_ADMIN":
        return True

    membership = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if not membership or str(membership.venue_role or "").upper() != "OWNER":
        return False

    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role="OWNER")
    return access.get("billing_access_mode") == BILLING_ACCESS_FULL


def require_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")
    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role="OWNER")
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        raise HTTPException(
            status_code=403,
            detail=access.get("billing_restricted_reason")
            or "Доступ к заведению ограничен из-за статуса подписки",
        )


def is_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> bool:
    if user.system_role in ("SUPER_ADMIN", "MODERATOR"):
        return True
    membership = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if not membership:
        return False
    access = get_user_billing_access(
        db,
        venue_id=venue_id,
        user=user,
        membership_role=str(membership.venue_role or ""),
    )
    return access.get("billing_access_mode") == BILLING_ACCESS_FULL


def require_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> None:
    if user.system_role in ("SUPER_ADMIN", "MODERATOR"):
        return
    membership = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Forbidden")
    access = get_user_billing_access(
        db,
        venue_id=venue_id,
        user=user,
        membership_role=str(membership.venue_role or ""),
    )
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        raise HTTPException(
            status_code=403,
            detail=access.get("billing_restricted_reason")
            or "Доступ к заведению ограничен из-за статуса подписки",
        )


def is_report_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    for code in ("SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"):
        try:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
            return True
        except HTTPException:
            pass
    return False


def require_report_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not is_report_viewer(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def has_revenue_view_access(db: Session, *, venue_id: int, user: User) -> bool:
    if is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW")
        return True
    except HTTPException:
        return False


def require_revenue_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not has_revenue_view_access(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


# Compatibility aliases keep the existing private helper names stable while routes
# are migrated out of app.routers.venues feature by feature.
_is_owner_or_super_admin = is_owner_or_super_admin
_require_owner_or_super_admin = require_owner_or_super_admin
_is_active_member_or_admin = is_active_member_or_admin
_require_active_member_or_admin = require_active_member_or_admin
_is_report_viewer = is_report_viewer
_require_report_viewer = require_report_viewer
_has_revenue_view_access = has_revenue_view_access
_require_revenue_viewer = require_revenue_viewer
