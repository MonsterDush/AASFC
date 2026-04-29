from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import json

from app.auth.deps import get_current_user
from app.auth.passwords import has_password
from app.auth.phone_auth import get_user_auth_methods, get_user_phone
from app.core.db import get_db
from app.core.roles_registry import VENUE_ROLE_TO_DEFAULT_ROLE
from app.core.permissions_registry import PERMISSIONS as PERMISSIONS_REGISTRY
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes, unique_permission_codes
from app.core.permission_policy import expand_permission_codes, get_default_permission_codes_for_role
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
    DailyReportTipAllocation,
    Adjustment,
    PayrollLine,
    PayrollRun,
    PayProfile,
    NotificationDeliveryLog,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.services.payroll.period_summary import build_member_period_summary, resolve_salary_period
from app.services.billing.access import BILLING_ACCESS_DENIED, BILLING_ACCESS_FULL, get_user_billing_access, get_venue_billing_snapshot
from app.services.demo.access import build_demo_banner_payload, build_demo_context_payload
from app.services.setup import build_setup_summary, build_setup_summary_map
from app.services.shifts.slots import normalize_shift_slot


router = APIRouter(tags=["me"])

from pydantic import BaseModel, Field, field_validator

class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)





class NotificationSettingsIn(BaseModel):
    notify_enabled: bool | None = None
    notify_adjustments: bool | None = None
    notify_shifts: bool | None = None
    notify_shift_comments: bool | None = None
    notify_day_economics: bool | None = None
    notify_salary: bool | None = None
    notify_soft_alerts: bool | None = None
    shift_reminder_lead_time_hours: int | None = Field(default=None)
    notification_detail_level: str | None = Field(default=None, max_length=16)

    @field_validator("shift_reminder_lead_time_hours")
    @classmethod
    def validate_shift_reminder_lead_time_hours(cls, value: int | None):
        if value is None:
            return value
        if value not in {1, 2, 6, 12, 18, 24}:
            raise ValueError("shift_reminder_lead_time_hours must be one of: 1, 2, 6, 12, 18, 24")
        return value

    @field_validator("notification_detail_level")
    @classmethod
    def validate_notification_detail_level(cls, value: str | None):
        if value is None:
            return value
        normalized = str(value or "").strip().lower()
        if normalized not in {"short", "standard", "detailed"}:
            raise ValueError("notification_detail_level must be one of: short, standard, detailed")
        return normalized


class ManualTipCreateIn(BaseModel):
    venue_id: int = Field(..., gt=0)
    date: date
    amount: int = Field(..., gt=0)
    note: str | None = Field(default=None, max_length=500)




def _notification_settings_meta(user: User) -> dict:
    telegram_linked = bool(getattr(user, "tg_user_id", None))
    disabled_reason = None
    if not telegram_linked:
        disabled_reason = "Привяжите Telegram в профиле, чтобы бот мог отправлять уведомления."
    return {
        "telegram_linked": telegram_linked,
        "tg_user_id": getattr(user, "tg_user_id", None),
        "tg_username": getattr(user, "tg_username", None),
        "can_receive_bot_notifications": telegram_linked,
        "settings_locked": not telegram_linked,
        "disabled_reason": disabled_reason,
    }




def _serialize_billing_access_payload(access: dict) -> dict:
    return {
        "billing_status": access.get("billing_status"),
        "billing_access_mode": access.get("billing_access_mode"),
        "paid_until": access.get("paid_until").isoformat() if access.get("paid_until") else None,
        "grace_until": access.get("grace_until").isoformat() if access.get("grace_until") else None,
        "billing_restricted_reason": access.get("billing_restricted_reason"),
        "billing_kind": access.get("billing_kind"),
        "is_trial": bool(access.get("is_trial")),
        "trial_until": access.get("trial_until").isoformat() if access.get("trial_until") else None,
    }




def _serialize_setup_payload(summary: dict | None) -> dict:
    summary = dict(summary or {})
    return {
        "setup_status": summary.get("status"),
        "setup_phase": summary.get("phase"),
        "setup_progress_total": int(summary.get("progress_total") or 0),
        "setup_progress_done": int(summary.get("progress_done") or 0),
        "setup_progress_resolved": int(summary.get("progress_resolved") or 0),
        "setup_resume_step": summary.get("resume_step"),
        "setup_prepare_done": bool(summary.get("prepare_done")),
        "setup_extra_done": bool(summary.get("extra_done")),
    }

