from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status, UploadFile, File
from sqlalchemy import select, delete, update, func, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes
from app.services.payroll.calculator import (
    PAY_COMPONENT_TYPES,
    BASE_SCOPE_FULL_PERIOD,
    BASE_SCOPE_WORKED_DATES,
    BOOST_RECALC_EXCESS_ONLY,
    BOOST_RECALC_REPLACE_ALL,
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_KPI_METRIC,
    BOOST_SOURCE_NONE,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
    MINIMUM_GUARANTEE_DAY,
    MINIMUM_GUARANTEE_MONTH,
    MINIMUM_GUARANTEE_SHIFT,
    calculate_payroll_for_month,
    parse_month_start,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.routers.venue_access import (
    _has_revenue_view_access,
    _is_active_member_or_admin,
    _is_owner_or_super_admin,
    _is_report_viewer,
    _require_active_member_or_admin,
    _require_owner_or_super_admin,
    _require_report_viewer,
    _require_revenue_viewer,
)
from app.models.user import User
from app.models.venue_setup_state import VenueSetupState
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.adjustment import Adjustment
from app.models.department import Department
from app.models.pay_profile import PayProfile
from app.models.pay_profile_assignment import PayProfileAssignment
from app.models.pay_component import PayComponent
from app.models.payroll_run import PayrollRun
from app.models.payroll_line import PayrollLine
from app.models.payroll_recalculation_log import PayrollRecalculationLog
from app.auth.venue_permissions import require_venue_permission, has_venue_permission

from app.routers.venue_common import (
    BASE_SCOPE_TITLES,
    BOOST_RECALC_TITLES,
    BOOST_SOURCE_TITLES,
    MINIMUM_GUARANTEE_SCOPE_TITLES,
)

from app.routers.venue_pay_profile_support import _parse_position_permission_codes


def _normalize_position_preset_item(raw: object, *, idx: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    raw_id = str(raw.get("id") or "").strip() or f"preset-{idx + 1}"
    try:
        rate = max(0, int(raw.get("rate") or 0))
    except Exception:
        rate = 0
    try:
        percent = max(0, min(100, int(raw.get("percent") or 0)))
    except Exception:
        percent = 0
    pay_profile_id = raw.get("pay_profile_id")
    try:
        pay_profile_id = int(pay_profile_id) if pay_profile_id not in (None, "", 0, "0") else None
    except Exception:
        pay_profile_id = None
    return {
        "id": raw_id,
        "title": title[:100],
        "rate": rate,
        "percent": percent,
        "pay_profile_id": pay_profile_id,
        "pay_profile_title": str(raw.get("pay_profile_title") or "").strip() or None,
        "template_id": str(raw.get("template_id") or "").strip() or None,
        "template_title": str(raw.get("template_title") or "").strip() or None,
        "permission_codes": _parse_position_permission_codes(raw.get("permission_codes")),
        "is_active": raw.get("is_active") is not False,
    }


def _load_position_presets_from_setup(db: Session, *, venue_id: int, include_inactive: bool = False) -> list[dict]:
    state = db.execute(select(VenueSetupState).where(VenueSetupState.venue_id == int(venue_id))).scalar_one_or_none()
    meta = getattr(state, "step_meta_json", None) or {}
    if not isinstance(meta, dict):
        return []
    raw_positions = meta.get("positions") or {}
    if not isinstance(raw_positions, dict):
        return []
    raw_presets = raw_positions.get("presets") or []
    if not isinstance(raw_presets, list):
        return []

    items: list[dict] = []
    for idx, raw in enumerate(raw_presets):
        item = _normalize_position_preset_item(raw, idx=idx)
        if not item:
            continue
        if not include_inactive and not item.get("is_active", True):
            continue
        items.append(item)

    profile_ids = sorted({int(x["pay_profile_id"]) for x in items if x.get("pay_profile_id")})
    if profile_ids:
        rows = db.execute(
            select(PayProfile.id, PayProfile.title).where(
                PayProfile.venue_id == int(venue_id),
                PayProfile.id.in_(profile_ids),
            )
        ).all()
        titles = {int(r.id): str(r.title or "") for r in rows}
        for item in items:
            pid = item.get("pay_profile_id")
            if pid and titles.get(int(pid)):
                item["pay_profile_title"] = titles[int(pid)]
    return items
