from __future__ import annotations

from datetime import datetime, timezone, date, time
import os
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.core.tg import normalize_tg_username

from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite
from app.models.venue_position import VenuePosition
from app.models.shift_interval import ShiftInterval
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.adjustment_dispute_comment import AdjustmentDisputeComment
from app.models.adjustment_dispute import AdjustmentDispute
from app.models.bonus import Bonus
from app.models.writeoff import Writeoff
from app.models.penalty import Penalty

from app.services.venues import create_venue
from app.services.tg_notify import send_telegram_message

router = APIRouter(prefix="/venues", tags=["venues"])


# ---------- Schemas ----------

class VenueCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    owner_usernames: Optional[List[str]] = None  # ["owner1", "@owner2"]


class VenueUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class InviteCreateIn(BaseModel):
    tg_username: str
    venue_role: str = "STAFF"  # "OWNER" | "STAFF"



class PositionCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    member_user_id: int = Field(..., gt=0)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    can_make_reports: bool = False
    can_view_reports: bool = False
    can_view_revenue: bool = False
    can_edit_schedule: bool = False
    is_active: bool = True


class PositionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    member_user_id: int | None = Field(default=None, gt=0)
    rate: int | None = Field(default=None, ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)
    can_make_reports: bool | None = None
    can_view_reports: bool | None = None
    can_view_revenue: bool | None = None
    can_edit_schedule: bool | None = None
    is_active: bool | None = None


class DailyReportUpsertIn(BaseModel):
    date: date
    cash: int = Field(0, ge=0)
    cashless: int = Field(0, ge=0)
    revenue_total: int = Field(0, ge=0)
    tips_total: int = Field(0, ge=0)

class AdjustmentCreateIn(BaseModel):
    type: str = Field(..., description="penalty|writeoff|bonus")
    date: date
    amount: int = Field(..., ge=0)
    reason: str | None = Field(default=None, max_length=500)
    member_user_id: int | None = Field(default=None, description="Required for penalty/bonus; optional for writeoff (null=venue)")

class DisputeCreateIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

class DisputeStatusUpdateIn(BaseModel):
    status: str = Field(..., description="OPEN|CLOSED")


class ShiftIntervalCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    start_time: time
    end_time: time
    is_active: bool = True


class ShiftIntervalUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    start_time: time | None = None
    end_time: time | None = None
    is_active: bool | None = None


class ShiftCreateIn(BaseModel):
    date: date
    interval_id: int = Field(..., gt=0)
    is_active: bool = True


class ShiftUpdateIn(BaseModel):
    date: date | Optional[date] = None
    interval_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class ShiftAssignmentAddIn(BaseModel):
    venue_position_id: int = Field(..., gt=0)



# ---------- Helpers ----------

def _is_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> bool:
    if user.system_role == "SUPER_ADMIN":
        return True

    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()

    return bool(m and m.venue_role == "OWNER")


def _require_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> bool:
    if user.system_role in ("SUPER_ADMIN", "MODERATOR"):
        return True
    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    return bool(m)


