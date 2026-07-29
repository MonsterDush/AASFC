from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.daily_report import DailyReport
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.shift_availability import ShiftAvailability
from app.models.shift_interval import ShiftInterval
from app.models.shift_swap_request import ShiftSwapRequest
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.routers.venue_access import _require_active_member_or_admin
from app.routers.venue_permissions import _is_schedule_editor, _require_schedule_editor
from app.routers.venue_payroll_support import _recalculate_payroll_for_dates
from app.routers.venue_shift_swap_notifications import _enqueue_shift_swap_job
from app.schemas.venue_shifts import (
    ShiftAvailabilityUpsertIn,
    ShiftSwapCreateIn,
    ShiftSwapDecisionIn,
)
from app.services.shifts.slots import normalize_shift_slot


router = APIRouter()


def _process_shift_swap_notification_jobs() -> None:
    # Keep the large notification worker out of the schedule router import path.
    from app.routers.venue_economics_notifications import process_pending_notification_jobs_once

    process_pending_notification_jobs_once()


def _clean_optional_text(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _normalize_shift_slot_for_venue(
    db: Session,
    *,
    venue_id: int,
    shift_slot: str | None,
) -> str:
    slot = normalize_shift_slot(shift_slot)
    if slot == "NIGHT":
        enabled = db.execute(
            select(Venue.night_shifts_enabled).where(Venue.id == int(venue_id))
        ).scalar_one_or_none()
        if not enabled:
            raise HTTPException(status_code=400, detail="Night shifts are disabled for this venue")
    return slot


def _parse_month_bounds(value: str) -> tuple[date, date]:
    try:
        year_text, month_text = str(value or "").split("-", 1)
        start = date(int(year_text), int(month_text), 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def _display_user(user: User | None) -> dict | None:
    if user is None:
        return None
    display_name = user.short_name or user.full_name or (
        f"@{user.tg_username}" if user.tg_username else f"Сотрудник #{int(user.id)}"
    )
    return {
        "id": int(user.id),
        "display_name": str(display_name),
        "short_name": user.short_name,
        "full_name": user.full_name,
        "tg_username": user.tg_username,
    }


def _load_active_position(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
) -> VenuePosition | None:
    return db.execute(
        select(VenuePosition)
        .join(
            VenueMember,
            (VenueMember.venue_id == VenuePosition.venue_id)
            & (VenueMember.user_id == VenuePosition.member_user_id),
        )
        .where(
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.member_user_id == int(member_user_id),
            VenuePosition.is_active.is_(True),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()


def _load_shift_assignment(
    db: Session,
    *,
    venue_id: int,
    shift_id: int,
    member_user_id: int | None = None,
) -> tuple[Shift, ShiftAssignment] | None:
    stmt = (
        select(Shift, ShiftAssignment)
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .where(
            Shift.id == int(shift_id),
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
        )
    )
    if member_user_id is not None:
        stmt = stmt.where(ShiftAssignment.member_user_id == int(member_user_id))
    return db.execute(stmt).first()


def _shift_is_closed(db: Session, shift: Shift) -> bool:
    return (
        db.execute(
            select(DailyReport.id).where(
                DailyReport.venue_id == int(shift.venue_id),
                DailyReport.date == shift.date,
                DailyReport.shift_slot == normalize_shift_slot(shift.shift_slot),
                DailyReport.status == "CLOSED",
            )
        ).scalar_one_or_none()
        is not None
    )


def _interval_bounds(target_date: date, interval: ShiftInterval) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, interval.start_time)
    end_date = target_date + timedelta(days=1) if interval.end_time <= interval.start_time else target_date
    return start, datetime.combine(end_date, interval.end_time)


def _replacement_conflict(
    db: Session,
    *,
    replacement_user_id: int,
    shift: Shift,
    interval: ShiftInterval,
) -> bool:
    target_start, target_end = _interval_bounds(shift.date, interval)
    rows = db.execute(
        select(Shift, ShiftInterval)
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .where(
            ShiftAssignment.member_user_id == int(replacement_user_id),
            Shift.is_active.is_(True),
            Shift.id != int(shift.id),
            Shift.date >= shift.date - timedelta(days=1),
            Shift.date <= shift.date + timedelta(days=1),
        )
    ).all()
    for existing_shift, existing_interval in rows:
        existing_start, existing_end = _interval_bounds(existing_shift.date, existing_interval)
        if target_start < existing_end and existing_start < target_end:
            return True
    return False


def _candidate_state(
    db: Session,
    *,
    shift: Shift,
    interval: ShiftInterval,
    requester_user_id: int,
    position: VenuePosition,
    availability_by_user: dict[int, str],
    assigned_user_ids: set[int],
) -> tuple[bool, str | None]:
    member_user_id = int(position.member_user_id)
    if member_user_id == int(requester_user_id):
        return False, "Это текущий сотрудник"
    if member_user_id in assigned_user_ids:
        return False, "Уже назначен на эту смену"
    if availability_by_user.get(member_user_id) == "UNAVAILABLE":
        return False, "Отметил, что не может"
    if _replacement_conflict(
        db,
        replacement_user_id=member_user_id,
        shift=shift,
        interval=interval,
    ):
        return False, "Есть пересекающаяся смена"
    return True, None


def _load_candidate_or_error(
    db: Session,
    *,
    venue_id: int,
    shift: Shift,
    requester_user_id: int,
    replacement_user_id: int,
) -> VenuePosition:
    position = _load_active_position(
        db,
        venue_id=venue_id,
        member_user_id=replacement_user_id,
    )
    if position is None:
        raise HTTPException(status_code=400, detail="Replacement is not an active venue member")
    interval = db.execute(
        select(ShiftInterval).where(ShiftInterval.id == int(shift.interval_id))
    ).scalar_one()
    availability = db.execute(
        select(ShiftAvailability.status).where(
            ShiftAvailability.venue_id == int(venue_id),
            ShiftAvailability.member_user_id == int(replacement_user_id),
            ShiftAvailability.date == shift.date,
            ShiftAvailability.shift_slot == normalize_shift_slot(shift.shift_slot),
        )
    ).scalar_one_or_none()
    assigned_user_ids = set(
        db.execute(
            select(ShiftAssignment.member_user_id).where(ShiftAssignment.shift_id == int(shift.id))
        ).scalars().all()
    )
    allowed, reason = _candidate_state(
        db,
        shift=shift,
        interval=interval,
        requester_user_id=requester_user_id,
        position=position,
        availability_by_user={int(replacement_user_id): availability} if availability else {},
        assigned_user_ids={int(value) for value in assigned_user_ids},
    )
    if not allowed:
        raise HTTPException(status_code=409, detail=reason or "Replacement is not available")
    return position


def _serialize_swap_request(
    request: ShiftSwapRequest,
    *,
    requester: User | None,
    replacement: User | None,
    shift: Shift,
) -> dict:
    return {
        "id": int(request.id),
        "venue_id": int(request.venue_id),
        "shift_id": int(request.shift_id),
        "assignment_id": int(request.assignment_id) if request.assignment_id is not None else None,
        "status": request.status,
        "comment": request.comment,
        "manager_comment": request.manager_comment,
        "requester": _display_user(requester),
        "replacement": _display_user(replacement),
        "replacement_user_id": int(request.replacement_user_id) if request.replacement_user_id else None,
        "replacement_position_id": (
            int(request.replacement_position_id) if request.replacement_position_id else None
        ),
        "date": shift.date.isoformat(),
        "shift_slot": normalize_shift_slot(shift.shift_slot),
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
    }


@router.get("/{venue_id}/shift-availability")
def list_shift_availability(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    target_date: date | None = Query(default=None, alias="date"),
    shift_slot: str | None = Query(default=None, pattern="^(DAY|NIGHT)$"),
    member_user_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    manager = _is_schedule_editor(db, venue_id=venue_id, user=user)
    if not manager and member_user_id is not None and int(member_user_id) != int(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    stmt = select(ShiftAvailability, User).join(
        User,
        User.id == ShiftAvailability.member_user_id,
    ).where(ShiftAvailability.venue_id == int(venue_id))
    if target_date is not None:
        stmt = stmt.where(ShiftAvailability.date == target_date)
    elif month:
        start, end = _parse_month_bounds(month)
        stmt = stmt.where(ShiftAvailability.date >= start, ShiftAvailability.date <= end)
    else:
        raise HTTPException(status_code=400, detail="month or date is required")
    if shift_slot:
        normalized_slot = _normalize_shift_slot_for_venue(
            db,
            venue_id=venue_id,
            shift_slot=shift_slot,
        )
        stmt = stmt.where(ShiftAvailability.shift_slot == normalized_slot)
    effective_user_id = member_user_id if manager else int(user.id)
    if effective_user_id is not None:
        stmt = stmt.where(ShiftAvailability.member_user_id == int(effective_user_id))

    rows = db.execute(
        stmt.order_by(ShiftAvailability.date.asc(), ShiftAvailability.member_user_id.asc())
    ).all()
    return {
        "items": [
            {
                "id": int(item.id),
                "date": item.date.isoformat(),
                "shift_slot": normalize_shift_slot(item.shift_slot),
                "status": item.status,
                "comment": item.comment,
                "member": _display_user(member),
            }
            for item, member in rows
        ]
    }


@router.put("/{venue_id}/shift-availability/{target_date}/{shift_slot}")
def upsert_shift_availability(
    venue_id: int,
    target_date: date,
    shift_slot: str,
    payload: ShiftAvailabilityUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if target_date < date.today():
        raise HTTPException(status_code=409, detail="Past availability cannot be changed")
    normalized_slot = _normalize_shift_slot_for_venue(
        db,
        venue_id=venue_id,
        shift_slot=shift_slot,
    )
    obj = db.execute(
        select(ShiftAvailability).where(
            ShiftAvailability.venue_id == int(venue_id),
            ShiftAvailability.member_user_id == int(user.id),
            ShiftAvailability.date == target_date,
            ShiftAvailability.shift_slot == normalized_slot,
        )
    ).scalar_one_or_none()
    if obj is None:
        obj = ShiftAvailability(
            venue_id=int(venue_id),
            member_user_id=int(user.id),
            date=target_date,
            shift_slot=normalized_slot,
            status=payload.status,
        )
        db.add(obj)
    obj.status = payload.status
    obj.comment = _clean_optional_text(payload.comment)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)
    return {
        "id": int(obj.id),
        "date": obj.date.isoformat(),
        "shift_slot": obj.shift_slot,
        "status": obj.status,
        "comment": obj.comment,
    }


@router.delete("/{venue_id}/shift-availability/{target_date}/{shift_slot}")
def delete_shift_availability(
    venue_id: int,
    target_date: date,
    shift_slot: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if target_date < date.today():
        raise HTTPException(status_code=409, detail="Past availability cannot be changed")
    normalized_slot = _normalize_shift_slot_for_venue(
        db,
        venue_id=venue_id,
        shift_slot=shift_slot,
    )
    obj = db.execute(
        select(ShiftAvailability).where(
            ShiftAvailability.venue_id == int(venue_id),
            ShiftAvailability.member_user_id == int(user.id),
            ShiftAvailability.date == target_date,
            ShiftAvailability.shift_slot == normalized_slot,
        )
    ).scalar_one_or_none()
    if obj is not None:
        db.delete(obj)
        db.commit()
    return {"ok": True}


@router.get("/{venue_id}/shifts/{shift_id}/swap-candidates")
def list_shift_swap_candidates(
    venue_id: int,
    shift_id: int,
    requester_user_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    manager = _is_schedule_editor(db, venue_id=venue_id, user=user)
    effective_requester_id = (
        int(requester_user_id)
        if manager and requester_user_id is not None
        else int(user.id)
    )
    row = _load_shift_assignment(
        db,
        venue_id=venue_id,
        shift_id=shift_id,
        member_user_id=effective_requester_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Shift assignment not found")
    shift, assignment = row
    requester_user_id = int(assignment.member_user_id)
    interval = db.execute(
        select(ShiftInterval).where(ShiftInterval.id == int(shift.interval_id))
    ).scalar_one()
    positions = db.execute(
        select(VenuePosition, User)
        .join(User, User.id == VenuePosition.member_user_id)
        .join(
            VenueMember,
            (VenueMember.venue_id == VenuePosition.venue_id)
            & (VenueMember.user_id == VenuePosition.member_user_id),
        )
        .where(
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.is_active.is_(True),
            VenueMember.is_active.is_(True),
        )
        .order_by(User.short_name.asc(), User.full_name.asc(), User.id.asc())
    ).all()
    availability_rows = db.execute(
        select(ShiftAvailability.member_user_id, ShiftAvailability.status).where(
            ShiftAvailability.venue_id == int(venue_id),
            ShiftAvailability.date == shift.date,
            ShiftAvailability.shift_slot == normalize_shift_slot(shift.shift_slot),
        )
    ).all()
    availability_by_user = {int(row.member_user_id): row.status for row in availability_rows}
    assigned_user_ids = {
        int(value)
        for value in db.execute(
            select(ShiftAssignment.member_user_id).where(ShiftAssignment.shift_id == int(shift.id))
        ).scalars().all()
    }
    items = []
    for position, member in positions:
        allowed, reason = _candidate_state(
            db,
            shift=shift,
            interval=interval,
            requester_user_id=requester_user_id,
            position=position,
            availability_by_user=availability_by_user,
            assigned_user_ids=assigned_user_ids,
        )
        if int(position.member_user_id) == requester_user_id:
            continue
        items.append(
            {
                "member": _display_user(member),
                "member_user_id": int(position.member_user_id),
                "venue_position_id": int(position.id),
                "position_title": position.title,
                "availability": availability_by_user.get(int(position.member_user_id)),
                "can_replace": allowed,
                "reason": reason,
            }
        )
    return {"items": items}


@router.get("/{venue_id}/shift-swap-requests")
def list_shift_swap_requests(
    venue_id: int,
    shift_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, pattern="^(OPEN|APPROVED|REJECTED|CANCELLED)$"),
    month: str | None = Query(default=None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    manager = _is_schedule_editor(db, venue_id=venue_id, user=user)
    replacement_alias = aliased(User)
    stmt = (
        select(ShiftSwapRequest, Shift, User, replacement_alias)
        .join(Shift, Shift.id == ShiftSwapRequest.shift_id)
        .join(User, User.id == ShiftSwapRequest.requester_user_id)
    )
    stmt = stmt.outerjoin(
        replacement_alias,
        replacement_alias.id == ShiftSwapRequest.replacement_user_id,
    ).where(ShiftSwapRequest.venue_id == int(venue_id))
    if not manager:
        stmt = stmt.where(
            sa.or_(
                ShiftSwapRequest.requester_user_id == int(user.id),
                ShiftSwapRequest.replacement_user_id == int(user.id),
            )
        )
    if shift_id is not None:
        stmt = stmt.where(ShiftSwapRequest.shift_id == int(shift_id))
    if status:
        stmt = stmt.where(ShiftSwapRequest.status == status)
    if month:
        start, end = _parse_month_bounds(month)
        stmt = stmt.where(Shift.date >= start, Shift.date <= end)
    rows = db.execute(stmt.order_by(ShiftSwapRequest.created_at.desc())).all()
    return {
        "items": [
            _serialize_swap_request(
                request,
                requester=requester,
                replacement=replacement,
                shift=shift,
            )
            for request, shift, requester, replacement in rows
        ]
    }


@router.post("/{venue_id}/shifts/{shift_id}/swap-requests")
def create_shift_swap_request(
    venue_id: int,
    shift_id: int,
    payload: ShiftSwapCreateIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    row = _load_shift_assignment(
        db,
        venue_id=venue_id,
        shift_id=shift_id,
        member_user_id=int(user.id),
    )
    if row is None:
        raise HTTPException(status_code=403, detail="Only the assigned employee can request a swap")
    shift, assignment = row
    if shift.date < date.today() or _shift_is_closed(db, shift):
        raise HTTPException(status_code=409, detail="This shift can no longer be exchanged")
    existing = db.execute(
        select(ShiftSwapRequest).where(
            ShiftSwapRequest.assignment_id == int(assignment.id),
            ShiftSwapRequest.status == "OPEN",
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An open swap request already exists")

    replacement_position = None
    if payload.replacement_user_id is not None:
        replacement_position = _load_candidate_or_error(
            db,
            venue_id=venue_id,
            shift=shift,
            requester_user_id=int(user.id),
            replacement_user_id=int(payload.replacement_user_id),
        )
    request = ShiftSwapRequest(
        venue_id=int(venue_id),
        shift_id=int(shift.id),
        assignment_id=int(assignment.id),
        requester_user_id=int(user.id),
        replacement_user_id=(
            int(replacement_position.member_user_id) if replacement_position is not None else None
        ),
        replacement_position_id=(
            int(replacement_position.id) if replacement_position is not None else None
        ),
        comment=_clean_optional_text(payload.comment),
        status="OPEN",
    )
    db.add(request)
    db.flush()
    _enqueue_shift_swap_job(db, request_id=int(request.id), event_kind="created")
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An open swap request already exists")
    db.refresh(request)
    background_tasks.add_task(_process_shift_swap_notification_jobs)
    return {"id": int(request.id), "status": request.status}


def _load_open_request(
    db: Session,
    *,
    venue_id: int,
    request_id: int,
) -> ShiftSwapRequest:
    request = db.execute(
        select(ShiftSwapRequest)
        .where(
            ShiftSwapRequest.id == int(request_id),
            ShiftSwapRequest.venue_id == int(venue_id),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Swap request not found")
    if request.status != "OPEN":
        raise HTTPException(status_code=409, detail="Swap request is already closed")
    return request


@router.post("/{venue_id}/shift-swap-requests/{request_id}/cancel")
def cancel_shift_swap_request(
    venue_id: int,
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    request = _load_open_request(db, venue_id=venue_id, request_id=request_id)
    if int(request.requester_user_id) != int(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")
    request.status = "CANCELLED"
    request.updated_at = datetime.utcnow()
    _enqueue_shift_swap_job(db, request_id=int(request.id), event_kind="cancelled")
    db.commit()
    background_tasks.add_task(_process_shift_swap_notification_jobs)
    return {"ok": True, "status": request.status}


@router.post("/{venue_id}/shift-swap-requests/{request_id}/reject")
def reject_shift_swap_request(
    venue_id: int,
    request_id: int,
    payload: ShiftSwapDecisionIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)
    request = _load_open_request(db, venue_id=venue_id, request_id=request_id)
    request.status = "REJECTED"
    request.manager_comment = _clean_optional_text(payload.comment)
    request.decided_by_user_id = int(user.id)
    request.decided_at = datetime.utcnow()
    request.updated_at = datetime.utcnow()
    _enqueue_shift_swap_job(db, request_id=int(request.id), event_kind="rejected")
    db.commit()
    background_tasks.add_task(_process_shift_swap_notification_jobs)
    return {"ok": True, "status": request.status}


@router.post("/{venue_id}/shift-swap-requests/{request_id}/approve")
def approve_shift_swap_request(
    venue_id: int,
    request_id: int,
    payload: ShiftSwapDecisionIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)
    request = _load_open_request(db, venue_id=venue_id, request_id=request_id)
    if request.assignment_id is None:
        raise HTTPException(status_code=409, detail="The original assignment no longer exists")
    row = db.execute(
        select(Shift, ShiftAssignment)
        .join(ShiftAssignment, ShiftAssignment.id == int(request.assignment_id))
        .where(
            Shift.id == int(request.shift_id),
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
        )
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=409, detail="The original assignment no longer exists")
    shift, assignment = row
    if int(assignment.member_user_id) != int(request.requester_user_id):
        raise HTTPException(status_code=409, detail="The original assignment has changed")
    if shift.date < date.today() or _shift_is_closed(db, shift):
        raise HTTPException(status_code=409, detail="This shift can no longer be exchanged")
    replacement_user_id = payload.replacement_user_id or request.replacement_user_id
    if replacement_user_id is None:
        raise HTTPException(status_code=400, detail="Choose a replacement before approval")
    replacement_position = _load_candidate_or_error(
        db,
        venue_id=venue_id,
        shift=shift,
        requester_user_id=int(request.requester_user_id),
        replacement_user_id=int(replacement_user_id),
    )

    assignment.member_user_id = int(replacement_position.member_user_id)
    assignment.venue_position_id = int(replacement_position.id)
    assignment.reminder_sent_at = None
    request.replacement_user_id = int(replacement_position.member_user_id)
    request.replacement_position_id = int(replacement_position.id)
    request.status = "APPROVED"
    request.manager_comment = _clean_optional_text(payload.comment)
    request.decided_by_user_id = int(user.id)
    request.decided_at = datetime.utcnow()
    request.updated_at = datetime.utcnow()
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[shift.date],
        calculated_by_user_id=int(user.id),
        trigger_reason="shift_swap_approved",
    )
    _enqueue_shift_swap_job(db, request_id=int(request.id), event_kind="approved")
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Replacement is already assigned to this shift")
    background_tasks.add_task(_process_shift_swap_notification_jobs)
    return {"ok": True, "status": request.status}
