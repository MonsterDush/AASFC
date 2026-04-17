from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DemoEvent, User
from .session import get_demo_template_venue, get_public_demo_venue


SECTION_LABELS: dict[str, str] = {
    "/owner-summary.html": "Сводка",
    "/owner-expenses.html": "Расходы",
    "/owner-payroll.html": "Начисления",
    "/owner-turnover.html": "Выручка",
    "/owner-revenue.html": "Выручка",
    "/owner-day-economics.html": "Экономика дня",
    "/owner-finance-ledger.html": "Движение денег",
    "/app-venue.html": "Карточка заведения",
    "/app-dashboard.html": "Dashboard",
    "/staff-shifts.html": "График",
    "/staff-salary.html": "Зарплата",
    "/staff-salary-summary.html": "Итоги зарплаты",
    "/staff-report.html": "Отчёты",
    "/staff-adjustments.html": "Штрафы и бонусы",
}

EVENT_LABELS: dict[str, str] = {
    "demo_start": "Старт DEMO",
    "page_view": "Просмотр страницы",
    "cta_click": "Клик по CTA",
    "tour_started": "Старт экскурсии",
    "tour_completed": "Завершение экскурсии",
    "switch_persona": "Переключение роли",
    "exit_demo": "Выход из DEMO",
}

CTA_LABELS: dict[str, str] = {
    "link": "Ссылка",
    "primary": "Основная CTA",
    "secondary": "Вторая CTA",
    "contact": "Оставить заявку",
    "telegram": "Telegram",
    "site": "Сайт",
}


def _normalize_str(value: Any, *, max_len: int) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:max_len]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _round_pct(numerator: int | float, denominator: int | float) -> float | None:
    try:
        den = float(denominator or 0)
    except Exception:
        den = 0.0
    if den <= 0:
        return None
    return round((float(numerator or 0) / den) * 100.0, 1)


def _section_key(page_path: str | None) -> str:
    raw = str(page_path or "").strip()
    if not raw:
        return "unknown"
    try:
        parsed = urlparse(raw)
        path = str(parsed.path or raw).strip()
    except Exception:
        path = raw
    if not path:
        return "unknown"
    tail = path.rsplit("/", 1)[-1].strip().lower()
    if not tail:
        return "unknown"
    if tail.endswith(".html"):
        tail = tail[:-5]
    return tail or "unknown"


def _section_label(page_path: str | None) -> str:
    raw = str(page_path or "").strip()
    if not raw:
        return "Неизвестный раздел"
    try:
        parsed = urlparse(raw)
        path = str(parsed.path or raw).strip()
    except Exception:
        path = raw
    if not path:
        return "Неизвестный раздел"
    if path in SECTION_LABELS:
        return SECTION_LABELS[path]
    key = _section_key(path)
    title = key.replace("-", " ").replace("_", " ").strip()
    if not title:
        return "Неизвестный раздел"
    return title[:1].upper() + title[1:]


def _event_label(event_name: str | None) -> str:
    key = str(event_name or "").strip().lower()
    if not key:
        return "Событие"
    return EVENT_LABELS.get(key, key)


def _cta_label(cta_code: str | None) -> str:
    key = str(cta_code or "").strip().lower()
    if not key:
        return "CTA"
    return CTA_LABELS.get(key, key)


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


def _add_months(year: int, month: int, count: int) -> tuple[int, int]:
    total = (int(year) * 12 + (int(month) - 1)) + int(count)
    new_year = total // 12
    new_month = (total % 12) + 1
    return new_year, new_month


