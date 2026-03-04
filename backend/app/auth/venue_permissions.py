from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.models import Permission, RolePermissionDefault, User, VenueMember, VenuePosition


def require_venue_permission(
    db: Session,
    *,
    venue_id: int,
    user: User,
    permission_code: str,
) -> None:
    """Raises 403 if user doesn't have given permission for the venue.

    Rules:
    - SUPER_ADMIN: always allow
    - MODERATOR: allow if permission is granted by default for MODERATOR
    - Venue members: allow if granted by default for mapped role (OWNER/MANAGER/STAFF)
    """

    # system roles
    if user.system_role == "SUPER_ADMIN":
        return

    def _has_default(role: str) -> bool:
        return bool(
            db.execute(
                select(RolePermissionDefault)
                .join(Permission, Permission.code == RolePermissionDefault.permission_code)
                .where(
                    RolePermissionDefault.role == role,
                    RolePermissionDefault.permission_code == permission_code,
                    RolePermissionDefault.is_granted_by_default.is_(True),
                    Permission.is_active.is_(True),
                )
            ).scalar_one_or_none()
        )

    if user.system_role == "MODERATOR":
        if _has_default("MODERATOR"):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    # venue membership
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a venue member")

    # ---- per-position permissions (fine-grained) ----
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()

    def _parse_pos_codes(raw: str | None) -> set[str]:
        if not raw:
            return set()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return {str(x or "").strip().upper() for x in data if str(x or "").strip()}
        except Exception:
            pass
        return set()

    pos_codes = _parse_pos_codes(getattr(pos, "permission_codes", None)) if pos is not None else set()
    if permission_code.strip().upper() in pos_codes:
        return

    # ---- legacy position flags mapping (backwards compatibility) ----
    if pos is not None:
        pc = permission_code.strip().upper()
        if pc in {"SHIFT_REPORT_VIEW"} and bool(pos.can_view_reports or pos.can_make_reports):
            return
        if pc in {"SHIFT_REPORT_EDIT", "SHIFT_REPORT_CLOSE"} and bool(pos.can_make_reports):
            return
        if pc in {"SHIFTS_VIEW", "SHIFTS_MANAGE"} and bool(pos.can_edit_schedule):
            return
        if pc == "ADJUSTMENTS_VIEW" and bool(getattr(pos, "can_view_adjustments", False) or getattr(pos, "can_manage_adjustments", False)):
            return
        if pc == "ADJUSTMENTS_MANAGE" and bool(getattr(pos, "can_manage_adjustments", False)):
            return
        if pc == "DISPUTES_RESOLVE" and bool(getattr(pos, "can_resolve_disputes", False)):
            return

    defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
    if not defaults_role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    if _has_default(defaults_role):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
