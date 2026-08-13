from __future__ import annotations

from datetime import datetime, timezone

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tg import normalize_tg_username
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.models.pay_profile import PayProfile
from app.models.pay_profile_assignment import PayProfileAssignment


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
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return _parse_codes_raw(data)
        except Exception:
            pass
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
    return []


def _extract_codes_from_preset(preset: dict) -> list[str]:
    raw = preset.get("permission_codes")
    return _parse_codes_raw(raw)


def _sync_default_pay_profile_assignment(db: Session, *, venue_id: int, user_id: int, pay_profile_id: int | None) -> None:
    if pay_profile_id is None:
        return
    profile = db.execute(
        select(PayProfile).where(
            PayProfile.id == int(pay_profile_id),
            PayProfile.venue_id == int(venue_id),
        )
    ).scalar_one_or_none()
    if profile is None:
        return

    rows = db.execute(
        select(PayProfileAssignment).where(
            PayProfileAssignment.venue_id == int(venue_id),
            PayProfileAssignment.member_user_id == int(user_id),
        )
    ).scalars().all()

    now_dt = datetime.utcnow()
    active_same = None
    for row in rows:
        if int(row.pay_profile_id) == int(profile.id):
            active_same = row
            row.is_active = True
            row.start_date = None
            row.end_date = None
            row.updated_at = now_dt
        else:
            row.is_active = False
            row.updated_at = now_dt

    if active_same is None:
        db.add(
            PayProfileAssignment(
                venue_id=int(venue_id),
                pay_profile_id=int(profile.id),
                member_user_id=int(user_id),
                start_date=None,
                end_date=None,
                is_active=True,
                updated_at=now_dt,
            )
        )


def normalize_phone_e164(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) < 11 or len(digits) > 15:
        return None
    return "+" + digits


def build_invite_link(token: str) -> str:
    return f"/invite-accept.html?token={token}"


def _ensure_unique_token(db: Session) -> str:
    for _ in range(10):
        token = uuid.uuid4().hex
        exists = db.query(VenueInvite.id).filter(VenueInvite.invite_token == token).first()
        if not exists:
            return token
    raise RuntimeError("Failed to generate unique invite token")


def _apply_default_position(db: Session, *, inv: VenueInvite, user_id: int) -> None:
    preset = getattr(inv, "default_position_json", None)
    if not isinstance(preset, dict) or not preset.get("title"):
        return

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

    pay_profile_id_raw = preset.get("pay_profile_id")
    try:
        pay_profile_id = int(pay_profile_id_raw) if pay_profile_id_raw not in (None, "", 0, "0") else None
    except Exception:
        pay_profile_id = None
    _sync_default_pay_profile_assignment(db, venue_id=int(inv.venue_id), user_id=int(user_id), pay_profile_id=pay_profile_id)


def _accept_invite_record(db: Session, *, inv: VenueInvite, user_id: int, accepted_via: str | None = None) -> None:
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

    _apply_default_position(db, inv=inv, user_id=user_id)

    inv.accepted_user_id = user_id
    inv.accepted_at = datetime.now(timezone.utc)
    inv.accepted_via = accepted_via
    inv.is_active = False


def create_venue_invite(
    db: Session,
    *,
    venue_id: int,
    venue_role: str,
    invite_channel: str,
    tg_username: str | None = None,
    phone_e164: str | None = None,
    contact_label: str | None = None,
    created_by_user_id: int | None = None,
    expires_at=None,
) -> VenueInvite:
    channel = str(invite_channel or "").strip().upper()
    if channel not in ("TELEGRAM", "PHONE"):
        raise ValueError("Bad invite_channel")

    username = normalize_tg_username(tg_username) if tg_username else None
    phone = normalize_phone_e164(phone_e164)
    if channel == "TELEGRAM" and not username:
        raise ValueError("Telegram username is required")
    if channel == "PHONE" and not phone:
        raise ValueError("Phone is required")

    q = db.query(VenueInvite).filter(
        VenueInvite.venue_id == venue_id,
        VenueInvite.venue_role == venue_role,
        VenueInvite.accepted_user_id.is_(None),
    )
    if channel == "TELEGRAM":
        q = q.filter(VenueInvite.invite_channel == "TELEGRAM", VenueInvite.invited_tg_username == username)
    else:
        q = q.filter(VenueInvite.invite_channel == "PHONE", VenueInvite.invited_phone_e164 == phone)
    inv = q.one_or_none()

    if inv is None:
        inv = VenueInvite(
            venue_id=venue_id,
            invited_tg_username=username,
            invited_phone_e164=phone,
            invited_contact_label=(str(contact_label or "").strip() or None),
            invite_channel=channel,
            invite_token=_ensure_unique_token(db),
            venue_role=venue_role,
            is_active=True,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )
        db.add(inv)
    else:
        inv.is_active = True
        inv.revoked_at = None
        inv.expires_at = expires_at
        inv.created_by_user_id = created_by_user_id
        inv.invited_tg_username = username
        inv.invited_phone_e164 = phone
        inv.invited_contact_label = (str(contact_label or "").strip() or None)
        inv.invite_channel = channel
        if not inv.invite_token:
            inv.invite_token = _ensure_unique_token(db)

    db.flush()
    return inv