def _serialize_demo_payload(user: User | None, *, venue: Venue | None = None, venue_id: int | None = None) -> dict:
    payload = build_demo_context_payload(user, venue=venue, venue_id=venue_id)
    payload["demo_banner"] = build_demo_banner_payload()
    return payload


def _notification_settings_payload(user: User) -> dict:
    return {
        "notify_enabled": user.notify_enabled,
        "notify_adjustments": user.notify_adjustments,
        "notify_shifts": user.notify_shifts,
        "notify_shift_comments": user.notify_shift_comments,
        "notify_day_economics": user.notify_day_economics,
        "notify_salary": user.notify_salary,
        "notify_soft_alerts": user.notify_soft_alerts,
        "shift_reminder_lead_time_hours": user.shift_reminder_lead_time_hours,
        "notification_detail_level": user.notification_detail_level,
        "shift_reminder_lead_time_options": [1, 2, 6, 12, 18, 24],
        "notification_detail_level_options": ["short", "standard", "detailed"],
        **_notification_settings_meta(user),
    }

@router.get("/me")
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
        "notify_shift_comments": user.notify_shift_comments,
        "notify_day_economics": user.notify_day_economics,
        "notify_salary": user.notify_salary,
        "notify_soft_alerts": user.notify_soft_alerts,
        "shift_reminder_lead_time_hours": user.shift_reminder_lead_time_hours,
        "notification_detail_level": user.notification_detail_level,
        "phone": get_user_phone(db, user_id=user.id),
        "auth_methods": get_user_auth_methods(db, user_id=user.id),
        "has_password": has_password(user),
        "password_set_at": user.password_set_at.isoformat() if user.password_set_at else None,
        **_serialize_demo_payload(user),
    }


@router.get("/me/permissions/catalog")
def my_permissions_catalog(user: User = Depends(get_current_user)):
    """Return full permission registry for dynamic UI builders.

    The list is sourced from code registry, so new permissions appear in UI
    immediately after frontend/backend deploy even before sync_permissions.
    """
    return {
        "items": [
            {
                "code": p.code,
                "group": p.group,
                "title": p.title,
                "description": p.description,
            }
            for p in PERMISSIONS_REGISTRY
        ]
    }



@router.get("/me/profile")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "id": user.id,
        "tg_user_id": user.tg_user_id,
        "tg_username": user.tg_username,
        "full_name": user.full_name,
        "short_name": user.short_name,
        "phone": get_user_phone(db, user_id=user.id),
        "auth_methods": get_user_auth_methods(db, user_id=user.id),
        "has_password": has_password(user),
        "password_set_at": user.password_set_at.isoformat() if user.password_set_at else None,
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
    return _notification_settings_payload(user)


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
    if payload.notify_shift_comments is not None:
        user.notify_shift_comments = bool(payload.notify_shift_comments)
    if payload.notify_day_economics is not None:
        user.notify_day_economics = bool(payload.notify_day_economics)
    if payload.notify_salary is not None:
        user.notify_salary = bool(payload.notify_salary)
    if payload.notify_soft_alerts is not None:
        user.notify_soft_alerts = bool(payload.notify_soft_alerts)
    if payload.shift_reminder_lead_time_hours is not None:
        user.shift_reminder_lead_time_hours = int(payload.shift_reminder_lead_time_hours)
    if payload.notification_detail_level is not None:
        user.notification_detail_level = str(payload.notification_detail_level).strip().lower() or "standard"
    db.commit()
    return {
        "ok": True,
        "settings": _notification_settings_payload(user),
    }


