from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status, UploadFile, File
from sqlalchemy import select, delete, update, func, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.routers.venue_access import (
    _has_revenue_view_access,
    _is_active_member_or_admin,
    _is_owner_or_super_admin,
    _is_report_viewer,
    _require_active_member_or_admin,
    _require_owner_or_super_admin,
    _require_report_viewer,
    _require_revenue_viewer,
)
from app.models.user import User
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.models.shift_assignment import ShiftAssignment
from app.auth.venue_permissions import require_venue_permission, has_venue_permission


def _can_manage_staff(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    return has_venue_permission(db, venue_id=venue_id, user=user, permission_code="STAFF_MANAGE")


def _require_staff_manage_or_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _can_manage_staff(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")




def _is_shift_comments_allowed(db: Session, *, venue_id: int, shift_id: int, user: User) -> bool:
    # Admins
    if user.system_role in ("SUPER_ADMIN", "MODERATOR", "STAFF", "OWNER"):
        return True

    # Venue members (owner/staff)
    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if m is not None:
        return True

    # Position-based staff (common case in current MVP)
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if pos is not None:
        return True

    # Fallback: assigned to this shift
    sa = db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.member_user_id == user.id,
        )
    ).scalar_one_or_none()
    return bool(sa)


def _require_shift_comments_allowed(db: Session, *, venue_id: int, shift_id: int, user: User) -> None:
    if not _is_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_schedule_editor(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="SHIFTS_MANAGE")
        return True
    except HTTPException:
        return False

def _require_schedule_editor(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_schedule_editor(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_report_maker(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    # Permission-based (preferred)
    for code in ("SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"):
        try:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
            return True
        except HTTPException:
            pass

    return False


def _require_report_maker(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_report_maker(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="ADJUSTMENTS_VIEW")
        return True
    except HTTPException:
        return False

def _require_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_viewer(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_adjustments_manager(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="ADJUSTMENTS_MANAGE")
        return True
    except HTTPException:
        return False

def _require_adjustments_manager(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_manager(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _has_adjustments_manage_access(db: Session, *, venue_id: int, user: User) -> bool:
    return _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_adjustments_manager(db, venue_id=venue_id, user=user)


def _require_dispute_resolver(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DISPUTES_RESOLVE")
        return
    except HTTPException:
        raise HTTPException(status_code=403, detail="Forbidden")

def _has_revenue_export_access(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_EXPORT")
        return True
    except HTTPException:
        return False


def _require_revenue_exporter(db: Session, *, venue_id: int, user: User) -> None:
    if not _has_revenue_export_access(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")

