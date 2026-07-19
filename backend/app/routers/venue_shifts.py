from fastapi import APIRouter

from app.routers.venue_core import (
    BaseModel,
    DailyReport,
    Depends,
    Field,
    HTTPException,
    Query,
    RedirectResponse,
    Request,
    Session,
    Shift,
    ShiftAssignment,
    ShiftComment,
    ShiftInterval,
    User,
    Venue,
    VenueMember,
    VenuePosition,
    _has_revenue_view_access,
    _require_active_member_or_admin,
    calendar,
    date,
    get_current_user,
    get_db,
    make_signed_token,
    normalize_shift_slot,
    quote,
    sa,
    select,
    timedelta,
    update,
    verify_signed_token,
)
from app.routers.venue_common import (
    _SCHEDULE_SHARE_TTL_SECONDS,
)
from app.schemas.venue_shifts import (
    ShiftAssignmentAddIn,
    ShiftCreateIn,
    ShiftUpdateIn,
)
from app.routers.venue_permissions import (
    _require_schedule_editor,
    _require_shift_comments_allowed,
)
from app.routers.venue_payroll_support import (
    _recalculate_payroll_for_dates,
)
from app.routers.venue_notification_common import (
    _frontend_base_url,
)
from app.routers.venue_reports import _rebuild_report_tip_allocations
from app.routers.venue_schedule_templates import _normalize_shift_slot_for_venue, _shift_slot_label



router = APIRouter()


_SCHEDULE_EXPORT_VIEW_LABELS = {
    "month": "Месяц",
    "week": "Неделя",
}

_MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def _month_period_bounds(month_value: str) -> tuple[date, date]:
    try:
        year_text, month_text = str(month_value or "").strip().split("-", 1)
        year = int(year_text)
        month = int(month_text)
        start = date(year, month, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    last_day = calendar.monthrange(start.year, start.month)[1]
    return start, date(start.year, start.month, last_day)


def _week_period_bounds(week_start_value: date) -> tuple[date, date]:
    start = week_start_value - timedelta(days=week_start_value.weekday())
    return start, start + timedelta(days=6)


def _format_schedule_period_label(*, view: str, period_start: date, period_end: date) -> str:
    if view == "week":
        return f"{period_start.strftime('%d.%m')}–{period_end.strftime('%d.%m.%Y')}"
    return f"{_MONTH_NAMES_RU.get(period_start.month, period_start.strftime('%m'))} {period_start.year}"


def _build_schedule_export_filters_text(
    *,
    view: str,
    interval_titles: list[str],
    staffing_state: str,
    shift_slot: str | None = None,
) -> str:
    parts = [_SCHEDULE_EXPORT_VIEW_LABELS.get(view, "График"), "Все сотрудники"]
    if shift_slot:
        parts.append("Ночные смены" if normalize_shift_slot(shift_slot) == "NIGHT" else "Дневные смены")
    if interval_titles:
        parts.append(f"Интервалы: {', '.join(interval_titles)}")
    if staffing_state == "unstaffed":
        parts.append("Только без назначений")
    elif staffing_state == "staffed":
        parts.append("Только с назначениями")
    return " • ".join(parts)


def _build_staff_shifts_deep_link_path(
    *,
    venue_id: int,
    view: str,
    period_start: date,
    interval_ids: list[int],
    staffing_state: str,
    shift_slot: str | None = None,
) -> str:
    params: list[tuple[str, str]] = [
        ("venue_id", str(int(venue_id))),
        ("view", view),
    ]
    if view == "week":
        params.append(("week", period_start.isoformat()))
    else:
        params.append(("month", period_start.strftime("%Y-%m")))
    if interval_ids:
        params.append(("intervals", ",".join(str(int(x)) for x in interval_ids)))
    if shift_slot:
        params.append(("shift_slot", normalize_shift_slot(shift_slot)))
    if staffing_state == "unstaffed":
        params.append(("unstaffed", "1"))
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params)
    return f"/staff-shifts.html?{query}"