@router.get("/me/notification-history")
def get_notification_history(
    limit: int = Query(30, ge=1, le=100),
    notification_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(NotificationDeliveryLog, Venue.name.label("venue_name"))
        .outerjoin(Venue, Venue.id == NotificationDeliveryLog.venue_id)
        .where(NotificationDeliveryLog.user_id == user.id)
    )
    if notification_type:
        stmt = stmt.where(NotificationDeliveryLog.notification_type == str(notification_type).strip())
    if status:
        stmt = stmt.where(NotificationDeliveryLog.status == str(status).strip())
    stmt = stmt.order_by(
        func.coalesce(NotificationDeliveryLog.sent_at, NotificationDeliveryLog.planned_at).desc(),
        NotificationDeliveryLog.id.desc(),
    ).limit(int(limit))

    rows = db.execute(stmt).all()
    items = []
    for row in rows:
        log_entry = row[0]
        venue_name = row[1]
        items.append({
            "id": int(log_entry.id),
            "notification_type": log_entry.notification_type,
            "status": log_entry.status,
            "venue_id": log_entry.venue_id,
            "venue_name": venue_name,
            "shift_id": log_entry.shift_id,
            "shift_assignment_id": log_entry.shift_assignment_id,
            "planned_at": log_entry.planned_at.isoformat() if log_entry.planned_at else None,
            "sent_at": log_entry.sent_at.isoformat() if log_entry.sent_at else None,
            "idempotency_key": log_entry.idempotency_key,
            "error_text": log_entry.error_text,
            "payload_preview": log_entry.payload_preview,
        })

    return {
        "items": items,
        "limit": int(limit),
        **_notification_settings_meta(user),
    }