def resolve_demo_analytics_period(
    *,
    range_type: str = "month",
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    mode = str(range_type or "month").strip().lower()
    if mode not in {"month", "quarter", "year", "period"}:
        mode = "month"

    if mode == "month":
        y = int(year or now.year)
        m = int(month or now.month)
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        end_y, end_m = _add_months(y, m, 1)
        end = datetime(end_y, end_m, 1, tzinfo=timezone.utc)
        label = f"{y:04d}-{m:02d}"
    elif mode == "quarter":
        y = int(year or now.year)
        q = int(quarter or (((now.month - 1) // 3) + 1))
        q = min(max(q, 1), 4)
        start_month = ((q - 1) * 3) + 1
        start = datetime(y, start_month, 1, tzinfo=timezone.utc)
        end_y, end_m = _add_months(y, start_month, 3)
        end = datetime(end_y, end_m, 1, tzinfo=timezone.utc)
        label = f"Q{q} {y}"
    elif mode == "year":
        y = int(year or now.year)
        start = datetime(y, 1, 1, tzinfo=timezone.utc)
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        label = str(y)
    else:
        start_date = date_from or now.date().replace(day=1)
        end_date = date_to or now.date()
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        label = f"{start_date.isoformat()} — {end_date.isoformat()}"

    return {
        "range_type": mode,
        "label": label,
        "start_at": start,
        "end_at": end,
        "date_from": start.date().isoformat(),
        "date_to": (end - timedelta(days=1)).date().isoformat(),
        "year": int(start.year),
        "month": int(start.month),
        "quarter": int(((start.month - 1) // 3) + 1),
    }


def get_demo_analytics_summary(
    db: Session,
    *,
    limit_pages: int = 6,
    limit_events: int = 12,
    days: int = 14,
) -> dict[str, Any]:
    total_events = int(db.execute(select(func.count(DemoEvent.id))).scalar() or 0)
    unique_sessions = int(db.execute(select(func.count(func.distinct(DemoEvent.session_id)))).scalar() or 0)
    cta_clicks = int(
        db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == "cta_click")).scalar() or 0
    )
    page_views = int(
        db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == "page_view")).scalar() or 0
    )
    persona_switches = int(
        db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == "switch_persona")).scalar() or 0
    )
    tour_started = int(
        db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == "tour_started")).scalar() or 0
    )
    tour_completed = int(
        db.execute(select(func.count(DemoEvent.id)).where(DemoEvent.event_name == "tour_completed")).scalar() or 0
    )

    top_pages_rows = db.execute(
        select(DemoEvent.page_path, func.count(DemoEvent.id).label("cnt"))
        .where(DemoEvent.event_name == "page_view", DemoEvent.page_path.is_not(None))
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
            "event_label": _event_label(row.event_name),
            "persona": row.persona,
            "page_path": row.page_path,
            "section_label": _section_label(row.page_path),
            "cta_code": row.cta_code,
            "cta_label": _cta_label(row.cta_code),
            "session_id": row.session_id,
            "venue_id": row.venue_id,
            "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
            "meta": row.meta_json or {},
        }
        for row in recent_rows
    ]

    event_name_rows = db.execute(
        select(DemoEvent.event_name, func.count(DemoEvent.id).label("cnt"))
        .group_by(DemoEvent.event_name)
        .order_by(func.count(DemoEvent.id).desc(), DemoEvent.event_name.asc())
    ).all()
    events_by_name = [{"event_name": row[0], "event_label": _event_label(row[0]), "count": int(row[1] or 0)} for row in event_name_rows]

    persona_expr = func.coalesce(DemoEvent.persona, "UNKNOWN")
    page_expr = func.coalesce(DemoEvent.page_path, "UNKNOWN")
    cta_expr = func.coalesce(DemoEvent.cta_code, "UNKNOWN")
    day_expr = func.date(DemoEvent.created_at)

    persona_rows = db.execute(
        select(
            persona_expr.label("persona"),
            func.count(DemoEvent.id).label("cnt"),
        )
        .group_by(persona_expr)
        .order_by(func.count(DemoEvent.id).desc())
    ).all()
    events_by_persona = [{"persona": row[0], "count": int(row[1] or 0)} for row in persona_rows]

    cta_rows = db.execute(
        select(
            cta_expr.label("cta_code"),
            func.count(DemoEvent.id).label("cnt"),
        )
        .where(DemoEvent.event_name == "cta_click", DemoEvent.cta_code.is_not(None))
        .group_by(cta_expr)
        .order_by(func.count(DemoEvent.id).desc(), cta_expr.asc())
    ).all()
    cta_breakdown = [{"cta_code": row[0], "cta_label": _cta_label(row[0]), "count": int(row[1] or 0)} for row in cta_rows]

    page_persona_rows = db.execute(
        select(
            persona_expr.label("persona"),
            page_expr.label("page_path"),
            func.count(DemoEvent.id).label("cnt"),
        )
        .where(DemoEvent.event_name == "page_view", DemoEvent.page_path.is_not(None))
        .group_by(persona_expr, page_expr)
        .order_by(func.count(DemoEvent.id).desc(), page_expr.asc())
    ).all()
    top_pages_by_persona: dict[str, list[dict[str, Any]]] = {}
    for persona, page_path, cnt in page_persona_rows:
        bucket = top_pages_by_persona.setdefault(str(persona), [])
        if len(bucket) < int(limit_pages):
            bucket.append({
                "page_path": page_path,
                "label": _section_label(page_path),
                "views": int(cnt or 0),
            })

    session_persona_rows = db.execute(
        select(
            persona_expr.label("persona"),
            func.count(func.distinct(DemoEvent.session_id)).label("cnt"),
        )
        .where(DemoEvent.session_id.is_not(None))
        .group_by(persona_expr)
        .order_by(func.count(func.distinct(DemoEvent.session_id)).desc())
    ).all()
    sessions_by_persona = [{"persona": row[0], "sessions": int(row[1] or 0)} for row in session_persona_rows]

    since = datetime.now(timezone.utc) - timedelta(days=max(int(days), 1) - 1)
    trend_rows = db.execute(
        select(
            day_expr.label("day"),
            func.count(DemoEvent.id).label("cnt"),
        )
        .where(DemoEvent.created_at >= since)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    ).all()
    activity_by_day = [
        {
            "date": str(row[0])[:10],
            "events": int(row[1] or 0),
        }
        for row in trend_rows
    ]

    public_venue = get_public_demo_venue(db)
    template_venue = get_demo_template_venue(db)

    return {
        "totals": {
            "events": total_events,
            "unique_sessions": unique_sessions,
            "cta_clicks": cta_clicks,
            "page_views": page_views,
            "persona_switches": persona_switches,
            "tour_started": tour_started,
            "tour_completed": tour_completed,
            "conversion_rate_tour": _round_pct(tour_completed, tour_started),
        },
        "top_pages": top_pages,
        "top_pages_by_persona": top_pages_by_persona,
        "events_by_name": events_by_name,
        "events_by_persona": events_by_persona,
        "sessions_by_persona": sessions_by_persona,
        "cta_breakdown": cta_breakdown,
        "activity_by_day": activity_by_day,
        "recent_events": recent_events,
        "public_venue_id": int(public_venue.id) if public_venue else None,
        "template_venue_id": int(template_venue.id) if template_venue else None,
    }


