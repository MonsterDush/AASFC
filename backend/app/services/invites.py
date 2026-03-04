from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition


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

            data = {
                "title": str(preset.get("title")).strip(),
                "rate": int(preset.get("rate") or 0),
                "percent": int(preset.get("percent") or 0),
                "can_make_reports": bool(preset.get("can_make_reports") or False),
                "can_view_reports": bool(preset.get("can_view_reports") or False),
                "can_view_revenue": bool(preset.get("can_view_revenue") or False),
                "can_edit_schedule": bool(preset.get("can_edit_schedule") or False),
                "can_view_adjustments": bool(preset.get("can_view_adjustments") or False),
                "can_manage_adjustments": bool(preset.get("can_manage_adjustments") or False),
                "can_resolve_disputes": bool(preset.get("can_resolve_disputes") or False),
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
