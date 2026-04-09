from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tg import normalize_tg_username
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.services.invites import create_venue_invite, normalize_phone_e164
from app.services.billing.manager import get_or_create_billing_state
from app.services.setup import get_or_create_setup_state


def _find_verified_phone_user(db: Session, phone_e164: str) -> User | None:
    ident = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "PHONE",
            AuthIdentity.phone_e164 == phone_e164,
            AuthIdentity.is_verified.is_(True),
        )
    ).scalar_one_or_none()
    if ident is None:
        return None
    return db.execute(select(User).where(User.id == ident.user_id)).scalar_one_or_none()


# создаёт заведение и назначает/приглашает владельца(ев)
def create_venue(
    db: Session,
    *,
    name: str,
    owner_usernames: list[str] | None = None,
    owner_user_id: int | None = None,
    owner_tg_username: str | None = None,
    owner_phone: str | None = None,
    created_by_user_id: int | None = None,
):
    venue = Venue(name=name)
    db.add(venue)
    db.flush()  # чтобы venue.id появился

    if owner_user_id:
        user = db.query(User).filter(User.id == owner_user_id).one_or_none()
        if user is None:
            raise ValueError("Owner user not found")
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

    elif owner_phone:
        phone = normalize_phone_e164(owner_phone)
        if not phone:
            raise ValueError("Bad owner_phone")
        user = _find_verified_phone_user(db, phone)
        if user is not None:
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
            create_venue_invite(
                db,
                venue_id=venue.id,
                venue_role="OWNER",
                invite_channel="PHONE",
                phone_e164=phone,
                created_by_user_id=created_by_user_id,
            )

    elif owner_tg_username:
        username = normalize_tg_username(owner_tg_username)
        if not username:
            raise ValueError("Bad owner_tg_username")
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
            create_venue_invite(
                db,
                venue_id=venue.id,
                venue_role="OWNER",
                invite_channel="TELEGRAM",
                tg_username=username,
                created_by_user_id=created_by_user_id,
            )

    else:
        owners = owner_usernames or []
        owners_norm: list[str] = []
        for u in owners:
            nu = normalize_tg_username(u)
            if nu:
                owners_norm.append(nu)

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
                create_venue_invite(
                    db,
                    venue_id=venue.id,
                    venue_role="OWNER",
                    invite_channel="TELEGRAM",
                    tg_username=username,
                    created_by_user_id=created_by_user_id,
                )

    get_or_create_billing_state(db, venue_id=venue.id)
    get_or_create_setup_state(db, venue_id=venue.id)

    db.commit()
    db.refresh(venue)
    return venue
