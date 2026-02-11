from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.venue import Venue
from app.core.tg import normalize_tg_username
from app.models.user import User
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite

#создает заведение с владельцем (если найден по имени) или приглашает по имени (если не найден)
def create_venue(db, *, name: str, owner_usernames: list[str] | None = None):
    venue = Venue(name=name)
    db.add(venue)
    db.flush()  # чтобы venue.id появился

    owners = owner_usernames or []
    owners_norm: list[str] = []
    for u in owners:
        nu = normalize_tg_username(u)
        if nu:
            owners_norm.append(nu)

    # уникализируем, сохраняя порядок
    owners_norm = list(dict.fromkeys(owners_norm))

    for username in owners_norm:
        user = db.query(User).filter(User.tg_username == username).one_or_none()

        if user:
            mem = (
                db.query(VenueMember)
                .filter(VenueMember.venue_id == venue.id, VenueMember.user_id == user.id)
                .one_or_none()
            )
            if mem:
                mem.venue_role = "OWNER"
                mem.is_active = True
            else:
                db.add(VenueMember(venue_id=venue.id, user_id=user.id, venue_role="OWNER", is_active=True))
        else:
            inv = (
                db.query(VenueInvite)
                .filter(
                    VenueInvite.venue_id == venue.id,
                    VenueInvite.invited_tg_username == username,
                    VenueInvite.venue_role == "OWNER",
                )
                .one_or_none()
            )
            if inv:
                inv.is_active = True
            else:
                db.add(VenueInvite(venue_id=venue.id, invited_tg_username=username, venue_role="OWNER", is_active=True))

    db.commit()
    db.refresh(venue)
    return venue

