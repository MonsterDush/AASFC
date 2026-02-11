from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember


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

        inv.accepted_user_id = user_id
        inv.accepted_at = datetime.now(timezone.utc)
        inv.is_active = False
        accepted += 1

    if accepted:
        db.commit()

    return accepted