def _require_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_active_member_or_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_schedule_editor(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(pos and pos.can_edit_schedule)


def _require_schedule_editor(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_schedule_editor(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_report_maker(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(pos and pos.can_make_reports)


def _require_report_maker(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_report_maker(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_report_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    # report maker can always view
    return bool(pos and (pos.can_view_reports or pos.can_make_reports))


def _require_report_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_report_viewer(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _can_view_revenue(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    # report maker can always view numbers
    return bool(pos and (pos.can_view_revenue or pos.can_make_reports))


def _is_adjustments_manager(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(pos and pos.can_manage_adjustments)


def _require_adjustments_manager(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_manager(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(pos and (pos.can_view_adjustments or pos.can_manage_adjustments))


def _require_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_viewer(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_disputes_resolver(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(pos and (pos.can_resolve_disputes or pos.can_manage_adjustments))


def _require_disputes_resolver(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_disputes_resolver(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")



# ---------- Routes ----------

@router.post("")
def create_venue_admin_only(
    payload: VenueCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = create_venue(
        db,
        name=payload.name,
        owner_usernames=payload.owner_usernames,
    )
    return {"id": venue.id, "name": venue.name}


@router.get("")
def list_venues_admin_only(
    q: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    stmt = select(Venue.id, Venue.name, Venue.is_archived, Venue.archived_at).order_by(Venue.id.desc())

    if q:
        stmt = stmt.where(Venue.name.ilike(f"%{q.strip()}%"))

    if not include_archived:
        stmt = stmt.where(Venue.is_archived.is_(False))

    rows = db.execute(stmt).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "is_archived": bool(r.is_archived),
            "archived_at": r.archived_at.isoformat() if r.archived_at else None,
        }
        for r in rows
    ]


@router.patch("/{venue_id}")
def update_venue(
    venue_id: int,
    payload: VenueUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    venue.name = payload.name.strip()
    db.commit()
    return {"id": venue.id, "name": venue.name}


@router.post("/{venue_id}/archive")
def archive_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    if not venue.is_archived:
        venue.is_archived = True
        venue.archived_at = datetime.now(timezone.utc)
        db.commit()

    return {"ok": True}


@router.post("/{venue_id}/unarchive")
def unarchive_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    if venue.is_archived:
        venue.is_archived = False
        venue.archived_at = None
        db.commit()

    return {"ok": True}


@router.delete("/{venue_id}")
def delete_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hard-delete venue (allowed only when archived).

    We delete dependent rows explicitly using bulk deletes to avoid SQLAlchemy
    trying to NULL-out NOT NULL FKs (e.g. venue_members.venue_id).
    """
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    if not venue.is_archived:
        raise HTTPException(400, "Archive venue before delete")

    venue_shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)

    # Shift assignments
    db.execute(delete(ShiftAssignment).where(ShiftAssignment.shift_id.in_(venue_shift_ids)))

    # Shifts & intervals
    db.execute(delete(Shift).where(Shift.venue_id == venue_id))
    db.execute(delete(ShiftInterval).where(ShiftInterval.venue_id == venue_id))

    # Positions / invites / members
    db.execute(delete(VenuePosition).where(VenuePosition.venue_id == venue_id))
    db.execute(delete(VenueInvite).where(VenueInvite.venue_id == venue_id))
    db.execute(delete(VenueMember).where(VenueMember.venue_id == venue_id))

    # Daily reports
    db.execute(delete(DailyReport).where(DailyReport.venue_id == venue_id))

    # Venue itself
    db.execute(delete(Venue).where(Venue.id == venue_id))

    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/members")
def get_members(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    members = (
        db.query(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name,VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .filter(VenueMember.venue_id == venue_id, VenueMember.is_active.is_(True))
        .all()
    )

    invites = (
        db.query(VenueInvite.id, VenueInvite.invited_tg_username, VenueInvite.venue_role, VenueInvite.created_at)
        .filter(
            VenueInvite.venue_id == venue_id,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .order_by(VenueInvite.created_at.desc())
        .all()
    )

    return {
        "members": [
            {"user_id": r.id, "tg_user_id": r.tg_user_id, "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                "full_name": r.full_name,
                "short_name": r.short_name, "venue_role": r.venue_role}
            for r in members
        ],
        "pending_invites": [
            {
                "id": r.id,
                "tg_username": r.invited_tg_username,
                "venue_role": r.venue_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in invites
        ],
    }



# ---------- Positions (job roles inside venue) ----------

@router.get("/{venue_id}/positions")
def list_positions(
    venue_id: int,
    include_inactive: bool = Query(False, description="If true, return inactive members/positions too (owner/admin only)."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_schedule_editor(db, venue_id=venue_id, user=user)

    if include_inactive:
        _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    stmt = (
        select(
            VenuePosition.id,
            VenuePosition.title,
            VenuePosition.member_user_id,
            VenuePosition.rate,
            VenuePosition.percent,
            VenuePosition.can_make_reports,
            VenuePosition.can_view_reports,
            VenuePosition.can_view_revenue,
            VenuePosition.can_edit_schedule,
            VenuePosition.is_active,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
            VenueMember.venue_role,
            VenueMember.is_active.label("member_is_active"),
        )
        .join(User, User.id == VenuePosition.member_user_id)
        .join(
            VenueMember,
            (VenueMember.venue_id == VenuePosition.venue_id)
            & (VenueMember.user_id == VenuePosition.member_user_id),
        )
        .where(VenuePosition.venue_id == venue_id)
        .order_by(VenuePosition.id.desc())
    )

    if not include_inactive:
        stmt = stmt.where(VenuePosition.is_active.is_(True), VenueMember.is_active.is_(True))

    rows = db.execute(stmt).all()

    return [
        {
            "id": r.id,
            "title": r.title,
            "member_user_id": r.member_user_id,
            "rate": r.rate,
            "percent": r.percent,
            "can_make_reports": bool(r.can_make_reports),
            "can_view_reports": bool(r.can_view_reports),
            "can_view_revenue": bool(r.can_view_revenue),
            "can_edit_schedule": bool(r.can_edit_schedule),
            "is_active": bool(r.is_active),
            "member": {
                "user_id": r.member_user_id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
                "is_active": bool(r.member_is_active),
            },
        }
        for r in rows
    ]


@router.post("/{venue_id}/positions")
def create_position(
    venue_id: int,
    payload: PositionCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    # validate member exists in this venue (active)
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == payload.member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=400, detail="Member not found in venue")

    existing = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == payload.member_user_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        pos = VenuePosition(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            title=payload.title.strip(),
            rate=payload.rate,
            percent=payload.percent,
            can_make_reports=payload.can_make_reports,
            can_view_reports=payload.can_view_reports,
            can_view_revenue=payload.can_view_revenue,
            can_edit_schedule=payload.can_edit_schedule,
            is_active=payload.is_active,
        )
        db.add(pos)
        db.commit()
        db.refresh(pos)
        return {"id": pos.id}

    # update-in-place
    existing.title = payload.title.strip()
    existing.rate = payload.rate
    existing.percent = payload.percent
    existing.can_make_reports = payload.can_make_reports
    existing.can_view_reports = payload.can_view_reports
    existing.can_view_revenue = payload.can_view_revenue
    existing.can_edit_schedule = payload.can_edit_schedule
    existing.is_active = payload.is_active
    db.commit()
    return {"id": existing.id, "mode": "updated"}


@router.patch("/{venue_id}/positions/{position_id}")
def update_position(
    venue_id: int,
    position_id: int,
    payload: PositionUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    if payload.member_user_id is not None and payload.member_user_id != pos.member_user_id:
        # validate member exists
        vm = db.execute(
            select(VenueMember).where(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == payload.member_user_id,
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if vm is None:
            raise HTTPException(status_code=400, detail="Member not found in venue")

        clash = db.execute(
            select(VenuePosition).where(
                VenuePosition.venue_id == venue_id,
                VenuePosition.member_user_id == payload.member_user_id,
            )
        ).scalar_one_or_none()
        if clash is not None and clash.id != pos.id:
            raise HTTPException(status_code=409, detail="Position for this member already exists")

        pos.member_user_id = payload.member_user_id

    if payload.title is not None:
        pos.title = payload.title.strip()
    if payload.rate is not None:
        pos.rate = payload.rate
    if payload.percent is not None:
        pos.percent = payload.percent
    if payload.can_make_reports is not None:
        pos.can_make_reports = payload.can_make_reports
    if payload.can_view_reports is not None:
        pos.can_view_reports = payload.can_view_reports
    if payload.can_view_revenue is not None:
        pos.can_view_revenue = payload.can_view_revenue
    if payload.can_edit_schedule is not None:
        pos.can_edit_schedule = payload.can_edit_schedule
    if payload.is_active is not None:
        pos.is_active = payload.is_active

    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/positions/{position_id}")
def delete_position(
    venue_id: int,
    position_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    pos.is_active = False
    db.commit()
    return {"ok": True}


# ---------- Daily reports ----------

@router.post("/{venue_id}/reports")
def upsert_daily_report(
    venue_id: int,
    payload: DailyReportUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    obj = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == payload.date)
    ).scalar_one_or_none()

    if obj is None:
        obj = DailyReport(
            venue_id=venue_id,
            date=payload.date,
            cash=payload.cash,
            cashless=payload.cashless,
            revenue_total=payload.revenue_total,
            tips_total=payload.tips_total,
            created_by_user_id=user.id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return {"id": obj.id, "date": obj.date.isoformat(), "mode": "created"}

    obj.cash = payload.cash
    obj.cashless = payload.cashless
    obj.revenue_total = payload.revenue_total
    obj.tips_total = payload.tips_total
    obj.updated_by_user_id = user.id
    obj.updated_at = datetime.utcnow()
    db.commit()
    return {"id": obj.id, "date": obj.date.isoformat(), "mode": "updated"}


@router.get("/{venue_id}/reports")
def list_daily_reports(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    rows = db.execute(
        select(DailyReport)
        .where(DailyReport.venue_id == venue_id, DailyReport.date >= start, DailyReport.date < end)
        .order_by(DailyReport.date.asc())
    ).scalars().all()

    show_numbers = _can_view_revenue(db, venue_id=venue_id, user=user)
    return [
        {
            "id": r.id,
            "date": r.date.isoformat(),
            "cash": r.cash if show_numbers else None,
            "cashless": r.cashless if show_numbers else None,
            "revenue_total": r.revenue_total if show_numbers else None,
        "tips_total": r.tips_total if show_numbers else None,
            "tips_total": r.tips_total if show_numbers else None,
        }
        for r in rows
    ]


@router.get("/{venue_id}/reports/{report_date}")
def get_daily_report(
    venue_id: int,
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    r = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")

    show_numbers = _can_view_revenue(db, venue_id=venue_id, user=user)
    return {
        "id": r.id,
        "date": r.date.isoformat(),
        "cash": r.cash if show_numbers else None,
        "cashless": r.cashless if show_numbers else None,
        "revenue_total": r.revenue_total if show_numbers else None,
            "tips_total": r.tips_total if show_numbers else None,
    }



# ---------- Daily report attachments ----------

def _reports_upload_dir() -> str:
    return os.getenv("REPORTS_UPLOAD_DIR", "/var/www/axelio/dev/uploads/reports")


@router.get("/{venue_id}/reports/{report_date}/attachments")
def list_daily_report_attachments(
    venue_id: int,
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    report = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    rows = db.execute(
        select(DailyReportAttachment)
        .where(
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_id == report.id,
            DailyReportAttachment.is_active.is_(True),
        )
        .order_by(DailyReportAttachment.id.asc())
    ).scalars().all()

    return [
        {
            "id": a.id,
            "file_name": a.file_name,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/{venue_id}/reports/{report_date}/attachments")
async def upload_daily_report_attachments(
    venue_id: int,
    report_date: date,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    report = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    base_dir = os.path.join(_reports_upload_dir(), str(venue_id), report_date.isoformat())
    os.makedirs(base_dir, exist_ok=True)

    created = []
    for f in files:
        if not f.filename:
            continue
        safe_name = os.path.basename(f.filename)
        ext = os.path.splitext(safe_name)[1].lower()
        uid = uuid.uuid4().hex
        stored_name = f"{uid}{ext}"
        storage_path = os.path.join(base_dir, stored_name)

        content = await f.read()
        with open(storage_path, "wb") as out:
            out.write(content)

        a = DailyReportAttachment(
            venue_id=venue_id,
            report_id=report.id,
            file_name=safe_name,
            storage_path=storage_path,
            uploaded_by_user_id=user.id,
            created_at=datetime.utcnow(),
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        created.append({"id": a.id, "file_name": a.file_name})

    return {"items": created}


@router.get("/{venue_id}/reports/{report_date}/attachments/{attachment_id}/download")
def download_daily_report_attachment(
    venue_id: int,
    report_date: date,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    report = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_id == report.id,
            DailyReportAttachment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not os.path.exists(a.storage_path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(a.storage_path, filename=a.file_name)


@router.post("/{venue_id}/invites")
def create_invite(
    venue_id: int,
    payload: InviteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    username = normalize_tg_username(payload.tg_username)
    if not username:
        raise HTTPException(status_code=400, detail="Bad tg_username")

    role = payload.venue_role
    if role not in ("OWNER", "STAFF"):
        raise HTTPException(status_code=400, detail="Bad venue_role")

    existing_user = db.query(User).filter(User.tg_username == username).one_or_none()
    if existing_user:
        mem = db.query(VenueMember).filter(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == existing_user.id,
        ).one_or_none()

        if mem:
            mem.venue_role = role
            mem.is_active = True
        else:
            db.add(VenueMember(venue_id=venue_id, user_id=existing_user.id, venue_role=role, is_active=True))

        db.commit()
        return {"ok": True, "mode": "member_added"}

    inv = db.query(VenueInvite).filter(
        VenueInvite.venue_id == venue_id,
        VenueInvite.invited_tg_username == username,
        VenueInvite.venue_role == role,
    ).one_or_none()

    if inv:
        inv.is_active = True
    else:
        db.add(VenueInvite(venue_id=venue_id, invited_tg_username=username, venue_role=role, is_active=True))

    db.commit()
    return {"ok": True, "mode": "invited"}


@router.delete("/{venue_id}/invites/{invite_id}")
def cancel_invite(
    venue_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    inv = db.query(VenueInvite).filter(VenueInvite.id == invite_id, VenueInvite.venue_id == venue_id).one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")

    inv.is_active = False
    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/members/{member_user_id}")
def remove_member(
    venue_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if vm.venue_role == "OWNER":
        owners = db.execute(
            select(VenueMember.id).where(
                VenueMember.venue_id == venue_id,
                VenueMember.venue_role == "OWNER",
                VenueMember.is_active.is_(True),
            )
        ).all()
        if len(owners) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove last OWNER")

    vm.is_active = False

    # Deactivate member's position (if exists) and remove their assignments in this venue
    venue_shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)

    # Remove their assignments first (FK depends on venue_positions)
    db.execute(
        delete(ShiftAssignment).where(
            ShiftAssignment.member_user_id == member_user_id,
            ShiftAssignment.shift_id.in_(venue_shift_ids),
        )
    )

    # Remove member's position (if exists)
    db.execute(
        delete(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == member_user_id,
        )
    )

    db.commit()
    return {"ok": True}

@router.post("/{venue_id}/leave", status_code=204)
def leave_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Находим активное членство пользователя в заведении
    membership = (
        db.query(VenueMember)
        .filter(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == current_user.id,
            VenueMember.is_active.is_(True),
        )
        .one_or_none()
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не являетесь участником этого заведения",
        )

    # Если это OWNER — проверяем, что он не последний владелец
    if membership.venue_role == "OWNER":
        owners_count = (
            db.query(VenueMember)
            .filter(
                VenueMember.venue_id == venue_id,
                VenueMember.venue_role == "OWNER",
                VenueMember.is_active.is_(True),
            )
            .count()
        )

        if owners_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя выйти из заведения: вы последний владелец",
            )

    # Деактивируем membership
    membership.is_active = False
    db.add(membership)

    # Deactivate user's position (if exists) and remove their assignments in this venue
    venue_shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)

    # Remove assignments first
    db.execute(
        delete(ShiftAssignment).where(
            ShiftAssignment.member_user_id == current_user.id,
            ShiftAssignment.shift_id.in_(venue_shift_ids),
        )
    )

    # Remove user's position (if exists)
    db.execute(
        delete(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == current_user.id,
        )
    )

    db.commit()

    return None
# ---------- Schedule: shift intervals & shifts ----------

@router.get("/{venue_id}/shift-intervals")
def list_shift_intervals(
    venue_id: int,
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List reusable time intervals for shifts.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    stmt = select(ShiftInterval).where(ShiftInterval.venue_id == venue_id)
    if not include_inactive:
        stmt = stmt.where(ShiftInterval.is_active.is_(True))

    rows = db.execute(stmt.order_by(ShiftInterval.start_time.asc(), ShiftInterval.id.asc())).scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "start_time": r.start_time.strftime("%H:%M"),
            "end_time": r.end_time.strftime("%H:%M"),
            "is_active": bool(r.is_active),
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

    obj = ShiftInterval(
        venue_id=venue_id,
        title=payload.title.strip(),
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_active=payload.is_active,
    )
    db.add(obj)
    try:
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

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.start_time is not None:
        obj.start_time = payload.start_time
    if payload.end_time is not None:
        obj.end_time = payload.end_time
    if payload.is_active is not None:
        obj.is_active = payload.is_active

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

    obj.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/shifts")
def list_shifts(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List shifts for a venue.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    stmt = select(Shift).where(Shift.venue_id == venue_id, Shift.is_active.is_(True))

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

    shifts = db.execute(stmt.order_by(Shift.date.asc(), Shift.id.asc())).scalars().all()

    # preload daily reports for these shift dates (for report_exists + salary calculation)
    shift_dates = {s.date for s in shifts}
    report_by_date: dict[date, DailyReport] = {}
    if shift_dates:
        rrows = db.execute(
            select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date.in_(shift_dates))
        ).scalars().all()
        report_by_date = {r.date: r for r in rrows}

    show_revenue = _can_view_revenue(db, venue_id=venue_id, user=user)

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

    
    # tips share: split report.tips_total equally between unique employees scheduled for that day
    members_by_date: dict[date, set[int]] = {}
    for sh in shifts:
        sset = members_by_date.setdefault(sh.date, set())
        for a in assignments_by_shift.get(sh.id, []):
            try:
                sset.add(int(a["member_user_id"]))
            except Exception:
                pass

    tips_share_by_date: dict[date, float] = {}
    for d0, members in members_by_date.items():
        rep = report_by_date.get(d0)
        if rep and members:
            tips_share_by_date[d0] = float(rep.tips_total or 0) / float(len(members))
        else:
            tips_share_by_date[d0] = 0.0

    my_has_by_date = {d0: (user.id in members_by_date.get(d0, set())) for d0 in members_by_date.keys()}
    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "interval": interval_payload(s.interval_id),
            "interval_id": s.interval_id,
            "is_active": bool(s.is_active),
            "assignments": assignments_by_shift.get(s.id, []),
            "report_exists": bool(report_by_date.get(s.date)),
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
                tips_share_by_date.get(s.date)
                if (report_by_date.get(s.date) and my_has_by_date.get(s.date))
                else None
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

    obj = Shift(
        venue_id=venue_id,
        date=payload.date,
        interval_id=payload.interval_id,
        is_active=payload.is_active,
        created_by_user_id=user.id,
    )

    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # likely unique constraint
        raise HTTPException(status_code=409, detail="Shift already exists for this date and interval")

    db.refresh(obj)
    return {"id": obj.id}


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
    if payload.is_active is not None:
        obj.is_active = payload.is_active

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shift already exists for this date and interval")

    return {"ok": True}


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

    obj.is_active = False
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

    db.delete(a)
    db.commit()
    return {"ok": True}


# ---------- Adjustments (penalties / writeoffs / bonuses) ----------

def _notify_user(db: Session, user_id: int, text: str) -> None:
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if u and u.tg_user_id:
        send_telegram_message(int(u.tg_user_id), text)


def _notify_adjustments_moderators(db: Session, venue_id: int, text: str) -> None:
    # owners
    owner_user_ids = db.execute(
        select(VenueMember.user_id).where(
            VenueMember.venue_id == venue_id,
            VenueMember.venue_role == "OWNER",
            VenueMember.is_active.is_(True),
        )
    ).scalars().all()

    # positions with resolver rights
    resolver_user_ids = db.execute(
        select(VenuePosition.member_user_id).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.is_active.is_(True),
            (VenuePosition.can_resolve_disputes.is_(True) | VenuePosition.can_manage_adjustments.is_(True)),
        )
    ).scalars().all()

    ids = set(owner_user_ids) | set(resolver_user_ids)
    for uid in ids:
        _notify_user(db, uid, text)


def _adjustment_payload(obj, t: str):
    base = {
        "type": t,
        "id": obj.id,
        "venue_id": obj.venue_id,
        "member_user_id": getattr(obj, "member_user_id", None),
        "date": obj.date.isoformat(),
        "amount": int(obj.amount),
        "reason": obj.reason,
        "created_by_user_id": obj.created_by_user_id,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    }
    return base


@router.post("/{venue_id}/adjustments")
def create_adjustment(
    venue_id: int,
    payload: AdjustmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    t = (payload.type or "").strip().lower()
    if t not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad type")

    if t in ("penalty", "bonus"):
        if not payload.member_user_id:
            raise HTTPException(status_code=400, detail="member_user_id required")
    if t == "writeoff":
        # member_user_id is optional; null means venue-level
        pass

    if t == "penalty":
        obj = Penalty(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            date=payload.date,
            amount=payload.amount,
            reason=payload.reason,
            created_by_user_id=user.id,
            created_at=datetime.utcnow(),
        )
    elif t == "bonus":
        obj = Bonus(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            date=payload.date,
            amount=payload.amount,
            reason=payload.reason,
            created_by_user_id=user.id,
            created_at=datetime.utcnow(),
        )
    else:
        obj = Writeoff(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            date=payload.date,
            amount=payload.amount,
            reason=payload.reason,
            created_by_user_id=user.id,
            created_at=datetime.utcnow(),
        )

    db.add(obj)
    db.commit()
    db.refresh(obj)

    # notify target employee (only if member_user_id set)
    if getattr(obj, "member_user_id", None):
        title = {"penalty": "Штраф", "bonus": "Премия", "writeoff": "Списание"}.get(t, "Изменение")
        _notify_user(db, int(obj.member_user_id), f"{title} · {payload.date.isoformat()} · {payload.amount}\n{payload.reason or ''}".strip())

    return _adjustment_payload(obj, t)


@router.get("/{venue_id}/adjustments")
def list_adjustments(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    type: str | None = Query(default=None, description="penalty|writeoff|bonus"),
    mine: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    t = (type or "").strip().lower() or None
    if t and t not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad type")

    if mine:
        # employee view: only own items (no venue-level writeoffs)
        pass
    else:
        _require_adjustments_viewer(db, venue_id=venue_id, user=user)

    items: list[dict] = []

    def add_rows(rows, tt):
        for r in rows:
            items.append(_adjustment_payload(r, tt))

    if (t is None) or (t == "penalty"):
        stmt = select(Penalty).where(
            Penalty.venue_id == venue_id,
            Penalty.is_active.is_(True),
            Penalty.date >= start,
            Penalty.date < end,
        )
        if mine:
            stmt = stmt.where(Penalty.member_user_id == user.id)
        add_rows(db.execute(stmt).scalars().all(), "penalty")

    if (t is None) or (t == "bonus"):
        stmt = select(Bonus).where(
            Bonus.venue_id == venue_id,
            Bonus.is_active.is_(True),
            Bonus.date >= start,
            Bonus.date < end,
        )
        if mine:
            stmt = stmt.where(Bonus.member_user_id == user.id)
        add_rows(db.execute(stmt).scalars().all(), "bonus")

    if (t is None) or (t == "writeoff"):
        stmt = select(Writeoff).where(
            Writeoff.venue_id == venue_id,
            Writeoff.is_active.is_(True),
            Writeoff.date >= start,
            Writeoff.date < end,
        )
        if mine:
            stmt = stmt.where(Writeoff.member_user_id == user.id)
        add_rows(db.execute(stmt).scalars().all(), "writeoff")

    items.sort(key=lambda x: (x["date"], x["type"], x["id"]))
    return {"items": items}


@router.get("/{venue_id}/adjustments/{target_type}/{target_id}")
def get_adjustment(
    venue_id: int,
    target_type: str,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    t = (target_type or "").strip().lower()
    if t not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad target_type")

    # access rules:
    # - managers/viewers: can view everything
    # - others: only their own (and only if member_user_id exists)
    can_all = _is_adjustments_viewer(db, venue_id=venue_id, user=user)

    if t == "penalty":
        obj = db.execute(select(Penalty).where(Penalty.id == target_id, Penalty.venue_id == venue_id, Penalty.is_active.is_(True))).scalar_one_or_none()
    elif t == "bonus":
        obj = db.execute(select(Bonus).where(Bonus.id == target_id, Bonus.venue_id == venue_id, Bonus.is_active.is_(True))).scalar_one_or_none()
    else:
        obj = db.execute(select(Writeoff).where(Writeoff.id == target_id, Writeoff.venue_id == venue_id, Writeoff.is_active.is_(True))).scalar_one_or_none()

    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if not can_all:
        mid = getattr(obj, "member_user_id", None)
        if not mid or int(mid) != int(user.id):
            raise HTTPException(status_code=403, detail="Forbidden")

    # dispute info
    disp = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.target_type == t,
            AdjustmentDispute.target_id == target_id,
            AdjustmentDispute.is_active.is_(True),
        ).order_by(AdjustmentDispute.id.desc())
    ).scalar_one_or_none()

    data = _adjustment_payload(obj, t)
    data["dispute"] = (
        {
            "id": disp.id,
            "status": disp.status,
            "created_by_user_id": disp.created_by_user_id,
            "created_at": disp.created_at.isoformat(),
            "resolved_by_user_id": disp.resolved_by_user_id,
            "resolved_at": disp.resolved_at.isoformat() if disp.resolved_at else None,
        }
        if disp else None
    )
    return data


@router.post("/{venue_id}/adjustments/{target_type}/{target_id}/dispute")
def create_dispute(
    venue_id: int,
    target_type: str,
    target_id: int,
    payload: DisputeCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    t = (target_type or "").strip().lower()
    if t not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad target_type")

    # check target exists and belongs to user (unless viewer)
    can_all = _is_adjustments_viewer(db, venue_id=venue_id, user=user)

    if t == "penalty":
        obj = db.execute(select(Penalty).where(Penalty.id == target_id, Penalty.venue_id == venue_id, Penalty.is_active.is_(True))).scalar_one_or_none()
    elif t == "bonus":
        obj = db.execute(select(Bonus).where(Bonus.id == target_id, Bonus.venue_id == venue_id, Bonus.is_active.is_(True))).scalar_one_or_none()
    else:
        obj = db.execute(select(Writeoff).where(Writeoff.id == target_id, Writeoff.venue_id == venue_id, Writeoff.is_active.is_(True))).scalar_one_or_none()

    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if not can_all:
        mid = getattr(obj, "member_user_id", None)
        if not mid or int(mid) != int(user.id):
            raise HTTPException(status_code=403, detail="Forbidden")

    disp = AdjustmentDispute(
        venue_id=venue_id,
        target_type=t,
        target_id=target_id,
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
        status="OPEN",
        is_active=True,
    )
    db.add(disp)
    db.commit()
    db.refresh(disp)

    c = AdjustmentDisputeComment(
        dispute_id=disp.id,
        author_user_id=user.id,
        message=payload.message,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    db.add(c)
    db.commit()

    # notify moderators/resolvers
    title = {"penalty": "Штраф", "bonus": "Премия", "writeoff": "Списание"}.get(t, "Изменение")
    _notify_adjustments_moderators(
        db,
        venue_id,
        f"Оспорено: {title} #{target_id} · {getattr(obj,'date').isoformat()} · {getattr(obj,'amount')}\n{payload.message}",
    )

    return {"id": disp.id, "status": disp.status}


@router.post("/{venue_id}/disputes/{dispute_id}/comments")
def add_dispute_comment(
    venue_id: int,
    dispute_id: int,
    payload: DisputeCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    disp = db.execute(select(AdjustmentDispute).where(AdjustmentDispute.id == dispute_id, AdjustmentDispute.venue_id == venue_id, AdjustmentDispute.is_active.is_(True))).scalar_one_or_none()
    if disp is None:
        raise HTTPException(status_code=404, detail="Dispute not found")

    c = AdjustmentDisputeComment(
        dispute_id=disp.id,
        author_user_id=user.id,
        message=payload.message,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    db.add(c)
    db.commit()

    # notify resolvers if not author
    _notify_adjustments_moderators(db, venue_id, f"Комментарий к спору #{disp.id}:\n{payload.message}")

    return {"ok": True}


@router.patch("/{venue_id}/disputes/{dispute_id}")
def update_dispute_status(
    venue_id: int,
    dispute_id: int,
    payload: DisputeStatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_disputes_resolver(db, venue_id=venue_id, user=user)

    disp = db.execute(select(AdjustmentDispute).where(AdjustmentDispute.id == dispute_id, AdjustmentDispute.venue_id == venue_id, AdjustmentDispute.is_active.is_(True))).scalar_one_or_none()
    if disp is None:
        raise HTTPException(status_code=404, detail="Dispute not found")

    st = (payload.status or "").strip().upper()
    if st not in ("OPEN", "CLOSED"):
        raise HTTPException(status_code=400, detail="Bad status")

    disp.status = st
    if st == "CLOSED":
        disp.resolved_by_user_id = user.id
        disp.resolved_at = datetime.utcnow()
    else:
        disp.resolved_by_user_id = None
        disp.resolved_at = None

    db.commit()
    return {"ok": True, "status": disp.status}
