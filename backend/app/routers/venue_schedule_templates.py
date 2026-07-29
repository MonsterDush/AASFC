from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    Query,
    Session,
    Shift,
    ShiftInterval,
    ShiftScheduleTemplate,
    ShiftScheduleTemplateItem,
    User,
    Venue,
    _require_active_member_or_admin,
    date,
    delete,
    func,
    get_current_user,
    get_db,
    normalize_shift_slot,
    select,
    timedelta,
)
from app.schemas.venue_shifts import (
    ShiftScheduleTemplateApplyIn,
    ShiftScheduleTemplateCreateIn,
    ShiftScheduleTemplateItemIn,
    ShiftScheduleTemplateUpdateIn,
)
from app.routers.venue_permissions import (
    _require_schedule_editor,
)
from app.routers.venue_payroll_support import (
    _recalculate_payroll_for_dates,
)
from app.routers.venue_reports import (
    _rebuild_closed_report_tip_allocations_for_keys,
)


router = APIRouter()


_SHIFT_TEMPLATE_APPLY_MODES = {"SKIP_FILLED_DAYS", "ADD_MISSING", "REPLACE_MONTH"}
_WEEKDAY_TITLES_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}
def _venue_night_shifts_enabled(db: Session, *, venue_id: int) -> bool:
    return bool(
        db.execute(
            select(Venue.night_shifts_enabled).where(Venue.id == int(venue_id))
        ).scalar_one_or_none()
    )


def _normalize_shift_slot_for_venue(db: Session, *, venue_id: int, shift_slot: str | None) -> str:
    slot = normalize_shift_slot(shift_slot)
    if slot == "NIGHT" and not _venue_night_shifts_enabled(db, venue_id=venue_id):
        raise HTTPException(status_code=400, detail="Night shifts are disabled for this venue")
    return slot


def _shift_slot_label(slot: str | None) -> str:
    return "Ночь" if normalize_shift_slot(slot) == "NIGHT" else "День"


def _shift_template_weekday_slot_title(weekday: int, slot: str | None) -> str:
    weekday = int(weekday)
    weekday_title = _WEEKDAY_TITLES_RU.get(weekday, str(weekday))
    if normalize_shift_slot(slot) == "NIGHT":
        return f"Ночь · {weekday_title}"
    return weekday_title


