from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
import logging
import os
import calendar
import json
import hashlib
import re
import uuid

from typing import Optional, List
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, update, func, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.guards import require_super_admin
from app.core.db import SessionLocal, get_db
from app.core.config import settings
from app.core.tg import normalize_tg_username
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes
from app.core.permissions_registry import PERMISSIONS
from app.services import tg_notify
from app.services.notification_logs import (
    log_notification_attempt,
    lock_notification_idempotency_key,
    notification_delivery_exists,
    notification_dedupe_scope,
)
from app.services.xlsx_export import (
    build_expenses_xlsx,
    build_monthly_summary_xlsx,
    build_payroll_xlsx,
    build_revenue_csv,
    build_revenue_xlsx,
)
from app.services.signed_links import make_signed_token, verify_signed_token
from app.services.finance.expenses import list_expense_allocations
from app.services.finance.revenue import rebuild_revenue_entries_for_report, delete_revenue_entries_for_report, compute_revenue_summary
from app.services.finance.summary import get_monthly_finance_summary
from app.services.finance.recurring_expenses import (
    delete_daily_recurring_accruals_for_date,
    sync_daily_recurring_accruals_for_date,
)
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
from app.services.payroll.period_summary import resolve_salary_period
from app.services.tips import build_equal_tip_allocations, build_weighted_by_position_tip_allocations
from app.services.shifts import normalize_shift_slot
from app.services.financial_privacy import (
    FINANCIAL_VALUES_HIDDEN_MESSAGE,
    financial_visibility_payload,
    sanitize_financial_payload_for_user,
    should_hide_financial_values_for_user,
)
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
from app.routers.venue_economics import router as venue_economics_router
from app.routers.venue_catalogs import router as venue_catalogs_router
from app.routers.venue_finance import router as venue_finance_router


from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite
from app.models.venue_position import VenuePosition
from app.models.venue_setup_state import VenueSetupState
from app.models.shift_interval import ShiftInterval
from app.models.shift import Shift
from app.models.shift_comment import ShiftComment
from app.models.shift_assignment import ShiftAssignment
from app.models.shift_schedule_template import ShiftScheduleTemplate, ShiftScheduleTemplateItem
from app.models.daily_report import DailyReport
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.daily_report_value import DailyReportValue
from app.models.daily_report_audit import DailyReportAudit
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.notification_delivery_log import NotificationDeliveryLog
from app.models.notification_job import NotificationJob
from app.models.adjustment import Adjustment
from app.models.adjustment_dispute import AdjustmentDispute
from app.models.adjustment_dispute_comment import AdjustmentDisputeComment
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.kpi_metric import KpiMetric
from app.models.expense_category import ExpenseCategory
from app.models.supplier import Supplier
from app.models.expense import Expense
from app.models.expense_attachment import ExpenseAttachment
from app.models.expense_allocation import ExpenseAllocation
from app.models.finance_entry import FinanceEntry
from app.models.balance_adjustment import BalanceAdjustment
from app.models.payment_method_transfer import PaymentMethodTransfer
from app.models.recurring_expense_rule import RecurringExpenseRule
from app.models.recurring_expense_rule_payment_method import RecurringExpenseRulePaymentMethod
from app.models.recurring_expense_accrual import RecurringExpenseAccrual
from app.models.permission import Permission
from app.models.auth_identity import AuthIdentity
from app.models.pay_profile import PayProfile
from app.models.pay_profile_assignment import PayProfileAssignment
from app.models.pay_component import PayComponent
from app.models.payroll_run import PayrollRun
from app.models.payroll_line import PayrollLine
from app.models.payroll_recalculation_log import PayrollRecalculationLog
from app.models.penalty import Penalty
from app.models.bonus import Bonus
from app.models.writeoff import Writeoff
from app.models.expense_recognition_entry import ExpenseRecognitionEntry
from app.models.day_economics_plan import DayEconomicsPlan
from app.models.day_economics_month_plan import DayEconomicsMonthPlan
from app.models.day_economics_plan_template import DayEconomicsPlanTemplate
from app.models.department_month_plan import DepartmentMonthPlan
from app.models.department_day_plan import DepartmentDayPlan
from app.models.venue_economics_rule import VenueEconomicsRule

from app.auth.venue_permissions import require_venue_permission, has_venue_permission

from app.services.venues import create_venue
from app.services.invites import build_invite_link, create_venue_invite, normalize_phone_e164
from app.services.setup import build_setup_summary, build_setup_summary_map
from app.services.billing import (
    BILLING_ACCESS_FULL,
    can_grant_self_service_trial,
    get_user_billing_access,
    get_venue_billing_snapshot,
    grant_self_service_trial,
    list_billing_transactions,
    send_super_admin_billing_alert_once,
)
from app.settings import settings

router = APIRouter(prefix="/venues", tags=["venues"])


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



class VenueSelfServiceCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)



# ---------- Schemas ----------

class VenueCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    owner_usernames: Optional[List[str]] = None  # legacy fallback ["owner1", "@owner2"]
    owner_user_id: int | None = None
    owner_tg_username: str | None = None
    owner_phone: str | None = None


class VenueUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class InviteCreateIn(BaseModel):
    invite_channel: str = "TELEGRAM"  # TELEGRAM | PHONE
    tg_username: str | None = None
    phone: str | None = None
    contact_label: str | None = None
    venue_role: str = "STAFF"  # OWNER | STAFF



class InviteDefaultPositionIn(BaseModel):
    # preset position data to apply after invite is accepted
    title: str = Field(..., min_length=1, max_length=100)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    pay_profile_title: str | None = Field(default=None, max_length=120)
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None



class InviteDefaultPositionPatchIn(BaseModel):
    default_position: InviteDefaultPositionIn | None = None


class VenueSettingsOut(BaseModel):
    tips_enabled: bool = False
    night_shifts_enabled: bool = False
    tips_split_mode: str = "EQUAL"
    tips_weights: dict | None = None


class VenueSettingsPatchIn(BaseModel):
    tips_enabled: bool | None = None
    night_shifts_enabled: bool | None = None
    tips_split_mode: str | None = None
    tips_weights: dict | None = None


class PositionCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    member_user_id: int = Field(..., gt=0)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    is_active: bool = True
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


class PositionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    member_user_id: int | None = Field(default=None, gt=0)
    rate: int | None = Field(default=None, ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


class PositionPresetOut(BaseModel):
    id: str
    title: str
    rate: int = 0
    percent: int = 0
    pay_profile_id: int | None = None
    pay_profile_title: str | None = None
    template_id: str | None = None
    template_title: str | None = None
    permission_codes: list[str] = []
    is_active: bool = True


class PositionPresetsOut(BaseModel):
    items: list[PositionPresetOut] = []


class PayProfileCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class PayProfileUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class PayProfileAssignmentCreateIn(BaseModel):
    member_user_id: int = Field(..., gt=0)
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True


class PayProfileAssignmentUpdateIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None


class PayComponentCreateIn(BaseModel):
    component_type: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=120)
    amount_minor: int | None = Field(default=None, ge=0)
    rate_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    department_id: int | None = Field(default=None, gt=0)
    department_ids: list[int] | None = None
    kpi_metric_id: int | None = Field(default=None, gt=0)
    threshold_value: int | None = Field(default=None, ge=0)
    steps_json: dict | list | None = None
    base_scope: str | None = Field(default=None, min_length=1, max_length=24)
    boost_enabled: bool = False
    boost_percent_bps: int | None = Field(default=None, ge=0)
    boost_source_type: str | None = Field(default=None, min_length=1, max_length=40)
    boost_recalc_mode: str | None = Field(default=None, min_length=1, max_length=24)
    boost_department_id: int | None = Field(default=None, gt=0)
    boost_department_ids: list[int] | None = None
    boost_kpi_metric_id: int | None = Field(default=None, gt=0)
    boost_threshold_value: int | None = Field(default=None, ge=0)
    minimum_guarantee_minor: int | None = Field(default=None, ge=0)
    minimum_guarantee_scope: str | None = Field(default=None, min_length=1, max_length=16)
    maximum_cap_minor: int | None = Field(default=None, ge=0)
    sort_order: int = Field(0, ge=0)
    is_active: bool = True


class PayComponentUpdateIn(BaseModel):
    component_type: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    amount_minor: int | None = Field(default=None, ge=0)
    rate_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    department_id: int | None = Field(default=None, gt=0)
    department_ids: list[int] | None = None
    kpi_metric_id: int | None = Field(default=None, gt=0)
    threshold_value: int | None = Field(default=None, ge=0)
    steps_json: dict | list | None = None
    base_scope: str | None = Field(default=None, min_length=1, max_length=24)
    boost_enabled: bool | None = None
    boost_percent_bps: int | None = Field(default=None, ge=0)
    boost_source_type: str | None = Field(default=None, min_length=1, max_length=40)
    boost_recalc_mode: str | None = Field(default=None, min_length=1, max_length=24)
    boost_department_id: int | None = Field(default=None, gt=0)
    boost_department_ids: list[int] | None = None
    boost_kpi_metric_id: int | None = Field(default=None, gt=0)
    boost_threshold_value: int | None = Field(default=None, ge=0)
    minimum_guarantee_minor: int | None = Field(default=None, ge=0)
    minimum_guarantee_scope: str | None = Field(default=None, min_length=1, max_length=16)
    maximum_cap_minor: int | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PayrollCalculateIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="YYYY-MM")


class ReportValueIn(BaseModel):
    ref_id: int = Field(..., ge=1)
    value: int = Field(0, ge=0)


class DailyReportUpsertIn(BaseModel):
    date: date

    # legacy fields (kept for backwards compatibility)
    cash: int = Field(0, ge=0)
    cashless: int = Field(0, ge=0)
    revenue_total: int = Field(0, ge=0)
    tips_total: int = Field(0, ge=0)

    # dynamic values (A2)
    payments: list[ReportValueIn] | None = None
    departments: list[ReportValueIn] | None = None
    kpis: list[ReportValueIn] | None = None

    # optional comment (stored on report)
    comment: str | None = None


class DailyReportCloseIn(BaseModel):
    comment: str | None = None





class AdjustmentCreateIn(BaseModel):
    type: str = Field(..., description="penalty|writeoff|bonus")
    date: date
    amount: int = Field(0, ge=0)
    reason: str | None = Field(default=None, max_length=500)
    member_user_id: int | None = Field(default=None, gt=0)


class DisputeCreateIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

class DisputeCommentIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

class DisputeStatusIn(BaseModel):
    status: str = Field(..., min_length=4, max_length=20)  # OPEN | CLOSED

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


def _normalize_shift_interval_title(title: str) -> str:
    value = str(title or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Interval title is required")
    return value


def _ensure_shift_interval_title_unique(
    db: Session,
    *,
    venue_id: int,
    title: str,
    exclude_interval_id: int | None = None,
) -> None:
    stmt = select(ShiftInterval.id).where(
        ShiftInterval.venue_id == venue_id,
        func.lower(ShiftInterval.title) == title.lower(),
    )
    if exclude_interval_id is not None:
        stmt = stmt.where(ShiftInterval.id != exclude_interval_id)
    exists_id = db.execute(stmt.limit(1)).scalar_one_or_none()
    if exists_id is not None:
        raise HTTPException(status_code=409, detail="Shift interval with this title already exists")


def _count_interval_shift_usage(db: Session, *, venue_id: int, interval_id: int) -> int:
    return int(
        db.execute(
            select(func.count(Shift.id)).where(
                Shift.venue_id == venue_id,
                Shift.interval_id == interval_id,
            )
        ).scalar_one()
        or 0
    )


def _count_interval_template_usage(db: Session, *, venue_id: int, interval_id: int) -> int:
    return int(
        db.execute(
            select(func.count(ShiftScheduleTemplateItem.id))
            .join(ShiftScheduleTemplate, ShiftScheduleTemplate.id == ShiftScheduleTemplateItem.template_id)
            .where(
                ShiftScheduleTemplate.venue_id == venue_id,
                ShiftScheduleTemplateItem.interval_id == interval_id,
            )
        ).scalar_one()
        or 0
    )


class ShiftCreateIn(BaseModel):
    date: date
    interval_id: int = Field(..., gt=0)
    is_active: bool = True
    shift_slot: str | None = Field(default="DAY", max_length=16)


class ShiftUpdateIn(BaseModel):
    date: date | Optional[date] = None
    interval_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    shift_slot: str | None = Field(default=None, max_length=16)


class ShiftScheduleTemplateItemIn(BaseModel):
    weekday: int = Field(..., ge=0, le=6, description="0=Monday ... 6=Sunday")
    interval_id: int = Field(..., gt=0)
    shift_slot: str | None = Field(default="DAY", max_length=16)


class ShiftScheduleTemplateCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = True
    items: list[ShiftScheduleTemplateItemIn] = Field(default_factory=list)


class ShiftScheduleTemplateUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    items: list[ShiftScheduleTemplateItemIn] | None = None


class ShiftScheduleTemplateApplyIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="YYYY-MM")
    mode: str = Field(..., min_length=4, max_length=32)


class ShiftAssignmentAddIn(BaseModel):
    venue_position_id: int = Field(..., gt=0)



# ---------- Helpers ----------

def _can_manage_staff(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    return has_venue_permission(db, venue_id=venue_id, user=user, permission_code="STAFF_MANAGE")


def _require_staff_manage_or_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _can_manage_staff(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")




def _is_shift_comments_allowed(db: Session, *, venue_id: int, shift_id: int, user: User) -> bool:
    # Admins
    if user.system_role in ("SUPER_ADMIN", "MODERATOR", "STAFF", "OWNER"):
        return True

    # Venue members (owner/staff)
    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if m is not None:
        return True

    # Position-based staff (common case in current MVP)
    pos = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == user.id,
            VenuePosition.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if pos is not None:
        return True

    # Fallback: assigned to this shift
    sa = db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.member_user_id == user.id,
        )
    ).scalar_one_or_none()
    return bool(sa)


def _require_shift_comments_allowed(db: Session, *, venue_id: int, shift_id: int, user: User) -> None:
    if not _is_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_schedule_editor(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="SHIFTS_MANAGE")
        return True
    except HTTPException:
        return False

