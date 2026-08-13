from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.models.venue_invite import VenueInvite
from app.services.invites import accept_invite_by_token, build_public_invite_payload

router = APIRouter(prefix="/public/invites", tags=["public-invites"])


@router.get("/{token}")
def get_public_invite(token: str, db: Session = Depends(get_db)):
    inv = (
        db.query(VenueInvite)
        .options(joinedload(VenueInvite.venue))
        .filter(VenueInvite.invite_token == token)
        .one_or_none()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return build_public_invite_payload(inv)


@router.post("/{token}/accept")
def accept_public_invite(token: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        inv = accept_invite_by_token(db, token=token, user=user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if detail == "Invite not found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    inv = (
        db.query(VenueInvite)
        .options(joinedload(VenueInvite.venue))
        .filter(VenueInvite.id == inv.id)
        .one()
    )
    return {"ok": True, "invite": build_public_invite_payload(inv), "venue_id": inv.venue_id}
