from __future__ import annotations

import json

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions_registry import PERMISSIONS as PERMISSIONS_REGISTRY
from app.models.permission import Permission
from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition



def _normalize_permission_codes(db: Session, raw) -> list[str]:
    if not raw:
        return []
    arr = raw if isinstance(raw, list) else []
    cleaned: list[str] = []
    for x in arr:
        s = str(x or "").strip().upper()
        if s and s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        return []
    active = set(db.execute(select(Permission.code).where(Permission.code.in_(cleaned), Permission.is_active.is_(True))).scalars().all())
    registry = {p.code.strip().upper() for p in PERMISSIONS_REGISTRY}
    return [c for c in cleaned if c in active or c in registry]


def _derive_legacy_flags_from_permission_codes(codes: list[str]) -> dict[str, bool]:
    s = {str(c or "").strip().upper() for c in (codes or [])}
    s.discard("")
    can_make_reports = bool(s.intersection({"SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"}))
    can_view_reports = bool(s.intersection({"SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"}))
    can_view_revenue = bool(s.intersection({"SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"}))
    can_edit_schedule = bool(s.intersection({"SHIFTS_MANAGE"}))
    can_view_adjustments = bool(s.intersection({"ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"}))
    can_manage_adjustments = bool(s.intersection({"ADJUSTMENTS_MANAGE"}))
    can_resolve_disputes = bool(s.intersection({"DISPUTES_RESOLVE"}))
    return {
        "can_make_reports": can_make_reports,
        "can_view_reports": can_view_reports,
        "can_view_revenue": can_view_revenue,
        "can_edit_schedule": can_edit_schedule,
        "can_view_adjustments": can_view_adjustments,
        "can_manage_adjustments": can_manage_adjustments,
        "can_resolve_disputes": can_resolve_disputes,
    }


def _codes_from_invite_preset(preset: dict, db: Session) -> list[str]:
    # preferred: permission_codes / permissions
    raw_codes = preset.get("permission_codes") or preset.get("permissions")
    codes = _normalize_permission_codes(db, raw_codes)

    if codes:
        return codes

    # legacy fallback: map booleans to codes
    legacy: list[str] = []
    if bool(preset.get("can_make_reports")):
        legacy += ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_CLOSE"]
    elif bool(preset.get("can_view_reports")):
        legacy += ["SHIFT_REPORT_VIEW"]

    if bool(preset.get("can_edit_schedule")):
        legacy += ["SHIFTS_MANAGE"]

    if bool(preset.get("can_manage_adjustments")):
        legacy += ["ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"]
    elif bool(preset.get("can_view_adjustments")):
        legacy += ["ADJUSTMENTS_VIEW"]

    if bool(preset.get("can_resolve_disputes")):
        legacy += ["DISPUTES_RESOLVE"]

    return _normalize_permission_codes(db, legacy)

def accept_invites_for_user(db: Session, *, user_id: int, tg_username: str) -> int:
    if not tg_username:
        return 0

    invites = (
        db.query(VenueInvite)
        .filter(
            VenueInvite.invited_tg_username == tg_username,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .all()
    )

    accepted = 0
    for inv in invites:
        mem = (
            db.query(VenueMember)
            .filter(VenueMember.venue_id == inv.venue_id, VenueMember.user_id == user_id)
            .one_or_none()
        )
        if mem:
            mem.venue_role = inv.venue_role
            mem.is_active = True
        else:
            db.add(
                VenueMember(
                    venue_id=inv.venue_id,
                    user_id=user_id,
                    venue_role=inv.venue_role,
                    is_active=True,
                )
            )

        # Apply preset position (if any) to the newly accepted member.
        # This is a MVP implementation to allow "assign position to invited" before accept.
        preset = getattr(inv, "default_position_json", None)
        if isinstance(preset, dict) and preset.get("title"):
            existing_pos = db.execute(
                select(VenuePosition).where(
                    VenuePosition.venue_id == inv.venue_id,
                    VenuePosition.member_user_id == user_id,
                )
            ).scalar_one_or_none()
            codes = _codes_from_invite_preset(preset, db)
            flags = _derive_legacy_flags_from_permission_codes(codes)
            data = {
                "title": str(preset.get("title")).strip(),
                "rate": int(preset.get("rate") or 0),
                "percent": int(preset.get("percent") or 0),
                "permission_codes": json.dumps(codes),
                **flags,
                "is_active": True,
            }

            if existing_pos is None:
                db.add(
                    VenuePosition(
                        venue_id=inv.venue_id,
                        member_user_id=user_id,
                        **data,
                    )
                )
            else:
                for k, v in data.items():
                    setattr(existing_pos, k, v)

        inv.accepted_user_id = user_id
        inv.accepted_at = datetime.now(timezone.utc)
        inv.is_active = False
        accepted += 1

    if accepted:
        db.commit()

    return accepted
