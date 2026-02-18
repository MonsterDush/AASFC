from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.models import (
    User,
    Venue,
    VenueMember,
    Permission,
    RolePermissionDefault,
    VenuePosition,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    DailyReport,
    Adjustment,
)


router = APIRouter(tags=["me"])


from pydantic import BaseModel, Field

class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)





class NotificationSettingsIn(BaseModel):
    notify_enabled: bool | None = None
    notify_adjustments: bool | None = None
    notify_shifts: bool | None = None

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_user_id": user.tg_user_id,
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
        "system_role": user.system_role,
        "notify_enabled": user.notify_enabled,
        "notify_adjustments": user.notify_adjustments,
        "notify_shifts": user.notify_shifts,
    }



@router.get("/me/profile")
def get_profile(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
    }


@router.patch("/me/profile")
def update_profile(
    payload: ProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # пустые строки считаем как None
    if payload.full_name is not None:
        v = payload.full_name.strip()
        user.full_name = v or None
    if payload.short_name is not None:
        v = payload.short_name.strip()
        user.short_name = v or None
    db.commit()
    return {"ok": True}


@router.get("/me/notification-settings")
def get_notification_settings(user: User = Depends(get_current_user)):
    return {
        "notify_enabled": user.notify_enabled,
        "notify_adjustments": user.notify_adjustments,
        "notify_shifts": user.notify_shifts,
    }


@router.patch("/me/notification-settings")
def update_notification_settings(
    payload: NotificationSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.notify_enabled is not None:
        user.notify_enabled = bool(payload.notify_enabled)
    if payload.notify_adjustments is not None:
        user.notify_adjustments = bool(payload.notify_adjustments)
    if payload.notify_shifts is not None:
        user.notify_shifts = bool(payload.notify_shifts)
    db.commit()
    return {"ok": True}


@router.get("/me/venues")
def my_venues(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Venue.id, Venue.name, VenueMember.venue_role)
        .join(VenueMember, VenueMember.venue_id == Venue.id)
        .where(
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
        .order_by(Venue.id.desc())
    ).all()

    return [{"id": r.id, "name": r.name, "my_role": r.venue_role} for r in rows]


@router.get("/me/venues/{venue_id}/members")
def my_venue_members(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # доступ: любой активный member этого venue
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None and user.system_role not in ("SUPER_ADMIN", "MODERATOR"):
        # можно 403 — так правильнее
        return {"venue_id": venue_id, "members": []}

    rows = db.execute(
        select(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == venue_id,
            VenueMember.is_active.is_(True),
        )
        .order_by(VenueMember.venue_role.asc(), User.id.asc())
    ).all()

    return {
        "venue_id": venue_id,
        "members": [
            {
                "user_id": r.id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
            }
            for r in rows
        ],
    }


@router.get("/me/venues/{venue_id}/permissions")
def my_venue_permissions(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return permissions + venue role + position flags for current user.

    Position flags are used for MVP UI gating:
    - can_make_reports
    - can_edit_schedule
    """

    # ---- system roles ----
    if user.system_role == "SUPER_ADMIN":
        codes = db.scalars(select(Permission.code).where(Permission.is_active.is_(True))).all()
        return {
            "venue_id": venue_id,
            "role": "SUPER_ADMIN",
            "permissions": list(codes),
            "position": None,
            "position_flags": {"can_make_reports": True, "can_edit_schedule": True},
        }

    if user.system_role == "MODERATOR":
        codes = db.scalars(
            select(RolePermissionDefault.permission_code)
            .join(Permission, Permission.code == RolePermissionDefault.permission_code)
            .where(
                RolePermissionDefault.role == "MODERATOR",
                RolePermissionDefault.is_granted_by_default.is_(True),
                Permission.is_active.is_(True),
            )
        ).all()
        return {
            "venue_id": venue_id,
            "role": "MODERATOR",
            "permissions": list(codes),
            "position": None,
            "position_flags": {"can_make_reports": True, "can_edit_schedule": True},
        }

    # ---- venue membership ----
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        return {
            "venue_id": venue_id,
            "role": None,
            "permissions": [],
            "position": None,
            "position_flags": {"can_make_reports": False, "can_edit_schedule": False},
        }

    defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
    if not defaults_role:
        codes = []
    else:
        codes = db.scalars(
            select(RolePermissionDefault.permission_code)
            .join(Permission, Permission.code == RolePermissionDefault.permission_code)
            .where(
                RolePermissionDefault.role == defaults_role,
                RolePermissionDefault.is_granted_by_default.is_(True),
                Permission.is_active.is_(True),
            )
        ).all()

    # ---- position flags (MVP) ----
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()

    position_obj = None
    flags = {"can_make_reports": False, "can_edit_schedule": False, "can_view_adjustments": False, "can_manage_adjustments": False}
    if pos is not None:
        position_obj = {
            "id": pos.id,
            "title": pos.title,
            "rate": pos.rate,
            "percent": pos.percent,
            "can_make_reports": bool(pos.can_make_reports),
            "can_view_reports": bool(pos.can_view_reports or pos.can_make_reports),
            "can_view_revenue": bool(pos.can_view_revenue or pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
            "can_view_adjustments": bool(getattr(pos, "can_view_adjustments", False)),
            "can_manage_adjustments": bool(getattr(pos, "can_manage_adjustments", False)),
            "is_active": bool(pos.is_active),
        }
        flags = {
            "can_make_reports": bool(pos.can_make_reports),
            "can_view_reports": bool(pos.can_view_reports or pos.can_make_reports),
            "can_view_revenue": bool(pos.can_view_revenue or pos.can_make_reports),
            "can_edit_schedule": bool(pos.can_edit_schedule),
            "can_view_adjustments": bool(getattr(pos, "can_view_adjustments", False)),
            "can_manage_adjustments": bool(getattr(pos, "can_manage_adjustments", False)),
        }

    return {
        "venue_id": venue_id,
        "role": vm.venue_role,
        "permissions": list(codes),
        "position": position_obj,
        "position_flags": flags,
    }



@router.get("/me/shifts")
def my_shifts_across_venues(
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return current user's shifts across all active venues (for 'Общий' calendar)."""

    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    # only shifts where the user is assigned
    rows = db.execute(
        select(
            Shift.id.label("shift_id"),
            Shift.date.label("shift_date"),
            Shift.venue_id.label("venue_id"),
            Venue.name.label("venue_name"),
            Shift.interval_id.label("interval_id"),
            ShiftInterval.title.label("interval_title"),
            ShiftInterval.start_time.label("start_time"),
            ShiftInterval.end_time.label("end_time"),
            VenuePosition.rate.label("rate"),
            VenuePosition.percent.label("percent"),
        )
        .select_from(ShiftAssignment)  # <-- ВАЖНО: фиксируем левую таблицу
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(Venue, Venue.id == Shift.venue_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .where(
            ShiftAssignment.member_user_id == user.id,
            Shift.is_active.is_(True),
            Shift.date >= start,
            Shift.date < end,
        )
        .order_by(Shift.date.asc(), Shift.id.asc())
    ).all()


    if not rows:
        return []

    # preload daily reports per (venue_id, date) for salary calc
    keys = {(r.venue_id, r.shift_date) for r in rows}
    reports = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id.in_({k[0] for k in keys}),
            DailyReport.date.in_({k[1] for k in keys}),
        )
    ).scalars().all()
    report_by_key = {(r.venue_id, r.date): r for r in reports}

    out = []
    for r in rows:
        rep = report_by_key.get((r.venue_id, r.shift_date))
        my_salary = None
        revenue_total = None
        if rep is not None:
            revenue_total = rep.revenue_total
            try:
                my_salary = int(r.rate) + (int(r.percent) / 100.0) * rep.revenue_total
            except Exception:
                my_salary = None

        out.append(
            {
                "shift_id": r.shift_id,
                "date": r.shift_date.isoformat(),
                "venue": {"id": r.venue_id, "name": r.venue_name},
                "interval": {
                    "id": r.interval_id,
                    "title": r.interval_title,
                    "start_time": r.start_time.strftime("%H:%M"),
                    "end_time": r.end_time.strftime("%H:%M"),
                },
                "my_salary": my_salary,
                "revenue_total": revenue_total,
            }
        )

    return out


@router.get("/me/salary-summary")
def my_salary_summary(
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Monthly salary summary across all venues for current user.

    Includes:
      - earned: sum of calculated shift salaries (only for shifts that have a DailyReport)
      - bonuses: sum of adjustments with type=bonus
      - penalties: sum of adjustments with type=penalty or writeoff
      - net: earned + bonuses - penalties
    """

    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    # 1) Shifts assigned to this user (across all venues)
    rows = db.execute(
        select(
            Shift.id.label("shift_id"),
            Shift.date.label("shift_date"),
            Shift.venue_id.label("venue_id"),
            Venue.name.label("venue_name"),
            ShiftInterval.start_time.label("start_time"),
            VenuePosition.rate.label("rate"),
            VenuePosition.percent.label("percent"),
        )
        .select_from(ShiftAssignment)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(Venue, Venue.id == Shift.venue_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .where(
            ShiftAssignment.member_user_id == user.id,
            Shift.is_active.is_(True),
            Shift.date >= start,
            Shift.date < end,
        )
    ).all()

    # preload daily reports per (venue_id, date)
    keys = {(r.venue_id, r.shift_date) for r in rows}
    report_by_key = {}
    if keys:
        reports = db.execute(
            select(DailyReport).where(
                DailyReport.venue_id.in_({k[0] for k in keys}),
                DailyReport.date.in_({k[1] for k in keys}),
            )
        ).scalars().all()
        report_by_key = {(r.venue_id, r.date): r for r in reports}

    earned_by_venue: dict[int, int] = {}
    venue_name_by_id: dict[int, str] = {}
    for r in rows:
        venue_name_by_id[int(r.venue_id)] = r.venue_name
        rep = report_by_key.get((r.venue_id, r.shift_date))
        if rep is None:
            continue
        try:
            sal = int(r.rate) + (int(r.percent) / 100.0) * rep.revenue_total
            sal_i = int(round(float(sal)))
        except Exception:
            continue
        earned_by_venue[int(r.venue_id)] = earned_by_venue.get(int(r.venue_id), 0) + sal_i

    # 2) Adjustments for this user in the month
    adj_rows = db.execute(
        select(Adjustment.venue_id, Adjustment.type, Adjustment.amount)
        .where(
            Adjustment.member_user_id == user.id,
            Adjustment.is_active.is_(True),
            Adjustment.date >= start,
            Adjustment.date < end,
        )
    ).all()

    bonuses_by_venue: dict[int, int] = {}
    penalties_by_venue: dict[int, int] = {}
    for v_id, typ, amount in adj_rows:
        vid = int(v_id)
        t = str(typ or "").lower()
        a = int(amount or 0)
        if t == "bonus":
            bonuses_by_venue[vid] = bonuses_by_venue.get(vid, 0) + a
        else:
            # penalty + writeoff => treat as penalty
            penalties_by_venue[vid] = penalties_by_venue.get(vid, 0) + a

    # 3) Compose response
    venue_ids = set(earned_by_venue.keys()) | set(bonuses_by_venue.keys()) | set(penalties_by_venue.keys())
    if venue_ids and len(venue_name_by_id) != len(venue_ids):
        # best-effort: load missing venue names
        missing = list(venue_ids - set(venue_name_by_id.keys()))
        if missing:
            vs = db.execute(select(Venue.id, Venue.name).where(Venue.id.in_(missing))).all()
            for vid, vname in vs:
                venue_name_by_id[int(vid)] = vname

    items = []
    total_net = 0
    total_earned = 0
    total_bonus = 0
    total_pen = 0

    for vid in sorted(venue_ids):
        earned = int(earned_by_venue.get(vid, 0))
        bonus = int(bonuses_by_venue.get(vid, 0))
        pen = int(penalties_by_venue.get(vid, 0))
        net = earned + bonus - pen
        total_net += net
        total_earned += earned
        total_bonus += bonus
        total_pen += pen
        items.append(
            {
                "venue": {"id": vid, "name": venue_name_by_id.get(vid, "")},
                "earned": earned,
                "bonuses": bonus,
                "penalties": pen,
                "net": net,
            }
        )

    return {
        "month": month,
        "items": items,
        "totals": {
            "earned": total_earned,
            "bonuses": total_bonus,
            "penalties": total_pen,
            "net": total_net,
        },
    }