def accept_phone_invites_for_user(db: Session, *, user_id: int, phone_e164: str | None) -> int:
    phone = normalize_phone_e164(phone_e164)
    if not phone:
        return 0

    invites = (
        db.query(VenueInvite)
        .filter(
            VenueInvite.invite_channel == "PHONE",
            VenueInvite.invited_phone_e164 == phone,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .all()
    )

    accepted = 0
    for inv in invites:
        _accept_invite_record(db, inv=inv, user_id=user_id, accepted_via="PHONE_AUTO")
        accepted += 1

    if accepted:
        db.commit()

    return accepted

def accept_invites_for_user(db: Session, *, user_id: int, tg_username: str) -> int:
    if not tg_username:
        return 0

    username = normalize_tg_username(tg_username)
    invites = (
        db.query(VenueInvite)
        .filter(
            VenueInvite.invite_channel == "TELEGRAM",
            VenueInvite.invited_tg_username == username,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .all()
    )

    accepted = 0
    for inv in invites:
        _accept_invite_record(db, inv=inv, user_id=user_id, accepted_via="TELEGRAM_AUTO")
        accepted += 1

    if accepted:
        db.commit()

    return accepted


def get_invite_by_token(db: Session, token: str) -> VenueInvite | None:
    return db.query(VenueInvite).filter(VenueInvite.invite_token == str(token or "").strip()).one_or_none()


def get_invite_status(inv: VenueInvite) -> str:
    now = datetime.now(timezone.utc)
    if inv.accepted_user_id is not None:
        return "ACCEPTED"
    if inv.revoked_at is not None or not inv.is_active:
        return "REVOKED"
    expires_at = getattr(inv, "expires_at", None)
    if expires_at is not None:
        dt = expires_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < now:
            return "EXPIRED"
    return "PENDING"


def _get_verified_user_phone(db: Session, *, user_id: int) -> str | None:
    return db.execute(
        select(AuthIdentity.phone_e164).where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == "PHONE",
            AuthIdentity.is_verified.is_(True),
        )
    ).scalar_one_or_none()


def accept_invite_by_token(db: Session, *, token: str, user: User) -> VenueInvite:
    inv = get_invite_by_token(db, token)
    if inv is None:
        raise ValueError("Invite not found")

    status = get_invite_status(inv)
    if status == "ACCEPTED":
        if inv.accepted_user_id == user.id:
            return inv
        raise ValueError("Invite already accepted")
    if status == "REVOKED":
        raise ValueError("Invite revoked")
    if status == "EXPIRED":
        raise ValueError("Invite expired")

    if inv.invite_channel == "TELEGRAM":
        current_username = normalize_tg_username(getattr(user, "tg_username", None) or "")
        if not current_username or current_username != normalize_tg_username(inv.invited_tg_username or ""):
            raise PermissionError("This invite is bound to another Telegram account")
    elif inv.invite_channel == "PHONE":
        current_phone = normalize_phone_e164(_get_verified_user_phone(db, user_id=user.id))
        invited_phone = normalize_phone_e164(inv.invited_phone_e164)
        if not current_phone:
            raise PermissionError("This invite requires a verified phone number on your account")
        if not invited_phone or current_phone != invited_phone:
            raise PermissionError("This invite is bound to another phone number")

    _accept_invite_record(db, inv=inv, user_id=user.id, accepted_via=inv.invite_channel)
    db.commit()
    db.refresh(inv)
    return inv


def build_public_invite_payload(inv: VenueInvite) -> dict:
    venue: Venue | None = getattr(inv, "venue", None)
    return {
        "id": inv.id,
        "venue_id": inv.venue_id,
        "venue_name": venue.name if venue else None,
        "invite_channel": inv.invite_channel,
        "tg_username": inv.invited_tg_username,
        "phone": inv.invited_phone_e164,
        "contact_label": inv.invited_contact_label,
        "venue_role": inv.venue_role,
        "status": get_invite_status(inv),
        "is_active": bool(inv.is_active),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
        "accepted_user_id": inv.accepted_user_id,
        "accepted_via": inv.accepted_via,
        "invite_token": inv.invite_token,
        "invite_link": build_invite_link(inv.invite_token),
        "default_position": inv.default_position_json,
    }
