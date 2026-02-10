from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.venue import Venue
from app.models.venue_member import VenueMember


def create_venue(db: Session, *, name: str, owner_user_id: int | None = None) -> Venue:
    """
    Создаёт заведение.
    Если передан owner_user_id — добавляет владельца как активного OWNER участника.
    """
    venue = Venue(name=name)
    db.add(venue)
    db.commit()
    db.refresh(venue)

    if owner_user_id is not None:
        member = VenueMember(
            venue_id=venue.id,
            user_id=owner_user_id,
            venue_role="OWNER",
            is_active=True,
        )
        db.add(member)
        db.commit()

    return venue