def _require_schedule_editor(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_schedule_editor(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_report_maker(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    # Permission-based (preferred)
    for code in ("SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"):
        try:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
            return True
        except HTTPException:
            pass

    return False


def _require_report_maker(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_report_maker(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="ADJUSTMENTS_VIEW")
        return True
    except HTTPException:
        return False

def _require_adjustments_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_viewer(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_adjustments_manager(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="ADJUSTMENTS_MANAGE")
        return True
    except HTTPException:
        return False

def _require_adjustments_manager(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_adjustments_manager(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _has_adjustments_manage_access(db: Session, *, venue_id: int, user: User) -> bool:
    return _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_adjustments_manager(db, venue_id=venue_id, user=user)


def _require_dispute_resolver(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DISPUTES_RESOLVE")
        return
    except HTTPException:
        raise HTTPException(status_code=403, detail="Forbidden")

def _has_revenue_export_access(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_EXPORT")
        return True
    except HTTPException:
        return False


def _require_revenue_exporter(db: Session, *, venue_id: int, user: User) -> None:
    if not _has_revenue_export_access(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")



def _build_user_auth_snapshot_map(db: Session, user_ids: list[int]) -> dict[int, dict]:
    ids = [int(x) for x in user_ids if x]
    if not ids:
        return {}
    rows = db.execute(
        select(
            AuthIdentity.user_id,
            AuthIdentity.provider,
            AuthIdentity.phone_e164,
        ).where(
            AuthIdentity.user_id.in_(ids),
            AuthIdentity.is_verified.is_(True),
        )
    ).all()
    out: dict[int, dict] = {uid: {"phone": None, "auth_methods": []} for uid in ids}
    for r in rows:
        item = out.setdefault(int(r.user_id), {"phone": None, "auth_methods": []})
        provider = str(r.provider or "").strip().lower()
        if provider and provider not in item["auth_methods"]:
            item["auth_methods"].append(provider)
        if provider == "phone" and r.phone_e164 and not item["phone"]:
            item["phone"] = r.phone_e164
    return out


def _display_name(*, short_name: str | None = None, full_name: str | None = None, tg_username: str | None = None, phone: str | None = None, user_id: int | None = None) -> str:
    if short_name:
        return short_name
    if full_name:
        return full_name
    if tg_username:
        return f"@{tg_username}"
    if phone:
        return phone
    if user_id:
        return f"user #{user_id}"
    return "—"


def _serialize_user_brief(row, auth_map: dict[int, dict]) -> dict:
    snap = auth_map.get(int(row.id), {"phone": None, "auth_methods": []})
    phone = snap.get("phone")
    methods = list(snap.get("auth_methods") or [])
    return {
        "user_id": row.id,
        "tg_user_id": getattr(row, "tg_user_id", None),
        "tg_username": getattr(row, "tg_username", None),
        "full_name": getattr(row, "full_name", None),
        "short_name": getattr(row, "short_name", None),
        "phone": phone,
        "auth_methods": methods,
        "has_phone_auth": "phone" in methods,
        "has_telegram_auth": "telegram" in methods,
        "display_name": _display_name(
            short_name=getattr(row, "short_name", None),
            full_name=getattr(row, "full_name", None),
            tg_username=getattr(row, "tg_username", None),
            phone=phone,
            user_id=getattr(row, "id", None),
        ),
    }


def _build_pending_invite_target_map(db: Session, invites) -> dict[int, dict]:
    tg_usernames = []
    phones = []
    for inv in invites or []:
        channel = str(getattr(inv, "invite_channel", "") or "").strip().upper()
        if channel == "TELEGRAM":
            u = normalize_tg_username(getattr(inv, "invited_tg_username", None) or "")
            if u:
                tg_usernames.append(u)
        elif channel == "PHONE":
            p = normalize_phone_e164(getattr(inv, "invited_phone_e164", None))
            if p:
                phones.append(p)

    tg_rows = []
    if tg_usernames:
        tg_rows = db.execute(
            select(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name).where(User.tg_username.in_(list(dict.fromkeys(tg_usernames))))
        ).all()

    phone_rows = []
    if phones:
        phone_rows = db.execute(
            select(
                AuthIdentity.phone_e164,
                User.id,
                User.tg_user_id,
                User.tg_username,
                User.full_name,
                User.short_name,
            )
            .join(User, User.id == AuthIdentity.user_id)
            .where(
                AuthIdentity.provider == "PHONE",
                AuthIdentity.is_verified.is_(True),
                AuthIdentity.phone_e164.in_(list(dict.fromkeys(phones))),
            )
        ).all()

    user_ids = [int(r.id) for r in tg_rows] + [int(r.id) for r in phone_rows]
    auth_map = _build_user_auth_snapshot_map(db, user_ids)

    tg_lookup = {normalize_tg_username(r.tg_username or ""): _serialize_user_brief(r, auth_map) for r in tg_rows}
    phone_lookup = {normalize_phone_e164(r.phone_e164): _serialize_user_brief(r, auth_map) for r in phone_rows}

    out: dict[int, dict] = {}
    for inv in invites or []:
        channel = str(getattr(inv, "invite_channel", "") or "").strip().upper()
        linked = None
        if channel == "TELEGRAM":
            linked = tg_lookup.get(normalize_tg_username(getattr(inv, "invited_tg_username", None) or ""))
        elif channel == "PHONE":
            linked = phone_lookup.get(normalize_phone_e164(getattr(inv, "invited_phone_e164", None)))
        out[int(inv.id)] = {
            "target_status": "LINKED_USER" if linked else "WAITING_SIGNUP",
            "target_user": linked,
        }
    return out


def _build_owner_summary_by_venue(db: Session, venue_ids: list[int]) -> dict[int, dict]:
    ids = [int(x) for x in venue_ids if x]
    if not ids:
        return {}

    owner_rows = db.execute(
        select(
            VenueMember.venue_id,
            User.id,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
        )
        .join(User, User.id == VenueMember.user_id)
        .where(
            VenueMember.venue_id.in_(ids),
            VenueMember.venue_role == "OWNER",
            VenueMember.is_active.is_(True),
        )
    ).all()
    owner_auth_map = _build_user_auth_snapshot_map(db, [int(r.id) for r in owner_rows])

    pending_rows = db.execute(
        select(
            VenueInvite.id,
            VenueInvite.venue_id,
            VenueInvite.invite_channel,
            VenueInvite.invited_tg_username,
            VenueInvite.invited_phone_e164,
            VenueInvite.invited_contact_label,
            VenueInvite.invite_token,
            VenueInvite.created_at,
            VenueInvite.expires_at,
        ).where(
            VenueInvite.venue_id.in_(ids),
            VenueInvite.venue_role == "OWNER",
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
    ).all()
    pending_target_map = _build_pending_invite_target_map(db, pending_rows)

    out = {vid: {"state": "UNASSIGNED", "owners": [], "pending": []} for vid in ids}
    for r in owner_rows:
        item = _serialize_user_brief(r, owner_auth_map)
        out[int(r.venue_id)]["owners"].append(item)
        out[int(r.venue_id)]["state"] = "LINKED"

    for r in pending_rows:
        meta = pending_target_map.get(int(r.id), {"target_status": "WAITING_SIGNUP", "target_user": None})
        out[int(r.venue_id)]["pending"].append({
            "id": r.id,
            "channel": r.invite_channel,
            "tg_username": r.invited_tg_username,
            "phone": r.invited_phone_e164,
            "contact_label": r.invited_contact_label,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "invite_link": build_invite_link(r.invite_token),
            "target_status": meta.get("target_status"),
            "target_user": meta.get("target_user"),
        })
        if out[int(r.venue_id)]["state"] != "LINKED":
            out[int(r.venue_id)]["state"] = "PENDING"

    return out


# ---------- Routes ----------

@router.post("/self-service")
def create_venue_self_service(
    payload: VenueSelfServiceCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название заведения")

    trial_available = can_grant_self_service_trial(db, user_id=int(user.id))
    try:
        venue = create_venue(
            db,
            name=name,
            owner_user_id=int(user.id),
            created_by_user_id=int(user.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    trial_event = None
    if trial_available:
        _, _, trial_event = grant_self_service_trial(
            db,
            venue_id=int(venue.id),
            created_by_user_id=int(user.id),
        )
        db.commit()
        db.refresh(venue)
        try:
            username = f"@{user.tg_username}" if getattr(user, "tg_username", None) else f"user_id={int(user.id)}"
            send_super_admin_billing_alert_once(
                db,
                notification_type="self_service_trial_created",
                event_key=str(trial_event.id),
                venue_id=int(venue.id),
                text=(
                    f"Новое self-service заведение в Axelio: «{venue.name}». "
                    f"Владелец: {username}. Выдан пробный доступ на 3 дня."
                ),
                button_text="Открыть биллинг",
            )
            db.commit()
        except Exception:
            db.rollback()

    setup_summary = build_setup_summary(db, venue_id=int(venue.id), create_missing=False)
    billing_access = get_user_billing_access(db, venue_id=int(venue.id), user=user, membership_role="OWNER")
    trial_until = billing_access.get("trial_until")
    setup_url = f"/owner-setup.html?venue_id={int(venue.id)}&phase=prepare"
    billing_url = f"/app-venue.html?venue_id={int(venue.id)}"
    next_url = setup_url if trial_available else billing_url
    return {
        "id": int(venue.id),
        "name": venue.name,
        "my_role": "OWNER",
        "trial_granted": bool(trial_available),
        "trial_until": trial_until.isoformat() if trial_until else None,
        "next_url": next_url,
        "open_target": next_url,
        "billing_status": billing_access.get("billing_status"),
        "billing_access_mode": billing_access.get("billing_access_mode"),
        "paid_until": billing_access.get("paid_until").isoformat() if billing_access.get("paid_until") else None,
        "grace_until": billing_access.get("grace_until").isoformat() if billing_access.get("grace_until") else None,
        "billing_kind": billing_access.get("billing_kind"),
        "is_trial": bool(billing_access.get("is_trial")),
        "billing_restricted_reason": billing_access.get("billing_restricted_reason"),
        "setup_status": setup_summary.get("status"),
        "setup_phase": setup_summary.get("phase"),
        "setup_progress_total": int(setup_summary.get("progress_total") or 0),
        "setup_progress_done": int(setup_summary.get("progress_done") or 0),
        "setup_progress_resolved": int(setup_summary.get("progress_resolved") or 0),
        "setup_resume_step": setup_summary.get("resume_step"),
        "setup_prepare_done": bool(setup_summary.get("prepare_done")),
        "setup_extra_done": bool(setup_summary.get("extra_done")),
    }


@router.post("")
def create_venue_admin_only(
    payload: VenueCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        venue = create_venue(
            db,
            name=payload.name,
            owner_usernames=payload.owner_usernames,
            owner_user_id=payload.owner_user_id,
            owner_tg_username=payload.owner_tg_username,
            owner_phone=payload.owner_phone,
            created_by_user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    owner_summary = _build_owner_summary_by_venue(db, [venue.id]).get(venue.id, {"state": "UNASSIGNED", "owners": [], "pending": []})
    owner_pending_invite = owner_summary["pending"][0] if owner_summary.get("pending") else None
    owner_linked = owner_summary["owners"][0] if owner_summary.get("owners") else None
    setup_summary = build_setup_summary(db, venue_id=venue.id, create_missing=False)
    return {
        "id": venue.id,
        "name": venue.name,
        "owner_pending": owner_pending_invite is not None,
        "owner_linked": owner_linked,
        "owner_invite": owner_pending_invite,
        "owner_status": owner_summary,
        "setup_status": setup_summary.get("status"),
        "setup_phase": setup_summary.get("phase"),
        "setup_progress_total": int(setup_summary.get("progress_total") or 0),
        "setup_progress_done": int(setup_summary.get("progress_done") or 0),
        "setup_progress_resolved": int(setup_summary.get("progress_resolved") or 0),
        "setup_resume_step": setup_summary.get("resume_step"),
        "setup_prepare_done": bool(setup_summary.get("prepare_done")),
        "setup_extra_done": bool(setup_summary.get("extra_done")),
    }


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
    venue_ids = [int(r.id) for r in rows]
    owner_summary_map = _build_owner_summary_by_venue(db, venue_ids)
    setup_summary_map = build_setup_summary_map(db, venue_ids, create_missing=False) if venue_ids else {}
    return [
        {
            "id": r.id,
            "name": r.name,
            "is_archived": bool(r.is_archived),
            "archived_at": r.archived_at.isoformat() if r.archived_at else None,
            "owner_status": owner_summary_map.get(int(r.id), {"state": "UNASSIGNED", "owners": [], "pending": []}),
            "setup_status": (setup_summary_map.get(int(r.id)) or {}).get("status"),
            "setup_phase": (setup_summary_map.get(int(r.id)) or {}).get("phase"),
            "setup_progress_total": int(((setup_summary_map.get(int(r.id)) or {}).get("progress_total") or 0)),
            "setup_progress_done": int(((setup_summary_map.get(int(r.id)) or {}).get("progress_done") or 0)),
            "setup_progress_resolved": int(((setup_summary_map.get(int(r.id)) or {}).get("progress_resolved") or 0)),
            "setup_resume_step": (setup_summary_map.get(int(r.id)) or {}).get("resume_step"),
            "setup_prepare_done": bool((setup_summary_map.get(int(r.id)) or {}).get("prepare_done")),
            "setup_extra_done": bool((setup_summary_map.get(int(r.id)) or {}).get("extra_done")),
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
    _require_super_admin_or_moderator(user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    venue.name = payload.name.strip()
    db.commit()
    return {"id": venue.id, "name": venue.name}


def _table_exists(db: Session, model_or_table_name) -> bool:
    table_name = model_or_table_name if isinstance(model_or_table_name, str) else model_or_table_name.__tablename__
    try:
        return bool(inspect(db.get_bind()).has_table(table_name))
    except Exception:
        return True


def _safe_scalar_count(db: Session, stmt) -> int:
    try:
        return int(db.execute(stmt).scalar_one() or 0)
    except Exception:
        return 0


def _safe_delete_where(db: Session, model, *conditions) -> int:
    if not _table_exists(db, model):
        return 0
    stmt = delete(model)
    for condition in conditions:
        stmt = stmt.where(condition)
    try:
        result = db.execute(stmt)
    except Exception:
        return 0
    return int(getattr(result, "rowcount", 0) or 0)


def _build_venue_delete_check_payload(db: Session, venue: Venue) -> dict:
    venue_id = int(venue.id)
    shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)
    shift_schedule_template_ids = select(ShiftScheduleTemplate.id).where(ShiftScheduleTemplate.venue_id == venue_id)
    report_ids = select(DailyReport.id).where(DailyReport.venue_id == venue_id)
    adjustment_ids = select(Adjustment.id).where(Adjustment.venue_id == venue_id)
    dispute_ids = select(AdjustmentDispute.id).where(AdjustmentDispute.venue_id == venue_id)
    expense_ids = select(Expense.id).where(Expense.venue_id == venue_id)
    recurring_rule_ids = select(RecurringExpenseRule.id).where(RecurringExpenseRule.venue_id == venue_id)
    pay_profile_ids = select(PayProfile.id).where(PayProfile.venue_id == venue_id)
    payroll_run_ids = select(PayrollRun.id).where(PayrollRun.venue_id == venue_id)

    counts: dict[str, int] = {}

    def add_count(key: str, model, stmt) -> None:
        if not _table_exists(db, model):
            counts[key] = 0
            return
        counts[key] = _safe_scalar_count(db, stmt)

    add_count("venue_members", VenueMember, select(func.count(VenueMember.id)).where(VenueMember.venue_id == venue_id))
    add_count("venue_invites", VenueInvite, select(func.count(VenueInvite.id)).where(VenueInvite.venue_id == venue_id))
    add_count("venue_positions", VenuePosition, select(func.count(VenuePosition.id)).where(VenuePosition.venue_id == venue_id))

    add_count("shift_intervals", ShiftInterval, select(func.count(ShiftInterval.id)).where(ShiftInterval.venue_id == venue_id))
    add_count("shift_schedule_templates", ShiftScheduleTemplate, select(func.count(ShiftScheduleTemplate.id)).where(ShiftScheduleTemplate.venue_id == venue_id))
    add_count("shift_schedule_template_items", ShiftScheduleTemplateItem, select(func.count(ShiftScheduleTemplateItem.id)).where(ShiftScheduleTemplateItem.template_id.in_(shift_schedule_template_ids)))
    add_count("shifts", Shift, select(func.count(Shift.id)).where(Shift.venue_id == venue_id))
    add_count("shift_assignments", ShiftAssignment, select(func.count(ShiftAssignment.id)).where(ShiftAssignment.shift_id.in_(shift_ids)))
    add_count("shift_comments", ShiftComment, select(func.count(ShiftComment.id)).where(ShiftComment.shift_id.in_(shift_ids)))

    add_count("daily_reports", DailyReport, select(func.count(DailyReport.id)).where(DailyReport.venue_id == venue_id))
    add_count("daily_report_attachments", DailyReportAttachment, select(func.count(DailyReportAttachment.id)).where(DailyReportAttachment.venue_id == venue_id))
    add_count("daily_report_values", DailyReportValue, select(func.count(DailyReportValue.id)).where(DailyReportValue.report_id.in_(report_ids)))
    add_count("daily_report_audits", DailyReportAudit, select(func.count(DailyReportAudit.id)).where(DailyReportAudit.report_id.in_(report_ids)))
    add_count("daily_report_tip_allocations", DailyReportTipAllocation, select(func.count(DailyReportTipAllocation.id)).where(DailyReportTipAllocation.report_id.in_(report_ids)))

    add_count("adjustments", Adjustment, select(func.count(Adjustment.id)).where(Adjustment.venue_id == venue_id))
    add_count("adjustment_disputes", AdjustmentDispute, select(func.count(AdjustmentDispute.id)).where(AdjustmentDispute.venue_id == venue_id))
    add_count("adjustment_dispute_comments", AdjustmentDisputeComment, select(func.count(AdjustmentDisputeComment.id)).where(AdjustmentDisputeComment.dispute_id.in_(dispute_ids)))
    add_count("penalties", Penalty, select(func.count(Penalty.id)).where(Penalty.venue_id == venue_id))
    add_count("bonuses", Bonus, select(func.count(Bonus.id)).where(Bonus.venue_id == venue_id))
    add_count("writeoffs", Writeoff, select(func.count(Writeoff.id)).where(Writeoff.venue_id == venue_id))

    add_count("departments", Department, select(func.count(Department.id)).where(Department.venue_id == venue_id))
    add_count("payment_methods", PaymentMethod, select(func.count(PaymentMethod.id)).where(PaymentMethod.venue_id == venue_id))
    add_count("kpi_metrics", KpiMetric, select(func.count(KpiMetric.id)).where(KpiMetric.venue_id == venue_id))
    add_count("expense_categories", ExpenseCategory, select(func.count(ExpenseCategory.id)).where(ExpenseCategory.venue_id == venue_id))
    add_count("suppliers", Supplier, select(func.count(Supplier.id)).where(Supplier.venue_id == venue_id))

    add_count("expenses", Expense, select(func.count(Expense.id)).where(Expense.venue_id == venue_id))
    add_count("expense_allocations", ExpenseAllocation, select(func.count(ExpenseAllocation.id)).where(ExpenseAllocation.venue_id == venue_id))
    add_count("expense_recognition_entries", ExpenseRecognitionEntry, select(func.count(ExpenseRecognitionEntry.id)).where(ExpenseRecognitionEntry.venue_id == venue_id))
    add_count("finance_entries", FinanceEntry, select(func.count(FinanceEntry.id)).where(FinanceEntry.venue_id == venue_id))
    add_count("balance_adjustments", BalanceAdjustment, select(func.count(BalanceAdjustment.id)).where(BalanceAdjustment.venue_id == venue_id))
    add_count("payment_method_transfers", PaymentMethodTransfer, select(func.count(PaymentMethodTransfer.id)).where(PaymentMethodTransfer.venue_id == venue_id))
    add_count("recurring_expense_rules", RecurringExpenseRule, select(func.count(RecurringExpenseRule.id)).where(RecurringExpenseRule.venue_id == venue_id))
    add_count("recurring_expense_rule_payment_methods", RecurringExpenseRulePaymentMethod, select(func.count(RecurringExpenseRulePaymentMethod.rule_id)).where(RecurringExpenseRulePaymentMethod.rule_id.in_(recurring_rule_ids)))
    add_count("recurring_expense_accruals", RecurringExpenseAccrual, select(func.count(RecurringExpenseAccrual.id)).where(RecurringExpenseAccrual.venue_id == venue_id))

    add_count("day_economics_plans", DayEconomicsPlan, select(func.count(DayEconomicsPlan.id)).where(DayEconomicsPlan.venue_id == venue_id))
    add_count("day_economics_month_plans", DayEconomicsMonthPlan, select(func.count(DayEconomicsMonthPlan.id)).where(DayEconomicsMonthPlan.venue_id == venue_id))
    add_count("day_economics_plan_templates", DayEconomicsPlanTemplate, select(func.count(DayEconomicsPlanTemplate.id)).where(DayEconomicsPlanTemplate.venue_id == venue_id))
    add_count("department_day_plans", DepartmentDayPlan, select(func.count(DepartmentDayPlan.id)).where(DepartmentDayPlan.venue_id == venue_id))
    add_count("department_month_plans", DepartmentMonthPlan, select(func.count(DepartmentMonthPlan.id)).where(DepartmentMonthPlan.venue_id == venue_id))
    add_count("venue_economics_rules", VenueEconomicsRule, select(func.count(VenueEconomicsRule.id)).where(VenueEconomicsRule.venue_id == venue_id))

    add_count("pay_profiles", PayProfile, select(func.count(PayProfile.id)).where(PayProfile.venue_id == venue_id))
    add_count("pay_components", PayComponent, select(func.count(PayComponent.id)).where(PayComponent.venue_id == venue_id))
    add_count("pay_profile_assignments", PayProfileAssignment, select(func.count(PayProfileAssignment.id)).where(PayProfileAssignment.venue_id == venue_id))
    add_count("payroll_runs", PayrollRun, select(func.count(PayrollRun.id)).where(PayrollRun.venue_id == venue_id))
    add_count("payroll_lines", PayrollLine, select(func.count(PayrollLine.id)).where(PayrollLine.venue_id == venue_id))
    add_count("payroll_recalculation_logs", PayrollRecalculationLog, select(func.count(PayrollRecalculationLog.id)).where(PayrollRecalculationLog.venue_id == venue_id))

    add_count("notification_delivery_logs", NotificationDeliveryLog, select(func.count(NotificationDeliveryLog.id)).where(NotificationDeliveryLog.venue_id == venue_id))

    non_zero = [
        {"key": key, "count": value}
        for key, value in counts.items()
        if int(value or 0) > 0
    ]
    non_zero.sort(key=lambda item: (-item["count"], item["key"]))

    return {
        "venue": {
            "id": venue_id,
            "name": venue.name,
            "is_archived": bool(venue.is_archived),
            "archived_at": venue.archived_at.isoformat() if venue.archived_at else None,
        },
        "requires_archive": not bool(venue.is_archived),
        "can_delete": bool(venue.is_archived),
        "counts": counts,
        "non_zero_groups": non_zero,
        "totals": {
            "groups": len(counts),
            "groups_non_zero": len(non_zero),
            "rows": int(sum(int(v or 0) for v in counts.values())),
        },
    }


@router.get("/{venue_id}/delete-check")
def get_venue_delete_check(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin_or_moderator(user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    return _build_venue_delete_check_payload(db, venue)


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
    db.refresh(venue)

    return {
        "ok": True,
        "id": venue.id,
        "is_archived": bool(venue.is_archived),
        "archived_at": venue.archived_at.isoformat() if venue.archived_at else None,
    }


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
    db.refresh(venue)

    return {
        "ok": True,
        "id": venue.id,
        "is_archived": bool(venue.is_archived),
        "archived_at": venue.archived_at.isoformat() if venue.archived_at else None,
    }


@router.delete("/{venue_id}")
def delete_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hard-delete venue (allowed only when archived).

    Deletes dependent rows explicitly in a safe order to avoid FK errors on
    installations where DB-level cascades are incomplete or old migrations are still present.
    """
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Venue not found")

    if not venue.is_archived:
        raise HTTPException(400, "Archive venue before delete")

    shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)
    shift_schedule_template_ids = select(ShiftScheduleTemplate.id).where(ShiftScheduleTemplate.venue_id == venue_id)
    report_ids = select(DailyReport.id).where(DailyReport.venue_id == venue_id)
    dispute_ids = select(AdjustmentDispute.id).where(AdjustmentDispute.venue_id == venue_id)
    recurring_rule_ids = select(RecurringExpenseRule.id).where(RecurringExpenseRule.venue_id == venue_id)

    summary_before = _build_venue_delete_check_payload(db, venue)
    deleted: dict[str, int] = {}

    try:
        deleted["shift_comments"] = _safe_delete_where(db, ShiftComment, ShiftComment.shift_id.in_(shift_ids))
        deleted["shift_assignments"] = _safe_delete_where(db, ShiftAssignment, ShiftAssignment.shift_id.in_(shift_ids))

        deleted["daily_report_tip_allocations"] = _safe_delete_where(db, DailyReportTipAllocation, DailyReportTipAllocation.report_id.in_(report_ids))
        deleted["daily_report_values"] = _safe_delete_where(db, DailyReportValue, DailyReportValue.report_id.in_(report_ids))
        deleted["daily_report_audits"] = _safe_delete_where(db, DailyReportAudit, DailyReportAudit.report_id.in_(report_ids))
        deleted["daily_report_attachments"] = _safe_delete_where(db, DailyReportAttachment, DailyReportAttachment.venue_id == venue_id)

        deleted["adjustment_dispute_comments"] = _safe_delete_where(db, AdjustmentDisputeComment, AdjustmentDisputeComment.dispute_id.in_(dispute_ids))
        deleted["adjustment_disputes"] = _safe_delete_where(db, AdjustmentDispute, AdjustmentDispute.venue_id == venue_id)

        deleted["expense_allocations"] = _safe_delete_where(db, ExpenseAllocation, ExpenseAllocation.venue_id == venue_id)
        deleted["expense_recognition_entries"] = _safe_delete_where(db, ExpenseRecognitionEntry, ExpenseRecognitionEntry.venue_id == venue_id)
        deleted["recurring_expense_rule_payment_methods"] = _safe_delete_where(db, RecurringExpenseRulePaymentMethod, RecurringExpenseRulePaymentMethod.rule_id.in_(recurring_rule_ids))
        deleted["recurring_expense_accruals"] = _safe_delete_where(db, RecurringExpenseAccrual, RecurringExpenseAccrual.venue_id == venue_id)

        deleted["payroll_lines"] = _safe_delete_where(db, PayrollLine, PayrollLine.venue_id == venue_id)
        deleted["pay_profile_assignments"] = _safe_delete_where(db, PayProfileAssignment, PayProfileAssignment.venue_id == venue_id)
        deleted["pay_components"] = _safe_delete_where(db, PayComponent, PayComponent.venue_id == venue_id)

        deleted["notification_delivery_logs"] = _safe_delete_where(db, NotificationDeliveryLog, NotificationDeliveryLog.venue_id == venue_id)

        deleted["shifts"] = _safe_delete_where(db, Shift, Shift.venue_id == venue_id)
        deleted["shift_schedule_template_items"] = _safe_delete_where(db, ShiftScheduleTemplateItem, ShiftScheduleTemplateItem.template_id.in_(shift_schedule_template_ids))
        deleted["shift_schedule_templates"] = _safe_delete_where(db, ShiftScheduleTemplate, ShiftScheduleTemplate.venue_id == venue_id)
        deleted["shift_intervals"] = _safe_delete_where(db, ShiftInterval, ShiftInterval.venue_id == venue_id)

        deleted["daily_reports"] = _safe_delete_where(db, DailyReport, DailyReport.venue_id == venue_id)

        deleted["adjustments"] = _safe_delete_where(db, Adjustment, Adjustment.venue_id == venue_id)
        deleted["penalties"] = _safe_delete_where(db, Penalty, Penalty.venue_id == venue_id)
        deleted["bonuses"] = _safe_delete_where(db, Bonus, Bonus.venue_id == venue_id)
        deleted["writeoffs"] = _safe_delete_where(db, Writeoff, Writeoff.venue_id == venue_id)

        deleted["finance_entries"] = _safe_delete_where(db, FinanceEntry, FinanceEntry.venue_id == venue_id)
        deleted["balance_adjustments"] = _safe_delete_where(db, BalanceAdjustment, BalanceAdjustment.venue_id == venue_id)
        deleted["payment_method_transfers"] = _safe_delete_where(db, PaymentMethodTransfer, PaymentMethodTransfer.venue_id == venue_id)
        deleted["expenses"] = _safe_delete_where(db, Expense, Expense.venue_id == venue_id)
        deleted["recurring_expense_rules"] = _safe_delete_where(db, RecurringExpenseRule, RecurringExpenseRule.venue_id == venue_id)

        deleted["day_economics_plans"] = _safe_delete_where(db, DayEconomicsPlan, DayEconomicsPlan.venue_id == venue_id)
        deleted["day_economics_month_plans"] = _safe_delete_where(db, DayEconomicsMonthPlan, DayEconomicsMonthPlan.venue_id == venue_id)
        deleted["day_economics_plan_templates"] = _safe_delete_where(db, DayEconomicsPlanTemplate, DayEconomicsPlanTemplate.venue_id == venue_id)
        deleted["department_day_plans"] = _safe_delete_where(db, DepartmentDayPlan, DepartmentDayPlan.venue_id == venue_id)
        deleted["department_month_plans"] = _safe_delete_where(db, DepartmentMonthPlan, DepartmentMonthPlan.venue_id == venue_id)
        deleted["venue_economics_rules"] = _safe_delete_where(db, VenueEconomicsRule, VenueEconomicsRule.venue_id == venue_id)

        deleted["payroll_recalculation_logs"] = _safe_delete_where(db, PayrollRecalculationLog, PayrollRecalculationLog.venue_id == venue_id)
        deleted["payroll_runs"] = _safe_delete_where(db, PayrollRun, PayrollRun.venue_id == venue_id)
        deleted["pay_profiles"] = _safe_delete_where(db, PayProfile, PayProfile.venue_id == venue_id)

        deleted["departments"] = _safe_delete_where(db, Department, Department.venue_id == venue_id)
        deleted["payment_methods"] = _safe_delete_where(db, PaymentMethod, PaymentMethod.venue_id == venue_id)
        deleted["kpi_metrics"] = _safe_delete_where(db, KpiMetric, KpiMetric.venue_id == venue_id)
        deleted["expense_categories"] = _safe_delete_where(db, ExpenseCategory, ExpenseCategory.venue_id == venue_id)
        deleted["suppliers"] = _safe_delete_where(db, Supplier, Supplier.venue_id == venue_id)

        deleted["venue_positions"] = _safe_delete_where(db, VenuePosition, VenuePosition.venue_id == venue_id)
        deleted["venue_invites"] = _safe_delete_where(db, VenueInvite, VenueInvite.venue_id == venue_id)
        deleted["venue_members"] = _safe_delete_where(db, VenueMember, VenueMember.venue_id == venue_id)

        venue_deleted = _safe_delete_where(db, Venue, Venue.id == venue_id)
        if venue_deleted <= 0:
            raise HTTPException(404, "Venue not found")
        deleted["venue"] = venue_deleted

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except sa.exc.IntegrityError:
        db.rollback()
        current_check = _build_venue_delete_check_payload(db, venue)
        blockers = ", ".join(
            f"{item['key']}={item['count']}" for item in current_check.get("non_zero_groups", [])[:6]
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Не удалось удалить заведение: в базе остались связанные записи"
                + (f" ({blockers})" if blockers else "")
            ),
        )

    return {
        "ok": True,
        "id": venue_id,
        "deleted": deleted,
        "delete_check_before": summary_before,
    }


@router.get("/{venue_id}/members")
def get_members(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
    if not allowed:
        for code in ("STAFF_VIEW", "STAFF_MANAGE", "POSITIONS_VIEW", "POSITIONS_MANAGE", "POSITIONS_ASSIGN"):
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
                allowed = True
                break
            except HTTPException:
                pass
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    members = (
        db.query(User.id, User.tg_user_id, User.tg_username, User.full_name, User.short_name, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .filter(VenueMember.venue_id == venue_id, VenueMember.is_active.is_(True))
        .all()
    )
    member_auth_map = _build_user_auth_snapshot_map(db, [int(r.id) for r in members])

    invites = (
        db.query(
            VenueInvite.id,
            VenueInvite.invite_channel,
            VenueInvite.invited_tg_username,
            VenueInvite.invited_phone_e164,
            VenueInvite.invited_contact_label,
            VenueInvite.invite_token,
            VenueInvite.venue_role,
            VenueInvite.created_at,
            VenueInvite.expires_at,
            VenueInvite.default_position_json,
        )
        .filter(
            VenueInvite.venue_id == venue_id,
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_user_id.is_(None),
        )
        .order_by(VenueInvite.created_at.desc())
        .all()
    )
    invite_target_map = _build_pending_invite_target_map(db, invites)

    return {
        "members": [
            {
                **_serialize_user_brief(r, member_auth_map),
                "venue_role": r.venue_role,
            }
            for r in members
        ],
        "pending_invites": [
            {
                "id": r.id,
                "channel": r.invite_channel,
                "tg_username": r.invited_tg_username,
                "phone": r.invited_phone_e164,
                "contact_label": r.invited_contact_label,
                "venue_role": r.venue_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "invite_link": build_invite_link(r.invite_token),
                "default_position": r.default_position_json,
                "target_status": invite_target_map.get(int(r.id), {}).get("target_status", "WAITING_SIGNUP"),
                "target_user": invite_target_map.get(int(r.id), {}).get("target_user"),
            }
            for r in invites
        ],
    }



# ---------- Venue settings ----------

@router.get("/{venue_id}/settings", response_model=VenueSettingsOut)
def get_venue_settings(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    return VenueSettingsOut(
        tips_enabled=bool(getattr(venue, "tips_enabled", False)),
        night_shifts_enabled=bool(getattr(venue, "night_shifts_enabled", False)),
        tips_split_mode=str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL"),
        tips_weights=getattr(venue, "tips_weights", None),
    )


@router.patch("/{venue_id}/settings", response_model=VenueSettingsOut)
def patch_venue_settings(
    venue_id: int,
    payload: VenueSettingsPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="VENUE_SETTINGS_EDIT")

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    if payload.tips_enabled is not None:
        venue.tips_enabled = bool(payload.tips_enabled)

    if payload.night_shifts_enabled is not None:
        venue.night_shifts_enabled = bool(payload.night_shifts_enabled)

    if payload.tips_split_mode is not None:
        mode = str(payload.tips_split_mode).strip().upper()
        if mode not in ("EQUAL", "WEIGHTED_BY_POSITION"):
            raise HTTPException(status_code=400, detail="Bad tips_split_mode")
        venue.tips_split_mode = mode

    # stub (weights are stored, but not used yet)
    if payload.tips_weights is not None:
        venue.tips_weights = payload.tips_weights

    db.commit()
    db.refresh(venue)
    return VenueSettingsOut(
        tips_enabled=bool(getattr(venue, "tips_enabled", False)),
        night_shifts_enabled=bool(getattr(venue, "night_shifts_enabled", False)),
        tips_split_mode=str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL"),
        tips_weights=getattr(venue, "tips_weights", None),
    )


# ---------- Positions (job roles inside venue) ----------

def _parse_position_permission_codes(raw: str | None) -> list[str]:
    return parse_permission_codes(raw)


def _normalize_permission_codes(db: Session, codes: list[str] | None) -> list[str]:
    return normalize_known_permission_codes(db, codes)



def _require_pay_profiles_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")



def _require_pay_profiles_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")



def _require_payroll_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_CALCULATE")



def _require_payroll_calculate(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_CALCULATE")



def _parse_json_text(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None



def _get_pay_profile_or_404(db: Session, *, venue_id: int, profile_id: int) -> PayProfile:
    obj = db.execute(
        select(PayProfile).where(PayProfile.id == profile_id, PayProfile.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay profile not found")
    return obj



def _get_pay_profile_assignment_or_404(db: Session, *, venue_id: int, assignment_id: int) -> PayProfileAssignment:
    obj = db.execute(
        select(PayProfileAssignment).where(
            PayProfileAssignment.id == assignment_id,
            PayProfileAssignment.venue_id == venue_id,
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay profile assignment not found")
    return obj





def _get_member_active_pay_profile_assignment(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
    on_date: date | None = None,
) -> tuple[PayProfileAssignment, PayProfile] | tuple[None, None]:
    target_date = on_date or date.today()
    row = db.execute(
        select(PayProfileAssignment, PayProfile)
        .join(PayProfile, PayProfile.id == PayProfileAssignment.pay_profile_id)
        .where(
            PayProfileAssignment.venue_id == int(venue_id),
            PayProfileAssignment.member_user_id == int(member_user_id),
            PayProfileAssignment.is_active.is_(True),
            PayProfile.is_active.is_(True),
            sa.or_(PayProfileAssignment.start_date.is_(None), PayProfileAssignment.start_date <= target_date),
            sa.or_(PayProfileAssignment.end_date.is_(None), PayProfileAssignment.end_date >= target_date),
        )
        .order_by(PayProfileAssignment.start_date.desc().nullslast(), PayProfileAssignment.updated_at.desc().nullslast(), PayProfileAssignment.id.desc())
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def _sync_member_pay_profile_assignment(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
    pay_profile_id: int | None,
) -> tuple[PayProfileAssignment | None, PayProfile | None]:
    today = date.today()
    current_assignment, current_profile = _get_member_active_pay_profile_assignment(
        db, venue_id=venue_id, member_user_id=member_user_id, on_date=today
    )

    target_profile = None
    target_profile_id = int(pay_profile_id) if pay_profile_id else None
    if target_profile_id is not None:
        target_profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=target_profile_id)

    if target_profile_id is not None and current_assignment is not None and int(current_assignment.pay_profile_id) == target_profile_id:
        return current_assignment, current_profile

    if current_assignment is not None:
        if current_assignment.start_date is None and current_assignment.end_date is None:
            db.delete(current_assignment)
        else:
            if current_assignment.start_date and current_assignment.start_date > today:
                current_assignment.is_active = False
                current_assignment.end_date = current_assignment.start_date
            else:
                current_assignment.end_date = today
                current_assignment.is_active = False
            current_assignment.updated_at = datetime.utcnow()
            db.add(current_assignment)

    if target_profile is None:
        return None, None

    assignment = PayProfileAssignment(
        venue_id=int(venue_id),
        pay_profile_id=int(target_profile.id),
        member_user_id=int(member_user_id),
        start_date=today,
        end_date=None,
        is_active=True,
        updated_at=datetime.utcnow(),
    )
    db.add(assignment)
    db.flush()
    return assignment, target_profile


def _get_pay_component_or_404(db: Session, *, venue_id: int, component_id: int) -> PayComponent:
    obj = db.execute(
        select(PayComponent).where(PayComponent.id == component_id, PayComponent.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay component not found")
    return obj





def _normalize_int_ids(value: object) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            item_id = int(item)
        except Exception:
            continue
        if item_id <= 0 or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
    return result


def _dump_int_ids(value: object) -> str | None:
    ids = _normalize_int_ids(value)
    return json.dumps(ids, ensure_ascii=False) if ids else None


def _component_department_ids(component: PayComponent) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "department_ids_json", None))
    legacy_id = int(getattr(component, "department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _component_boost_department_ids(component: PayComponent) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "boost_department_ids_json", None))
    legacy_id = int(getattr(component, "boost_department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _department_titles_for_ids(db_departments: list[Department] | None, ids: list[int]) -> list[str]:
    if not ids:
        return []
    by_id = {int(dep.id): dep.title for dep in (db_departments or []) if dep is not None}
    return [str(by_id.get(int(dep_id)) or f"#{dep_id}") for dep_id in ids]


def _normalize_minimum_guarantee_scope(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw == MINIMUM_GUARANTEE_DAY:
        return MINIMUM_GUARANTEE_DAY
    if raw == MINIMUM_GUARANTEE_SHIFT:
        return MINIMUM_GUARANTEE_SHIFT
    return MINIMUM_GUARANTEE_MONTH


def _ensure_department_ids_in_venue(db: Session, *, venue_id: int, ids: list[int], detail: str) -> None:
    normalized = _normalize_int_ids(ids)
    if not normalized:
        return
    found = set(
        int(item)
        for item in db.execute(
            select(Department.id).where(
                Department.venue_id == int(venue_id),
                Department.id.in_(normalized),
            )
        ).scalars().all()
    )
    missing = [dep_id for dep_id in normalized if dep_id not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"{detail}: {', '.join(str(dep_id) for dep_id in missing)}")



def _effective_component_base_scope(component: PayComponent) -> str:
    raw = str(getattr(component, "base_scope", "") or "").strip().upper()
    if raw in {BASE_SCOPE_FULL_PERIOD, BASE_SCOPE_WORKED_DATES}:
        return raw
    component_type = str(getattr(component, "component_type", "") or "").strip().upper()
    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        return BASE_SCOPE_WORKED_DATES
    return BASE_SCOPE_FULL_PERIOD


def _effective_component_boost_source_type(component: PayComponent) -> str:
    raw = str(getattr(component, "boost_source_type", "") or "").strip().upper()
    if raw in {
        BOOST_SOURCE_NONE,
        BOOST_SOURCE_VENUE_MONTH_PLAN,
        BOOST_SOURCE_VENUE_DAY_PLAN,
        BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
        BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
        BOOST_SOURCE_KPI_METRIC,
    }:
        return raw
    return BOOST_SOURCE_NONE


def _effective_component_boost_recalc_mode(component: PayComponent) -> str:
    raw = str(getattr(component, "boost_recalc_mode", "") or "").strip().upper()
    if raw == BOOST_RECALC_EXCESS_ONLY:
        return BOOST_RECALC_EXCESS_ONLY
    return BOOST_RECALC_REPLACE_ALL

def _serialize_pay_component(component: PayComponent) -> dict:
    department = getattr(component, "department", None)
    department_ids = _component_department_ids(component)
    boost_department_ids = _component_boost_department_ids(component)
    kpi_metric = getattr(component, "kpi_metric", None)
    boost_department = getattr(component, "boost_department", None)
    boost_kpi_metric = getattr(component, "boost_kpi_metric", None)
    effective_base_scope = _effective_component_base_scope(component)
    effective_boost_source_type = _effective_component_boost_source_type(component)
    effective_boost_recalc_mode = _effective_component_boost_recalc_mode(component)
    return {
        "id": int(component.id),
        "pay_profile_id": int(component.pay_profile_id),
        "component_type": component.component_type,
        "title": component.title,
        "amount_minor": component.amount_minor,
        "rate_minor": component.rate_minor,
        "percent_bps": component.percent_bps,
        "department_id": component.department_id,
        "department_ids": department_ids,
        "department_title": department.title if department is not None else None,
        "department_titles": [department.title] if department is not None and int(component.department_id or 0) in department_ids else [],
        "kpi_metric_id": component.kpi_metric_id,
        "kpi_metric_title": kpi_metric.title if kpi_metric is not None else None,
        "threshold_value": component.threshold_value,
        "steps": _parse_json_text(component.steps_json),
        "base_scope": component.base_scope,
        "effective_base_scope": effective_base_scope,
        "effective_base_scope_title": BASE_SCOPE_TITLES.get(effective_base_scope, effective_base_scope),
        "boost_enabled": bool(component.boost_enabled),
        "boost_percent_bps": component.boost_percent_bps,
        "boost_source_type": component.boost_source_type,
        "effective_boost_source_type": effective_boost_source_type,
        "effective_boost_source_title": BOOST_SOURCE_TITLES.get(effective_boost_source_type, effective_boost_source_type),
        "boost_recalc_mode": component.boost_recalc_mode,
        "effective_boost_recalc_mode": effective_boost_recalc_mode,
        "effective_boost_recalc_mode_title": BOOST_RECALC_TITLES.get(effective_boost_recalc_mode, effective_boost_recalc_mode),
        "boost_department_id": component.boost_department_id,
        "boost_department_ids": boost_department_ids,
        "boost_department_title": boost_department.title if boost_department is not None else None,
        "boost_department_titles": [boost_department.title] if boost_department is not None and int(component.boost_department_id or 0) in boost_department_ids else [],
        "boost_kpi_metric_id": component.boost_kpi_metric_id,
        "boost_kpi_metric_title": boost_kpi_metric.title if boost_kpi_metric is not None else None,
        "boost_threshold_value": component.boost_threshold_value,
        "minimum_guarantee_minor": component.minimum_guarantee_minor,
        "minimum_guarantee_scope": component.minimum_guarantee_scope,
        "effective_minimum_guarantee_scope": _normalize_minimum_guarantee_scope(component.minimum_guarantee_scope),
        "effective_minimum_guarantee_scope_title": MINIMUM_GUARANTEE_SCOPE_TITLES.get(_normalize_minimum_guarantee_scope(component.minimum_guarantee_scope), "за месяц"),
        "maximum_cap_minor": component.maximum_cap_minor,
        "sort_order": int(component.sort_order or 0),
        "is_active": bool(component.is_active),
    }



def _validate_pay_component_fields(
    *,
    component_type: str,
    amount_minor: int | None,
    rate_minor: int | None,
    percent_bps: int | None,
    department_id: int | None,
    department_ids: list[int] | None = None,
    kpi_metric_id: int | None = None,
    threshold_value: int | None = None,
    steps_json: dict | list | None = None,
    base_scope: str | None = None,
    boost_enabled: bool = False,
    boost_percent_bps: int | None = None,
    boost_source_type: str | None = None,
    boost_recalc_mode: str | None = None,
    boost_department_id: int | None = None,
    boost_department_ids: list[int] | None = None,
    boost_kpi_metric_id: int | None = None,
    boost_threshold_value: int | None = None,
    minimum_guarantee_minor: int | None = None,
    minimum_guarantee_scope: str | None = None,
    maximum_cap_minor: int | None = None,
) -> None:
    component_type = str(component_type or "").strip().upper()
    normalized_base_scope = str(base_scope or "").strip().upper() if base_scope is not None else None
    normalized_boost_source_type = str(boost_source_type or "").strip().upper() if boost_source_type is not None else BOOST_SOURCE_NONE
    normalized_boost_recalc_mode = str(boost_recalc_mode or "").strip().upper() if boost_recalc_mode is not None else BOOST_RECALC_REPLACE_ALL
    is_percent_component = component_type in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"}
    normalized_department_ids = _normalize_int_ids(department_ids)
    normalized_boost_department_ids = _normalize_int_ids(boost_department_ids)
    raw_minimum_scope = str(minimum_guarantee_scope or "").strip().upper()
    if component_type == "MINIMUM_PAYOUT":
        if minimum_guarantee_scope is not None and raw_minimum_scope not in {MINIMUM_GUARANTEE_MONTH, MINIMUM_GUARANTEE_SHIFT, MINIMUM_GUARANTEE_DAY}:
            raise HTTPException(status_code=400, detail="minimum_guarantee_scope must be MONTH or SHIFT for MINIMUM_PAYOUT")
    elif minimum_guarantee_scope is not None and raw_minimum_scope not in {MINIMUM_GUARANTEE_MONTH, MINIMUM_GUARANTEE_DAY}:
        raise HTTPException(status_code=400, detail="minimum_guarantee_scope must be MONTH or DAY")
    if minimum_guarantee_minor is not None and maximum_cap_minor is not None and minimum_guarantee_minor > maximum_cap_minor:
        raise HTTPException(status_code=400, detail="minimum_guarantee_minor must be <= maximum_cap_minor")
    if component_type == "SALARY_FIXED_MONTH":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for SALARY_FIXED_MONTH")
        return
    if component_type == "SALARY_HOURLY":
        if rate_minor is None:
            raise HTTPException(status_code=400, detail="rate_minor is required for SALARY_HOURLY")
        return
    if component_type == "SALARY_PER_SHIFT":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for SALARY_PER_SHIFT")
        return
    if component_type == "MINIMUM_PAYOUT":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for MINIMUM_PAYOUT")
        return
    if component_type == "PERCENT_TOTAL_REVENUE":
        if percent_bps is None:
            raise HTTPException(status_code=400, detail="percent_bps is required for PERCENT_TOTAL_REVENUE")
    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        if percent_bps is None:
            raise HTTPException(status_code=400, detail="percent_bps is required for PERCENT_DEPARTMENT_REVENUE")
        if department_id is None and not normalized_department_ids:
            raise HTTPException(status_code=400, detail="department_id or department_ids is required for PERCENT_DEPARTMENT_REVENUE")
    if is_percent_component:
        if normalized_base_scope is not None and normalized_base_scope not in {BASE_SCOPE_FULL_PERIOD, BASE_SCOPE_WORKED_DATES}:
            raise HTTPException(status_code=400, detail="base_scope must be FULL_PERIOD or WORKED_DATES")
        if boost_enabled:
            if boost_percent_bps is None:
                raise HTTPException(status_code=400, detail="boost_percent_bps is required when boost is enabled")
            if percent_bps is not None and boost_percent_bps < percent_bps:
                raise HTTPException(status_code=400, detail="boost_percent_bps must be >= percent_bps")
            if normalized_boost_source_type not in {
                BOOST_SOURCE_VENUE_MONTH_PLAN,
                BOOST_SOURCE_VENUE_DAY_PLAN,
                BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
                BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
                BOOST_SOURCE_KPI_METRIC,
            }:
                raise HTTPException(status_code=400, detail="boost_source_type is required when boost is enabled")
            if normalized_boost_recalc_mode not in {BOOST_RECALC_REPLACE_ALL, BOOST_RECALC_EXCESS_ONLY}:
                raise HTTPException(status_code=400, detail="boost_recalc_mode must be REPLACE_ALL or EXCESS_ONLY")
            if normalized_boost_source_type == BOOST_SOURCE_KPI_METRIC:
                if boost_kpi_metric_id is None:
                    raise HTTPException(status_code=400, detail="boost_kpi_metric_id is required for KPI boost")
                if boost_threshold_value is None:
                    raise HTTPException(status_code=400, detail="boost_threshold_value is required for KPI boost")
                if normalized_boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY:
                    raise HTTPException(status_code=400, detail="EXCESS_ONLY is not supported for KPI boost")
            if normalized_boost_source_type in {BOOST_SOURCE_DEPARTMENT_MONTH_PLAN, BOOST_SOURCE_DEPARTMENT_DAY_PLAN} and boost_department_id is None and not normalized_boost_department_ids:
                raise HTTPException(status_code=400, detail="boost_department_id or boost_department_ids is required for department plan boost")
        return
    if component_type == "KPI_BONUS":
        if kpi_metric_id is None:
            raise HTTPException(status_code=400, detail="kpi_metric_id is required for KPI_BONUS")
        has_steps = False
        if isinstance(steps_json, list):
            has_steps = len(steps_json) > 0
        elif isinstance(steps_json, dict):
            raw_steps = steps_json.get("steps") if steps_json is not None else None
            has_steps = isinstance(raw_steps, list) and len(raw_steps) > 0
        if has_steps:
            return
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for KPI_BONUS without steps_json")
        return

def _serialize_pay_profile_assignment(assignment: PayProfileAssignment, member: User | None = None) -> dict:
    member_obj = None
    if member is not None:
        member_obj = {
            "user_id": int(member.id),
            "tg_user_id": member.tg_user_id,
            "tg_username": member.tg_username,
            "full_name": member.full_name,
            "short_name": member.short_name,
        }
    return {
        "id": int(assignment.id),
        "pay_profile_id": int(assignment.pay_profile_id),
        "member_user_id": int(assignment.member_user_id),
        "start_date": assignment.start_date.isoformat() if assignment.start_date else None,
        "end_date": assignment.end_date.isoformat() if assignment.end_date else None,
        "is_active": bool(assignment.is_active),
        "member": member_obj,
    }





def _serialize_pay_profile(profile: PayProfile, *, components_count: int | None = None, assignments_count: int | None = None) -> dict:
    payload = {
        "id": int(profile.id),
        "venue_id": int(profile.venue_id),
        "title": profile.title,
        "description": profile.description,
        "is_active": bool(profile.is_active),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if components_count is not None:
        payload["components_count"] = int(components_count)
    if assignments_count is not None:
        payload["assignments_count"] = int(assignments_count)
    return payload



def _load_pay_profile_detail(db: Session, *, venue_id: int, profile_id: int) -> dict:
    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    components = db.execute(
        select(PayComponent)
        .where(PayComponent.venue_id == venue_id, PayComponent.pay_profile_id == profile_id)
        .order_by(PayComponent.sort_order.asc(), PayComponent.id.asc())
    ).scalars().all()
    assignment_rows = db.execute(
        select(PayProfileAssignment, User)
        .join(User, User.id == PayProfileAssignment.member_user_id)
        .where(
            PayProfileAssignment.venue_id == venue_id,
            PayProfileAssignment.pay_profile_id == profile_id,
        )
        .order_by(PayProfileAssignment.is_active.desc(), PayProfileAssignment.start_date.desc(), PayProfileAssignment.id.desc())
    ).all()
    payload = _serialize_pay_profile(profile)
    payload["components"] = [_serialize_pay_component(component) for component in components]
    payload["assignments"] = [
        _serialize_pay_profile_assignment(assignment, member=member)
        for assignment, member in assignment_rows
    ]
    return payload



def _payroll_recalculation_logs_table_exists(db: Session) -> bool:
    try:
        return bool(inspect(db.get_bind()).has_table(PayrollRecalculationLog.__tablename__))
    except Exception:
        return True


def _serialize_payroll_recalculation_log(row: PayrollRecalculationLog | None) -> dict | None:
    if row is None:
        return None
    target_dates: list[str] = []
    try:
        raw_dates = json.loads(row.target_dates_json) if row.target_dates_json else []
        if isinstance(raw_dates, list):
            target_dates = [str(item) for item in raw_dates if item]
    except Exception:
        target_dates = []
    return {
        "id": int(row.id),
        "period_month": row.period_month.strftime("%Y-%m") if getattr(row, "period_month", None) else None,
        "trigger_reason": str(row.trigger_reason or ""),
        "triggered_by_user_id": int(row.triggered_by_user_id) if getattr(row, "triggered_by_user_id", None) is not None else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "target_dates": target_dates,
    }


def _create_payroll_recalculation_log(
    db: Session,
    *,
    venue_id: int,
    period_month: date,
    trigger_reason: str,
    triggered_by_user_id: int | None = None,
    target_dates: list[date] | tuple[date, ...] | None = None,
    details: dict | None = None,
) -> PayrollRecalculationLog | None:
    if not _payroll_recalculation_logs_table_exists(db):
        return None
    obj = PayrollRecalculationLog(
        venue_id=int(venue_id),
        period_month=period_month,
        triggered_by_user_id=int(triggered_by_user_id) if triggered_by_user_id is not None else None,
        trigger_reason=str(trigger_reason or "system"),
        target_dates_json=json.dumps(sorted({day.isoformat() for day in (target_dates or []) if isinstance(day, date)}), ensure_ascii=False),
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    return obj


def _latest_payroll_recalculation_log(db: Session, *, venue_id: int, period_month: date) -> PayrollRecalculationLog | None:
    if not _payroll_recalculation_logs_table_exists(db):
        return None
    return db.execute(
        select(PayrollRecalculationLog)
        .where(
            PayrollRecalculationLog.venue_id == int(venue_id),
            PayrollRecalculationLog.period_month == period_month,
        )
        .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _has_closed_report_for_date(db: Session, *, venue_id: int, target_date: date) -> bool:
    report_id = db.execute(
        select(DailyReport.id).where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date == target_date,
            DailyReport.status == "CLOSED",
        )
    ).scalar_one_or_none()
    return report_id is not None


def _recalculate_payroll_for_dates(
    db: Session,
    *,
    venue_id: int,
    target_dates: list[date] | tuple[date, ...],
    calculated_by_user_id: int | None = None,
    force: bool = False,
    trigger_reason: str = "system",
    details: dict | None = None,
) -> list[str]:
    months_done: list[str] = []
    seen: set[str] = set()
    target_dates = [day for day in target_dates if isinstance(day, date)]
    for target_date in target_dates:
        month = target_date.strftime("%Y-%m")
        if month in seen:
            continue
        if not force and not _has_closed_report_for_date(db, venue_id=venue_id, target_date=target_date):
            continue
        calculate_payroll_for_month(
            db=db,
            venue_id=int(venue_id),
            month=month,
            calculated_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
        )
        month_start = parse_month_start(month)
        month_target_dates = sorted(day for day in target_dates if day.strftime("%Y-%m") == month)
        _create_payroll_recalculation_log(
            db,
            venue_id=int(venue_id),
            period_month=month_start,
            trigger_reason=str(trigger_reason or "system"),
            triggered_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
            target_dates=month_target_dates,
            details=details or {},
        )
        seen.add(month)
        months_done.append(month)
    return months_done


def _load_payroll_payload(db: Session, *, venue_id: int, month: str) -> dict:
    month_start = parse_month_start(month)
    latest_recalculation = _latest_payroll_recalculation_log(db, venue_id=int(venue_id), period_month=month_start)
    run = db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == venue_id,
            PayrollRun.period_month == month_start,
        )
    ).scalar_one_or_none()
    if run is None:
        return {
            "month": month,
            "run": None,
            "lines": [],
            "total_amount_minor": 0,
            "lines_count": 0,
            "latest_recalculation": _serialize_payroll_recalculation_log(latest_recalculation),
        }

    rows = db.execute(
        select(PayrollLine, User, PayProfile)
        .join(User, User.id == PayrollLine.member_user_id)
        .outerjoin(PayProfile, PayProfile.id == PayrollLine.pay_profile_id)
        .where(PayrollLine.payroll_run_id == int(run.id))
        .order_by(User.short_name.asc(), User.full_name.asc(), PayrollLine.id.asc())
    ).all()

    lines = []
    for line, member, profile in rows:
        lines.append(
            {
                "id": int(line.id),
                "member_user_id": int(line.member_user_id),
                "amount_minor": int(line.amount_minor or 0),
                "pay_profile_id": int(line.pay_profile_id) if line.pay_profile_id is not None else None,
                "pay_profile_title": profile.title if profile is not None else None,
                "member": {
                    "user_id": int(member.id),
                    "tg_user_id": member.tg_user_id,
                    "tg_username": member.tg_username,
                    "full_name": member.full_name,
                    "short_name": member.short_name,
                },
                "breakdown": _parse_json_text(line.breakdown_json),
            }
        )

    return {
        "month": month,
        "run": {
            "id": int(run.id),
            "venue_id": int(run.venue_id),
            "period_month": run.period_month.isoformat() if run.period_month else None,
            "calculated_by_user_id": run.calculated_by_user_id,
            "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
            "total_amount_minor": int(run.total_amount_minor or 0),
            "lines_count": int(run.lines_count or 0),
        },
        "lines": lines,
        "total_amount_minor": int(run.total_amount_minor or 0),
        "lines_count": int(run.lines_count or 0),
        "latest_recalculation": _serialize_payroll_recalculation_log(latest_recalculation),
    }


def _month_starts_between(period_start: date, period_end: date) -> list[date]:
    current = date(period_start.year, period_start.month, 1)
    last = date(period_end.year, period_end.month, 1)
    months: list[date] = []
    while current <= last:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def _latest_payroll_recalculation_for_period(db: Session, *, venue_id: int, period_start: date, period_end: date) -> dict | None:
    months = _month_starts_between(period_start, period_end)
    if not months or not _payroll_recalculation_logs_table_exists(db):
        return None
    row = db.execute(
        select(PayrollRecalculationLog)
        .where(
            PayrollRecalculationLog.venue_id == int(venue_id),
            PayrollRecalculationLog.period_month.in_(months),
        )
        .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return _serialize_payroll_recalculation_log(row)


def _collect_venue_payroll_candidate_dates(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[int, set[date]]:
    candidates: dict[int, set[date]] = {}

    shift_rows = db.execute(
        select(ShiftAssignment.member_user_id, Shift.date)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(DailyReport, sa.and_(DailyReport.venue_id == Shift.venue_id, DailyReport.date == Shift.date))
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= period_start,
            Shift.date <= period_end,
            DailyReport.status == "CLOSED",
        )
        .distinct()
    ).all()
    for member_user_id, shift_date in shift_rows:
        if member_user_id is None or shift_date is None:
            continue
        candidates.setdefault(int(member_user_id), set()).add(shift_date)

    adjustment_rows = db.execute(
        select(Adjustment.member_user_id, Adjustment.date)
        .where(
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
            Adjustment.date >= period_start,
            Adjustment.date <= period_end,
            Adjustment.member_user_id.is_not(None),
        )
        .distinct()
    ).all()
    for member_user_id, adjustment_date in adjustment_rows:
        if member_user_id is None or adjustment_date is None:
            continue
        candidates.setdefault(int(member_user_id), set()).add(adjustment_date)

    return candidates


def _build_venue_payroll_period_payload(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    period_meta: dict,
) -> dict:
    member_dates = _collect_venue_payroll_candidate_dates(
        db,
        venue_id=int(venue_id),
        period_start=period_start,
        period_end=period_end,
    )

    member_ids = sorted(member_dates.keys())
    members = db.execute(
        select(User).where(User.id.in_(member_ids))
    ).scalars().all() if member_ids else []
    members_by_id = {int(member.id): member for member in members}

    lines: list[dict] = []
    total_amount_minor = 0
    latest_recalculation = _latest_payroll_recalculation_for_period(
        db,
        venue_id=int(venue_id),
        period_start=period_start,
        period_end=period_end,
    )

    for member_id in member_ids:
        dates = sorted(member_dates.get(member_id, set()))
        if not dates:
            continue

        earnings_minor = 0
        tips_minor = 0
        bonuses_minor = 0
        penalties_minor = 0
        total_minor = 0
        minutes_total = 0
        shifts_count = 0
        worked_dates: set[str] = set()
        pay_profile_titles: list[str] = []
        has_payroll_line = False
        components_map: dict[tuple[str, str, str, str], dict] = {}

        for target_date in dates:
            day_breakdown = build_member_day_breakdown(
                db,
                member_user_id=int(member_id),
                venue_id=int(venue_id),
                target_date=target_date,
            )
            summary = day_breakdown.get("summary") or {}
            context = day_breakdown.get("context") or {}
            earnings_minor += int(summary.get("earnings_minor") or 0)
            tips_minor += int(summary.get("tips_minor") or 0)
            bonuses_minor += int(summary.get("bonuses_minor") or 0)
            penalties_minor += int(summary.get("penalties_minor") or 0)
            total_minor += int(summary.get("total_minor") or 0)
            minutes_total += int(context.get("minutes_total") or 0)
            shifts_count += int(context.get("shifts_count") or 0)
            if context.get("has_payroll_line"):
                has_payroll_line = True
            pay_profile_title = str(context.get("pay_profile_title") or "").strip()
            if pay_profile_title:
                pay_profile_titles.append(pay_profile_title)
            for item in (day_breakdown.get("items") or []):
                if not isinstance(item, dict):
                    continue
                key = (
                    str(item.get("category") or ""),
                    str(item.get("component_type") or ""),
                    str(item.get("title") or ""),
                    str(item.get("formula_text") or ""),
                )
                existing = components_map.get(key)
                if existing is None:
                    existing = {
                        "category": str(item.get("category") or ""),
                        "component_type": str(item.get("component_type") or ""),
                        "title": str(item.get("title") or ""),
                        "base_text": str(item.get("base_text") or ""),
                        "formula_text": str(item.get("formula_text") or ""),
                        "amount_minor": 0,
                    }
                    components_map[key] = existing
                existing["amount_minor"] += int(item.get("amount_minor") or 0)
            if int(context.get("minutes_total") or 0) > 0 or int(context.get("shifts_count") or 0) > 0:
                worked_dates.add(target_date.isoformat())

        if not any([earnings_minor, tips_minor, bonuses_minor, penalties_minor, total_minor]):
            continue

        member = members_by_id.get(int(member_id))
        unique_titles = sorted({title for title in pay_profile_titles if title})
        if len(unique_titles) == 1:
            pay_profile_title = unique_titles[0]
        elif len(unique_titles) > 1:
            pay_profile_title = "Несколько профилей"
        else:
            pay_profile_title = None

        components = sorted(
            components_map.values(),
            key=lambda item: (0 if int(item.get("amount_minor") or 0) >= 0 else 1, str(item.get("title") or "")),
        )

        line_payload = {
            "id": None,
            "member_user_id": int(member_id),
            "amount_minor": int(total_minor),
            "pay_profile_id": None,
            "pay_profile_title": pay_profile_title,
            "member": {
                "user_id": int(member.id) if member is not None else int(member_id),
                "tg_user_id": getattr(member, "tg_user_id", None),
                "tg_username": getattr(member, "tg_username", None),
                "full_name": getattr(member, "full_name", None),
                "short_name": getattr(member, "short_name", None),
            },
            "breakdown": {
                "metrics": {
                    "hours_total": round(minutes_total / 60.0, 2),
                    "shifts_count": int(shifts_count),
                    "worked_dates_count": len(worked_dates),
                    "worked_dates": sorted(worked_dates),
                },
                "components": components,
                "summary": {
                    "earnings_minor": int(earnings_minor),
                    "tips_minor": int(tips_minor),
                    "bonuses_minor": int(bonuses_minor),
                    "penalties_minor": int(penalties_minor),
                    "total_minor": int(total_minor),
                },
                "period_mode": "range",
                "period": {
                    "date_from": period_start.isoformat(),
                    "date_to": period_end.isoformat(),
                },
            },
            "period_state": "ready" if has_payroll_line else ("partial" if total_minor else "empty"),
        }
        lines.append(line_payload)
        total_amount_minor += int(total_minor)

    lines.sort(key=lambda item: ((str(item.get("member", {}).get("short_name") or item.get("member", {}).get("full_name") or "").lower()), int(item.get("member_user_id") or 0)))

    return {
        **period_meta,
        "run": None,
        "lines": lines,
        "total_amount_minor": int(total_amount_minor),
        "lines_count": len(lines),
        "latest_recalculation": latest_recalculation,
    }




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


_ADJ_TYPE_LABELS = {
    "ru": {"penalty": "Штраф", "writeoff": "Списание", "bonus": "Премия", "tip": "Чаевые"},
    "en": {"penalty": "Penalty", "writeoff": "Write-off", "bonus": "Bonus", "tip": "Tips"},
}

def _ui_lang() -> str:
    # Minimal v1: default RU. Later we can store per-user language in DB and use it here.
    return (os.getenv("DEFAULT_UI_LANG") or "ru").lower()

def _adj_type_label(adj_type: str, lang: str | None = None) -> str:
    lt = (lang or _ui_lang() or "ru").lower()
    mp = _ADJ_TYPE_LABELS.get(lt) or _ADJ_TYPE_LABELS.get("ru", {})
    return mp.get(adj_type, adj_type)

def _venue_name(db: Session, venue_id: int) -> str:
    v = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    return (v.name if v else "Axelio")

def _should_notify_user(u: User, kind: str) -> bool:
    """Best-effort per-user notification gate.

    kind: 'adjustments' | 'shifts' | 'day_economics' | 'salary' | 'soft_alerts'
    """
    if not u:
        return False
    if not getattr(u, "notify_enabled", True):
        return False
    if kind == "adjustments":
        return bool(getattr(u, "notify_adjustments", True))
    if kind == "shifts":
        return bool(getattr(u, "notify_shifts", True))
    if kind == "day_economics":
        return bool(getattr(u, "notify_day_economics", True))
    if kind == "salary":
        return bool(getattr(u, "notify_salary", True))
    if kind == "soft_alerts":
        return bool(getattr(u, "notify_soft_alerts", True))
    return True



def _frontend_base_url() -> str:
    return settings.frontend_base_url()


def _build_owner_day_economics_link(*, venue_id: int, target_date: date) -> str:
    return f"{_frontend_base_url()}/owner-day-economics.html?venue_id={int(venue_id)}&date={quote(target_date.isoformat())}"


def _build_staff_salary_day_link(*, venue_id: int, target_date: date) -> str:
    month_value = target_date.strftime("%Y-%m")
    return (
        f"{_frontend_base_url()}/staff-salary.html?venue_id={int(venue_id)}"
        f"&month={quote(month_value)}&date={quote(target_date.isoformat())}&open_day=1"
    )


def _build_staff_adjustments_link(*, venue_id: int, adjustment_id: int, tab: str | None = None) -> str:
    suffix = f"&tab={quote(str(tab))}" if tab else ""
    return f"{_frontend_base_url()}/staff-adjustments.html?venue_id={int(venue_id)}&open={int(adjustment_id)}{suffix}"


def _build_owner_adjustments_link(*, venue_id: int, adjustment_id: int, tab: str | None = None) -> str:
    suffix = f"&tab={quote(str(tab))}" if tab else ""
    return f"{_frontend_base_url()}/app-adjustments.html?venue_id={int(venue_id)}&open={int(adjustment_id)}{suffix}"


def _display_user_name(user: User | None) -> str:
    if user is None:
        return "Сотрудник"
    return (user.short_name or user.full_name or (user.tg_username or str(user.id))).strip()


def _collect_adjustment_manager_recipients(db: Session, *, venue_id: int) -> list[User]:
    owners = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
            VenueMember.venue_role == "OWNER",
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).scalars().all()

    mgr_rows = db.execute(
        select(User)
        .join(VenuePosition, VenuePosition.member_user_id == User.id)
        .where(
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.is_active.is_(True),
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).scalars().all()

    uniq: dict[int, User] = {int(u.id): u for u in owners if getattr(u, "tg_user_id", None) is not None}
    for candidate in mgr_rows:
        if getattr(candidate, "tg_user_id", None) is None:
            continue
        if has_venue_permission(db, venue_id=venue_id, user=candidate, permission_code="ADJUSTMENTS_MANAGE"):
            uniq.setdefault(int(candidate.id), candidate)
    return list(uniq.values())


def _deliver_user_notification(
    db: Session,
    *,
    notification_type: str,
    recipient: User,
    venue_id: int,
    idempotency_key: str,
    text: str,
    url: str | None = None,
    button_text: str | None = None,
) -> tuple[bool, bool]:
    lock_notification_idempotency_key(db, idempotency_key)
    if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
        return False, False

    planned_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    pending_log = log_notification_attempt(
        db,
        notification_type=notification_type,
        status="pending",
        user_id=int(recipient.id),
        venue_id=int(venue_id),
        planned_at=planned_at,
        idempotency_key=idempotency_key,
        payload_preview=text[:2000],
    )
    db.flush()
    db.commit()

    result = tg_notify.notify_result(
        chat_id=int(recipient.tg_user_id),
        text=text,
        url=url,
        button_text=button_text,
    )
    ok = bool(result.get("ok"))
    retryable = bool(result.get("retryable"))
    try:
        pending_log.status = "sent" if ok else "failed"
        pending_log.sent_at = datetime.utcnow().replace(tzinfo=timezone.utc) if ok else None
        pending_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
        db.add(pending_log)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ok, (retryable and not ok)


def _enqueue_adjustment_assigned_job(db: Session, *, venue_id: int, adjustment_id: int) -> NotificationJob:
    idempotency_key = f"job:adjustment_assigned:{int(adjustment_id)}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "adjustment_id": int(adjustment_id)}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _enqueue_adjustment_dispute_event_job(
    db: Session,
    *,
    venue_id: int,
    dispute_id: int,
    comment_id: int,
    event_kind: str,
) -> NotificationJob:
    normalized_kind = str(event_kind or "comment").strip().lower()
    if normalized_kind not in {"opened", "comment"}:
        normalized_kind = "comment"
    idempotency_key = f"job:adjustment_dispute_event:{int(comment_id)}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {
                "venue_id": int(venue_id),
                "dispute_id": int(dispute_id),
                "comment_id": int(comment_id),
                "event_kind": normalized_kind,
            },
            ensure_ascii=False,
        ),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_adjustment_assigned_notification(db: Session, *, venue_id: int, adjustment_id: int) -> None:
    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == int(adjustment_id),
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None or not getattr(adj, "member_user_id", None):
        return

    recipient = db.execute(select(User).where(User.id == int(adj.member_user_id))).scalar_one_or_none()
    if recipient is None or not getattr(recipient, "tg_user_id", None):
        return
    if not _should_notify_user(recipient, "adjustments"):
        return

    venue_name = _venue_name(db, venue_id)
    label = _adj_type_label(adj.type)
    text = (
        f"{venue_name}: вам добавлен(а) {label} на {adj.date.isoformat()} "
        f"на сумму {adj.amount}. Причина: {(adj.reason or '—')}"
    )
    ok, retryable_error = _deliver_user_notification(
        db,
        notification_type="adjustment_assigned",
        recipient=recipient,
        venue_id=venue_id,
        idempotency_key=f"adjustment_assigned:{int(adj.id)}:{notification_dedupe_scope(recipient)}",
        text=text,
        url=_build_staff_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab=adj.type),
        button_text="Открыть",
    )
    if retryable_error and not ok:
        raise RuntimeError("adjustment assigned delivery failed with retryable error")


def _send_adjustment_dispute_event_notifications(
    db: Session,
    *,
    venue_id: int,
    dispute_id: int,
    comment_id: int,
    event_kind: str,
) -> None:
    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == int(dispute_id),
            AdjustmentDispute.venue_id == int(venue_id),
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        return

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == int(dis.adjustment_id),
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        return

    comment = db.execute(
        select(AdjustmentDisputeComment).where(
            AdjustmentDisputeComment.id == int(comment_id),
            AdjustmentDisputeComment.dispute_id == int(dis.id),
            AdjustmentDisputeComment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if comment is None:
        return

    author = db.execute(select(User).where(User.id == int(comment.author_user_id))).scalar_one_or_none()
    if author is None:
        return

    author_is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=author)
    recipients: list[User] = []
    if author_is_manager:
        if getattr(adj, "member_user_id", None):
            employee = db.execute(
                select(User).where(
                    User.id == int(adj.member_user_id),
                    User.tg_user_id.is_not(None),
                )
            ).scalar_one_or_none()
            if employee is not None:
                recipients.append(employee)
    else:
        recipients.extend(_collect_adjustment_manager_recipients(db, venue_id=venue_id))

    if not recipients:
        return

    venue_name = _venue_name(db, venue_id)
    who = _display_user_name(author)
    label = _adj_type_label(adj.type)
    prefix = "Новый спор" if str(event_kind or "comment").strip().lower() == "opened" else "Новый комментарий"
    message_text = (comment.message or dis.message or "—").strip() or "—"

    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    had_retryable_error = False
    delivered_any = False

    for recipient in recipients:
        if recipient is None or int(recipient.id) == int(author.id):
            continue
        if not getattr(recipient, "tg_user_id", None):
            continue
        if not _should_notify_user(recipient, "adjustments"):
            continue
        recipient_id = int(recipient.id)
        chat_id = int(recipient.tg_user_id)
        if recipient_id in seen_recipient_ids or chat_id in seen_tg_user_ids:
            continue

        recipient_is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=recipient)
        link = (
            _build_owner_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab="disputes")
            if recipient_is_manager
            else _build_staff_adjustments_link(venue_id=venue_id, adjustment_id=int(adj.id), tab="disputes")
        )
        if prefix == "Новый спор":
            text = (
                f"{venue_name}: {prefix}. {who} оспорил {label} #{adj.id} на {adj.date.isoformat()} "
                f"(сумма {adj.amount}).\nКомментарий: {message_text}"
            )
        else:
            text = f"{venue_name}: новый комментарий в споре по {label} #{adj.id} от {who}.\n{message_text}"

        ok, retryable_error = _deliver_user_notification(
            db,
            notification_type="adjustment_dispute_event",
            recipient=recipient,
            venue_id=venue_id,
            idempotency_key=f"adjustment_dispute_event:{int(comment.id)}:{notification_dedupe_scope(recipient)}",
            text=text,
            url=link,
            button_text="Открыть спор",
        )
        delivered_any = delivered_any or ok
        had_retryable_error = had_retryable_error or retryable_error
        seen_recipient_ids.add(recipient_id)
        seen_tg_user_ids.add(chat_id)

    if had_retryable_error and not delivered_any:
        raise RuntimeError("adjustment dispute delivery failed with retryable error")


def _can_receive_day_economics_summary(db: Session, *, venue_id: int, user: User) -> bool:
    if user is None:
        return False
    if not _should_notify_user(user, "day_economics"):
        return False
    if not getattr(user, "tg_user_id", None):
        return False
    return _has_revenue_view_access(db, venue_id=venue_id, user=user) and _is_report_viewer(db, venue_id=venue_id, user=user)


def _can_receive_soft_alerts(db: Session, *, venue_id: int, user: User) -> bool:
    if user is None:
        return False
    if not _should_notify_user(user, "soft_alerts"):
        return False
    if not getattr(user, "tg_user_id", None):
        return False
    return _has_revenue_view_access(db, venue_id=venue_id, user=user) and _is_report_viewer(db, venue_id=venue_id, user=user)


def _notification_detail_level(detail_level: str | None) -> str:
    level = str(detail_level or "standard").strip().lower()
    if level not in {"short", "standard", "detailed"}:
        return "standard"
    return level


def _soft_alert_signature(alerts: list[dict]) -> str:
    normalized: list[str] = []
    for item in alerts or []:
        code = str((item or {}).get("code") or "").strip().upper()
        severity = str((item or {}).get("severity") or "").strip().upper()
        if code:
            normalized.append(f"{severity}:{code}")
    normalized.sort()
    return hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:16] if normalized else "none"


def _select_soft_alerts_for_notification(economics: dict) -> list[dict]:
    alerts = economics.get("alerts") or []
    selected: list[dict] = []
    seen_codes: set[str] = set()
    for item in alerts:
        severity = str((item or {}).get("severity") or "").strip().upper()
        code = str((item or {}).get("code") or "").strip().upper()
        if severity not in {"WARN", "CRITICAL"}:
            continue
        if not code or code in seen_codes:
            continue
        selected.append(item)
        seen_codes.add(code)
    selected.sort(key=lambda item: (0 if str((item or {}).get("severity") or "").strip().upper() == "CRITICAL" else 1, str((item or {}).get("code") or "")))
    return selected


def _build_soft_alerts_notification_text(*, venue_name: str, target_date: date, economics: dict, alerts: list[dict], detail_level: str) -> str:
    level = _notification_detail_level(detail_level)
    summary = economics.get("summary") or {}
    metrics = economics.get("metrics") or {}
    rules = economics.get("rules") or {}

    lines: list[str] = [
        f"⚠️ Мягкие алерты · {_format_ru_date(target_date)}",
        f"Заведение: {venue_name}",
    ]
    if level in {"standard", "detailed"}:
        lines.extend(
            [
                f"Выручка: {_fmt_money_minor(summary.get('revenue_minor'))}",
                f"Расходы: {_fmt_money_minor(summary.get('expense_minor'))} ({_fmt_percent_bps(metrics.get('expense_ratio_bps'))})",
                f"ФОТ: {_fmt_money_minor(summary.get('payroll_minor'))} ({_fmt_percent_bps(metrics.get('payroll_ratio_bps'))})",
                f"Прибыль: {_fmt_money_minor(summary.get('profit_minor'))}",
            ]
        )

    lines.append("Что требует внимания:")
    visible = alerts if level == "detailed" else alerts[:4]
    for alert in visible:
        severity = str((alert or {}).get("severity") or "").strip().upper()
        title = str((alert or {}).get("title") or "Алерт").strip()
        detail = str((alert or {}).get("detail") or "").strip()
        icon = "🔴" if severity == "CRITICAL" else "🟠"
        lines.append(f"{icon} {title}")
        if level in {"standard", "detailed"} and detail:
            lines.append(f"  {detail}")
    extra = max(len(alerts) - len(visible), 0)
    if extra:
        lines.append(f"• ещё {extra}")

    if level == "detailed":
        max_payroll_ratio_bps = rules.get("max_payroll_ratio_bps")
        max_expense_ratio_bps = rules.get("max_expense_ratio_bps")
        min_coverage_bps = rules.get("min_assigned_shift_coverage_bps")
        policy_parts: list[str] = []
        if max_payroll_ratio_bps is not None:
            policy_parts.append(f"ФОТ ≤ {_fmt_percent_bps(max_payroll_ratio_bps)}")
        if max_expense_ratio_bps is not None:
            policy_parts.append(f"расходы ≤ {_fmt_percent_bps(max_expense_ratio_bps)}")
        if min_coverage_bps is not None:
            policy_parts.append(f"покрытие смен ≥ {_fmt_percent_bps(min_coverage_bps)}")
        if bool(rules.get("warn_on_draft_expenses", True)):
            policy_parts.append("черновые расходы учитываются")
        if policy_parts:
            lines.append("Пороговые правила: " + " · ".join(policy_parts))

    return "\n".join(lines)


def _fmt_money_minor(value_minor: int | None) -> str:
    minor = int(value_minor or 0)
    sign = "-" if minor < 0 else ""
    abs_minor = abs(minor)
    if abs_minor % 100 == 0:
        rub = abs_minor // 100
        return f"{sign}{rub:,} ₽".replace(",", " ")
    rub = abs_minor / 100.0
    return f"{sign}{rub:,.2f} ₽".replace(",", " ")


def _fmt_percent_bps(value_bps: int | None) -> str:
    if value_bps is None:
        return "—"
    value = int(value_bps) / 100.0
    rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{rendered}%"


def _format_ru_date(value: date) -> str:
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
    }
    return f"{value.day} {months.get(value.month, value.strftime('%m'))} {value.year}"


def _truncate_breakdown_items(items: list[dict], *, limit: int) -> list[dict]:
    return list(items[: max(int(limit), 0)])


def _render_breakdown(title: str, items: list[dict], *, limit: int) -> list[str]:
    if not items:
        return [f"{title}: —"]
    visible = _truncate_breakdown_items(items, limit=limit)
    lines = [f"{title}:"]
    for item in visible:
        lines.append(f"• {item.get('title') or 'Без названия'} — {_fmt_money_minor(int(item.get('amount_minor') or 0))}")
    extra = max(len(items) - len(visible), 0)
    if extra:
        lines.append(f"• ещё {extra}")
    return lines


def _build_day_economics_notification_text(*, venue_name: str, target_date: date, economics: dict, detail_level: str) -> str:
    level = _notification_detail_level(detail_level)

    summary = economics.get("summary") or {}
    payment_breakdown = economics.get("payment_revenue_breakdown") or []
    department_breakdown = economics.get("department_revenue_breakdown") or []

    lines: list[str] = [
        f"📊 Экономика дня · {_format_ru_date(target_date)}",
        f"Заведение: {venue_name}",
        f"Выручка: {_fmt_money_minor(summary.get('revenue_minor'))}",
        f"ФОТ: {_fmt_money_minor(summary.get('payroll_minor'))} ({_fmt_percent_bps(summary.get('payroll_ratio_bps'))})",
        f"Прибыль: {_fmt_money_minor(summary.get('profit_minor'))}",
    ]

    draft_total_minor = int(summary.get("draft_expense_total_minor") or 0)
    draft_count = int(summary.get("draft_expense_count") or 0)

    if level in {"standard", "detailed"}:
        lines.extend(_render_breakdown("По оплатам", payment_breakdown, limit=4 if level == "standard" else 8))
        lines.extend(_render_breakdown("По департаментам", department_breakdown, limit=4 if level == "standard" else 8))
        lines.append(f"Разовые расходы: {_fmt_money_minor(summary.get('point_expense_minor'))}")
        lines.append(f"Регулярные расходы: {_fmt_money_minor(summary.get('recurring_expense_minor'))}")
        if draft_count > 0 or draft_total_minor > 0:
            lines.append(f"Черновые расходы: {_fmt_money_minor(draft_total_minor)} ({draft_count} шт.)")
        else:
            lines.append("Черновые расходы: —")

    if level == "detailed":
        point_expenses = summary.get("point_expenses") or []
        recurring_expenses = summary.get("recurring_expenses") or []
        if point_expenses:
            lines.extend(_render_breakdown("Детализация разовых расходов", point_expenses, limit=6))
        if recurring_expenses:
            lines.extend(_render_breakdown("Детализация регулярных расходов", recurring_expenses, limit=6))

    return "\n".join(lines)


def _build_salary_day_breakdown_text(*, venue_name: str, target_date: date, breakdown: dict, detail_level: str) -> str:
    level = _notification_detail_level(detail_level)

    summary = breakdown.get("summary") or {}
    context = breakdown.get("context") or {}
    items = breakdown.get("items") or []
    state = str(breakdown.get("state") or "ready")

    lines: list[str] = [
        f"💸 Начисление за день · {_format_ru_date(target_date)}",
        f"Заведение: {venue_name}",
        f"Итого начисление: {_fmt_money_minor(summary.get('total_minor'))}",
    ]

    if state == "partial":
        lines.append("Данные частичные: часть начислений ещё в пересчёте")
    elif state == "no_payroll":
        lines.append("Начисление ещё не рассчитано payroll, ниже только доступные данные")
    elif state == "empty":
        lines.append("За этот день начислений не найдено")

    if level in {"standard", "detailed"}:
        lines.append(f"Основное начисление: {_fmt_money_minor(summary.get('earnings_minor'))}")
        if int(summary.get('tips_minor') or 0):
            lines.append(f"Чаевые: {_fmt_money_minor(summary.get('tips_minor'))}")
        if int(summary.get('bonuses_minor') or 0):
            lines.append(f"Премии: {_fmt_money_minor(summary.get('bonuses_minor'))}")
        if int(summary.get('penalties_minor') or 0):
            lines.append(f"Штрафы/списания: {_fmt_money_minor(-int(summary.get('penalties_minor') or 0))}")
        hours_total = context.get('hours_total')
        shifts_count = context.get('shifts_count')
        if hours_total not in (None, "") or shifts_count not in (None, ""):
            lines.append(f"Смен: {int(shifts_count or 0)} · Часы: {hours_total or 0}")

    if items and level in {"standard", "detailed"}:
        visible = items[:4] if level == "standard" else items[:8]
        lines.append("Из чего сложилось:")
        for item in visible:
            lines.append(f"• {item.get('title') or 'Компонент'} — {_fmt_money_minor(int(item.get('amount_minor') or 0))}")
            if level == "detailed":
                base_text = str(item.get('base_text') or '').strip()
                formula_text = str(item.get('formula_text') or '').strip()
                if base_text:
                    lines.append(f"  База: {base_text}")
                if formula_text:
                    lines.append(f"  Формула: {formula_text}")
        extra = max(len(items) - len(visible), 0)
        if extra:
            lines.append(f"• ещё {extra}")

    return "\n".join(lines)


def _collect_salary_day_notification_user_ids(db: Session, *, venue_id: int, target_date: date) -> list[int]:
    user_ids: set[int] = set()

    assignment_rows = db.execute(
        select(ShiftAssignment.member_user_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.date == target_date,
            Shift.is_active.is_(True),
            ShiftAssignment.member_user_id.is_not(None),
        )
    ).all()
    for (member_user_id,) in assignment_rows:
        if member_user_id is not None:
            user_ids.add(int(member_user_id))

    adjustment_rows = db.execute(
        select(Adjustment.member_user_id)
        .where(
            Adjustment.venue_id == int(venue_id),
            Adjustment.date == target_date,
            Adjustment.is_active.is_(True),
            Adjustment.member_user_id.is_not(None),
        )
    ).all()
    for (member_user_id,) in adjustment_rows:
        if member_user_id is not None:
            user_ids.add(int(member_user_id))

    tip_rows = db.execute(
        select(DailyReportTipAllocation.user_id)
        .join(DailyReport, DailyReport.id == DailyReportTipAllocation.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date == target_date,
            DailyReportTipAllocation.user_id.is_not(None),
        )
    ).all()
    for (user_id,) in tip_rows:
        if user_id is not None:
            user_ids.add(int(user_id))

    return sorted(user_ids)


def _enqueue_salary_day_breakdown_job(db: Session, *, venue_id: int, target_date: date) -> NotificationJob:
    idempotency_key = f"job:salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat()}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_salary_day_breakdown_notifications(db: Session, *, venue_id: int, target_date: date) -> None:
    user_ids = _collect_salary_day_notification_user_ids(db, venue_id=venue_id, target_date=target_date)
    if not user_ids:
        return

    users = db.execute(
        select(User)
        .where(User.id.in_(user_ids))
        .order_by(User.id.asc())
    ).scalars().all()
    if not users:
        return

    venue_name = _venue_name(db, venue_id)
    link = _build_staff_salary_day_link(venue_id=venue_id, target_date=target_date)
    seen_tg_user_ids: set[int] = set()
    delivered_any = False
    had_retryable_error = False

    for recipient in users:
        if not _should_notify_user(recipient, "salary"):
            continue
        if not getattr(recipient, "tg_user_id", None):
            continue
        active_member = db.execute(
            select(VenueMember.id).where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.user_id == int(recipient.id),
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if active_member is None and recipient.system_role not in {"SUPER_ADMIN", "MODERATOR"}:
            continue
        chat_id = int(recipient.tg_user_id)
        if chat_id in seen_tg_user_ids:
            continue
        seen_tg_user_ids.add(chat_id)

        dedupe_scope = f"tg:{chat_id}"
        idempotency_key = f"salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}"
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        breakdown = build_member_day_breakdown(
            db,
            member_user_id=int(recipient.id),
            venue_id=int(venue_id),
            target_date=target_date,
        )
        items = breakdown.get("items") or []
        total_minor = int((breakdown.get("summary") or {}).get("total_minor") or 0)
        if not items and total_minor == 0:
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        text = _build_salary_day_breakdown_text(
            venue_name=venue_name,
            target_date=target_date,
            breakdown=breakdown,
            detail_level=detail_level,
        )

        sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
        pending_log = log_notification_attempt(
            db,
            notification_type="salary_day_breakdown",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text="Открыть начисления",
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        delivered_any = delivered_any or ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_retryable_error and not delivered_any:
        raise RuntimeError("salary day breakdown delivery failed with retryable error")


def _enqueue_soft_alerts_job(db: Session, *, venue_id: int, target_date: date) -> NotificationJob:
    idempotency_key = f"job:soft_alerts:{int(venue_id)}:{target_date.isoformat()}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat()}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_soft_alert_notifications(db: Session, *, venue_id: int, target_date: date) -> None:
    members = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
        )
        .order_by(User.id.asc())
    ).scalars().all()
    if not members:
        return

    economics = get_day_economics(db=db, venue_id=venue_id, target_date=target_date)
    alerts = _select_soft_alerts_for_notification(economics)
    if not alerts:
        return

    recipients: list[User] = []
    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    for user in members:
        if not _can_receive_soft_alerts(db, venue_id=venue_id, user=user):
            continue
        user_id = int(user.id)
        tg_user_id = int(user.tg_user_id) if getattr(user, "tg_user_id", None) is not None else None
        if user_id in seen_recipient_ids:
            continue
        if tg_user_id is not None and tg_user_id in seen_tg_user_ids:
            continue
        recipients.append(user)
        seen_recipient_ids.add(user_id)
        if tg_user_id is not None:
            seen_tg_user_ids.add(tg_user_id)
    if not recipients:
        return

    venue_name = _venue_name(db, venue_id)
    link = _build_owner_day_economics_link(venue_id=venue_id, target_date=target_date)
    sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    alert_signature = _soft_alert_signature(alerts)
    had_retryable_error = False
    delivered_any = False

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        idempotency_key = f"soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}:{alert_signature}"
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        text = _build_soft_alerts_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            alerts=alerts,
            detail_level=detail_level,
        )

        pending_log = log_notification_attempt(
            db,
            notification_type="soft_alerts",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text="Открыть экономику дня",
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        delivered_any = delivered_any or ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_retryable_error and not delivered_any:
        raise RuntimeError("soft alerts delivery failed with retryable error")


def _enqueue_day_economics_summary_job(db: Session, *, venue_id: int, target_date: date) -> NotificationJob:
    idempotency_key = f"job:day_economics_summary:{int(venue_id)}:{target_date.isoformat()}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat()}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _claim_notification_job(db: Session) -> NotificationJob | None:
    now = datetime.utcnow()
    stale_before = now - timedelta(minutes=max(int(_NOTIFICATION_JOB_STALE_MINUTES), 1))
    stmt = (
        select(NotificationJob)
        .where(
            sa.or_(
                sa.and_(
                    NotificationJob.status == _NOTIFICATION_JOB_STATUS_PENDING,
                    NotificationJob.run_after <= now,
                ),
                sa.and_(
                    NotificationJob.status == _NOTIFICATION_JOB_STATUS_PROCESSING,
                    NotificationJob.locked_at.is_not(None),
                    NotificationJob.locked_at <= stale_before,
                ),
            )
        )
        .order_by(NotificationJob.run_after.asc(), NotificationJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    job.status = _NOTIFICATION_JOB_STATUS_PROCESSING
    job.locked_at = now
    job.attempts = int(job.attempts or 0) + 1
    job.updated_at = now
    db.flush()
    return job


def _complete_notification_job(db: Session, job: NotificationJob, *, status: str, last_error: str | None = None) -> None:
    now = datetime.utcnow()
    if status == _NOTIFICATION_JOB_STATUS_FAILED and int(job.attempts or 0) < int(job.max_attempts or _NOTIFICATION_JOB_MAX_ATTEMPTS):
        job.status = _NOTIFICATION_JOB_STATUS_PENDING
        job.run_after = now + timedelta(minutes=max(int(_NOTIFICATION_JOB_RETRY_MINUTES), 1))
        job.locked_at = None
        job.last_error = (last_error or None)
        job.updated_at = now
    else:
        job.status = status
        job.processed_at = now
        job.locked_at = None
        job.last_error = (last_error or None)
        job.updated_at = now


def process_pending_notification_jobs_once(limit: int = 10) -> int:
    processed = 0
    hard_limit = max(int(limit or 0), 0)
    if hard_limit <= 0:
        return 0

    while processed < hard_limit:
        with SessionLocal() as db:
            job = _claim_notification_job(db)
            if job is None:
                db.rollback()
                break
            job_id = int(job.id)
            db.commit()

        with SessionLocal() as db:
            job = db.get(NotificationJob, job_id)
            if job is None:
                processed += 1
                continue
            try:
                payload = json.loads(job.payload_json or "{}")
                if job.job_type == _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY:
                    _send_day_economics_summary_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN:
                    _send_salary_day_breakdown_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS:
                    _send_soft_alert_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED:
                    _send_adjustment_assigned_notification(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        adjustment_id=int(payload.get("adjustment_id")),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT:
                    _send_adjustment_dispute_event_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        dispute_id=int(payload.get("dispute_id")),
                        comment_id=int(payload.get("comment_id")),
                        event_kind=str(payload.get("event_kind") or "comment"),
                    )
                else:
                    raise ValueError(f"Unsupported notification job type: {job.job_type}")
                _complete_notification_job(db, job, status=_NOTIFICATION_JOB_STATUS_SENT)
                db.commit()
            except Exception as exc:
                db.rollback()
                with SessionLocal() as retry_db:
                    retry_job = retry_db.get(NotificationJob, job_id)
                    if retry_job is not None:
                        _complete_notification_job(
                            retry_db,
                            retry_job,
                            status=_NOTIFICATION_JOB_STATUS_FAILED,
                            last_error=str(exc)[:2000],
                        )
                        retry_db.commit()
                log.exception("notification job failed id=%s type=%s: %s", job_id, getattr(job, "job_type", None), exc)
            processed += 1

    return processed


def _send_day_economics_summary_notifications(db: Session, *, venue_id: int, target_date: date) -> None:
    members = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
        )
        .order_by(User.id.asc())
    ).scalars().all()
    if not members:
        return

    recipients: list[User] = []
    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    for user in members:
        if not _can_receive_day_economics_summary(db, venue_id=venue_id, user=user):
            continue
        user_id = int(user.id)
        tg_user_id = int(user.tg_user_id) if getattr(user, "tg_user_id", None) is not None else None
        if user_id in seen_recipient_ids:
            continue
        if tg_user_id is not None and tg_user_id in seen_tg_user_ids:
            continue
        recipients.append(user)
        seen_recipient_ids.add(user_id)
        if tg_user_id is not None:
            seen_tg_user_ids.add(tg_user_id)
    if not recipients:
        return

    economics = get_day_economics(db=db, venue_id=venue_id, target_date=target_date)
    venue_name = _venue_name(db, venue_id)
    link = _build_owner_day_economics_link(venue_id=venue_id, target_date=target_date)
    delivered_any = False
    had_retryable_error = False

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        idempotency_key = f"day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}"
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        text = _build_day_economics_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            detail_level=detail_level,
        )

        sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
        pending_log = log_notification_attempt(
            db,
            notification_type="day_economics_summary",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text="Открыть экономику дня",
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        delivered_any = delivered_any or ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_retryable_error and not delivered_any:
        raise RuntimeError("day economics summary delivery failed with retryable error")


