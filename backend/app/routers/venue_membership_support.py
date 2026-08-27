from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.tg import normalize_tg_username
from app.models.user import User
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite
from app.models.auth_identity import AuthIdentity
from app.services.invites import build_invite_link, normalize_phone_e164
from app.services.venue_member_names import base_member_display_name, normalize_owner_note


def _build_user_auth_snapshot_map(db: Session, user_ids: list[int]) -> dict[int, dict]:
    ids = [int(x) for x in user_ids if x]
    if not ids:
        return {}
    rows = db.execute(
        select(
            AuthIdentity.user_id,
            AuthIdentity.provider,
            AuthIdentity.phone_e164,
        ).where(
            AuthIdentity.user_id.in_(ids),
            AuthIdentity.is_verified.is_(True),
        )
    ).all()
    out: dict[int, dict] = {uid: {"phone": None, "auth_methods": []} for uid in ids}
    for r in rows:
        item = out.setdefault(int(r.user_id), {"phone": None, "auth_methods": []})
        provider = str(r.provider or "").strip().lower()
        if provider and provider not in item["auth_methods"]:
            item["auth_methods"].append(provider)
        if provider == "phone" and r.phone_e164 and not item["phone"]:
            item["phone"] = r.phone_e164
    return out


def _display_name(
    *,
    short_name: str | None = None,
    full_name: str | None = None,
    tg_username: str | None = None,
    phone: str | None = None,
    user_id: int | None = None,
) -> str:
    return base_member_display_name(
        short_name=short_name,
        full_name=full_name,
        tg_username=tg_username,
        phone=phone,
        user_id=user_id,
    )


def _serialize_user_brief(row, auth_map: dict[int, dict], *, owner_note: str | None = None) -> dict:
    snap = auth_map.get(int(row.id), {"phone": None, "auth_methods": []})
    phone = snap.get("phone")
    methods = list(snap.get("auth_methods") or [])
    private_note = normalize_owner_note(owner_note)
    return {
        "user_id": row.id,
        "tg_user_id": getattr(row, "tg_user_id", None),
        "tg_username": getattr(row, "tg_username", None),
        "full_name": getattr(row, "full_name", None),
        "short_name": getattr(row, "short_name", None),
        "phone": phone,
        "auth_methods": methods,
        "has_phone_auth": "phone" in methods,
        "has_telegram_auth": "telegram" in methods,
        "owner_note": private_note,
        "display_name": private_note
        or _display_name(
            short_name=getattr(row, "short_name", None),
            full_name=getattr(row, "full_name", None),
            tg_username=getattr(row, "tg_username", None),
            phone=phone,
            user_id=getattr(row, "id", None),
        ),
    }


def _build_pending_invite_target_map(db: Session, invites) -> dict[int, dict]:
    tg_usernames = []
    phones = []
    for inv in invites or []:
        channel = str(getattr(inv, "invite_channel", "") or "").strip().upper()
        if channel == "TELEGRAM":
            u = normalize_tg_username(getattr(inv, "invited_tg_username", None) or "")
            if u:
                tg_usernames.append(u)
        elif channel == "PHONE":
            p = normalize_phone_e164(getattr(inv, "invited_phone_e164", None))
            if p:
                phones.append(p)

    tg_rows = []
    if tg_usernames:
        tg_rows = db.execute(
            select(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name).where(
                User.tg_username.in_(list(dict.fromkeys(tg_usernames)))
            )
        ).all()

    phone_rows = []
    if phones:
        phone_rows = db.execute(
            select(
                AuthIdentity.phone_e164,
                User.id,
                User.tg_user_id,
                User.tg_username,
                User.full_name,
                User.short_name,
            )
            .join(User, User.id == AuthIdentity.user_id)
            .where(
                AuthIdentity.provider == "PHONE",
                AuthIdentity.is_verified.is_(True),
                AuthIdentity.phone_e164.in_(list(dict.fromkeys(phones))),
            )
        ).all()

    user_ids = [int(r.id) for r in tg_rows] + [int(r.id) for r in phone_rows]
    auth_map = _build_user_auth_snapshot_map(db, user_ids)

    tg_lookup = {normalize_tg_username(r.tg_username or ""): _serialize_user_brief(r, auth_map) for r in tg_rows}
    phone_lookup = {normalize_phone_e164(r.phone_e164): _serialize_user_brief(r, auth_map) for r in phone_rows}

    out: dict[int, dict] = {}
    for inv in invites or []:
        channel = str(getattr(inv, "invite_channel", "") or "").strip().upper()
        linked = None
        if channel == "TELEGRAM":
            linked = tg_lookup.get(normalize_tg_username(getattr(inv, "invited_tg_username", None) or ""))
        elif channel == "PHONE":
            linked = phone_lookup.get(normalize_phone_e164(getattr(inv, "invited_phone_e164", None)))
        out[int(inv.id)] = {
            "target_status": "LINKED_USER" if linked else "WAITING_SIGNUP",
            "target_user": linked,
        }
    return out


def _build_owner_summary_by_venue(db: Session, venue_ids: list[int]) -> dict[int, dict]:
    ids = [int(x) for x in venue_ids if x]
    if not ids:
        return {}

    owner_rows = db.execute(
        select(
            VenueMember.venue_id,
            User.id,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
        )
        .join(User, User.id == VenueMember.user_id)
        .where(
            VenueMember.venue_id.in_(ids),
            VenueMember.venue_role == "OWNER",
            VenueMember.is_active.is_(True),
        )
    ).all()
    owner_auth_map = _build_user_auth_snapshot_map(db, [int(r.id) for r in owner_rows])

    pending_rows = db.execute(
        select(
            VenueInvite.id,
            VenueInvite.venue_id,
            VenueInvite.invite_channel,
            VenueInvite.invited_tg_username,
            VenueInvite.invited_phone_e164,
            VenueInvite.invited_contact_label,
            VenueInvite.invite_token,
            VenueInvite.created_at,
            VenueInvite.expires_at,
        ).where(
            VenueInvite.venue_id.in_(ids),
            VenueInvite.venue_role == "OWNER",
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
    ).all()
    pending_target_map = _build_pending_invite_target_map(db, pending_rows)

    out = {vid: {"state": "UNASSIGNED", "owners": [], "pending": []} for vid in ids}
    for r in owner_rows:
        item = _serialize_user_brief(r, owner_auth_map)
        out[int(r.venue_id)]["owners"].append(item)
        out[int(r.venue_id)]["state"] = "LINKED"

    for r in pending_rows:
        meta = pending_target_map.get(int(r.id), {"target_status": "WAITING_SIGNUP", "target_user": None})
        out[int(r.venue_id)]["pending"].append(
            {
                "id": r.id,
                "channel": r.invite_channel,
                "tg_username": r.invited_tg_username,
                "phone": r.invited_phone_e164,
                "contact_label": r.invited_contact_label,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "invite_link": build_invite_link(r.invite_token),
                "target_status": meta.get("target_status"),
                "target_user": meta.get("target_user"),
            }
        )
        if out[int(r.venue_id)]["state"] != "LINKED":
            out[int(r.venue_id)]["state"] = "PENDING"

    return out


# ---------- Routes ----------
