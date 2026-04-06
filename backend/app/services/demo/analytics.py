from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DemoEvent, User, Venue
from .session import get_demo_template_venue, get_public_demo_venue


def _normalize_str(value: Any, *, max_len: int) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:max_len]


def ensure_demo_session_id(user: User | None) -> str | None:
    if user is None or not bool(getattr(user, "_demo_mode", False)):
        return None
    current = _normalize_str(getattr(user, "_demo_session_id", None), max_len=64)
    if current:
        return current
    generated = uuid.uuid4().hex
    setattr(user, "_demo_session_id", generated)
    return generated


def record_demo_event(
    db: Session,
    *,
    event_name: str,
    user: User | None = None,
    venue_id: int | None = None,
    persona: str | None = None,
    page_path: str | None = None,
    cta_code: str | None = None,
    session_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> DemoEvent | None:
    name = _normalize_str(event_name, max_len=64)
    if not name:
        return None
    demo_mode = bool(getattr(user, "_demo_mode", False)) if user is not None else bool(session_id)
    if not demo_mode and user is not None and not bool(getattr(user, "is_demo_user", False)):
        return None
    resolved_venue_id = int(venue_id) if venue_id is not None else (int(getattr(user, "_demo_venue_id", 0) or 0) or None)
    evt = DemoEvent(
        venue_id=resolved_venue_id,
        user_id=int(getattr(user, "id", 0) or 0) or None,
        session_id=_normalize_str(session_id or ensure_demo_session_id(user), max_len=64),
        event_name=name,
        persona=_normalize_str(persona or getattr(user, "_demo_persona", None), max_len=16),
        page_path=_normalize_str(page_path, max_len=255),
        cta_code=_normalize_str(cta_code, max_len=64),
        meta_json=meta or None,
    )
    db.add(evt)
    db.flush()
    return evt


def get_demo_analytics_summary(db: Session, *, limit_pages: int = 6, limit_events: int = 12) -> dict[str, Any]:
    total_events = int(db.execute(select(func.count(DemoEvent.id))).scalar() or 0)
    unique_sessions = int(db.execute(select(func.count(func.distinct(DemoEvent.session_id)))).scalar() or 0)
    cta_clicks = int(db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == 'cta_click')).scalar() or 0)
    page_views = int(db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == 'page_view')).scalar() or 0)
    persona_switches = int(db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == 'switch_persona')).scalar() or 0)
    tour_started = int(db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == 'tour_started')).scalar() or 0)
    tour_completed = int(db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == 'tour_completed')).scalar() or 0)

    top_pages_rows = db.execute(
        select(DemoEvent.page_path, func.count(DemoEvent.id).label('cnt'))
        .where(DemoEvent.event_name == 'page_view', DemoEvent.page_path.is_not(None))
        .group_by(DemoEvent.page_path)
        .order_by(func.count(DemoEvent.id).desc(), DemoEvent.page_path.asc())
        .limit(int(limit_pages))
    ).all()
    top_pages = [{"page_path": row[0], "views": int(row[1] or 0)} for row in top_pages_rows]

    recent_rows = db.execute(
        select(DemoEvent)
        .order_by(DemoEvent.created_at.desc(), DemoEvent.id.desc())
        .limit(int(limit_events))
    ).scalars().all()
    recent_events = [
        {
            "id": int(row.id),
            "event_name": row.event_name,
            "persona": row.persona,
            "page_path": row.page_path,
            "cta_code": row.cta_code,
            "session_id": row.session_id,
            "venue_id": row.venue_id,
            "created_at": row.created_at.isoformat() if getattr(row, 'created_at', None) else None,
            "meta": row.meta_json or {},
        }
        for row in recent_rows
    ]

    public_venue = get_public_demo_venue(db)
    template_venue = get_demo_template_venue(db)
    return {
        'totals': {
            'events': total_events,
            'unique_sessions': unique_sessions,
            'cta_clicks': cta_clicks,
            'page_views': page_views,
            'persona_switches': persona_switches,
            'tour_started': tour_started,
            'tour_completed': tour_completed,
        },
        'top_pages': top_pages,
        'recent_events': recent_events,
        'public_venue_id': int(public_venue.id) if public_venue else None,
        'template_venue_id': int(template_venue.id) if template_venue else None,
    }
