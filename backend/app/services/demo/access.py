from __future__ import annotations

from app.models import User, Venue
from app.settings import settings
from .session import DemoSessionContext, DEMO_PERSONA_OWNER

DEMO_ACCESS_FULL = "FULL"
DEMO_ACCESS_READONLY = "DEMO_READONLY"


def build_demo_banner_payload() -> dict:
    return {
        "return_url": (settings.DEMO_RETURN_URL or "https://axelio.ru").strip() or "https://axelio.ru",
        "primary_cta_url": (settings.DEMO_PRIMARY_CTA_URL or "https://axelio.ru/#contact").strip() or "https://axelio.ru/#contact",
        "secondary_cta_url": (settings.DEMO_SECONDARY_CTA_URL or f"{settings.frontend_base_url()}/auth.html").strip() or f"{settings.frontend_base_url()}/auth.html",
        "primary_cta_label": (settings.DEMO_PRIMARY_CTA_LABEL or "Оставить заявку").strip() or "Оставить заявку",
        "secondary_cta_label": (settings.DEMO_SECONDARY_CTA_LABEL or "Начать пользоваться").strip() or "Начать пользоваться",
    }


def get_demo_session_context(user: User | None) -> DemoSessionContext:
    if user is None:
        return DemoSessionContext(is_demo=False)
    return DemoSessionContext(
        is_demo=bool(getattr(user, "_demo_mode", False)),
        venue_id=getattr(user, "_demo_venue_id", None),
        persona=getattr(user, "_demo_persona", None),
        reference_year=getattr(user, "_demo_reference_year", None),
        reference_month=getattr(user, "_demo_reference_month", None),
    )


def get_demo_session_or_none(user: User | None) -> DemoSessionContext | None:
    ctx = get_demo_session_context(user)
    return ctx if ctx.is_demo else None


def is_demo_session_for_venue(user: User | None, *, venue_id: int | None, venue: Venue | None = None) -> bool:
    ctx = get_demo_session_context(user)
    if not ctx.is_demo:
        return False
    if venue_id is None or ctx.venue_id != int(venue_id):
        return False
    if venue is not None and not bool(getattr(venue, "is_demo", False)):
        return False
    return True


def build_demo_context_payload(user: User | None, *, venue: Venue | None = None, venue_id: int | None = None) -> dict:
    ctx = get_demo_session_context(user)
    target_venue_id = int(venue_id if venue_id is not None else (getattr(venue, "id", 0) or 0)) if (venue_id is not None or venue is not None) else None
    is_demo_venue = bool(getattr(venue, "is_demo", False)) if venue is not None else bool(ctx.is_demo and target_venue_id is None)
    session_matches_venue = bool(ctx.is_demo and ((target_venue_id is None) or (ctx.venue_id == target_venue_id)))

    reference_year = ctx.reference_year if session_matches_venue else getattr(venue, "demo_reference_year", None)
    reference_month = ctx.reference_month if session_matches_venue else getattr(venue, "demo_reference_month", None)

    return {
        "is_demo": bool(is_demo_venue),
        "demo_mode": bool(session_matches_venue),
        "demo_access_mode": DEMO_ACCESS_READONLY if session_matches_venue else DEMO_ACCESS_FULL,
        "demo_persona": (ctx.persona or DEMO_PERSONA_OWNER) if session_matches_venue else None,
        "demo_venue_id": ctx.venue_id if ctx.is_demo else None,
        "demo_reference_year": reference_year,
        "demo_reference_month": reference_month,
        "demo_restricted_reason": "Это пробный режим. Изменения здесь недоступны." if session_matches_venue else None,
    }