@router.get("/me/venues")
def my_venues(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Venue.id, Venue.name, Venue.is_archived, Venue.archived_at, Venue.is_demo, Venue.demo_reference_year, Venue.demo_reference_month, VenueMember.venue_role)
        .join(VenueMember, VenueMember.venue_id == Venue.id)
        .where(
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
        .order_by(Venue.id.desc())
    ).all()

    venue_ids = [int(r.id) for r in rows]
    position_codes_by_venue: dict[int, set[str]] = {}
    if venue_ids:
        position_rows = db.execute(
            select(VenuePosition.venue_id, VenuePosition.permission_codes)
            .where(
                VenuePosition.member_user_id == user.id,
                VenuePosition.is_active.is_(True),
                VenuePosition.venue_id.in_(venue_ids),
            )
        ).all()
        for row in position_rows:
            vid = int(row.venue_id)
            position_codes_by_venue.setdefault(vid, set()).update(parse_permission_codes(row.permission_codes))

    setup_summary_map = build_setup_summary_map(db, venue_ids, create_missing=False) if venue_ids else {}

    items = []
    is_admin = user.system_role in {"SUPER_ADMIN", "MODERATOR"}
    for r in rows:
        venue_id = int(r.id)
        role = str(r.venue_role or "").upper()
        is_owner = role == "OWNER"
        is_archived = bool(r.is_archived)
        billing_access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=role)
        billing_access_mode = str(billing_access.get("billing_access_mode") or BILLING_ACCESS_DENIED).upper()

        if billing_access_mode == BILLING_ACCESS_DENIED and not is_admin:
            continue
        if is_archived and not (is_owner or is_admin):
            continue
        if is_archived and not include_archived:
            continue

        raw_codes = sorted(position_codes_by_venue.get(venue_id, set()))
        normalized_codes = set(normalize_known_permission_codes(db, raw_codes)) if raw_codes else set()
        expanded_codes = expand_permission_codes(normalized_codes) if normalized_codes else set()

        defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(r.venue_role)
        default_codes = set(get_default_permission_codes_for_role(defaults_role)) if defaults_role else set()
        if defaults_role:
            default_codes.update(
                db.scalars(
                    select(RolePermissionDefault.permission_code)
                    .join(Permission, Permission.code == RolePermissionDefault.permission_code)
                    .where(
                        RolePermissionDefault.role == defaults_role,
                        RolePermissionDefault.is_granted_by_default.is_(True),
                        Permission.is_active.is_(True),
                    )
                ).all()
            )
        expanded_codes.update(expand_permission_codes(default_codes) if default_codes else set())
        demo_payload = _serialize_demo_payload(user, venue=r, venue_id=venue_id)
        can_open_venue = bool(
            billing_access_mode != BILLING_ACCESS_DENIED
            and (is_owner or is_admin or {"VENUE_VIEW", "VENUE_SETTINGS_EDIT"}.intersection(expanded_codes))
        )
        if demo_payload.get("demo_mode"):
            can_open_venue = True
            open_target = (
                f"/staff-shifts.html?venue_id={venue_id}"
                if str(demo_payload.get("demo_persona") or "").upper() == "STAFF"
                else f"/app-venue.html?venue_id={venue_id}"
            )
        else:
            open_target = (
                f"/app-venue.html?venue_id={venue_id}"
                if (billing_access_mode == "BILLING_READONLY" or can_open_venue)
                else f"/staff-shifts.html?venue_id={venue_id}"
            )

        items.append({
            "id": venue_id,
            "name": r.name,
            "my_role": r.venue_role,
            "is_archived": is_archived,
            "archived_at": r.archived_at.isoformat() if r.archived_at else None,
            "can_open_venue": can_open_venue or billing_access_mode == "BILLING_READONLY",
            "open_target": open_target,
            **_serialize_billing_access_payload(billing_access),
            **_serialize_setup_payload(setup_summary_map.get(venue_id)),
            **demo_payload,
        })

    return items


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
        return {"venue_id": venue_id, "members": []}

    if vm is not None and user.system_role not in ("SUPER_ADMIN", "MODERATOR"):
        access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=str(vm.venue_role or ""))
        if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
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
    """Return permissions + venue role for current user and billing state."""

    system_billing_snapshot = get_venue_billing_snapshot(db, venue_id=venue_id)
    system_billing_payload = {
        "billing_status": system_billing_snapshot.status,
        "billing_access_mode": BILLING_ACCESS_FULL,
        "paid_until": system_billing_snapshot.paid_until.isoformat() if system_billing_snapshot.paid_until else None,
        "grace_until": system_billing_snapshot.grace_until.isoformat() if system_billing_snapshot.grace_until else None,
        "billing_restricted_reason": None,
    }
    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    venue_inactive = bool(getattr(venue, "is_archived", False))
    demo_payload = _serialize_demo_payload(user, venue=venue, venue_id=venue_id)
    setup_summary = build_setup_summary(db, venue_id=venue_id, create_missing=False)

    if user.system_role == "SUPER_ADMIN":
        codes = db.scalars(select(Permission.code).where(Permission.is_active.is_(True))).all()
        return {
            "venue_id": venue_id,
            "role": "SUPER_ADMIN",
            "permissions": list(codes),
            "position": None,
            **system_billing_payload,
            **_serialize_setup_payload(setup_summary),
            **demo_payload,
        }

    if user.system_role == "MODERATOR":
        codes = set(get_default_permission_codes_for_role("MODERATOR"))
        codes.update(
            db.scalars(
                select(RolePermissionDefault.permission_code)
                .join(Permission, Permission.code == RolePermissionDefault.permission_code)
                .where(
                    RolePermissionDefault.role == "MODERATOR",
                    RolePermissionDefault.is_granted_by_default.is_(True),
                    Permission.is_active.is_(True),
                )
            ).all()
        )
        return {
            "venue_id": venue_id,
            "role": "MODERATOR",
            "permissions": sorted(expand_permission_codes(codes)),
            "position": None,
            **system_billing_payload,
            **_serialize_setup_payload(setup_summary),
            **demo_payload,
        }

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == user.id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        denied_payload = {
            "billing_status": system_billing_snapshot.status,
            "billing_access_mode": BILLING_ACCESS_DENIED,
            "paid_until": system_billing_snapshot.paid_until.isoformat() if system_billing_snapshot.paid_until else None,
            "grace_until": system_billing_snapshot.grace_until.isoformat() if system_billing_snapshot.grace_until else None,
            "billing_restricted_reason": system_billing_snapshot.restricted_reason,
        }
        return {
            "venue_id": venue_id,
            "role": None,
            "permissions": [],
            "position": None,
            "venue_inactive": venue_inactive,
            "access_denied_reason": "Заведение сейчас не активно" if venue_inactive else None,
            **denied_payload,
            **_serialize_setup_payload(setup_summary),
            **demo_payload,
        }

    role_upper = str(vm.venue_role or "").upper()
    billing_access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=role_upper)

    if venue_inactive and user.system_role not in ("SUPER_ADMIN", "MODERATOR") and role_upper != "OWNER":
        return {
            "venue_id": venue_id,
            "role": vm.venue_role,
            "permissions": [],
            "position": None,
            "venue_inactive": True,
            "access_denied_reason": "Заведение сейчас не активно",
            **_serialize_billing_access_payload(billing_access),
            **_serialize_setup_payload(setup_summary),
            **demo_payload,
        }

    if role_upper == "OWNER":
        all_codes = db.scalars(select(Permission.code).where(Permission.is_active.is_(True))).all()
        codes = list(all_codes)
    else:
        defaults_role = VENUE_ROLE_TO_DEFAULT_ROLE.get(vm.venue_role)
        if not defaults_role:
            codes = []
        else:
            codes = list(get_default_permission_codes_for_role(defaults_role))
            codes.extend(
                db.scalars(
                    select(RolePermissionDefault.permission_code)
                    .join(Permission, Permission.code == RolePermissionDefault.permission_code)
                    .where(
                        RolePermissionDefault.role == defaults_role,
                        RolePermissionDefault.is_granted_by_default.is_(True),
                        Permission.is_active.is_(True),
                    )
                ).all()
            )

    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()

    position_codes: list[str] = []
    position_obj = None
    if pos is not None:
        position_codes = parse_permission_codes(getattr(pos, "permission_codes", None))
        position_obj = {
            "id": pos.id,
            "title": pos.title,
            "rate": pos.rate,
            "percent": pos.percent,
            "is_active": bool(pos.is_active),
            "permission_codes": position_codes,
        }

    merged = unique_permission_codes(codes)
    if position_codes:
        for c in normalize_known_permission_codes(db, position_codes):
            if c not in merged:
                merged.append(c)
    merged = sorted(expand_permission_codes(merged))

    return {
        "venue_id": venue_id,
        "role": vm.venue_role,
        "permissions": merged,
        "position": position_obj,
        "venue_inactive": venue_inactive,
        "access_denied_reason": None,
        **_serialize_billing_access_payload(billing_access),
        **_serialize_setup_payload(setup_summary),
        **demo_payload,
    }


