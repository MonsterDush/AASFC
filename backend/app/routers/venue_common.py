from __future__ import annotations

import logging
import os
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.services.payroll.calculator import (
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
)
from app.services.financial_privacy import (
    FINANCIAL_VALUES_HIDDEN_MESSAGE,
    should_hide_financial_values_for_user,
)
from app.models.user import User


def _require_super_admin_or_moderator(user: User) -> None:
    role = str(getattr(user, "system_role", "") or "").upper()
    if role not in {"SUPER_ADMIN", "MODERATOR"}:
        raise HTTPException(status_code=403, detail="SUPER_ADMIN or MODERATOR required")


def _can_show_financial_values_for_user(user: User | None) -> bool:
    return not should_hide_financial_values_for_user(user)


def _require_financial_values_export_allowed(user: User | None) -> None:
    if should_hide_financial_values_for_user(user):
        raise HTTPException(status_code=403, detail=FINANCIAL_VALUES_HIDDEN_MESSAGE)


def _load_user_for_signed_export(db: Session, payload: dict) -> User | None:
    user_id = payload.get("user_id")
    if user_id is None:
        return None
    try:
        return db.get(User, int(user_id))
    except Exception:
        return None


log = logging.getLogger("axelio.day_economics_notifications")

_NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY = "day_economics_summary"
_NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN = "salary_day_breakdown"
_NOTIFICATION_JOB_TYPE_SOFT_ALERTS = "soft_alerts"
_NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED = "adjustment_assigned"
_NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT = "adjustment_dispute_event"
_NOTIFICATION_JOB_TYPE_SHIFT_COMMENT = "shift_comment"
_NOTIFICATION_JOB_TYPE_SHIFT_SWAP = "shift_swap"
_NOTIFICATION_JOB_STATUS_PENDING = "pending"
_NOTIFICATION_JOB_STATUS_PROCESSING = "processing"
_NOTIFICATION_JOB_STATUS_SENT = "sent"
_NOTIFICATION_JOB_STATUS_FAILED = "failed"
_NOTIFICATION_JOB_RETRY_MINUTES = int(os.getenv("NOTIFICATION_JOB_RETRY_MINUTES", "2"))
_NOTIFICATION_JOB_STALE_MINUTES = int(os.getenv("NOTIFICATION_JOB_STALE_MINUTES", "10"))
_NOTIFICATION_JOB_MAX_ATTEMPTS = int(os.getenv("NOTIFICATION_JOB_MAX_ATTEMPTS", "5"))

BASE_SCOPE_TITLES = {
    BASE_SCOPE_FULL_PERIOD: "по всему периоду",
    BASE_SCOPE_WORKED_DATES: "по отработанным дням",
}
BOOST_SOURCE_TITLES = {
    BOOST_SOURCE_NONE: "без условия",
    BOOST_SOURCE_VENUE_MONTH_PLAN: "месячный план заведения",
    BOOST_SOURCE_VENUE_DAY_PLAN: "суточный план заведения",
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: "месячный план департамента",
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN: "суточный план департамента",
    BOOST_SOURCE_KPI_METRIC: "KPI",
}
BOOST_RECALC_TITLES = {
    BOOST_RECALC_REPLACE_ALL: "весь объём",
    BOOST_RECALC_EXCESS_ONLY: "только превышение",
}
MINIMUM_GUARANTEE_SCOPE_TITLES = {
    MINIMUM_GUARANTEE_MONTH: "за месяц",
    MINIMUM_GUARANTEE_DAY: "за день",
    MINIMUM_GUARANTEE_SHIFT: "за каждую отработанную смену",
}
_SCHEDULE_SHARE_TTL_SECONDS = int(os.getenv("SCHEDULE_SHARE_TTL_SECONDS", "604800"))
