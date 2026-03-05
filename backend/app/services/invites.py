from __future__ import annotations

from datetime import datetime, timezone

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition


def _norm_code(x) -> str:
    return str(x or "").strip().upper()


def _parse_codes_raw(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        seen = set()
        for x in raw:
            v = _norm_code(x)
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # try JSON list
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return _parse_codes_raw(data)
        except Exception:
            pass
        # tolerate "['A', 'B']" or "A,B C"
        cleaned = s.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
        parts = re.split(r"[\s,;]+", cleaned)
        out = []
        seen = set()
        for p in parts:
            v = _norm_code(p)
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out
    # unknown type
    return []


def _extract_codes_from_preset(preset: dict) -> list[str]:
    # only source of truth
    raw = preset.get("permission_codes")
    return _parse_codes_raw(raw)


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
                "permission_codes": json.dumps(_extract_codes_from_preset(preset) or []),
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