def _parse_month_range(month: str) -> tuple[date, date]:
    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return start, end
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")


def _resolve_salary_period_or_400(
    *,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[date, date, dict]:
    try:
        return resolve_salary_period(month=month, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _load_payroll_summary_by_venue(db: Session, *, user_id: int, month_start: date) -> dict[int, dict]:
    rows = db.execute(
        select(
            PayrollLine.venue_id,
            Venue.name.label("venue_name"),
            func.coalesce(func.sum(PayrollLine.amount_minor), 0).label("earned_minor"),
            func.max(PayrollLine.id).label("payroll_line_id"),
        )
        .join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .join(Venue, Venue.id == PayrollLine.venue_id)
        .where(
            PayrollLine.member_user_id == int(user_id),
            PayrollRun.period_month == month_start,
        )
        .group_by(PayrollLine.venue_id, Venue.name)
    ).all()
    out: dict[int, dict] = {}
    for row in rows:
        vid = int(row.venue_id)
        earned_minor = int(row.earned_minor or 0)
        out[vid] = {
            "venue_id": vid,
            "venue_name": row.venue_name or "",
            "earned_minor": earned_minor,
            "earned": int(round(earned_minor / 100.0)),
            "source": "payroll",
            "payroll_line_id": int(row.payroll_line_id) if row.payroll_line_id is not None else None,
        }
    return out


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
            Shift.shift_slot.label("shift_slot"),
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
    keys = {(r.venue_id, r.shift_date, normalize_shift_slot(r.shift_slot)) for r in rows}
    reports = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id.in_({k[0] for k in keys}),
            DailyReport.date.in_({k[1] for k in keys}),
            DailyReport.shift_slot.in_({k[2] for k in keys}),
        )
    ).scalars().all()
    report_by_key = {(r.venue_id, r.date, normalize_shift_slot(getattr(r, "shift_slot", None))): r for r in reports}

    out = []
    for r in rows:
        slot = normalize_shift_slot(r.shift_slot)
        rep = report_by_key.get((r.venue_id, r.shift_date, slot))
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
                "shift_slot": slot,
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


