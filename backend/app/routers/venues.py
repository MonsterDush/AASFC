from __future__ import annotations

from datetime import datetime, timezone, date, time
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
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

from app.services.venues import create_venue

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
    can_edit_schedule: bool = False
    is_active: bool = True


class PositionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    member_user_id: int | None = Field(default=None, gt=0)
    rate: int | None = Field(default=None, ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)
    can_make_reports: bool | None = None
    can_edit_schedule: bool | None = None
    is_active: bool | None = None

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
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    if not venue.is_archived:
        raise HTTPException(400, "Archive venue before delete")

    db.delete(venue)
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
        db.query(User.id, User.tg_user_id, User.tg_username, VenueMember.venue_role)
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    rows = db.execute(
        select(
            VenuePosition.id,
            VenuePosition.title,
            VenuePosition.member_user_id,
            VenuePosition.rate,
            VenuePosition.percent,
            VenuePosition.can_make_reports,
            VenuePosition.can_edit_schedule,
            VenuePosition.is_active,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
            VenueMember.venue_role,
        )
        .join(User, User.id == VenuePosition.member_user_id)
        .join(VenueMember, (VenueMember.venue_id == VenuePosition.venue_id) & (VenueMember.user_id == VenuePosition.member_user_id))
        .where(VenuePosition.venue_id == venue_id)
        .order_by(VenuePosition.id.desc())
    ).all()

    return [
        {
            "id": r.id,
            "title": r.title,
            "member_user_id": r.member_user_id,
            "rate": r.rate,
            "percent": r.percent,
            "can_make_reports": bool(r.can_make_reports),
            "can_edit_schedule": bool(r.can_edit_schedule),
            "is_active": bool(r.is_active),
            "member": {
                "user_id": r.member_user_id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
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

    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "interval": interval_payload(s.interval_id),
            "interval_id": s.interval_id,
            "is_active": bool(s.is_active),
            "assignments": assignments_by_shift.get(s.id, []),
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
            VenuePosition.is_active.is_(True),
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