def get_demo_analytics_dashboard(
    db: Session,
    *,
    range_type: str = "month",
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit_sections: int = 50,
    limit_recent: int = 20,
) -> dict[str, Any]:
    period = resolve_demo_analytics_period(
        range_type=range_type,
        year=year,
        month=month,
        quarter=quarter,
        date_from=date_from,
        date_to=date_to,
    )
    start_at: datetime = period["start_at"]
    end_at: datetime = period["end_at"]
    filters = (DemoEvent.created_at >= start_at, DemoEvent.created_at < end_at)

    persona_expr = func.coalesce(DemoEvent.persona, "UNKNOWN")
    page_expr = func.coalesce(DemoEvent.page_path, "UNKNOWN")
    cta_expr = func.coalesce(DemoEvent.cta_code, "UNKNOWN")
    day_expr = func.date(DemoEvent.created_at)

    total_events = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters)).scalar())
    unique_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.session_id.is_not(None))).scalar())
    page_views = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "page_view")).scalar())
    page_view_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.event_name == "page_view", DemoEvent.session_id.is_not(None))).scalar())
    cta_clicks = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "cta_click")).scalar())
    cta_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.event_name == "cta_click", DemoEvent.session_id.is_not(None))).scalar())
    tour_started = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "tour_started")).scalar())
    tour_started_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.event_name == "tour_started", DemoEvent.session_id.is_not(None))).scalar())
    tour_completed = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "tour_completed")).scalar())
    tour_completed_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.event_name == "tour_completed", DemoEvent.session_id.is_not(None))).scalar())
    demo_start_sessions = _safe_int(db.execute(select(func.count(func.distinct(DemoEvent.session_id))).where(*filters, DemoEvent.event_name == "demo_start", DemoEvent.session_id.is_not(None))).scalar())
    persona_switches = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "switch_persona")).scalar())
    exits = _safe_int(db.execute(select(func.count(DemoEvent.id)).where(*filters, DemoEvent.event_name == "exit_demo")).scalar())

    totals = {
        "events": total_events,
        "unique_sessions": unique_sessions,
        "page_views": page_views,
        "page_view_sessions": page_view_sessions,
        "cta_clicks": cta_clicks,
        "cta_sessions": cta_sessions,
        "demo_start_sessions": demo_start_sessions,
        "persona_switches": persona_switches,
        "tour_started": tour_started,
        "tour_started_sessions": tour_started_sessions,
        "tour_completed": tour_completed,
        "tour_completed_sessions": tour_completed_sessions,
        "exit_events": exits,
        "conversion_rate_cta_sessions": _round_pct(cta_sessions, unique_sessions),
        "conversion_rate_cta_clicks": _round_pct(cta_clicks, page_views),
        "conversion_rate_tour_sessions": _round_pct(tour_completed_sessions, tour_started_sessions),
        "conversion_rate_tour_events": _round_pct(tour_completed, tour_started),
        "conversion_rate_session_to_page": _round_pct(page_view_sessions, unique_sessions),
    }

    section_page_rows = db.execute(
        select(
            page_expr.label("page_path"),
            persona_expr.label("persona"),
            func.count(DemoEvent.id).label("views"),
            func.count(func.distinct(DemoEvent.session_id)).label("sessions"),
        )
        .where(*filters, DemoEvent.event_name == "page_view", DemoEvent.page_path.is_not(None))
        .group_by(page_expr, persona_expr)
        .order_by(func.count(DemoEvent.id).desc(), page_expr.asc())
    ).all()

    section_cta_rows = db.execute(
        select(
            page_expr.label("page_path"),
            persona_expr.label("persona"),
            func.count(DemoEvent.id).label("clicks"),
            func.count(func.distinct(DemoEvent.session_id)).label("sessions"),
        )
        .where(*filters, DemoEvent.event_name == "cta_click", DemoEvent.page_path.is_not(None))
        .group_by(page_expr, persona_expr)
        .order_by(func.count(DemoEvent.id).desc(), page_expr.asc())
    ).all()

    section_map: dict[str, dict[str, Any]] = {}

    def ensure_section(page_path: str) -> dict[str, Any]:
        bucket = section_map.get(page_path)
        if bucket is None:
            bucket = {
                "page_path": page_path,
                "section_key": _section_key(page_path),
                "label": _section_label(page_path),
                "views": 0,
                "sessions": 0,
                "cta_clicks": 0,
                "cta_sessions": 0,
                "view_share_pct": None,
                "cta_conversion_pct": None,
                "persona_breakdown": {},
            }
            section_map[page_path] = bucket
        return bucket

    for page_path, persona, views, sessions in section_page_rows:
        item = ensure_section(str(page_path))
        item["views"] += _safe_int(views)
        item["sessions"] += _safe_int(sessions)
        p = item["persona_breakdown"].setdefault(str(persona), {"views": 0, "sessions": 0, "cta_clicks": 0, "cta_sessions": 0})
        p["views"] += _safe_int(views)
        p["sessions"] += _safe_int(sessions)

    for page_path, persona, clicks, sessions in section_cta_rows:
        item = ensure_section(str(page_path))
        item["cta_clicks"] += _safe_int(clicks)
        item["cta_sessions"] += _safe_int(sessions)
        p = item["persona_breakdown"].setdefault(str(persona), {"views": 0, "sessions": 0, "cta_clicks": 0, "cta_sessions": 0})
        p["cta_clicks"] += _safe_int(clicks)
        p["cta_sessions"] += _safe_int(sessions)

    sections = list(section_map.values())
    for item in sections:
        item["view_share_pct"] = _round_pct(item["views"], page_views)
        item["cta_conversion_pct"] = _round_pct(item["cta_sessions"], item["sessions"])
        ordered = {}
        for persona in ["OWNER", "STAFF", "UNKNOWN"]:
            if persona in item["persona_breakdown"]:
                ordered[persona] = item["persona_breakdown"][persona]
        for persona, value in item["persona_breakdown"].items():
            if persona not in ordered:
                ordered[persona] = value
        item["persona_breakdown"] = ordered
    sections.sort(key=lambda row: (-_safe_int(row.get("views")), -_safe_int(row.get("sessions")), str(row.get("label") or "")))
    sections = sections[: max(int(limit_sections or 50), 1)]

    persona_total_rows = db.execute(
        select(persona_expr.label("persona"), func.count(DemoEvent.id).label("cnt"))
        .where(*filters)
        .group_by(persona_expr)
        .order_by(func.count(DemoEvent.id).desc(), persona_expr.asc())
    ).all()
    persona_session_rows = db.execute(
        select(persona_expr.label("persona"), func.count(func.distinct(DemoEvent.session_id)).label("cnt"))
        .where(*filters, DemoEvent.session_id.is_not(None))
        .group_by(persona_expr)
        .order_by(func.count(func.distinct(DemoEvent.session_id)).desc(), persona_expr.asc())
    ).all()
    persona_page_rows = db.execute(
        select(persona_expr.label("persona"), func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters, DemoEvent.event_name == "page_view")
        .group_by(persona_expr)
        .order_by(func.count(DemoEvent.id).desc(), persona_expr.asc())
    ).all()
    persona_cta_rows = db.execute(
        select(persona_expr.label("persona"), func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters, DemoEvent.event_name == "cta_click")
        .group_by(persona_expr)
        .order_by(func.count(DemoEvent.id).desc(), persona_expr.asc())
    ).all()
    persona_event_rows = db.execute(
        select(persona_expr.label("persona"), DemoEvent.event_name, func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters)
        .group_by(persona_expr, DemoEvent.event_name)
        .order_by(persona_expr.asc(), func.count(DemoEvent.id).desc(), DemoEvent.event_name.asc())
    ).all()

    persona_map: dict[str, dict[str, Any]] = {}

    def ensure_persona(persona: str) -> dict[str, Any]:
        bucket = persona_map.get(persona)
        if bucket is None:
            bucket = {
                "persona": persona,
                "events": 0,
                "sessions": 0,
                "page_views": 0,
                "page_view_sessions": 0,
                "cta_clicks": 0,
                "cta_sessions": 0,
                "tour_started": 0,
                "tour_started_sessions": 0,
                "tour_completed": 0,
                "tour_completed_sessions": 0,
                "demo_start_sessions": 0,
                "exit_events": 0,
                "conversion_rate_cta_sessions": None,
                "conversion_rate_tour_sessions": None,
            }
            persona_map[persona] = bucket
        return bucket

    for persona, cnt in persona_total_rows:
        ensure_persona(str(persona))["events"] = _safe_int(cnt)
    for persona, cnt in persona_session_rows:
        ensure_persona(str(persona))["sessions"] = _safe_int(cnt)
    for persona, cnt, sessions in persona_page_rows:
        bucket = ensure_persona(str(persona))
        bucket["page_views"] = _safe_int(cnt)
        bucket["page_view_sessions"] = _safe_int(sessions)
    for persona, cnt, sessions in persona_cta_rows:
        bucket = ensure_persona(str(persona))
        bucket["cta_clicks"] = _safe_int(cnt)
        bucket["cta_sessions"] = _safe_int(sessions)
    for persona, event_name, cnt, sessions in persona_event_rows:
        bucket = ensure_persona(str(persona))
        name = str(event_name or "").strip().lower()
        if name == "tour_started":
            bucket["tour_started"] = _safe_int(cnt)
            bucket["tour_started_sessions"] = _safe_int(sessions)
        elif name == "tour_completed":
            bucket["tour_completed"] = _safe_int(cnt)
            bucket["tour_completed_sessions"] = _safe_int(sessions)
        elif name == "demo_start":
            bucket["demo_start_sessions"] = _safe_int(sessions)
        elif name == "exit_demo":
            bucket["exit_events"] = _safe_int(cnt)

    personas = list(persona_map.values())
    for bucket in personas:
        bucket["conversion_rate_cta_sessions"] = _round_pct(bucket["cta_sessions"], bucket["sessions"])
        bucket["conversion_rate_tour_sessions"] = _round_pct(bucket["tour_completed_sessions"], bucket["tour_started_sessions"])
    personas.sort(key=lambda row: (-_safe_int(row.get("sessions")), -_safe_int(row.get("events")), str(row.get("persona") or "")))

    event_rows = db.execute(
        select(DemoEvent.event_name, func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters)
        .group_by(DemoEvent.event_name)
        .order_by(func.count(DemoEvent.id).desc(), DemoEvent.event_name.asc())
    ).all()
    events_by_name = [
        {
            "event_name": row[0],
            "event_label": _event_label(row[0]),
            "count": _safe_int(row[1]),
            "sessions": _safe_int(row[2]),
        }
        for row in event_rows
    ]

    cta_rows = db.execute(
        select(cta_expr.label("cta_code"), func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters, DemoEvent.event_name == "cta_click")
        .group_by(cta_expr)
        .order_by(func.count(DemoEvent.id).desc(), cta_expr.asc())
    ).all()
    ctas = [
        {
            "cta_code": row[0],
            "cta_label": _cta_label(row[0]),
            "clicks": _safe_int(row[1]),
            "sessions": _safe_int(row[2]),
            "conversion_rate_sessions": _round_pct(_safe_int(row[2]), unique_sessions),
        }
        for row in cta_rows
    ]

    activity_rows = db.execute(
        select(day_expr.label("day"), func.count(DemoEvent.id).label("cnt"), func.count(func.distinct(DemoEvent.session_id)).label("sessions"))
        .where(*filters)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    ).all()
    activity_map = {str(row[0])[:10]: {"date": str(row[0])[:10], "events": _safe_int(row[1]), "sessions": _safe_int(row[2])} for row in activity_rows}
    activity_by_day: list[dict[str, Any]] = []
    cursor = start_at.date()
    final_day = (end_at - timedelta(days=1)).date()
    while cursor <= final_day:
        key = cursor.isoformat()
        activity_by_day.append(activity_map.get(key, {"date": key, "events": 0, "sessions": 0}))
        cursor += timedelta(days=1)

    recent_rows = db.execute(
        select(DemoEvent)
        .where(*filters)
        .order_by(DemoEvent.created_at.desc(), DemoEvent.id.desc())
        .limit(max(int(limit_recent or 20), 1))
    ).scalars().all()
    recent_events = [
        {
            "id": int(row.id),
            "event_name": row.event_name,
            "event_label": _event_label(row.event_name),
            "persona": row.persona or "UNKNOWN",
            "page_path": row.page_path,
            "section_label": _section_label(row.page_path),
            "cta_code": row.cta_code,
            "cta_label": _cta_label(row.cta_code),
            "session_id": row.session_id,
            "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
            "meta": row.meta_json or {},
        }
        for row in recent_rows
    ]

    funnel = [
        {
            "key": "sessions",
            "label": "Сессии",
            "sessions": unique_sessions,
            "conversion_pct": 100.0 if unique_sessions else None,
        },
        {
            "key": "page_view",
            "label": "Сессии с просмотром страниц",
            "sessions": page_view_sessions,
            "conversion_pct": _round_pct(page_view_sessions, unique_sessions),
        },
        {
            "key": "tour_started",
            "label": "Сессии со стартом экскурсии",
            "sessions": tour_started_sessions,
            "conversion_pct": _round_pct(tour_started_sessions, unique_sessions),
        },
        {
            "key": "tour_completed",
            "label": "Сессии с завершением экскурсии",
            "sessions": tour_completed_sessions,
            "conversion_pct": _round_pct(tour_completed_sessions, unique_sessions),
        },
        {
            "key": "cta",
            "label": "Сессии с CTA-кликом",
            "sessions": cta_sessions,
            "conversion_pct": _round_pct(cta_sessions, unique_sessions),
        },
    ]

    public_venue = get_public_demo_venue(db)
    template_venue = get_demo_template_venue(db)

    return {
        "period": {
            **{k: v for k, v in period.items() if k not in {"start_at", "end_at"}},
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        "totals": totals,
        "funnel": funnel,
        "personas": personas,
        "sections": sections,
        "events_by_name": events_by_name,
        "cta_breakdown": ctas,
        "activity_by_day": activity_by_day,
        "recent_events": recent_events,
        "public_venue": {
            "id": int(public_venue.id),
            "name": public_venue.name,
        } if public_venue is not None else None,
        "template_venue": {
            "id": int(template_venue.id),
            "name": template_venue.name,
        } if template_venue is not None else None,
    }
