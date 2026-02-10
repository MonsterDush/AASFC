from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models.user import User
from app.services.venues import create_venue

router = APIRouter(prefix="/venues", tags=["venues"])


class VenueCreateIn(BaseModel):
    name: str


@router.post("")
def create_venue_admin_only(
    payload: VenueCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    """
    Создание заведения — только SUPER_ADMIN.
    При создании можно автоматически добавить самого SUPER_ADMIN как OWNER в venue_members.
    """
    venue = create_venue(db, name=payload.name, owner_user_id=user.id)
    return {"id": venue.id, "name": venue.name}