def _normalize_shift_schedule_template_title(title: str) -> str:
    value = str(title or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Template title is required")
    return value


def _ensure_shift_schedule_template_title_unique(
    db: Session,
    *,
    venue_id: int,
    title: str,
    exclude_template_id: int | None = None,
) -> None:
    stmt = select(ShiftScheduleTemplate.id).where(
        ShiftScheduleTemplate.venue_id == venue_id,
        func.lower(ShiftScheduleTemplate.title) == title.lower(),
    )
    if exclude_template_id is not None:
        stmt = stmt.where(ShiftScheduleTemplate.id != exclude_template_id)
    exists_id = db.execute(stmt.limit(1)).scalar_one_or_none()
    if exists_id is not None:
        raise HTTPException(status_code=409, detail="Schedule template with this title already exists")


def _parse_shift_schedule_template_month(month_value: str) -> tuple[date, date, date]:
    try:
        year_text, month_text = str(month_value or "").strip().split("-", 1)
        year = int(year_text)
        month = int(month_text)
        start = date(year, month, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    if month == 12:
        end_exclusive = date(year + 1, 1, 1)
    else:
        end_exclusive = date(year, month + 1, 1)
    return start, end_exclusive, end_exclusive - timedelta(days=1)


def _get_shift_schedule_template_or_404(db: Session, *, venue_id: int, template_id: int) -> ShiftScheduleTemplate:
    obj = db.execute(
        select(ShiftScheduleTemplate).where(
            ShiftScheduleTemplate.id == int(template_id),
            ShiftScheduleTemplate.venue_id == int(venue_id),
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Schedule template not found")
    return obj


def _normalize_shift_schedule_template_items(
    db: Session,
    *,
    venue_id: int,
    raw_items: list[ShiftScheduleTemplateItemIn] | None,
    require_active_intervals: bool = False,
) -> list[dict]:
    items = raw_items or []
    interval_ids = sorted({int(item.interval_id) for item in items if int(item.interval_id) > 0})
    intervals_by_id: dict[int, ShiftInterval] = {}
    if interval_ids:
        stmt = select(ShiftInterval).where(
            ShiftInterval.venue_id == venue_id,
            ShiftInterval.id.in_(interval_ids),
        )
        if require_active_intervals:
            stmt = stmt.where(ShiftInterval.is_active.is_(True))
        rows = db.execute(stmt).scalars().all()
        intervals_by_id = {int(r.id): r for r in rows}

    missing_ids = [iid for iid in interval_ids if iid not in intervals_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Some shift intervals are not available for this venue: {', '.join(map(str, missing_ids))}",
        )

    night_enabled = _venue_night_shifts_enabled(db, venue_id=venue_id)
    normalized: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    order_by_weekday: dict[tuple[int, str], int] = {}
    for item in items:
        weekday = int(item.weekday)
        if weekday < 0 or weekday > 6:
            raise HTTPException(status_code=400, detail="weekday must be in range 0..6")
        interval_id = int(item.interval_id)
        slot = normalize_shift_slot(item.shift_slot)
        if slot == "NIGHT" and not night_enabled:
            raise HTTPException(status_code=400, detail="Night shifts are disabled for this venue")
        key = (weekday, interval_id, slot)
        if key in seen:
            continue
        seen.add(key)
        order_key = (weekday, slot)
        sort_order = order_by_weekday.get(order_key, 0)
        order_by_weekday[order_key] = sort_order + 1
        normalized.append(
            {
                "weekday": weekday,
                "interval_id": interval_id,
                "shift_slot": slot,
                "sort_order": sort_order,
            }
        )
    return normalized


def _replace_shift_schedule_template_items(
    db: Session,
    *,
    template: ShiftScheduleTemplate,
    venue_id: int,
    raw_items: list[ShiftScheduleTemplateItemIn] | None,
) -> None:
    normalized = _normalize_shift_schedule_template_items(db, venue_id=venue_id, raw_items=raw_items)
    db.execute(delete(ShiftScheduleTemplateItem).where(ShiftScheduleTemplateItem.template_id == template.id))
    db.flush()
    for item in normalized:
        db.add(
            ShiftScheduleTemplateItem(
                template_id=template.id,
                weekday=item["weekday"],
                interval_id=item["interval_id"],
                shift_slot=item["shift_slot"],
                sort_order=item["sort_order"],
            )
        )


def _serialize_shift_schedule_template(template: ShiftScheduleTemplate) -> dict:
    items = list(getattr(template, "items", []) or [])
    return {
        "id": int(template.id),
        "venue_id": int(template.venue_id),
        "title": template.title,
        "description": template.description,
        "is_active": bool(template.is_active),
        "created_by_user_id": template.created_by_user_id,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "items": [
            {
                "id": int(item.id),
                "weekday": int(item.weekday),
                "weekday_title": _WEEKDAY_TITLES_RU.get(int(item.weekday), str(item.weekday)),
                "weekday_slot_title": _shift_template_weekday_slot_title(int(item.weekday), getattr(item, "shift_slot", None)),
                "interval_id": int(item.interval_id),
                "shift_slot": normalize_shift_slot(getattr(item, "shift_slot", None)),
                "shift_slot_label": _shift_slot_label(getattr(item, "shift_slot", None)),
                "sort_order": int(item.sort_order or 0),
                "interval": {
                    "id": int(item.interval.id),
                    "title": item.interval.title,
                    "start_time": item.interval.start_time.strftime("%H:%M") if item.interval and item.interval.start_time else None,
                    "end_time": item.interval.end_time.strftime("%H:%M") if item.interval and item.interval.end_time else None,
                    "is_active": bool(item.interval.is_active) if item.interval else False,
                } if getattr(item, "interval", None) is not None else None,
            }
            for item in items
        ],
    }


@router.get("/{venue_id}/shift-schedule-templates")
def list_shift_schedule_templates(
    venue_id: int,
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    stmt = select(ShiftScheduleTemplate).where(ShiftScheduleTemplate.venue_id == venue_id)
    if not include_inactive:
        stmt = stmt.where(ShiftScheduleTemplate.is_active.is_(True))
    rows = db.execute(stmt.order_by(ShiftScheduleTemplate.title.asc(), ShiftScheduleTemplate.id.asc())).scalars().all()
    return [_serialize_shift_schedule_template(row) for row in rows]


@router.post("/{venue_id}/shift-schedule-templates")
def create_shift_schedule_template(
    venue_id: int,
    payload: ShiftScheduleTemplateCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    title = _normalize_shift_schedule_template_title(payload.title)
    _ensure_shift_schedule_template_title_unique(db, venue_id=venue_id, title=title)

    obj = ShiftScheduleTemplate(
        venue_id=venue_id,
        title=title,
        description=(payload.description or None),
        is_active=bool(payload.is_active),
        created_by_user_id=user.id,
    )
    db.add(obj)
    db.flush()
    _replace_shift_schedule_template_items(db, template=obj, venue_id=venue_id, raw_items=payload.items)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(obj)
    return _serialize_shift_schedule_template(obj)


@router.get("/{venue_id}/shift-schedule-templates/{template_id}")
def get_shift_schedule_template(
    venue_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    obj = _get_shift_schedule_template_or_404(db, venue_id=venue_id, template_id=template_id)
    return _serialize_shift_schedule_template(obj)


@router.patch("/{venue_id}/shift-schedule-templates/{template_id}")
def update_shift_schedule_template(
    venue_id: int,
    template_id: int,
    payload: ShiftScheduleTemplateUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)
    obj = _get_shift_schedule_template_or_404(db, venue_id=venue_id, template_id=template_id)

    if payload.title is not None:
        title = _normalize_shift_schedule_template_title(payload.title)
        _ensure_shift_schedule_template_title_unique(db, venue_id=venue_id, title=title, exclude_template_id=template_id)
        obj.title = title
    payload_fields_set = getattr(payload, "model_fields_set", None)
    if payload_fields_set is None:
        payload_fields_set = getattr(payload, "__fields_set__", set())
    if "description" in payload_fields_set:
        obj.description = payload.description or None
    if payload.is_active is not None:
        obj.is_active = bool(payload.is_active)
    if payload.items is not None:
        if not _venue_night_shifts_enabled(db, venue_id=venue_id):
            has_stored_night_items = db.execute(
                select(ShiftScheduleTemplateItem.id)
                .where(
                    ShiftScheduleTemplateItem.template_id == int(obj.id),
                    ShiftScheduleTemplateItem.shift_slot == "NIGHT",
                )
                .limit(1)
            ).scalar_one_or_none() is not None
            if has_stored_night_items:
                raise HTTPException(
                    status_code=409,
                    detail="В шаблоне сохранены ночные интервалы. Сначала включите ночные смены, затем измените шаблон.",
                )
        _replace_shift_schedule_template_items(db, template=obj, venue_id=venue_id, raw_items=payload.items)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(obj)
    return _serialize_shift_schedule_template(obj)


@router.delete("/{venue_id}/shift-schedule-templates/{template_id}")
def delete_shift_schedule_template(
    venue_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)
    obj = _get_shift_schedule_template_or_404(db, venue_id=venue_id, template_id=template_id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/shift-schedule-templates/{template_id}/apply")
def apply_shift_schedule_template(
    venue_id: int,
    template_id: int,
    payload: ShiftScheduleTemplateApplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)
    template = _get_shift_schedule_template_or_404(db, venue_id=venue_id, template_id=template_id)
    if not bool(template.is_active):
        raise HTTPException(status_code=400, detail="Schedule template is archived")

    mode = str(payload.mode or "").strip().upper()
    if mode not in _SHIFT_TEMPLATE_APPLY_MODES:
        raise HTTPException(status_code=400, detail="Unknown apply mode")

    month_start, month_end_exclusive, month_end = _parse_shift_schedule_template_month(payload.month)
    items = list(getattr(template, "items", []) or [])
    if not items:
        raise HTTPException(status_code=400, detail="Schedule template has no intervals")

    # Validate that all intervals still belong to this venue and are active before generation.
    validation_payload = [
        ShiftScheduleTemplateItemIn(weekday=int(item.weekday), interval_id=int(item.interval_id), shift_slot=item.shift_slot)
        for item in items
    ]
    normalized_items = _normalize_shift_schedule_template_items(
        db,
        venue_id=venue_id,
        raw_items=validation_payload,
        require_active_intervals=True,
    )
    items_by_weekday: dict[int, list[dict]] = {}
    for item in normalized_items:
        items_by_weekday.setdefault(int(item["weekday"]), []).append(item)

    existing_month_shifts = db.execute(
        select(Shift).where(
            Shift.venue_id == venue_id,
            Shift.date >= month_start,
            Shift.date < month_end_exclusive,
        )
    ).scalars().all()
    existing_active_dates = {shift.date for shift in existing_month_shifts if bool(shift.is_active)}
    existing_by_key = {
        (shift.date, int(shift.interval_id), normalize_shift_slot(getattr(shift, "shift_slot", None))): shift
        for shift in existing_month_shifts
    }

    archived_count = 0
    if mode == "REPLACE_MONTH":
        for shift in existing_month_shifts:
            if bool(shift.is_active):
                shift.is_active = False
                archived_count += 1

    created_count = 0
    restored_count = 0
    skipped_count = 0
    skipped_filled_days: set[date] = set()
    changed_dates: set[date] = set()
    generated_targets = 0

    current = month_start
    while current < month_end_exclusive:
        day_items = items_by_weekday.get(current.weekday(), [])
        if not day_items:
            current += timedelta(days=1)
            continue

        if mode == "SKIP_FILLED_DAYS" and current in existing_active_dates:
            skipped_count += len(day_items)
            skipped_filled_days.add(current)
            current += timedelta(days=1)
            continue

        for item in day_items:
            generated_targets += 1
            interval_id = int(item["interval_id"])
            slot = normalize_shift_slot(item.get("shift_slot"))
            key = (current, interval_id, slot)
            existing = existing_by_key.get(key)
            if existing is not None:
                if bool(existing.is_active):
                    skipped_count += 1
                    continue
                existing.is_active = True
                existing.created_by_user_id = user.id
                restored_count += 1
                changed_dates.add(current)
                continue

            shift = Shift(
                venue_id=venue_id,
                date=current,
                interval_id=interval_id,
                shift_slot=slot,
                created_by_user_id=user.id,
                is_active=True,
            )
            db.add(shift)
            db.flush()
            existing_by_key[key] = shift
            created_count += 1
            changed_dates.add(current)

        current += timedelta(days=1)

    if archived_count > 0:
        changed_dates.update(shift.date for shift in existing_month_shifts if month_start <= shift.date < month_end_exclusive)

    if changed_dates:
        _rebuild_closed_report_tip_allocations_for_keys(
            db,
            venue_id=venue_id,
            report_keys={
                (changed_date, shift_slot)
                for changed_date in changed_dates
                for shift_slot in ("DAY", "NIGHT")
            },
        )
        _recalculate_payroll_for_dates(
            db,
            venue_id=venue_id,
            target_dates=sorted(changed_dates),
            calculated_by_user_id=user.id,
            trigger_reason="shift_schedule_template_apply",
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not generate shifts for this template")

    return {
        "ok": True,
        "template_id": int(template.id),
        "template_title": template.title,
        "month": payload.month,
        "period_start": month_start.isoformat(),
        "period_end": month_end.isoformat(),
        "mode": mode,
        "generated_targets": int(generated_targets),
        "created_count": int(created_count),
        "restored_count": int(restored_count),
        "skipped_count": int(skipped_count),
        "archived_count": int(archived_count),
        "skipped_filled_days_count": int(len(skipped_filled_days)),
    }


# ---------- Schedule: shift intervals & shifts ----------
