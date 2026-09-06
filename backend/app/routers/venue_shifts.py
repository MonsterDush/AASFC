import re
from datetime import datetime

from fastapi import APIRouter

from app.routers.venue_core import (
    BackgroundTasks,
    BaseModel,
    DailyReport,
    DailyReportTipAllocation,
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
from app.models.shift_comment_mention import ShiftCommentMention
from app.models.shift_swap_request import ShiftSwapRequest
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
from app.routers.venue_shift_notifications import _enqueue_shift_comment_job
from app.routers.venue_economics_notifications import process_pending_notification_jobs_once
from app.routers.venue_reports import (
    _rebuild_closed_report_tip_allocations_for_keys,
    _rebuild_report_tip_allocations,
)
from app.routers.venue_schedule_templates import _normalize_shift_slot_for_venue, _shift_slot_label
from app.services.venue_member_names import load_member_display_names, load_owner_notes, owner_display_name
from app.services.shift_interval_scope import interval_scope_payloads, require_interval_position_match


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


def _require_shift_position_match(db: Session, *, venue_id: int, shift: Shift, position: VenuePosition) -> None:
    interval = db.execute(
        select(ShiftInterval).where(ShiftInterval.id == int(shift.interval_id), ShiftInterval.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if interval is not None:
        require_interval_position_match(db, venue_id=venue_id, interval=interval, position=position)


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
    shift_slot: str | None = Query(default=None, pattern="^(DAY|NIGHT)$"),
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

    normalized_shift_slot = (
        _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=shift_slot) if shift_slot else None
    )

    normalized_interval_ids = sorted({int(item) for item in (interval_ids or []) if int(item) > 0})
    interval_titles: list[str] = []
    if normalized_interval_ids:
        interval_rows = (
            db.execute(
                select(ShiftInterval)
                .where(
                    ShiftInterval.venue_id == venue_id,
                    ShiftInterval.id.in_(normalized_interval_ids),
                )
                .order_by(ShiftInterval.start_time.asc(), ShiftInterval.id.asc())
            )
            .scalars()
            .all()
        )
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
    shift_slot: str | None = Query(default=None, pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List shifts for a venue.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    normalized_shift_slot = (
        _normalize_shift_slot_for_venue(db, venue_id=venue_id, shift_slot=shift_slot) if shift_slot else None
    )

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

    assignment_exists = sa.exists(select(1).select_from(ShiftAssignment).where(ShiftAssignment.shift_id == Shift.id))
    if staffing_state == "staffed":
        stmt = stmt.where(assignment_exists)
    elif staffing_state == "unstaffed":
        stmt = stmt.where(sa.not_(assignment_exists))

    shifts = db.execute(stmt.order_by(Shift.date.asc(), Shift.id.asc())).scalars().all()

    # Preload reports by date and slot. A venue can have separate DAY and NIGHT
    # reports for the same calendar date.
    shift_dates = {s.date for s in shifts}
    report_by_date_slot: dict[tuple[date, str], DailyReport] = {}
    if shift_dates:
        report_stmt = select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date.in_(shift_dates))
        if normalized_shift_slot is not None:
            report_stmt = report_stmt.where(DailyReport.shift_slot == normalized_shift_slot)
        rrows = db.execute(report_stmt).scalars().all()
        report_by_date_slot = {(r.date, normalize_shift_slot(getattr(r, "shift_slot", None))): r for r in rrows}

    show_revenue = _has_revenue_view_access(db, venue_id=venue_id, user=user)

    # preload intervals
    interval_ids = {s.interval_id for s in shifts}
    intervals = {}
    interval_position_titles: dict[int, str] = {}
    if interval_ids:
        rows = db.execute(select(ShiftInterval).where(ShiftInterval.id.in_(interval_ids))).scalars().all()
        intervals = {r.id: r for r in rows}
        required_position_ids = sorted({int(r.position_id) for r in rows if r.position_id is not None})
        if required_position_ids:
            position_rows = db.execute(
                select(VenuePosition.id, VenuePosition.title).where(
                    VenuePosition.venue_id == venue_id,
                    VenuePosition.id.in_(required_position_ids),
                )
            ).all()
            interval_position_titles = {int(row.id): str(row.title or "") for row in position_rows}

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
        owner_notes = load_owner_notes(
            db,
            venue_id=venue_id,
            viewer=user,
            member_user_ids=[int(row.member_user_id) for row in arows],
        )
        member_display_names = load_member_display_names(
            db,
            venue_id=venue_id,
            member_user_ids=[int(row.member_user_id) for row in arows],
        )
        for r in arows:
            owner_note = owner_notes.get(int(r.member_user_id))
            display_name_override = member_display_names.get(int(r.member_user_id))
            assignments_by_shift.setdefault(r.shift_id, []).append(
                {
                    "member_user_id": r.member_user_id,
                    "venue_position_id": r.venue_position_id,
                    "position_title": r.title,
                    "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                    "owner_note": owner_note,
                    "display_name": owner_display_name(
                        owner_note=display_name_override,
                        short_name=r.short_name,
                        full_name=r.full_name,
                        tg_username=r.tg_username,
                        user_id=r.member_user_id,
                    ),
                }
            )

    interval_scopes = interval_scope_payloads(db, venue_id=venue_id, intervals=list(intervals.values()))

    def interval_payload(interval_id: int):
        it = intervals.get(interval_id)
        if not it:
            return None
        return {
            "id": it.id,
            "title": it.title,
            "start_time": it.start_time.strftime("%H:%M"),
            "end_time": it.end_time.strftime("%H:%M"),
            "position_id": int(it.position_id) if it.position_id is not None else None,
            **interval_scopes[it.id],
            "position_title": (
                interval_position_titles.get(int(it.position_id)) if it.position_id is not None else None
            ),
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

    my_tip_by_report_id: dict[int, int] = {}
    report_ids = sorted({int(report.id) for report in report_by_date_slot.values()})
    if report_ids:
        tip_rows = db.execute(
            select(DailyReportTipAllocation.report_id, DailyReportTipAllocation.amount).where(
                DailyReportTipAllocation.report_id.in_(report_ids),
                DailyReportTipAllocation.user_id == user.id,
            )
        ).all()
        my_tip_by_report_id = {int(row.report_id): int(row.amount or 0) for row in tip_rows}

    def report_for_shift(shift: Shift) -> DailyReport | None:
        return report_by_date_slot.get((shift.date, normalize_shift_slot(getattr(shift, "shift_slot", None))))

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
            "report_exists": bool(report_for_shift(s)),
            "report_closed": bool(
                report_for_shift(s) and str(getattr(report_for_shift(s), "status", "") or "").upper() == "CLOSED"
            ),
            "revenue_total": (report_for_shift(s).revenue_total if (show_revenue and report_for_shift(s)) else None),
            "my_salary": (
                (
                    my_assignment_by_shift.get(s.id)["rate"]
                    + (my_assignment_by_shift.get(s.id)["percent"] / 100.0) * report_for_shift(s).revenue_total
                )
                if (report_for_shift(s) and my_assignment_by_shift.get(s.id))
                else None
            ),
            "my_tips_share": (
                my_tip_by_report_id.get(int(report_for_shift(s).id), 0)
                if report_for_shift(s) and my_assignment_by_shift.get(s.id)
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

    position = None
    if payload.venue_position_id is not None:
        position = db.execute(
            select(VenuePosition)
            .join(
                VenueMember,
                (VenueMember.venue_id == VenuePosition.venue_id)
                & (VenueMember.user_id == VenuePosition.member_user_id),
            )
            .where(
                VenuePosition.id == payload.venue_position_id,
                VenuePosition.venue_id == venue_id,
                VenuePosition.is_active.is_(True),
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if position is None:
            raise HTTPException(status_code=400, detail="Member position not found in venue")
        require_interval_position_match(db, venue_id=venue_id, interval=interval, position=position)

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
        db.flush()
        if position is not None:
            db.add(
                ShiftAssignment(shift_id=obj.id, member_user_id=position.member_user_id, venue_position_id=position.id)
            )
            db.flush()
            _rebuild_closed_report_tip_allocations_for_keys(
                db,
                venue_id=venue_id,
                report_keys={(obj.date, slot)},
            )
            _recalculate_payroll_for_dates(
                db,
                venue_id=venue_id,
                target_dates=[obj.date],
                calculated_by_user_id=user.id,
                trigger_reason="shift_assignment_added",
            )
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")
    except Exception:
        db.rollback()
        raise

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

    obj = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    previous_date = obj.date
    previous_slot = normalize_shift_slot(getattr(obj, "shift_slot", None))
    date_changed = payload.date is not None and payload.date != obj.date
    interval_changed = payload.interval_id is not None and payload.interval_id != obj.interval_id
    active_changed = payload.is_active is not None and payload.is_active != obj.is_active
    slot_changed = payload.shift_slot is not None and normalize_shift_slot(payload.shift_slot) != normalize_shift_slot(
        getattr(obj, "shift_slot", None)
    )
    normalized_payload_slot: str | None = None
    if payload.shift_slot is not None:
        normalized_payload_slot = _normalize_shift_slot_for_venue(
            db,
            venue_id=venue_id,
            shift_slot=payload.shift_slot,
        )
    elif payload.is_active is True and normalize_shift_slot(getattr(obj, "shift_slot", None)) == "NIGHT":
        # Inactive NIGHT rows may remain as history after night mode is disabled.
        # They must not be reactivated without enabling night shifts again.
        _normalize_shift_slot_for_venue(
            db,
            venue_id=venue_id,
            shift_slot=getattr(obj, "shift_slot", None),
        )

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
    if normalized_payload_slot is not None:
        obj.shift_slot = normalized_payload_slot
    if payload.is_active is not None:
        obj.is_active = payload.is_active

    try:
        # If shift start time changed - allow reminders to be re-sent.
        if date_changed or interval_changed or slot_changed:
            db.execute(
                update(ShiftAssignment).where(ShiftAssignment.shift_id == shift_id).values(reminder_sent_at=None)
            )
        if date_changed or interval_changed or slot_changed or active_changed:
            if date_changed or slot_changed or active_changed:
                _rebuild_closed_report_tip_allocations_for_keys(
                    db,
                    venue_id=venue_id,
                    report_keys={
                        (previous_date, previous_slot),
                        (obj.date, normalize_shift_slot(getattr(obj, "shift_slot", None))),
                    },
                )
            _recalculate_payroll_for_dates(
                db,
                venue_id=venue_id,
                target_dates=[previous_date, obj.date],
                calculated_by_user_id=user.id,
                trigger_reason="shift_updated",
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None))}


@router.delete("/{venue_id}/shifts/{shift_id}")
def delete_shift(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    obj = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    shift_date = obj.date
    shift_slot = normalize_shift_slot(getattr(obj, "shift_slot", None))
    obj.is_active = False
    db.execute(
        update(ShiftSwapRequest)
        .where(
            ShiftSwapRequest.shift_id == int(shift_id),
            ShiftSwapRequest.status == "OPEN",
        )
        .values(
            status="CANCELLED",
            manager_comment="Смена удалена из графика",
            decided_by_user_id=int(user.id),
            decided_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    _rebuild_closed_report_tip_allocations_for_keys(
        db,
        venue_id=venue_id,
        report_keys={(shift_date, shift_slot)},
    )
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
    required_position_title = None
    if interval.position_id is not None:
        required_position_title = db.execute(
            select(VenuePosition.title).where(
                VenuePosition.id == int(interval.position_id),
                VenuePosition.venue_id == venue_id,
            )
        ).scalar_one_or_none()

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
    owner_notes = load_owner_notes(
        db,
        venue_id=venue_id,
        viewer=user,
        member_user_ids=[int(row.member_user_id) for row in assigns],
    )

    member_display_names = load_member_display_names(
        db, venue_id=venue_id, member_user_ids=[int(row.member_user_id) for row in assigns]
    )
    scope = interval_scope_payloads(db, venue_id=venue_id, intervals=[interval])[interval.id]

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
            "position_id": int(interval.position_id) if interval.position_id is not None else None,
            "position_title": required_position_title,
            **scope,
        },
        "assignments": [
            {
                "id": r.id,
                "member_user_id": r.member_user_id,
                "venue_position_id": r.venue_position_id,
                "member": {
                    "user_id": r.member_user_id,
                    "tg_user_id": r.tg_user_id,
                    "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                    "owner_note": owner_notes.get(int(r.member_user_id)),
                    "display_name": owner_display_name(
                        owner_note=member_display_names.get(int(r.member_user_id)),
                        short_name=r.short_name,
                        full_name=r.full_name,
                        tg_username=r.tg_username,
                        user_id=r.member_user_id,
                    ),
                },
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
            VenuePosition.is_active.is_(True),
            VenuePosition.member_user_id.is_not(None),
        )
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=400, detail="Position not found")

    _require_shift_position_match(
        db,
        venue_id=venue_id,
        shift=shift,
        position=pos,
    )

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
        if int(existing.venue_position_id) == int(pos.id):
            return {"id": existing.id, "mode": "exists"}
        existing.venue_position_id = int(pos.id)
        existing.reminder_sent_at = None
        closed_report = db.execute(
            select(DailyReport).where(
                DailyReport.venue_id == venue_id,
                DailyReport.date == shift.date,
                DailyReport.shift_slot == normalize_shift_slot(getattr(shift, "shift_slot", None)),
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
            trigger_reason="shift_assignment_position_changed",
        )
        db.commit()
        return {"id": existing.id, "mode": "position_updated", "venue_position_id": int(pos.id)}

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
            DailyReport.shift_slot == normalize_shift_slot(getattr(shift, "shift_slot", None)),
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
        select(ShiftAssignment)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.member_user_id == member_user_id,
            Shift.venue_id == venue_id,
        )
    ).scalar_one_or_none()

    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    shift_row = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id)).scalar_one_or_none()
    db.execute(
        update(ShiftSwapRequest)
        .where(
            ShiftSwapRequest.assignment_id == int(a.id),
            ShiftSwapRequest.status == "OPEN",
        )
        .values(
            status="CANCELLED",
            manager_comment="Назначение удалено управляющим",
            decided_by_user_id=int(user.id),
            decided_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db.delete(a)
    if shift_row is not None:
        shift_date = shift_row.date
        closed_report = db.execute(
            select(DailyReport).where(
                DailyReport.venue_id == venue_id,
                DailyReport.date == shift_date,
                DailyReport.shift_slot == normalize_shift_slot(getattr(shift_row, "shift_slot", None)),
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


_MAX_SHIFT_COMMENT_MENTIONS = 20


class ShiftCommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    mentioned_user_ids: list[int] = Field(default_factory=list, max_length=_MAX_SHIFT_COMMENT_MENTIONS)
    reply_to_comment_id: int | None = Field(default=None, gt=0)


def _shift_comment_user_display_name(user: User) -> str:
    value = user.short_name or user.full_name or (f"@{user.tg_username}" if user.tg_username else None)
    return str(value or f"Сотрудник #{int(user.id)}").strip()


def _shift_comment_user_brief(user: User, *, owner_note: str | None = None) -> dict:
    return {
        "id": int(user.id),
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
        "display_name": owner_display_name(
            owner_note=owner_note,
            short_name=user.short_name,
            full_name=user.full_name,
            tg_username=user.tg_username,
            user_id=user.id,
        ),
    }


def _normalize_shift_comment_mention_ids(values: list[int] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for raw in values or []:
        value = int(raw)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if len(normalized) > _MAX_SHIFT_COMMENT_MENTIONS:
        raise HTTPException(
            status_code=400, detail=f"Можно упомянуть не более {_MAX_SHIFT_COMMENT_MENTIONS} сотрудников"
        )
    return normalized


def _shift_comment_has_mention_token(text: str, user: User, *, display_name: str | None = None) -> bool:
    labels = [
        display_name,
        _shift_comment_user_display_name(user),
        str(user.tg_username or "").lstrip("@").strip(),
    ]
    for label in labels:
        if not label:
            continue
        token = f"@{label.lstrip('@')}"
        if re.search(rf"(?<![\w@]){re.escape(token)}(?!\w)", str(text or ""), flags=re.IGNORECASE):
            return True
    return False


def _load_shift_comment_mentionable_members(
    db: Session,
    *,
    venue_id: int,
    exclude_user_id: int | None = None,
) -> list[tuple[User, str, str | None]]:
    stmt = (
        select(User, VenueMember.venue_role, VenuePosition.title)
        .join(
            VenueMember,
            (VenueMember.user_id == User.id)
            & (VenueMember.venue_id == int(venue_id))
            & VenueMember.is_active.is_(True),
        )
        .outerjoin(
            VenuePosition,
            (VenuePosition.member_user_id == User.id)
            & (VenuePosition.venue_id == int(venue_id))
            & VenuePosition.is_active.is_(True),
        )
        .order_by(
            sa.func.coalesce(User.short_name, User.full_name, User.tg_username, sa.cast(User.id, sa.String)).asc(),
            User.id.asc(),
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != int(exclude_user_id))
    grouped: dict[int, tuple[User, str, set[str]]] = {}
    for member, venue_role, position_title in db.execute(stmt).all():
        item = grouped.setdefault(int(member.id), (member, venue_role, set()))
        if position_title:
            item[2].add(str(position_title))
    return [
        (member, venue_role, ", ".join(sorted(titles, key=str.casefold)) or None)
        for member, venue_role, titles in grouped.values()
    ]


def _serialize_shift_comment(
    comment: ShiftComment,
    author: User,
    *,
    mention_users: list[User] | None = None,
    parent: tuple[ShiftComment, User] | None = None,
    owner_notes: dict[int, str] | None = None,
) -> dict:
    private_notes = owner_notes or {}
    reply_to = None
    if parent is not None:
        parent_comment, parent_author = parent
        reply_to = {
            "id": int(parent_comment.id),
            "text": parent_comment.text,
            "author": _shift_comment_user_brief(parent_author, owner_note=private_notes.get(int(parent_author.id))),
        }
    return {
        "id": int(comment.id),
        "shift_id": int(comment.shift_id),
        "text": comment.text,
        "created_at": comment.created_at.isoformat(),
        "author": _shift_comment_user_brief(author, owner_note=private_notes.get(int(author.id))),
        "mentions": [
            {
                "user_id": int(mentioned_user.id),
                "display_name": owner_display_name(
                    owner_note=private_notes.get(int(mentioned_user.id)),
                    short_name=mentioned_user.short_name,
                    full_name=mentioned_user.full_name,
                    tg_username=mentioned_user.tg_username,
                    user_id=mentioned_user.id,
                ),
            }
            for mentioned_user in (mention_users or [])
        ],
        "reply_to": reply_to,
    }


@router.get("/{venue_id}/shifts/{shift_id}/mentionable-members")
def list_shift_comment_mentionable_members(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)
    shift = db.execute(
        select(Shift).where(
            Shift.id == shift_id,
            Shift.venue_id == venue_id,
            Shift.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    rows = _load_shift_comment_mentionable_members(
        db,
        venue_id=venue_id,
        exclude_user_id=int(user.id),
    )
    names = load_member_display_names(db, venue_id=venue_id, member_user_ids=[member.id for member, _, _ in rows])
    return [
        {
            "user_id": int(member.id),
            "display_name": _shift_comment_user_brief(member, owner_note=names.get(int(member.id)))["display_name"],
            "tg_username": member.tg_username,
            "position_title": position_title,
            "venue_role": venue_role,
        }
        for member, venue_role, position_title in rows
    ]


@router.get("/{venue_id}/shifts/{shift_id}/comments")
def list_shift_comments(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))
    ).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    rows = db.execute(
        select(ShiftComment, User)
        .join(User, User.id == ShiftComment.author_user_id)
        .where(ShiftComment.shift_id == shift_id)
        .order_by(ShiftComment.created_at.asc(), ShiftComment.id.asc())
    ).all()

    comment_rows = list(rows)
    comment_ids = [int(comment.id) for comment, _ in comment_rows]
    mentions_by_comment: dict[int, list[User]] = {}
    if comment_ids:
        mention_rows = db.execute(
            select(ShiftCommentMention, User)
            .join(User, User.id == ShiftCommentMention.mentioned_user_id)
            .where(ShiftCommentMention.comment_id.in_(comment_ids))
            .order_by(ShiftCommentMention.comment_id.asc(), ShiftCommentMention.id.asc())
        ).all()
        for mention, mentioned_user in mention_rows:
            mentions_by_comment.setdefault(int(mention.comment_id), []).append(mentioned_user)

    rows_by_id = {int(comment.id): (comment, author) for comment, author in comment_rows}
    visible_user_ids = {int(author.id) for _comment, author in comment_rows}
    visible_user_ids.update(int(member.id) for members in mentions_by_comment.values() for member in members)
    owner_notes = load_member_display_names(
        db,
        venue_id=venue_id,
        member_user_ids=visible_user_ids,
    )
    return [
        _serialize_shift_comment(
            comment,
            author,
            mention_users=mentions_by_comment.get(int(comment.id), []),
            parent=rows_by_id.get(int(comment.parent_comment_id)) if comment.parent_comment_id is not None else None,
            owner_notes=owner_notes,
        )
        for comment, author in comment_rows
    ]


@router.post("/{venue_id}/shifts/{shift_id}/comments")
def add_shift_comment(
    venue_id: int,
    shift_id: int,
    payload: ShiftCommentIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(
        select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))
    ).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")

    parent: tuple[ShiftComment, User] | None = None
    if payload.reply_to_comment_id is not None:
        parent = db.execute(
            select(ShiftComment, User)
            .join(User, User.id == ShiftComment.author_user_id)
            .where(
                ShiftComment.id == int(payload.reply_to_comment_id),
                ShiftComment.shift_id == int(shift_id),
            )
        ).first()
        if parent is None:
            raise HTTPException(status_code=400, detail="Комментарий для ответа не найден в этой смене")

    mention_ids = _normalize_shift_comment_mention_ids(payload.mentioned_user_ids)
    mentionable_rows = _load_shift_comment_mentionable_members(
        db,
        venue_id=venue_id,
        exclude_user_id=int(user.id),
    )
    mentionable_users = {int(member.id): member for member, _, _ in mentionable_rows}
    invalid_ids = [mentioned_user_id for mentioned_user_id in mention_ids if mentioned_user_id not in mentionable_users]
    if invalid_ids:
        raise HTTPException(status_code=400, detail="Некоторые упомянутые сотрудники не входят в это заведение")
    mention_names = load_member_display_names(db, venue_id=venue_id, member_user_ids=mention_ids)
    missing_tokens = [
        mentioned_user_id
        for mentioned_user_id in mention_ids
        if not _shift_comment_has_mention_token(
            text, mentionable_users[mentioned_user_id], display_name=mention_names.get(mentioned_user_id)
        )
    ]
    if missing_tokens:
        raise HTTPException(
            status_code=400, detail="Упоминание удалено из текста; выберите сотрудника через подсказку ещё раз"
        )

    c = ShiftComment(
        shift_id=shift_id,
        author_user_id=user.id,
        parent_comment_id=int(payload.reply_to_comment_id) if payload.reply_to_comment_id is not None else None,
        text=text,
    )
    db.add(c)
    db.flush()
    mention_users = [mentionable_users[mentioned_user_id] for mentioned_user_id in mention_ids]
    for mentioned_user in mention_users:
        db.add(
            ShiftCommentMention(
                comment_id=int(c.id),
                mentioned_user_id=int(mentioned_user.id),
            )
        )
    _enqueue_shift_comment_job(db, venue_id=venue_id, comment_id=int(c.id))
    db.commit()
    db.refresh(c)
    background_tasks.add_task(process_pending_notification_jobs_once, 10)

    return _serialize_shift_comment(
        c,
        user,
        mention_users=mention_users,
        parent=parent,
        owner_notes=load_member_display_names(
            db,
            venue_id=venue_id,
            member_user_ids=[
                int(user.id),
                *[int(member.id) for member in mention_users],
                *([int(parent[1].id)] if parent is not None else []),
            ],
        ),
    )
