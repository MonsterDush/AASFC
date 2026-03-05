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
    # preferred keys
    raw = preset.get("permission_codes")
    if raw is None:
        raw = preset.get("permissions")
    return _parse_codes_raw(raw)


def _legacy_codes_from_flags(preset: dict) -> list[str]:
    codes: list[str] = []
    if bool(preset.get("can_make_reports")):
        codes += ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_CLOSE"]
    elif bool(preset.get("can_view_reports")):
        codes += ["SHIFT_REPORT_VIEW"]

    if bool(preset.get("can_edit_schedule")):
        codes += ["SHIFTS_VIEW", "SHIFTS_MANAGE"]

    if bool(preset.get("can_view_adjustments")):
        codes += ["ADJUSTMENTS_VIEW"]
    if bool(preset.get("can_manage_adjustments")):
        codes += ["ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"]
    if bool(preset.get("can_resolve_disputes")):
        codes += ["DISPUTES_RESOLVE"]

    # unique
    out = []
    seen = set()
    for c in codes:
        v = _norm_code(c)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _derive_flags_from_codes(codes: list[str]) -> dict[str, bool]:
    s = {_norm_code(c) for c in (codes or [])}
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
            # permission_codes are the source of truth. If preset doesn't contain them, fall back to legacy flags.
            codes = _extract_codes_from_preset(preset)
            if not codes:
                codes = _legacy_codes_from_flags(preset)

            flags = _derive_flags_from_codes(codes)

            data = {
                "title": str(preset.get("title")).strip(),
                "rate": int(preset.get("rate") or 0),
                "percent": int(preset.get("percent") or 0),
                "permission_codes": json.dumps(codes or []),
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
