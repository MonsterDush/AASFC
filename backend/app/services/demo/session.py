from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, Venue, VenueMember
from app.settings import settings

DEMO_SESSION_MODE = "DEMO"
DEMO_PERSONA_OWNER = "OWNER"
DEMO_PERSONA_STAFF = "STAFF"
ALLOWED_DEMO_PERSONAS = {DEMO_PERSONA_OWNER, DEMO_PERSONA_STAFF}


@dataclass(frozen=True)
class DemoSessionContext:
    is_demo: bool
    venue_id: int | None = None
    persona: str | None = None
    reference_year: int | None = None
    reference_month: int | None = None


def normalize_demo_persona(value: str | None, *, default: str = DEMO_PERSONA_OWNER) -> str:
    raw = str(value or "").strip().upper()
    if raw in ALLOWED_DEMO_PERSONAS:
        return raw
    return default


def is_demo_session_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return str(payload.get("session_mode") or "").strip().upper() == DEMO_SESSION_MODE


def _parse_demo_context_from_payload(payload: dict[str, Any] | None) -> DemoSessionContext:
    if not is_demo_session_payload(payload):
        return DemoSessionContext(is_demo=False)

    venue_id_raw = payload.get("demo_venue_id")
    try:
        venue_id = int(venue_id_raw) if venue_id_raw is not None else None
    except Exception:
        venue_id = None

    reference_year_raw = payload.get("demo_reference_year")
    try:
        reference_year = int(reference_year_raw) if reference_year_raw is not None else None
    except Exception:
        reference_year = None

    reference_month_raw = payload.get("demo_reference_month")
    try:
        reference_month = int(reference_month_raw) if reference_month_raw is not None else None
    except Exception:
        reference_month = None

    return DemoSessionContext(
        is_demo=True,
        venue_id=venue_id,
        persona=normalize_demo_persona(payload.get("demo_persona"), default=DEMO_PERSONA_OWNER),
        reference_year=reference_year,
        reference_month=reference_month,
    )


def apply_auth_payload_to_user(user: User | None, payload: dict[str, Any] | None) -> User | None:
    if user is None:
        return None
    ctx = _parse_demo_context_from_payload(payload)
    setattr(user, "_auth_session_mode", DEMO_SESSION_MODE if ctx.is_demo else "NORMAL")
    setattr(user, "_demo_mode", bool(ctx.is_demo))
    setattr(user, "_demo_venue_id", ctx.venue_id)
    setattr(user, "_demo_persona", ctx.persona)
    setattr(user, "_demo_reference_year", ctx.reference_year)
    setattr(user, "_demo_reference_month", ctx.reference_month)
    return user


def sanitize_frontend_next_path(next_path: str | None) -> str | None:
    raw = str(next_path or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return None
    if not raw.startswith("/") or raw.startswith("//"):
        return None
    return raw


def _frontend_base_url() -> str:
    return (settings.frontend_base_url() or "").rstrip("/")


def _with_venue_param(path: str, *, venue_id: int) -> str:
    parsed = urlparse(path)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query = [(k, v) for (k, v) in query if k != "venue_id"]
    query.append(("venue_id", str(int(venue_id))))
    return urlunparse(parsed._replace(query=urlencode(query)))


def default_demo_target_path(*, venue_id: int, persona: str | None = None) -> str:
    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    if persona_upper == DEMO_PERSONA_STAFF:
        return f"/staff-shifts.html?venue_id={int(venue_id)}"
    return f"/app-venue.html?venue_id={int(venue_id)}"


def build_demo_start_url(*, venue_id: int, persona: str | None = None, next_path: str | None = None) -> str:
    safe_path = sanitize_frontend_next_path(next_path)
    target_path = _with_venue_param(safe_path, venue_id=int(venue_id)) if safe_path else default_demo_target_path(venue_id=int(venue_id), persona=persona)
    base = _frontend_base_url() or ""
    if base:
        return urljoin(base + "/", target_path.lstrip("/"))
    return target_path


def get_public_demo_venue(db: Session) -> Venue | None:
    return db.execute(
        select(Venue)
        .where(Venue.is_demo.is_(True))
        .order_by(Venue.id.asc())
    ).scalar_one_or_none()


def get_demo_user_for_venue(db: Session, *, venue_id: int, persona: str) -> User | None:
    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    return db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            User.is_demo_user.is_(True),
            User.demo_persona == persona_upper,
            VenueMember.venue_id == int(venue_id),
            VenueMember.venue_role == persona_upper,
            VenueMember.is_active.is_(True),
        )
        .order_by(User.id.asc())
    ).scalar_one_or_none()


def build_demo_session_claims(*, venue: Venue, persona: str) -> dict[str, Any]:
    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    return {
        "session_mode": DEMO_SESSION_MODE,
        "demo_venue_id": int(venue.id),
        "demo_persona": persona_upper,
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
    }
