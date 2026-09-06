from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    Query,
    Session,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    ShiftScheduleTemplate,
    ShiftScheduleTemplateItem,
    User,
    VenuePosition,
    _require_active_member_or_admin,
    date,
    func,
    get_current_user,
    get_db,
    select,
    update,
)
from app.services.shift_interval_scope import interval_scope_payloads, set_interval_positions
from app.schemas.venue_shifts import (
    ShiftIntervalCreateIn,
    ShiftIntervalUpdateIn,
)
from app.routers.venue_scheduling_support import (
    _count_interval_shift_usage,
    _count_interval_template_usage,
    _ensure_shift_interval_title_unique,
    _normalize_shift_interval_title,
)
from app.routers.venue_permissions import (
    _require_schedule_editor,
)


router = APIRouter()


def _catalog_position_or_400(
    db: Session,
    *,
    venue_id: int,
    position_id: int | None,
) -> VenuePosition | None:
    if position_id is None:
        return None
    position = db.execute(
        select(VenuePosition).where(
            VenuePosition.id == int(position_id),
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.member_user_id.is_(None),
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=400, detail="Position not found")
    return position


def _requested_position_ids(db: Session, *, venue_id: int, payload, existing_ids: list[int] | None = None) -> list[int]:
    fields = payload.model_fields_set
    if "position_ids" in fields:
        ids = sorted(set(payload.position_ids or []))
        if "position_id" in fields and ids != ([payload.position_id] if payload.position_id else []):
            raise HTTPException(status_code=422, detail="Use position_ids or position_id, not conflicting values")
    elif "position_id" in fields:
        ids = [payload.position_id] if payload.position_id else []
    else:
        return list(existing_ids or [])
    for position_id in ids:
        # Retain an existing archived role when unrelated fields are edited.
        if position_id not in (existing_ids or []):
            _catalog_position_or_400(db, venue_id=venue_id, position_id=position_id)
    return ids


@router.get("/{venue_id}/shift-intervals")
def list_shift_intervals(
    venue_id: int,
    include_inactive: bool = Query(default=False),
    position_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List reusable time intervals for shifts.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    stmt = select(ShiftInterval).where(ShiftInterval.venue_id == venue_id)
    if position_id is not None:
        _catalog_position_or_400(db, venue_id=venue_id, position_id=position_id)

    if not include_inactive:
        stmt = stmt.where(ShiftInterval.is_active.is_(True))

    rows = db.execute(stmt.order_by(ShiftInterval.start_time.asc(), ShiftInterval.id.asc())).scalars().all()
    scopes = interval_scope_payloads(db, venue_id=venue_id, intervals=list(rows))
    if position_id is not None:
        rows = [
            row for row in rows if not scopes[row.id]["position_ids"] or position_id in scopes[row.id]["position_ids"]
        ]

    usage_rows = db.execute(
        select(Shift.interval_id, func.count(Shift.id)).where(Shift.venue_id == venue_id).group_by(Shift.interval_id)
    ).all()
    usage_by_interval = {int(interval_id): int(count or 0) for interval_id, count in usage_rows}
    template_usage_rows = db.execute(
        select(ShiftScheduleTemplateItem.interval_id, func.count(ShiftScheduleTemplateItem.id))
        .join(ShiftScheduleTemplate, ShiftScheduleTemplate.id == ShiftScheduleTemplateItem.template_id)
        .where(ShiftScheduleTemplate.venue_id == venue_id)
        .group_by(ShiftScheduleTemplateItem.interval_id)
    ).all()
    template_usage_by_interval = {int(interval_id): int(count or 0) for interval_id, count in template_usage_rows}
    return [
        {
            "id": r.id,
            "title": r.title,
            "start_time": r.start_time.strftime("%H:%M"),
            "end_time": r.end_time.strftime("%H:%M"),
            "position_id": int(r.position_id) if r.position_id is not None else None,
            "position_title": ", ".join(scopes[r.id]["position_titles"]) or None,
            **scopes[r.id],
            "is_active": bool(r.is_active),
            "usage_count": usage_by_interval.get(r.id, 0),
            "template_usage_count": template_usage_by_interval.get(r.id, 0),
            "can_delete": (usage_by_interval.get(r.id, 0) + template_usage_by_interval.get(r.id, 0)) == 0,
        }
        for r in rows
    ]


@router.post("/{venue_id}/shift-intervals")
def create_shift_interval(
    venue_id: int,
    payload: ShiftIntervalCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a reusable shift interval (schedule editor only)."""
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    title = _normalize_shift_interval_title(payload.title)
    _ensure_shift_interval_title_unique(db, venue_id=venue_id, title=title)
    position_ids = _requested_position_ids(db, venue_id=venue_id, payload=payload)

    obj = ShiftInterval(
        venue_id=venue_id,
        title=title,
        position_id=payload.position_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_active=payload.is_active,
    )
    db.add(obj)
    try:
        set_interval_positions(db, interval=obj, position_ids=position_ids)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/shift-intervals/{interval_id}")
def update_shift_interval(
    venue_id: int,
    interval_id: int,
    payload: ShiftIntervalUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(ShiftInterval).where(ShiftInterval.id == interval_id, ShiftInterval.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift interval not found")

    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    scope_changed = bool({"position_id", "position_ids"} & fields_set)
    if scope_changed:
        existing_ids = interval_scope_payloads(db, venue_id=venue_id, intervals=[obj])[obj.id]["position_ids"]
        position_ids = _requested_position_ids(db, venue_id=venue_id, payload=payload, existing_ids=existing_ids)

    start_changed = payload.start_time is not None and payload.start_time != obj.start_time

    if payload.title is not None:
        title = _normalize_shift_interval_title(payload.title)
        _ensure_shift_interval_title_unique(db, venue_id=venue_id, title=title, exclude_interval_id=interval_id)
        obj.title = title
    if payload.start_time is not None:
        obj.start_time = payload.start_time
    if payload.end_time is not None:
        obj.end_time = payload.end_time
    if payload.is_active is not None:
        obj.is_active = payload.is_active
    if scope_changed:
        set_interval_positions(db, interval=obj, position_ids=position_ids)

    # If shift start time changed - allow reminders to be re-sent for future shifts.
    if start_changed:
        future_shift_ids = db.scalars(
            select(Shift.id).where(
                Shift.venue_id == venue_id,
                Shift.interval_id == interval_id,
                Shift.is_active.is_(True),
                Shift.date >= date.today(),
            )
        ).all()
        if future_shift_ids:
            db.execute(
                update(ShiftAssignment)
                .where(ShiftAssignment.shift_id.in_(future_shift_ids))
                .values(reminder_sent_at=None)
            )

    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/shift-intervals/{interval_id}")
def delete_shift_interval(
    venue_id: int,
    interval_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(ShiftInterval).where(ShiftInterval.id == interval_id, ShiftInterval.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Shift interval not found")

    usage_count = _count_interval_shift_usage(db, venue_id=venue_id, interval_id=interval_id)
    template_usage_count = _count_interval_template_usage(db, venue_id=venue_id, interval_id=interval_id)
    if usage_count > 0 or template_usage_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Shift interval is already used in shifts or schedule templates and cannot be deleted. Archive it instead.",
        )

    db.delete(obj)
    db.commit()
    return {"ok": True}