def _build_staff_shifts_share_token(
    *,
    venue_id: int,
    view: str,
    period_start: date,
    interval_ids: list[int],
    staffing_state: str,
    shift_slot: str | None = None,
) -> str:
    return make_signed_token(
        {
            "action": "staff_shifts_share",
            "venue_id": int(venue_id),
            "view": str(view),
            "period_start": period_start.isoformat(),
            "interval_ids": [int(item) for item in (interval_ids or []) if int(item) > 0],
            "staffing_state": str(staffing_state or "all"),
            "shift_slot": normalize_shift_slot(shift_slot) if shift_slot else None,
        },
        ttl_seconds=_SCHEDULE_SHARE_TTL_SECONDS,
    )


def _build_staff_shifts_share_path(token: str) -> str:
    return f"/venues/share/staff-shifts/{quote(token)}"


def _build_staff_shifts_share_url(*, request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{_build_staff_shifts_share_path(token)}"


def _build_telegram_share_url(*, url: str, text: str) -> str:
    return f"https://t.me/share/url?url={quote(url)}&text={quote(text or '')}"


@router.get("/share/staff-shifts/{token}")
def open_staff_shifts_share_link(token: str):
    try:
        payload = verify_signed_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid share token")

    if str(payload.get("action") or "") != "staff_shifts_share":
        raise HTTPException(status_code=401, detail="Invalid share token")

    venue_id = int(payload.get("venue_id") or 0)
    if venue_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid share token")

    view = str(payload.get("view") or "month").strip().lower()
    if view not in {"month", "week"}:
        view = "month"

    raw_period_start = payload.get("period_start")
    try:
        period_start = date.fromisoformat(str(raw_period_start))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid share token")

    raw_interval_ids = payload.get("interval_ids") or []
    interval_ids = [int(item) for item in raw_interval_ids if int(item) > 0]
    staffing_state = str(payload.get("staffing_state") or "all").strip().lower()
    if staffing_state not in {"all", "staffed", "unstaffed"}:
        staffing_state = "all"
    raw_shift_slot = payload.get("shift_slot")
    shift_slot = normalize_shift_slot(raw_shift_slot) if raw_shift_slot else None

    deep_link_path = _build_staff_shifts_deep_link_path(
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        interval_ids=interval_ids,
        staffing_state=staffing_state,
        shift_slot=shift_slot,
    )
    return RedirectResponse(url=f"{_frontend_base_url()}{deep_link_path}", status_code=307)


@router.get("/{venue_id}/shifts/export-metadata")
def get_shifts_export_metadata(
    venue_id: int,
    request: Request,
    view: str = Query(default="month", pattern="^(month|week)$"),
    month: str | None = Query(default=None, description="YYYY-MM"),
    week_start: date | None = Query(default=None),
    interval_ids: list[int] | None = Query(default=None),
    staffing_state: str = Query(default="all", pattern="^(all|staffed|unstaffed)$"),
    shift_slot: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Metadata for client-side schedule export, download and share flows."""
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    if view == "week":
        if week_start is None:
            raise HTTPException(status_code=400, detail="week_start is required for week export metadata")
        period_start, period_end = _week_period_bounds(week_start)
    else:
        if not month:
            raise HTTPException(status_code=400, detail="month is required for month export metadata")
        period_start, period_end = _month_period_bounds(month)

    normalized_shift_slot = _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=shift_slot) if shift_slot else None

    normalized_interval_ids = sorted({int(item) for item in (interval_ids or []) if int(item) > 0})
    interval_titles: list[str] = []
    if normalized_interval_ids:
        interval_rows = db.execute(
            select(ShiftInterval)
            .where(
                ShiftInterval.venue_id == venue_id,
                ShiftInterval.id.in_(normalized_interval_ids),
            )
            .order_by(ShiftInterval.start_time.asc(), ShiftInterval.id.asc())
        ).scalars().all()
        interval_titles = [str(row.title or "").strip() for row in interval_rows if str(row.title or "").strip()]
        normalized_interval_ids = [int(row.id) for row in interval_rows]

    period_label = _format_schedule_period_label(view=view, period_start=period_start, period_end=period_end)
    filters_text = _build_schedule_export_filters_text(
        view=view,
        interval_titles=interval_titles,
        staffing_state=staffing_state,
        shift_slot=normalized_shift_slot,
    )
    deep_link_path = _build_staff_shifts_deep_link_path(
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        interval_ids=normalized_interval_ids,
        staffing_state=staffing_state,
        shift_slot=normalized_shift_slot,
    )
    share_title = f"График смен · {venue.name}"
    share_text = f"{venue.name}\n{period_label}\n{filters_text}"
    share_token = _build_staff_shifts_share_token(
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        interval_ids=normalized_interval_ids,
        staffing_state=staffing_state,
        shift_slot=normalized_shift_slot,
    )
    share_path = _build_staff_shifts_share_path(share_token)
    share_url = _build_staff_shifts_share_url(request=request, token=share_token)

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "view": view,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_label": period_label,
        "filters_text": filters_text,
        "interval_titles": interval_titles,
        "staffing_state": staffing_state,
        "shift_slot": normalized_shift_slot,
        "shift_slot_label": _shift_slot_label(normalized_shift_slot) if normalized_shift_slot else None,
        "logo_url": None,
        "app_logo_url": "/logo.png",
        "deep_link_path": deep_link_path,
        "deep_link_url": f"{_frontend_base_url()}{deep_link_path}",
        "share_title": share_title,
        "share_text": share_text,
        "share_token": share_token,
        "share_path": share_path,
        "share_url": share_url,
        "telegram_share_url": _build_telegram_share_url(url=share_url, text=share_text),
        "share_expires_in": _SCHEDULE_SHARE_TTL_SECONDS,
    }


@router.get("/{venue_id}/shifts")
def list_shifts(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    interval_ids: list[int] | None = Query(default=None),
    staffing_state: str = Query(default="all", pattern="^(all|staffed|unstaffed)$"),
    shift_slot: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List shifts for a venue.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    normalized_shift_slot = _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=shift_slot) if shift_slot else None

    stmt = select(Shift).where(Shift.venue_id == venue_id, Shift.is_active.is_(True))
    if normalized_shift_slot is not None:
        stmt = stmt.where(Shift.shift_slot == normalized_shift_slot)

    if interval_ids:
        normalized_ids = sorted({int(x) for x in interval_ids if int(x) > 0})
        if normalized_ids:
            stmt = stmt.where(Shift.interval_id.in_(normalized_ids))

    if month:
        try:
            y, m = month.split("-")
            y = int(y)
            m = int(m)
            start = date(y, m, 1)
            if m == 12:
                end = date(y + 1, 1, 1)
            else:
                end = date(y, m + 1, 1)
        except Exception:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        stmt = stmt.where(Shift.date >= start, Shift.date < end)
    else:
        if date_from:
            stmt = stmt.where(Shift.date >= date_from)
        if date_to:
            stmt = stmt.where(Shift.date <= date_to)

    assignment_exists = sa.exists(
        select(1)
        .select_from(ShiftAssignment)
        .where(ShiftAssignment.shift_id == Shift.id)
    )
    if staffing_state == "staffed":
        stmt = stmt.where(assignment_exists)
    elif staffing_state == "unstaffed":
        stmt = stmt.where(sa.not_(assignment_exists))

    shifts = db.execute(stmt.order_by(Shift.date.asc(), Shift.id.asc())).scalars().all()

    # preload daily reports for these shift dates (for report_exists + salary calculation)
    shift_dates = {s.date for s in shifts}
    report_by_date: dict[date, DailyReport] = {}
    if shift_dates:
        report_stmt = select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date.in_(shift_dates))
        if normalized_shift_slot is not None:
            report_stmt = report_stmt.where(DailyReport.shift_slot == normalized_shift_slot)
        rrows = db.execute(report_stmt).scalars().all()
        report_by_date = {r.date: r for r in rrows}

    show_revenue = _has_revenue_view_access(db, venue_id=venue_id, user=user)

    # preload intervals
    interval_ids = {s.interval_id for s in shifts}
    intervals = {}
    if interval_ids:
        rows = db.execute(select(ShiftInterval).where(ShiftInterval.id.in_(interval_ids))).scalars().all()
        intervals = {r.id: r for r in rows}

    # preload assignments
    shift_ids = [s.id for s in shifts]
    assignments_by_shift = {sid: [] for sid in shift_ids}
    if shift_ids:
        arows = db.execute(
            select(
                ShiftAssignment.shift_id,
                ShiftAssignment.member_user_id,
                ShiftAssignment.venue_position_id,
                VenuePosition.title,
                User.tg_username,
                User.full_name,
                User.short_name,
            )
            .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
            .join(User, User.id == ShiftAssignment.member_user_id)
            .where(ShiftAssignment.shift_id.in_(shift_ids))
            .order_by(ShiftAssignment.id.asc())
        ).all()
        for r in arows:
            assignments_by_shift.setdefault(r.shift_id, []).append(
                {
                    "member_user_id": r.member_user_id,
                    "venue_position_id": r.venue_position_id,
                    "position_title": r.title,
                    "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                "full_name": r.full_name,
                "short_name": r.short_name,
                }
            )

    def interval_payload(interval_id: int):
        it = intervals.get(interval_id)
        if not it:
            return None
        return {
            "id": it.id,
            "title": it.title,
            "start_time": it.start_time.strftime("%H:%M"),
            "end_time": it.end_time.strftime("%H:%M"),
        }

    # preload my assignments (so we can compute my_salary without leaking others' rates)
    my_assignment_by_shift: dict[int, dict] = {}
    if shift_ids:
        my_rows = db.execute(
            select(
                ShiftAssignment.shift_id,
                VenuePosition.rate,
                VenuePosition.percent,
            )
            .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
            .where(
                ShiftAssignment.shift_id.in_(shift_ids),
                ShiftAssignment.member_user_id == user.id,
            )
        ).all()
        my_assignment_by_shift = {r.shift_id: {"rate": int(r.rate), "percent": int(r.percent)} for r in my_rows}

    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "interval": interval_payload(s.interval_id),
            "interval_id": s.interval_id,
            "shift_slot": normalize_shift_slot(getattr(s, "shift_slot", None)),
            "shift_slot_label": _shift_slot_label(getattr(s, "shift_slot", None)),
            "is_active": bool(s.is_active),
            "assignments": assignments_by_shift.get(s.id, []),
            "report_exists": bool(report_by_date.get(s.date)),
            "report_closed": bool(report_by_date.get(s.date) and str(getattr(report_by_date.get(s.date), "status", "") or "").upper() == "CLOSED"),
            "revenue_total": (
                report_by_date.get(s.date).revenue_total
                if (show_revenue and report_by_date.get(s.date))
                else None
            ),
            "my_salary": (
                (my_assignment_by_shift.get(s.id)["rate"] + (my_assignment_by_shift.get(s.id)["percent"] / 100.0) * report_by_date.get(s.date).revenue_total)
                if (report_by_date.get(s.date) and my_assignment_by_shift.get(s.id))
                else None
            ),
            "my_tips_share": (
                (report_by_date.get(s.date).tips_total / max(1, len({a["member_user_id"] for a in assignments_by_shift.get(s.id, [])})))
                if (report_by_date.get(s.date) and my_assignment_by_shift.get(s.id) and report_by_date.get(s.date).tips_total)
                else 0
            ),
        }
        for s in shifts
    ]


@router.post("/{venue_id}/shifts")
def create_shift(
    venue_id: int,
    payload: ShiftCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a shift for a specific date+interval (schedule editor only)."""
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    interval = db.execute(
        select(ShiftInterval).where(
            ShiftInterval.id == payload.interval_id,
            ShiftInterval.venue_id == venue_id,
            ShiftInterval.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if interval is None:
        raise HTTPException(status_code=400, detail="Shift interval not found")

    slot = _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=payload.shift_slot)

    obj = Shift(
        venue_id=venue_id,
        date=payload.date,
        interval_id=payload.interval_id,
        shift_slot=slot,
        is_active=payload.is_active,
        created_by_user_id=user.id,
    )

    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # likely unique constraint
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")

    db.refresh(obj)
    return {"id": obj.id, "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None))}


@router.patch("/{venue_id}/shifts/{shift_id}")
def update_shift(
    venue_id: int,
    shift_id: int,
    payload: ShiftUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    previous_date = obj.date
    date_changed = payload.date is not None and payload.date != obj.date
    interval_changed = payload.interval_id is not None and payload.interval_id != obj.interval_id
    active_changed = payload.is_active is not None and payload.is_active != obj.is_active
    slot_changed = payload.shift_slot is not None and normalize_shift_slot(payload.shift_slot) != normalize_shift_slot(getattr(obj, "shift_slot", None))

    if payload.date is not None:
        obj.date = payload.date
    if payload.interval_id is not None:
        interval = db.execute(
            select(ShiftInterval).where(
                ShiftInterval.id == payload.interval_id,
                ShiftInterval.venue_id == venue_id,
                ShiftInterval.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if interval is None:
            raise HTTPException(status_code=400, detail="Shift interval not found")
        obj.interval_id = payload.interval_id
    if payload.shift_slot is not None:
        obj.shift_slot = _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=payload.shift_slot)
    if payload.is_active is not None:
        obj.is_active = payload.is_active

    try:
        # If shift start time changed - allow reminders to be re-sent.
        if date_changed or interval_changed or slot_changed:
            db.execute(
                update(ShiftAssignment)
                .where(ShiftAssignment.shift_id == shift_id)
                .values(reminder_sent_at=None)
            )
        if date_changed or interval_changed or slot_changed or active_changed:
            _recalculate_payroll_for_dates(
                db,
                venue_id=venue_id,
                target_dates=[previous_date, obj.date],
                calculated_by_user_id=user.id,
                trigger_reason="shift_updated",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")

    return {"ok": True, "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None))}


@router.delete("/{venue_id}/shifts/{shift_id}")
def delete_shift(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    shift_date = obj.date
    obj.is_active = False
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[shift_date],
        calculated_by_user_id=user.id,
        trigger_reason="shift_deleted",
    )
    db.commit()
    return {"ok": True}

@router.get("/{venue_id}/shifts/{shift_id}")
def get_shift(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    interval = db.execute(select(ShiftInterval).where(ShiftInterval.id == obj.interval_id)).scalar_one()
    assigns = db.execute(
        select(
            ShiftAssignment.id,
            ShiftAssignment.member_user_id,
            ShiftAssignment.venue_position_id,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
            VenuePosition.title.label("position_title"),
        )
        .join(User, User.id == ShiftAssignment.member_user_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .where(ShiftAssignment.shift_id == obj.id)
        .order_by(User.id.asc())
    ).all()

    return {
        "id": obj.id,
        "venue_id": obj.venue_id,
        "date": obj.date.isoformat(),
        "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None)),
        "shift_slot_label": _shift_slot_label(getattr(obj, "shift_slot", None)),
        "is_active": bool(obj.is_active),
        "interval": {
            "id": interval.id,
            "title": interval.title,
            "start_time": interval.start_time.isoformat(timespec="minutes"),
            "end_time": interval.end_time.isoformat(timespec="minutes"),
        },
        "assignments": [
            {
                "id": r.id,
                "member_user_id": r.member_user_id,
                "venue_position_id": r.venue_position_id,
                "member": {"user_id": r.member_user_id, "tg_user_id": r.tg_user_id, "tg_username": r.tg_username},
                "position_title": r.position_title,
            }
            for r in assigns
        ],
    }


@router.post("/{venue_id}/shifts/{shift_id}/assignments")
def add_shift_assignment(
    venue_id: int,
    shift_id: int,
    payload: ShiftAssignmentAddIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Assign one venue position (member) to a shift.

    You can call this multiple times to assign several people to the same shift.
    """
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    shift = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))
    ).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.id == payload.venue_position_id,
            VenuePosition.venue_id == venue_id,
        )
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=400, detail="Position not found")

    # validate member exists & active in venue
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == pos.member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=400, detail="Member not found in venue")

    existing = db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.member_user_id == pos.member_user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "mode": "exists"}

    a = ShiftAssignment(
        shift_id=shift_id,
        member_user_id=pos.member_user_id,
        venue_position_id=pos.id,
    )
    db.add(a)

    closed_report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == shift.date,
            DailyReport.status == "CLOSED",
        )
    ).scalar_one_or_none()
    if closed_report is not None:
        venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
        if venue is not None:
            _rebuild_report_tip_allocations(db, report=closed_report, venue=venue)

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[shift.date],
        calculated_by_user_id=user.id,
        trigger_reason="shift_assignment_added",
    )
    db.commit()
    db.refresh(a)
    return {"id": a.id}


@router.delete("/{venue_id}/shifts/{shift_id}/assignments/{member_user_id}")
def remove_shift_assignment(
    venue_id: int,
    shift_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    a = db.execute(
        select(ShiftAssignment).join(Shift, Shift.id == ShiftAssignment.shift_id).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.member_user_id == member_user_id,
            Shift.venue_id == venue_id,
        )
    ).scalar_one_or_none()

    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    shift_date = db.execute(
        select(Shift.date).where(Shift.id == shift_id, Shift.venue_id == venue_id)
    ).scalar_one_or_none()
    db.delete(a)
    if shift_date is not None:
        closed_report = db.execute(
            select(DailyReport).where(
                DailyReport.venue_id == venue_id,
                DailyReport.date == shift_date,
                DailyReport.status == "CLOSED",
            )
        ).scalar_one_or_none()
        if closed_report is not None:
            venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
            if venue is not None:
                _rebuild_report_tip_allocations(db, report=closed_report, venue=venue)
        _recalculate_payroll_for_dates(
            db,
            venue_id=venue_id,
            target_dates=[shift_date],
            calculated_by_user_id=user.id,
            trigger_reason="shift_assignment_removed",
        )
    db.commit()
    return {"ok": True}



class ShiftCommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/{venue_id}/shifts/{shift_id}/comments")
def list_shift_comments(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    rows = db.execute(
        select(ShiftComment, User)
        .join(User, User.id == ShiftComment.author_user_id)
        .where(ShiftComment.shift_id == shift_id)
        .order_by(ShiftComment.created_at.asc(), ShiftComment.id.asc())
    ).all()

    return [
        {
            "id": c.id,
            "shift_id": c.shift_id,
            "text": c.text,
            "created_at": c.created_at.isoformat(),
            "author": {
                "id": u.id,
                "tg_username": u.tg_username,
                "full_name": u.full_name,
                "short_name": u.short_name,
            },
        }
        for (c, u) in rows
    ]


@router.post("/{venue_id}/shifts/{shift_id}/comments")
def add_shift_comment(
    venue_id: int,
    shift_id: int,
    payload: ShiftCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")

    c = ShiftComment(shift_id=shift_id, author_user_id=user.id, text=text)
    db.add(c)
    db.commit()
    db.refresh(c)

    return {
        "id": c.id,
        "shift_id": c.shift_id,
        "text": c.text,
        "created_at": c.created_at.isoformat(),
        "author": {
            "id": user.id,
            "tg_username": user.tg_username,
            "full_name": user.full_name,
            "short_name": user.short_name,
        },
    }
