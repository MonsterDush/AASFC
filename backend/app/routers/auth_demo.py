from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.core.db import get_db
from app.models import User, Venue
from app.services.demo.access import build_demo_banner_payload, get_demo_session_or_none
from app.services.demo.analytics import record_demo_event
from app.services.demo.session import (
    DEMO_PERSONA_OWNER,
    build_demo_session_claims,
    build_demo_start_url,
    get_demo_user_for_venue,
    get_public_demo_venue,
    normalize_demo_persona,
)

from .auth_common import _clear_access_cookie, _write_access_cookie
from .auth_schemas import DemoSwitchPersonaIn


router = APIRouter()


def _build_demo_session_payload(*, venue: Venue, persona: str, session_id: str | None = None) -> dict:
    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    claims = build_demo_session_claims(venue=venue, persona=persona_upper, session_id=session_id)
    return {
        "ok": True,
        "demo_mode": True,
        "demo_persona": persona_upper,
        "demo_venue_id": int(venue.id),
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
        "redirect_url": build_demo_start_url(
            venue_id=int(venue.id),
            persona=persona_upper,
        ),
        "banner": build_demo_banner_payload(),
        "claims": claims,
    }


def _resolve_demo_identity_or_404(db: Session, *, persona: str) -> tuple[Venue, User, str]:
    venue = get_public_demo_venue(db)
    if venue is None:
        raise HTTPException(status_code=404, detail="Публичное DEMO-заведение не настроено")

    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    demo_user = get_demo_user_for_venue(db, venue_id=int(venue.id), persona=persona_upper)
    if demo_user is None:
        raise HTTPException(status_code=404, detail=f"DEMO-пользователь для роли {persona_upper} не настроен")

    return venue, demo_user, persona_upper


@router.get("/demo/start")
def start_demo_session(
    db: Session = Depends(get_db),
    persona: str = Query(default=DEMO_PERSONA_OWNER),
    next_path: str | None = Query(default=None),
):
    venue, demo_user, persona_upper = _resolve_demo_identity_or_404(db, persona=persona)
    claims = build_demo_session_claims(venue=venue, persona=persona_upper)
    redirect_url = build_demo_start_url(venue_id=int(venue.id), persona=persona_upper, next_path=next_path)
    redirect = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _write_access_cookie(redirect, user=demo_user, extra_claims=claims)
    try:
        record_demo_event(
            db,
            event_name="demo_start",
            user=demo_user,
            venue_id=int(venue.id),
            persona=persona_upper,
            page_path=redirect_url,
            session_id=claims.get("demo_session_id"),
            meta={"source": "auth_start"},
        )
        db.commit()
    except Exception:
        db.rollback()
    return redirect


@router.post("/demo/switch-persona")
def switch_demo_persona(
    payload: DemoSwitchPersonaIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo_ctx = get_demo_session_or_none(user)
    if demo_ctx is None:
        raise HTTPException(status_code=403, detail="DEMO-сессия не активна")

    venue = db.execute(select(Venue).where(Venue.id == int(demo_ctx.venue_id))).scalar_one_or_none()
    if venue is None or not bool(getattr(venue, "is_demo", False)):
        raise HTTPException(status_code=404, detail="DEMO-заведение не найдено")

    persona_upper = normalize_demo_persona(payload.persona, default=DEMO_PERSONA_OWNER)
    demo_user = get_demo_user_for_venue(db, venue_id=int(venue.id), persona=persona_upper)
    if demo_user is None:
        raise HTTPException(status_code=404, detail=f"DEMO-пользователь для роли {persona_upper} не настроен")

    claims = build_demo_session_claims(venue=venue, persona=persona_upper)
    body = {
        "ok": True,
        "demo_mode": True,
        "demo_persona": persona_upper,
        "demo_venue_id": int(venue.id),
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
        "redirect_url": build_demo_start_url(
            venue_id=int(venue.id), persona=persona_upper, next_path=payload.next_path
        ),
        "banner": build_demo_banner_payload(),
    }
    resp = JSONResponse(body)
    _write_access_cookie(resp, user=demo_user, extra_claims=claims)
    try:
        record_demo_event(
            db,
            event_name="switch_persona",
            user=demo_user,
            venue_id=int(venue.id),
            persona=persona_upper,
            page_path=body.get("redirect_url"),
            session_id=claims.get("demo_session_id"),
            meta={"source": "auth_switch"},
        )
        db.commit()
    except Exception:
        db.rollback()
    return resp


@router.post("/demo/exit")
def exit_demo_session(
    response: Response, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)
):
    demo_ctx = get_demo_session_or_none(user)
    if demo_ctx is None:
        return {"ok": True, "demo_mode": False, "redirect_url": build_demo_banner_payload().get("return_url")}
    try:
        record_demo_event(
            db,
            event_name="exit_demo",
            user=user,
            session_id=getattr(demo_ctx, "session_id", None),
            meta={"source": "auth_exit"},
        )
        db.commit()
    except Exception:
        db.rollback()
    _clear_access_cookie(response)
    return {"ok": True, "demo_mode": False, "redirect_url": build_demo_banner_payload().get("return_url")}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    _clear_access_cookie(response)
    return