@router.get("/me/payroll-line")
def my_payroll_line(
    month: str = Query(..., description="YYYY-MM"),
    venue_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    month_start, _month_end = _parse_month_range(month)

    rows = db.execute(
        select(PayrollLine, PayrollRun, Venue, PayProfile)
        .join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .join(Venue, Venue.id == PayrollLine.venue_id)
        .outerjoin(PayProfile, PayProfile.id == PayrollLine.pay_profile_id)
        .where(
            PayrollLine.member_user_id == int(user.id),
            PayrollRun.period_month == month_start,
            *([PayrollLine.venue_id == int(venue_id)] if venue_id is not None else []),
        )
        .order_by(Venue.name.asc(), PayrollLine.id.asc())
    ).all()

    items = []
    for line, run, venue, profile in rows:
        try:
            breakdown = json.loads(line.breakdown_json) if line.breakdown_json else None
        except Exception:
            breakdown = None
        items.append(
            {
                "id": int(line.id),
                "venue": {"id": int(venue.id), "name": venue.name},
                "month": month,
                "amount_minor": int(line.amount_minor or 0),
                "amount": int(round(int(line.amount_minor or 0) / 100.0)),
                "pay_profile_id": int(line.pay_profile_id) if line.pay_profile_id is not None else None,
                "pay_profile_title": profile.title if profile is not None else None,
                "run": {
                    "id": int(run.id),
                    "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
                },
                "breakdown": breakdown,
                "source": "payroll",
            }
        )

    if venue_id is not None:
        return items[0] if items else None
    return {"month": month, "items": items}


@router.get("/me/salary-day-breakdown")
def my_salary_day_breakdown(
    venue_id: int = Query(..., gt=0),
    date_value: date = Query(..., alias="date"),
    shift_slot: str = Query(default="TOTAL", pattern="^(TOTAL|DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id == int(user.id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None and user.system_role not in ("SUPER_ADMIN", "MODERATOR"):
        raise HTTPException(status_code=403, detail="Forbidden")

    return build_member_day_breakdown(
        db,
        member_user_id=int(user.id),
        venue_id=int(venue_id),
        target_date=date_value,
        shift_slot=shift_slot,
    )


@router.post("/me/manual-tips")
def create_manual_tip(
    payload: ManualTipCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == int(payload.venue_id),
            VenueMember.user_id == int(user.id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None and user.system_role not in ("SUPER_ADMIN", "MODERATOR"):
        raise HTTPException(status_code=403, detail="Forbidden")

    obj = Adjustment(
        venue_id=int(payload.venue_id),
        type="tip",
        member_user_id=int(user.id),
        date=payload.date,
        amount=int(payload.amount or 0),
        reason=(payload.note or "").strip() or None,
        created_by_user_id=int(user.id),
        is_active=True,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {
        "id": int(obj.id),
        "venue_id": int(obj.venue_id),
        "date": obj.date.isoformat(),
        "amount": int(obj.amount or 0),
        "reason": obj.reason,
        "type": obj.type,
    }


@router.get("/me/salary-summary")
def my_salary_summary(
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Salary summary for current user for month or arbitrary range."""

    period_start, period_end, period_meta = _resolve_salary_period_or_400(
        month=month,
        date_from=date_from,
        date_to=date_to,
    )

    payload = build_member_period_summary(
        db,
        member_user_id=int(user.id),
        period_start=period_start,
        period_end=period_end,
    )

    response = {
        "items": payload.get("items") or [],
        "totals": payload.get("totals") or {
            "earned": 0,
            "tips": 0,
            "bonuses": 0,
            "penalties": 0,
            "net": 0,
            "earned_minor": 0,
            "tips_minor": 0,
            "bonuses_minor": 0,
            "penalties_minor": 0,
            "net_minor": 0,
        },
        "period": {
            "date_from": period_start.isoformat(),
            "date_to": period_end.isoformat(),
            **period_meta,
        },
    }
    if month is not None:
        response["month"] = month
    return response

