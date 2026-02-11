from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.auth.deps import get_current_user  # <-- если у тебя другое имя, см. ниже
from app.core.db import get_db
from app.core.tg import normalize_tg_username

from app.models.user import User
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite
from app.models.venue import Venue

from app.services.venues import create_venue

router = APIRouter(prefix="/venues", tags=["venues"])


# ---------- Schemas ----------

class VenueCreateIn(BaseModel):
    name: str
    owner_usernames: Optional[List[str]] = None  # ["owner1", "@owner2"]


class InviteCreateIn(BaseModel):
    tg_username: str
    venue_role: str = "STAFF"  # "OWNER" | "STAFF"


# ---------- Helpers ----------

def _is_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> bool:
    # SUPER_ADMIN?
    if user.system_role == "SUPER_ADMIN":
        return True

    # OWNER?
    m = (
        db.query(VenueMember)
        .filter(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
        .one_or_none()
    )
    return bool(m and m.venue_role == "OWNER")


def _require_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------- Routes ----------

@router.post("")
def create_venue_admin_only(
    payload: VenueCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    """
    Создание заведения — только SUPER_ADMIN.

    В payload можно передать owner_usernames — для каждого:
    - если пользователь уже есть в users -> создаём venue_members OWNER
    - если нет -> создаём venue_invites OWNER (pending)
    """
    venue = create_venue(
        db,
        name=payload.name,
        owner_usernames=payload.owner_usernames,
        # если твой сервис пока требует owner_user_id — см. примечание ниже
    )
    return {"id": venue.id, "name": venue.name}

@router.get("")
def list_venues_admin_only(
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    rows = db.query(Venue.id, Venue.name).order_by(Venue.id.desc()).all()
    return [{"id": r.id, "name": r.name} for r in rows]

@router.get("/{venue_id}/members")
def get_members(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Members + Pending invites.
    Доступ: SUPER_ADMIN или OWNER этого venue.
    """
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    members = (
        db.query(User.id, User.tg_user_id, User.tg_username, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .filter(VenueMember.venue_id == venue_id, VenueMember.is_active.is_(True))
        .all()
    )

    invites = (
        db.query(VenueInvite.id, VenueInvite.invited_tg_username, VenueInvite.venue_role, VenueInvite.created_at)
        .filter(
            VenueInvite.venue_id == venue_id,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .order_by(VenueInvite.created_at.desc())
        .all()
    )

    return {
        "members": [
            {
                "user_id": r.id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "venue_role": r.venue_role,
            }
            for r in members
        ],
        "pending_invites": [
            {
                "id": r.id,
                "tg_username": r.invited_tg_username,
                "venue_role": r.venue_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in invites
        ],
    }


@router.post("/{venue_id}/invites")
def create_invite(
    venue_id: int,
    payload: InviteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Создать приглашение (или сразу добавить member, если пользователь уже есть).
    Доступ: SUPER_ADMIN или OWNER этого venue.
    """
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    username = normalize_tg_username(payload.tg_username)
    if not username:
        raise HTTPException(status_code=400, detail="Bad tg_username")

    role = payload.venue_role
    if role not in ("OWNER", "STAFF"):
        raise HTTPException(status_code=400, detail="Bad venue_role")

    # Если пользователь уже есть — сразу membership
    existing_user = db.query(User).filter(User.tg_username == username).one_or_none()
    if existing_user:
        mem = (
            db.query(VenueMember)
            .filter(VenueMember.venue_id == venue_id, VenueMember.user_id == existing_user.id)
            .one_or_none()
        )
        if mem:
            mem.venue_role = role
            mem.is_active = True
        else:
            db.add(VenueMember(venue_id=venue_id, user_id=existing_user.id, venue_role=role, is_active=True))
        db.commit()
        return {"ok": True, "mode": "member_added"}

    inv = (
        db.query(VenueInvite)
        .filter(
            VenueInvite.venue_id == venue_id,
            VenueInvite.invited_tg_username == username,
            VenueInvite.venue_role == role,
        )
        .one_or_none()
    )
    if inv:
        inv.is_active = True
    else:
        db.add(VenueInvite(venue_id=venue_id, invited_tg_username=username, venue_role=role, is_active=True))

    db.commit()
    return {"ok": True, "mode": "invited"}


@router.delete("/{venue_id}/invites/{invite_id}")
def cancel_invite(
    venue_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Отменить приглашение.
    Доступ: SUPER_ADMIN или OWNER этого venue.
    """
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    inv = db.query(VenueInvite).filter(VenueInvite.id == invite_id, VenueInvite.venue_id == venue_id).one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")

    inv.is_active = False
    db.commit()
    return {"ok": True}
