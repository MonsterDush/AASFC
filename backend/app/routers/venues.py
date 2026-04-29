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
from app.core.tg import normalize_tg_username, send_telegram_message
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes
from app.core.permissions_registry import PERMISSIONS
from app.services import tg_notify
from app.services.notification_logs import log_notification_attempt
from app.services.xlsx_export import (
    build_expenses_xlsx,
    build_monthly_summary_xlsx,
    build_payroll_xlsx,
    build_revenue_csv,
    build_revenue_xlsx,
)
from app.services.signed_links import make_signed_token, verify_signed_token
from app.services.finance.expenses import rebuild_expense_allocations_for_expense, delete_expense_allocations_for_expense, list_expense_allocations
from app.services.finance.revenue import rebuild_revenue_entries_for_report, delete_revenue_entries_for_report, compute_revenue_summary
from app.services.finance.summary import get_day_finance_summary, get_finance_summary, get_monthly_finance_summary
from app.services.finance.day_economics import (
    copy_day_economics_month_plan_from_previous_month,
    copy_day_economics_plan_templates,
    get_day_economics,
    get_day_economics_plan,
    get_day_economics_plan_override,
    get_day_economics_month_plan,
    get_venue_economics_rules,
    list_day_economics_plan_templates,
    list_department_day_plans,
    list_department_month_plans,
    autofill_department_day_plans_from_history,
    autofill_department_month_plans_from_last_month,
    copy_department_day_plans_from_date,
    distribute_department_month_plans_from_venue_plan,
    upsert_department_day_plans,
    upsert_department_month_plans,
    upsert_day_economics_month_plan,
    upsert_day_economics_plan,
    upsert_day_economics_plan_template,
    upsert_venue_economics_rules,
)
from app.services.finance.balance_adjustments import rebuild_balance_adjustment_entries, delete_balance_adjustment_entries
from app.services.finance.payment_transfers import rebuild_payment_method_transfer_entries, delete_payment_method_transfer_entries
from app.services.finance.recurring_expenses import (
    delete_daily_recurring_accruals_for_date,
    generate_draft_expenses_for_month,
    list_rule_payment_method_ids,
    normalize_rule_fields,
    replace_rule_payment_methods,
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
    calculate_payroll_for_month,
    parse_month_start,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.services.payroll.period_summary import resolve_salary_period
from app.services.tips import build_equal_tip_allocations, build_weighted_by_position_tip_allocations

from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_invite import VenueInvite
from app.models.venue_position import VenuePosition
from app.models.shift_interval import ShiftInterval
from app.models.shift import Shift
from app.models.shift_comment import ShiftComment
from app.models.shift_assignment import ShiftAssignment
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
from app.services.shifts.slots import normalize_shift_slot

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
}
_SCHEDULE_SHARE_TTL_SECONDS = int(os.getenv("SCHEDULE_SHARE_TTL_SECONDS", "604800"))


_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalize_code(code: str) -> str:
    c = (code or "").strip().lower().replace(" ", "_")
    if not _CODE_RE.match(c):
        raise HTTPException(
            status_code=400,
            detail="Bad code format. Use латиницу/цифры и символы _- (пример: hookah, cashless, fruit_bowl)",
        )
    return c

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


class DepartmentPlanItemIn(BaseModel):
    department_id: int = Field(..., gt=0)
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class DepartmentPlanBulkIn(BaseModel):
    items: list[DepartmentPlanItemIn] = Field(default_factory=list)


class DepartmentPlanItemOut(BaseModel):
    department_id: int
    department_title: str
    department_code: str | None = None
    month: str | None = None
    date: str | None = None
    revenue_plan_minor: int | None = None
    notes: str | None = None
    actual_current_minor: int = 0
    actual_previous_minor: int | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DepartmentPlanMonthOut(BaseModel):
    month: str
    items: list[DepartmentPlanItemOut] = Field(default_factory=list)
    department_count: int = 0
    saved_count: int | None = None
    deleted_count: int | None = None


class DepartmentPlanDayOut(BaseModel):
    date: str
    items: list[DepartmentPlanItemOut] = Field(default_factory=list)
    department_count: int = 0
    saved_count: int | None = None
    deleted_count: int | None = None


class DepartmentPlanCopyOut(BaseModel):
    copied: int = 0
    skipped: int = 0
    copied_from_date: str | None = None
    plan: DepartmentPlanDayOut


class DepartmentPlanAutofillOut(BaseModel):
    copied: int = 0
    skipped: int = 0
    copied_from_month: str | None = None
    distributed_total_minor: int | None = None
    mode: str | None = None
    lookback_weeks: int | None = None
    used_source_dates: list[str] = Field(default_factory=list)
    used_points: int | None = None
    plan: dict


class PayrollCalculateIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="YYYY-MM")


class ReportValueIn(BaseModel):
    ref_id: int = Field(..., ge=1)
    value: int = Field(0, ge=0)


class DailyReportUpsertIn(BaseModel):
    date: date
    shift_slot: str | None = None

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




class CatalogItemCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class CatalogItemUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class KpiMetricCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    unit: str = Field("QTY", min_length=1, max_length=24)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class KpiMetricUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class SupplierCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class SupplierUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ExpenseCreateIn(BaseModel):
    category_id: int = Field(..., gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    amount_minor: int = Field(..., ge=0)
    expense_date: date
    spread_months: int = Field(1, ge=1, le=120)
    status: str = Field('DRAFT', min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class ExpenseUpdateIn(BaseModel):
    category_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    clear_supplier: bool = False
    clear_payment_method: bool = False
    amount_minor: int | None = Field(default=None, ge=0)
    expense_date: date | None = None
    spread_months: int | None = Field(default=None, ge=1, le=120)
    status: str | None = Field(default=None, min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class FinanceSummaryOut(BaseModel):
    month: str | None = None
    period_start: date
    period_end: date
    revenue_minor: int
    expense_minor: int
    expense_without_payroll_minor: int | None = None
    payroll_minor: int
    payroll_expense_minor: int | None = None
    total_cost_minor: int | None = None
    adjustments_minor: int
    refunds_minor: int
    profit_minor: int
    margin_bps: int | None = None
    expense_ratio_bps: int | None = None
    payroll_ratio_bps: int | None = None
    total_cost_ratio_bps: int | None = None


class MonthlyFinanceBreakdownRowOut(BaseModel):
    title: str
    code: str | None = None
    subtitle: str | None = None
    amount_minor: int


class PaymentMethodBalanceRowOut(BaseModel):
    payment_method_id: int
    title: str
    code: str | None = None
    inflow_minor: int
    outflow_minor: int
    balance_minor: int


class MonthlyFinanceSummaryOut(FinanceSummaryOut):
    income_mode: str
    revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    expense_categories: list[MonthlyFinanceBreakdownRowOut]
    payment_method_balances: list[PaymentMethodBalanceRowOut]
    draft_expense_count: int = 0
    draft_expense_total_minor: int = 0


class DailyFinanceSummaryOut(FinanceSummaryOut):
    date: date
    income_mode: str
    shift_slot: str = "TOTAL"
    slot_costs_available: bool = True
    revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    point_expenses: list[MonthlyFinanceBreakdownRowOut]
    point_expense_minor: int
    recurring_expenses: list[MonthlyFinanceBreakdownRowOut]
    recurring_expense_minor: int
    payment_method_balances: list[PaymentMethodBalanceRowOut]
    draft_expense_count: int = 0
    draft_expense_total_minor: int = 0

class DayEconomicsReportOut(BaseModel):
    exists: bool
    report_id: int | None = None
    status: str
    shift_slot: str = "TOTAL"
    closed_at: datetime | None = None
    closed_by_user_id: int | None = None
    comment: str | None = None
    revenue_total_minor: int = 0
    tips_total_minor: int = 0


class DayEconomicsTeamOut(BaseModel):
    total_shift_count: int = 0
    assignment_count: int = 0
    assigned_user_count: int = 0
    assigned_shift_count: int = 0
    unassigned_shift_count: int = 0


class DayEconomicsMetricsOut(BaseModel):
    result_status: str
    revenue_per_assigned_minor: int | None = None
    tips_per_assigned_minor: int | None = None
    profit_per_assigned_minor: int | None = None
    revenue_per_shift_minor: int | None = None
    profit_per_shift_minor: int | None = None
    assignments_per_shift: float | None = None
    assigned_shift_coverage_bps: int | None = None
    expense_ratio_bps: int | None = None
    point_expense_ratio_bps: int | None = None
    recurring_expense_ratio_bps: int | None = None
    payroll_ratio_bps: int | None = None
    top_department_title: str | None = None
    top_department_share_bps: int | None = None
    kpi_metric_count: int = 0
    nonzero_kpi_metric_count: int = 0
    kpi_total_value_numeric: int = 0


class DepartmentShareRowOut(MonthlyFinanceBreakdownRowOut):
    share_bps: int | None = None


class KpiFactRowOut(BaseModel):
    metric_id: int
    title: str
    code: str | None = None
    unit: str
    value_numeric: int


class KpiSummaryOut(BaseModel):
    metric_count: int = 0
    nonzero_metric_count: int = 0
    total_value_numeric: int = 0


class DayEconomicsPlanOut(BaseModel):
    date: date
    source: str = 'NONE'
    template_weekday: int | None = None
    template_weekday_title: str | None = None
    template_month: str | None = None
    template_month_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    day_kind: str | None = None
    day_kind_title: str | None = None
    title: str | None = None
    notes: str | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DayEconomicsPlanIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    day_kind: str | None = Field(default=None, min_length=0, max_length=16)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)


class DayEconomicsPlanTemplateOut(BaseModel):
    weekday: int
    weekday_title: str
    date: date
    source: str = 'WEEKDAY_TEMPLATE'
    template_weekday: int | None = None
    template_weekday_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    notes: str | None = None


class DayEconomicsPlanTemplateIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)




class DayEconomicsMonthPlanOut(BaseModel):
    month: str
    source: str = 'MONTH_TEMPLATE'
    template_month: str | None = None
    template_month_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    notes: str | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DayEconomicsMonthPlanIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class DayEconomicsMonthPlanCopyOut(BaseModel):
    copied: bool
    copied_from_month: str
    plan: DayEconomicsMonthPlanOut


class DayEconomicsTemplateCopyIn(BaseModel):
    source_weekday: int = Field(..., ge=0, le=6)
    target_weekdays: list[int] = Field(default_factory=list)
    overwrite: bool = True


class DayEconomicsTemplateCopyOut(BaseModel):
    source_weekday: int
    source_weekday_title: str
    copied_count: int
    copied: list[DayEconomicsPlanTemplateOut]
    skipped_count: int
    skipped: list[dict]


class VenueEconomicsRulesOut(BaseModel):
    max_expense_ratio_bps: int | None = None
    max_payroll_ratio_bps: int | None = None
    min_revenue_per_assigned_minor: int | None = None
    min_assigned_shift_coverage_bps: int | None = None
    min_profit_minor: int | None = None
    warn_on_draft_expenses: bool = True


class VenueEconomicsRulesIn(BaseModel):
    max_expense_ratio_bps: int | None = Field(default=None, ge=0)
    max_payroll_ratio_bps: int | None = Field(default=None, ge=0)
    min_revenue_per_assigned_minor: int | None = Field(default=None, ge=0)
    min_assigned_shift_coverage_bps: int | None = Field(default=None, ge=0, le=10000)
    min_profit_minor: int | None = None
    warn_on_draft_expenses: bool = True


class DayEconomicsPlanFactOut(BaseModel):
    revenue_fact_minor: int
    revenue_plan_minor: int | None = None
    revenue_delta_minor: int | None = None
    revenue_progress_bps: int | None = None
    profit_fact_minor: int
    profit_plan_minor: int | None = None
    profit_delta_minor: int | None = None
    revenue_per_assigned_fact_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    revenue_per_assigned_delta_minor: int | None = None
    assigned_user_fact: int = 0
    assigned_user_target: int | None = None
    assigned_user_delta: int | None = None


class DayEconomicsAlertOut(BaseModel):
    severity: str
    code: str
    title: str
    detail: str


class DayEconomicsRollupDayOut(BaseModel):
    date: date
    profit_minor: int
    revenue_minor: int


class DayEconomicsRollupOut(BaseModel):
    month: str
    days_in_period: int
    evaluated_day_count: int
    closed_day_count: int
    profit_total_minor: int
    avg_profit_minor: int | None = None
    avg_revenue_per_assigned_minor: int | None = None
    profitable_day_count: int = 0
    loss_day_count: int = 0
    best_day: DayEconomicsRollupDayOut | None = None
    worst_day: DayEconomicsRollupDayOut | None = None


class DayEconomicsOut(BaseModel):
    date: date
    shift_slot: str = "TOTAL"
    report: DayEconomicsReportOut
    team: DayEconomicsTeamOut
    metrics: DayEconomicsMetricsOut
    summary: DailyFinanceSummaryOut
    payment_revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    department_revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    department_share_breakdown: list[DepartmentShareRowOut]
    kpi_breakdown: list[KpiFactRowOut]
    kpi_summary: KpiSummaryOut
    plan: DayEconomicsPlanOut
    rules: VenueEconomicsRulesOut
    plan_fact: DayEconomicsPlanFactOut
    alerts: list[DayEconomicsAlertOut]
    rollup: DayEconomicsRollupOut



class BalanceAdjustmentCreateIn(BaseModel):
    payment_method_id: int = Field(..., gt=0)
    adjustment_date: date
    delta_minor: int
    status: str = Field('CONFIRMED', min_length=5, max_length=16)
    reason: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=1000)


class BalanceAdjustmentUpdateIn(BaseModel):
    payment_method_id: int | None = Field(default=None, gt=0)
    adjustment_date: date | None = None
    delta_minor: int | None = None
    status: str | None = Field(default=None, min_length=5, max_length=16)
    reason: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=1000)


class PaymentMethodTransferCreateIn(BaseModel):
    from_payment_method_id: int = Field(..., gt=0)
    to_payment_method_id: int = Field(..., gt=0)
    transfer_date: date
    amount_minor: int = Field(..., gt=0)
    status: str = Field('CONFIRMED', min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class PaymentMethodTransferUpdateIn(BaseModel):
    from_payment_method_id: int | None = Field(default=None, gt=0)
    to_payment_method_id: int | None = Field(default=None, gt=0)
    transfer_date: date | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class RecurringExpenseRuleCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    category_id: int = Field(..., gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    is_active: bool = True
    start_date: date
    end_date: date | None = None
    frequency: str = Field('MONTHLY', min_length=7, max_length=16)
    day_of_month: int = Field(1, ge=1, le=31)
    generation_mode: str = Field('FIXED', min_length=4, max_length=16)
    amount_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    spread_months: int = Field(1, ge=1, le=120)
    description: str | None = Field(default=None, max_length=1000)
    payment_method_ids: list[int] = Field(default_factory=list)


class RecurringExpenseRuleUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    clear_supplier: bool = False
    clear_payment_method: bool = False
    is_active: bool | None = None
    start_date: date | None = None
    end_date: date | None = None
    clear_end_date: bool = False
    frequency: str | None = Field(default=None, min_length=7, max_length=16)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    generation_mode: str | None = Field(default=None, min_length=4, max_length=16)
    amount_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    spread_months: int | None = Field(default=None, ge=1, le=120)
    description: str | None = Field(default=None, max_length=1000)
    payment_method_ids: list[int] | None = None


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


class ShiftCreateIn(BaseModel):
    date: date
    interval_id: int = Field(..., gt=0)
    is_active: bool = True
    shift_slot: str = "DAY"


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

    if not m or str(m.venue_role or "").upper() != "OWNER":
        return False

    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role="OWNER")
    return access.get("billing_access_mode") == BILLING_ACCESS_FULL


def _require_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")
    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role="OWNER")
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        raise HTTPException(status_code=403, detail=access.get("billing_restricted_reason") or "Доступ к заведению ограничен из-за статуса подписки")


def _can_manage_staff(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    return has_venue_permission(db, venue_id=venue_id, user=user, permission_code="STAFF_MANAGE")


def _require_staff_manage_or_owner_or_super_admin(db: Session, *, venue_id: int, user: User) -> None:
    if not _can_manage_staff(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> bool:
    if user.system_role in ("SUPER_ADMIN", "MODERATOR"):
        return True
    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if not m:
        return False
    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=str(m.venue_role or ""))
    return access.get("billing_access_mode") == BILLING_ACCESS_FULL


def _require_active_member_or_admin(db: Session, *, venue_id: int, user: User) -> None:
    if user.system_role in ("SUPER_ADMIN", "MODERATOR"):
        return
    m = db.query(VenueMember).filter(
        VenueMember.venue_id == venue_id,
        VenueMember.user_id == user.id,
        VenueMember.is_active.is_(True),
    ).one_or_none()
    if not m:
        raise HTTPException(status_code=403, detail="Forbidden")
    access = get_user_billing_access(db, venue_id=venue_id, user=user, membership_role=str(m.venue_role or ""))
    if access.get("billing_access_mode") != BILLING_ACCESS_FULL:
        raise HTTPException(status_code=403, detail=access.get("billing_restricted_reason") or "Доступ к заведению ограничен из-за статуса подписки")


def _get_expense_category_or_404(db: Session, *, venue_id: int, category_id: int) -> ExpenseCategory:
    obj = db.execute(
        select(ExpenseCategory).where(ExpenseCategory.id == category_id, ExpenseCategory.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense category not found")
    return obj


def _get_supplier_or_404(db: Session, *, venue_id: int, supplier_id: int) -> Supplier:
    obj = db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return obj


def _get_payment_method_or_404(db: Session, *, venue_id: int, payment_method_id: int) -> PaymentMethod:
    obj = db.execute(
        select(PaymentMethod).where(PaymentMethod.id == payment_method_id, PaymentMethod.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return obj


def _serialize_expense_allocation(allocation: ExpenseAllocation) -> dict:
    return {
        "id": allocation.id,
        "expense_id": allocation.expense_id,
        "venue_id": allocation.venue_id,
        "month": allocation.month.isoformat() if allocation.month else None,
        "amount_minor": int(allocation.amount_minor or 0),
        "created_at": allocation.created_at.isoformat() if allocation.created_at else None,
    }


def _serialize_expense(
    expense: Expense,
    category: ExpenseCategory | None = None,
    supplier: Supplier | None = None,
    payment_method: PaymentMethod | None = None,
    allocations: list[ExpenseAllocation] | None = None,
) -> dict:
    cat = category or getattr(expense, "category", None)
    sup = supplier or getattr(expense, "supplier", None)
    pm = payment_method or getattr(expense, "payment_method", None)
    allocs = allocations if allocations is not None else list(getattr(expense, "allocations", []) or [])
    return {
        "id": expense.id,
        "venue_id": expense.venue_id,
        "category_id": expense.category_id,
        "supplier_id": expense.supplier_id,
        "payment_method_id": expense.payment_method_id,
        "recurring_rule_id": expense.recurring_rule_id,
        "amount_minor": int(expense.amount_minor or 0),
        "expense_date": expense.expense_date.isoformat() if expense.expense_date else None,
        "generated_for_month": expense.generated_for_month.isoformat() if expense.generated_for_month else None,
        "spread_months": int(expense.spread_months or 1),
        "status": str(getattr(expense, 'status', 'CONFIRMED') or 'CONFIRMED').upper(),
        "comment": expense.comment,
        "created_by_user_id": expense.created_by_user_id,
        "created_at": expense.created_at.isoformat() if expense.created_at else None,
        "updated_at": expense.updated_at.isoformat() if expense.updated_at else None,
        "category": {
            "id": cat.id,
            "code": cat.code,
            "title": cat.title,
        } if cat is not None else None,
        "supplier": {
            "id": sup.id,
            "title": sup.title,
            "contact": sup.contact,
        } if sup is not None else None,
        "payment_method": {
            "id": pm.id,
            "code": pm.code,
            "title": pm.title,
        } if pm is not None else None,
        "allocations": [_serialize_expense_allocation(a) for a in allocs],
    }


def _serialize_balance_adjustment(adjustment: BalanceAdjustment, payment_method: PaymentMethod | None = None) -> dict:
    pm = payment_method or getattr(adjustment, 'payment_method', None)
    return {
        'id': adjustment.id,
        'venue_id': adjustment.venue_id,
        'payment_method_id': adjustment.payment_method_id,
        'adjustment_date': adjustment.adjustment_date.isoformat() if adjustment.adjustment_date else None,
        'delta_minor': int(adjustment.delta_minor or 0),
        'status': str(getattr(adjustment, 'status', 'CONFIRMED') or 'CONFIRMED').upper(),
        'reason': adjustment.reason,
        'comment': adjustment.comment,
        'created_by_user_id': adjustment.created_by_user_id,
        'created_at': adjustment.created_at.isoformat() if adjustment.created_at else None,
        'updated_at': adjustment.updated_at.isoformat() if adjustment.updated_at else None,
        'payment_method': {
            'id': pm.id,
            'code': pm.code,
            'title': pm.title,
        } if pm is not None else None,
    }


def _serialize_payment_method_transfer(
    transfer: PaymentMethodTransfer,
    from_payment_method: PaymentMethod | None = None,
    to_payment_method: PaymentMethod | None = None,
) -> dict:
    from_pm = from_payment_method or getattr(transfer, 'from_payment_method', None)
    to_pm = to_payment_method or getattr(transfer, 'to_payment_method', None)
    return {
        'id': transfer.id,
        'venue_id': transfer.venue_id,
        'from_payment_method_id': transfer.from_payment_method_id,
        'to_payment_method_id': transfer.to_payment_method_id,
        'transfer_date': transfer.transfer_date.isoformat() if transfer.transfer_date else None,
        'amount_minor': int(transfer.amount_minor or 0),
        'status': str(getattr(transfer, 'status', 'CONFIRMED') or 'CONFIRMED').upper(),
        'comment': transfer.comment,
        'created_by_user_id': transfer.created_by_user_id,
        'created_at': transfer.created_at.isoformat() if transfer.created_at else None,
        'updated_at': transfer.updated_at.isoformat() if transfer.updated_at else None,
        'from_payment_method': {
            'id': from_pm.id,
            'code': from_pm.code,
            'title': from_pm.title,
        } if from_pm is not None else None,
        'to_payment_method': {
            'id': to_pm.id,
            'code': to_pm.code,
            'title': to_pm.title,
        } if to_pm is not None else None,
    }


def _serialize_finance_entry(
    entry: FinanceEntry,
    payment_method: PaymentMethod | None = None,
    department: Department | None = None,
) -> dict:
    pm = payment_method or getattr(entry, 'payment_method', None)
    dept = department or getattr(entry, 'department', None)
    return {
        'id': entry.id,
        'venue_id': entry.venue_id,
        'entry_date': entry.entry_date.isoformat() if entry.entry_date else None,
        'amount_minor': int(entry.amount_minor or 0),
        'direction': str(entry.direction or '').upper(),
        'kind': str(entry.kind or '').upper(),
        'source_type': str(entry.source_type or '').lower(),
        'source_id': int(entry.source_id) if entry.source_id is not None else None,
        'meta_json': entry.meta_json or None,
        'payment_method': {
            'id': pm.id,
            'code': pm.code,
            'title': pm.title,
        } if pm is not None else None,
        'department': {
            'id': dept.id,
            'code': dept.code,
            'title': dept.title,
        } if dept is not None else None,
        'created_at': entry.created_at.isoformat() if entry.created_at else None,
    }


def _serialize_recurring_expense_rule(
    rule: RecurringExpenseRule,
    category: ExpenseCategory | None = None,
    supplier: Supplier | None = None,
    payment_method: PaymentMethod | None = None,
    basis_payment_methods: list[PaymentMethod] | None = None,
) -> dict:
    cat = category or getattr(rule, "category", None)
    sup = supplier or getattr(rule, "supplier", None)
    pm = payment_method or getattr(rule, "payment_method", None)
    basis = basis_payment_methods
    if basis is None:
        basis = [getattr(link, "payment_method", None) for link in (getattr(rule, "payment_method_links", []) or [])]
        basis = [x for x in basis if x is not None]
    return {
        "id": rule.id,
        "venue_id": rule.venue_id,
        "title": rule.title,
        "category_id": rule.category_id,
        "supplier_id": rule.supplier_id,
        "payment_method_id": rule.payment_method_id,
        "is_active": bool(rule.is_active),
        "start_date": rule.start_date.isoformat() if rule.start_date else None,
        "end_date": rule.end_date.isoformat() if rule.end_date else None,
        "frequency": str(rule.frequency or "MONTHLY").upper(),
        "day_of_month": int(rule.day_of_month or 1),
        "generation_mode": str(rule.generation_mode or "FIXED").upper(),
        "amount_minor": int(rule.amount_minor or 0) if rule.amount_minor is not None else None,
        "percent_bps": int(rule.percent_bps or 0) if rule.percent_bps is not None else None,
        "spread_months": int(rule.spread_months or 1),
        "description": rule.description,
        "created_by_user_id": rule.created_by_user_id,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        "category": {
            "id": cat.id, "code": cat.code, "title": cat.title,
        } if cat is not None else None,
        "supplier": {
            "id": sup.id, "title": sup.title, "contact": sup.contact,
        } if sup is not None else None,
        "payment_method": {
            "id": pm.id, "code": pm.code, "title": pm.title,
        } if pm is not None else None,
        "basis_payment_methods": [
            {"id": item.id, "code": item.code, "title": item.title}
            for item in basis
        ],
        "payment_method_ids": [int(item.id) for item in basis],
    }


def _require_recurring_expenses_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="RECURRING_EXPENSES_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")


def _require_recurring_expenses_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="RECURRING_EXPENSES_MANAGE")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")


def _require_finance_ledger_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="FINANCE_LEDGER_VIEW")
        return
    except HTTPException:
        pass
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")



def _require_payment_transfers_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_TRANSFERS_MANAGE")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")


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


def _is_report_viewer(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True

    # Permission-based (preferred)
    for code in ("SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"):
        try:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
            return True
        except HTTPException:
            pass

    return False


def _require_report_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _is_report_viewer(db, venue_id=venue_id, user=user):
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

def _has_revenue_view_access(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW")
        return True
    except HTTPException:
        return False


def _require_revenue_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _has_revenue_view_access(db, venue_id=venue_id, user=user):
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
    if minimum_guarantee_scope is not None and raw_minimum_scope not in {MINIMUM_GUARANTEE_MONTH, MINIMUM_GUARANTEE_DAY}:
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



def _empty_usage_counts() -> dict:
    return {"usage_component_count": 0, "usage_profile_count": 0}


def _build_percent_boost_usage_map(db: Session, *, venue_id: int) -> dict:
    rows = db.execute(
        select(
            PayComponent.boost_source_type,
            PayComponent.boost_department_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type.in_(["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"]),
            PayComponent.boost_enabled.is_(True),
            PayComponent.boost_percent_bps.is_not(None),
            PayComponent.boost_source_type.in_(
                [
                    BOOST_SOURCE_VENUE_MONTH_PLAN,
                    BOOST_SOURCE_VENUE_DAY_PLAN,
                    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
                    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
                ]
            ),
        )
        .group_by(PayComponent.boost_source_type, PayComponent.boost_department_id)
    ).all()
    result = {
        BOOST_SOURCE_VENUE_MONTH_PLAN: _empty_usage_counts(),
        BOOST_SOURCE_VENUE_DAY_PLAN: _empty_usage_counts(),
        BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: {},
        BOOST_SOURCE_DEPARTMENT_DAY_PLAN: {},
    }
    for source_type, department_id, component_count, profile_count in rows:
        source_key = str(source_type or '').strip().upper()
        payload = {
            "usage_component_count": int(component_count or 0),
            "usage_profile_count": int(profile_count or 0),
        }
        if source_key in {BOOST_SOURCE_VENUE_MONTH_PLAN, BOOST_SOURCE_VENUE_DAY_PLAN}:
            result[source_key] = payload
        elif source_key in {BOOST_SOURCE_DEPARTMENT_MONTH_PLAN, BOOST_SOURCE_DEPARTMENT_DAY_PLAN}:
            dep_id = int(department_id or 0)
            if dep_id > 0:
                result[source_key][dep_id] = payload
    return result


def _build_kpi_usage_map(db: Session, *, venue_id: int) -> dict[int, dict]:
    result: dict[int, dict] = {}

    bonus_rows = db.execute(
        select(
            PayComponent.kpi_metric_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type == "KPI_BONUS",
            PayComponent.kpi_metric_id.is_not(None),
        )
        .group_by(PayComponent.kpi_metric_id)
    ).all()
    for metric_id, component_count, profile_count in bonus_rows:
        key = int(metric_id or 0)
        if key <= 0:
            continue
        bucket = result.setdefault(key, {
            "usage_component_count": 0,
            "usage_bonus_component_count": 0,
            "usage_boost_component_count": 0,
            "usage_bonus_profile_count": 0,
            "usage_boost_profile_count": 0,
        })
        bucket["usage_component_count"] += int(component_count or 0)
        bucket["usage_bonus_component_count"] += int(component_count or 0)
        bucket["usage_bonus_profile_count"] += int(profile_count or 0)

    boost_rows = db.execute(
        select(
            PayComponent.boost_kpi_metric_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type.in_(["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"]),
            PayComponent.boost_enabled.is_(True),
            PayComponent.boost_source_type == BOOST_SOURCE_KPI_METRIC,
            PayComponent.boost_kpi_metric_id.is_not(None),
        )
        .group_by(PayComponent.boost_kpi_metric_id)
    ).all()
    for metric_id, component_count, profile_count in boost_rows:
        key = int(metric_id or 0)
        if key <= 0:
            continue
        bucket = result.setdefault(key, {
            "usage_component_count": 0,
            "usage_bonus_component_count": 0,
            "usage_boost_component_count": 0,
            "usage_bonus_profile_count": 0,
            "usage_boost_profile_count": 0,
        })
        bucket["usage_component_count"] += int(component_count or 0)
        bucket["usage_boost_component_count"] += int(component_count or 0)
        bucket["usage_boost_profile_count"] += int(profile_count or 0)

    return result


def _attach_usage_to_day_plan(plan: dict, usage_counts: dict | None) -> dict:
    payload = dict(plan or {})
    counts = usage_counts or _empty_usage_counts()
    payload["usage_component_count"] = int(counts.get("usage_component_count", 0) or 0)
    payload["usage_profile_count"] = int(counts.get("usage_profile_count", 0) or 0)
    return payload


def _attach_usage_to_department_plan_payload(payload: dict, usage_map: dict[int, dict] | None) -> dict:
    result = dict(payload or {})
    items = []
    for item in list(result.get("items") or []):
        row = dict(item or {})
        dep_id = int(row.get("department_id") or 0)
        counts = (usage_map or {}).get(dep_id) or _empty_usage_counts()
        row["usage_component_count"] = int(counts.get("usage_component_count", 0) or 0)
        row["usage_profile_count"] = int(counts.get("usage_profile_count", 0) or 0)
        items.append(row)
    result["items"] = items
    return result


def _usage_counts_for_effective_plan(plan: dict, usage_map: dict) -> dict:
    source = str((plan or {}).get("source") or "").strip().upper()
    if source == "DATE_OVERRIDE":
        return dict((usage_map or {}).get(BOOST_SOURCE_VENUE_DAY_PLAN) or _empty_usage_counts())
    if source == "MONTH_TEMPLATE":
        return dict((usage_map or {}).get(BOOST_SOURCE_VENUE_MONTH_PLAN) or _empty_usage_counts())
    return _empty_usage_counts()


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


@router.get("/{venue_id}/positions")
def list_positions(
    venue_id: int,
    include_inactive: bool = Query(False, description="If true, return inactive members/positions too (requires manage)."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_schedule_editor(db, venue_id=venue_id, user=user)
    if not allowed:
        for code in ("POSITIONS_VIEW", "POSITIONS_MANAGE", "SHIFTS_VIEW", "SHIFTS_MANAGE"):
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
                allowed = True
                break
            except HTTPException:
                pass
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    if include_inactive:
        manage_ok = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
        if not manage_ok:
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")
                manage_ok = True
            except HTTPException:
                manage_ok = False
        if not manage_ok:
            raise HTTPException(status_code=403, detail="Forbidden")

    stmt = (
        select(
            VenuePosition.id,
            VenuePosition.title,
            VenuePosition.member_user_id,
            VenuePosition.rate,
            VenuePosition.percent,
            VenuePosition.permission_codes,
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

    items = []
    for r in rows:
        assignment, profile = _get_member_active_pay_profile_assignment(db, venue_id=venue_id, member_user_id=int(r.member_user_id), on_date=date.today())
        items.append({
            "id": r.id,
            "title": r.title,
            "member_user_id": r.member_user_id,
            "rate": r.rate,
            "percent": r.percent,
            "pay_profile_id": int(profile.id) if profile is not None else None,
            "pay_profile_title": profile.title if profile is not None else None,
            "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None,
            "permission_codes": _parse_position_permission_codes(getattr(r, "permission_codes", None)),
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
        })
    return items


@router.post("/{venue_id}/positions")
def create_position(
    venue_id: int,
    payload: PositionCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    # Setting permission codes requires POSITION_PERMISSIONS_MANAGE
    if payload.permission_codes is not None and not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITION_PERMISSIONS_MANAGE")

    codes_provided = payload.permission_codes is not None
    norm_codes = _normalize_permission_codes(db, payload.permission_codes or []) if codes_provided else []

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

    if payload.pay_profile_id is not None and not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")

    if existing is None:
        pos = VenuePosition(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            title=payload.title.strip(),
            rate=payload.rate,
            percent=payload.percent,
            permission_codes=json.dumps(norm_codes),
            is_active=payload.is_active,
        )
        db.add(pos)
        db.flush()
        assignment, profile = _sync_member_pay_profile_assignment(
            db,
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            pay_profile_id=payload.pay_profile_id,
        )
        db.commit()
        db.refresh(pos)
        return {"id": pos.id, "pay_profile_id": int(profile.id) if profile is not None else None, "pay_profile_title": profile.title if profile is not None else None, "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None}

    # update-in-place
    existing.title = payload.title.strip()
    existing.rate = payload.rate
    existing.percent = payload.percent
    if codes_provided:
        existing.permission_codes = json.dumps(norm_codes)
    existing.is_active = payload.is_active
    assignment, profile = _sync_member_pay_profile_assignment(
        db,
        venue_id=venue_id,
        member_user_id=payload.member_user_id,
        pay_profile_id=payload.pay_profile_id,
    )

    db.commit()
    return {"id": existing.id, "mode": "updated", "pay_profile_id": int(profile.id) if profile is not None else None, "pay_profile_title": profile.title if profile is not None else None, "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None}


@router.patch("/{venue_id}/positions/{position_id}")
def update_position(
    venue_id: int,
    position_id: int,
    payload: PositionUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    is_owner = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
    if not is_owner:
        # General editing of position requires POSITIONS_MANAGE
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    # Changing member assignment is a separate permission
    if payload.member_user_id is not None and payload.member_user_id != pos.member_user_id:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")

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

    # Editing permission codes is a separate permission (matrix)
    codes_provided = payload.permission_codes is not None
    norm_codes: list[str] | None = None
    perms_changed = False
    if codes_provided:
        norm_codes = _normalize_permission_codes(db, payload.permission_codes or [])
        current = set(_parse_position_permission_codes(getattr(pos, "permission_codes", None)))
        incoming = set(norm_codes)
        perms_changed = current != incoming

    if perms_changed and not is_owner:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITION_PERMISSIONS_MANAGE")

    if payload.title is not None:
        pos.title = payload.title.strip()
    if payload.rate is not None:
        pos.rate = payload.rate
    if payload.percent is not None:
        pos.percent = payload.percent
    if payload.is_active is not None:
        pos.is_active = payload.is_active

    if perms_changed:
        pos.permission_codes = json.dumps(norm_codes or [])

    assignment = None
    profile = None
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "pay_profile_id" in fields_set:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")
        assignment, profile = _sync_member_pay_profile_assignment(
            db,
            venue_id=venue_id,
            member_user_id=pos.member_user_id,
            pay_profile_id=payload.pay_profile_id,
        )
    else:
        assignment, profile = _get_member_active_pay_profile_assignment(db, venue_id=venue_id, member_user_id=pos.member_user_id, on_date=date.today())

    db.commit()
    db.refresh(pos)

    return {
        "ok": True,
        "id": pos.id,
        "title": pos.title,
        "member_user_id": pos.member_user_id,
        "rate": pos.rate,
        "percent": pos.percent,
        "pay_profile_id": int(profile.id) if profile is not None else None,
        "pay_profile_title": profile.title if profile is not None else None,
        "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None,
        "permission_codes": _parse_position_permission_codes(getattr(pos, "permission_codes", None)),
        "is_active": bool(pos.is_active),
    }


@router.delete("/{venue_id}/positions/{position_id}")
def delete_position(
    venue_id: int,
    position_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    pos.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/pay-profiles")
def list_pay_profiles(
    venue_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_view(db, venue_id=venue_id, user=user)

    stmt = select(PayProfile).where(PayProfile.venue_id == venue_id).order_by(PayProfile.is_active.desc(), PayProfile.title.asc(), PayProfile.id.asc())
    if not include_inactive:
        stmt = stmt.where(PayProfile.is_active.is_(True))
    profiles = db.execute(stmt).scalars().all()
    profile_ids = [int(profile.id) for profile in profiles]

    components_counts = {
        int(profile_id): int(count or 0)
        for profile_id, count in db.execute(
            select(PayComponent.pay_profile_id, func.count(PayComponent.id))
            .where(PayComponent.venue_id == venue_id, PayComponent.pay_profile_id.in_(profile_ids) if profile_ids else sa.true())
            .group_by(PayComponent.pay_profile_id)
        ).all()
    } if profile_ids else {}

    assignments_counts = {
        int(profile_id): int(count or 0)
        for profile_id, count in db.execute(
            select(PayProfileAssignment.pay_profile_id, func.count(PayProfileAssignment.id))
            .where(PayProfileAssignment.venue_id == venue_id, PayProfileAssignment.pay_profile_id.in_(profile_ids) if profile_ids else sa.true())
            .group_by(PayProfileAssignment.pay_profile_id)
        ).all()
    } if profile_ids else {}

    return [
        _serialize_pay_profile(
            profile,
            components_count=components_counts.get(int(profile.id), 0),
            assignments_count=assignments_counts.get(int(profile.id), 0),
        )
        for profile in profiles
    ]


@router.get("/{venue_id}/pay-profiles/{profile_id}")
def get_pay_profile(
    venue_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_view(db, venue_id=venue_id, user=user)
    return _load_pay_profile_detail(db, venue_id=venue_id, profile_id=profile_id)


@router.post("/{venue_id}/pay-profiles")
def create_pay_profile(
    venue_id: int,
    payload: PayProfileCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = PayProfile(
        venue_id=venue_id,
        title=payload.title.strip(),
        description=(payload.description or None),
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _serialize_pay_profile(profile, components_count=0, assignments_count=0)


@router.patch("/{venue_id}/pay-profiles/{profile_id}")
def update_pay_profile(
    venue_id: int,
    profile_id: int,
    payload: PayProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    if 'title' in fields_set and payload.title is not None:
        profile.title = payload.title.strip()
    if 'description' in fields_set:
        profile.description = payload.description or None
    if 'is_active' in fields_set and payload.is_active is not None:
        profile.is_active = payload.is_active
    profile.updated_at = datetime.utcnow()
    db.commit()
    return _load_pay_profile_detail(db, venue_id=venue_id, profile_id=profile_id)


@router.delete("/{venue_id}/pay-profiles/{profile_id}")
def delete_pay_profile(
    venue_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    used = db.execute(select(PayrollLine.id).where(PayrollLine.pay_profile_id == profile_id).limit(1)).scalar_one_or_none()
    if used is not None:
        raise HTTPException(status_code=400, detail="Pay profile is already used in payroll runs. Archive it instead of deleting.")

    db.delete(profile)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/pay-profiles/{profile_id}/assignments")
def create_pay_profile_assignment(
    venue_id: int,
    profile_id: int,
    payload: PayProfileAssignmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == payload.member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=400, detail="Member not found in venue")

    assignment = PayProfileAssignment(
        venue_id=venue_id,
        pay_profile_id=profile_id,
        member_user_id=payload.member_user_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(assignment)
    db.commit()
    member = db.execute(select(User).where(User.id == payload.member_user_id)).scalar_one_or_none()
    return _serialize_pay_profile_assignment(assignment, member=member)


@router.patch("/{venue_id}/pay-profile-assignments/{assignment_id}")
def update_pay_profile_assignment(
    venue_id: int,
    assignment_id: int,
    payload: PayProfileAssignmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    assignment = _get_pay_profile_assignment_or_404(db, venue_id=venue_id, assignment_id=assignment_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    new_start_date = payload.start_date if 'start_date' in fields_set else assignment.start_date
    new_end_date = payload.end_date if 'end_date' in fields_set else assignment.end_date
    if new_start_date and new_end_date and new_end_date < new_start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if 'start_date' in fields_set:
        assignment.start_date = payload.start_date
    if 'end_date' in fields_set:
        assignment.end_date = payload.end_date
    if 'is_active' in fields_set and payload.is_active is not None:
        assignment.is_active = payload.is_active
    assignment.updated_at = datetime.utcnow()
    db.commit()
    member = db.execute(select(User).where(User.id == assignment.member_user_id)).scalar_one_or_none()
    return _serialize_pay_profile_assignment(assignment, member=member)


@router.delete("/{venue_id}/pay-profile-assignments/{assignment_id}")
def delete_pay_profile_assignment(
    venue_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    assignment = _get_pay_profile_assignment_or_404(db, venue_id=venue_id, assignment_id=assignment_id)
    db.delete(assignment)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/pay-profiles/{profile_id}/components")
def create_pay_component(
    venue_id: int,
    profile_id: int,
    payload: PayComponentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)

    component_type = payload.component_type.strip().upper()
    if component_type not in PAY_COMPONENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported pay component type")

    if payload.department_id is not None:
        dep = db.execute(select(Department.id).where(Department.id == payload.department_id, Department.venue_id == venue_id)).scalar_one_or_none()
        if dep is None:
            raise HTTPException(status_code=400, detail="Department not found in venue")
    if payload.kpi_metric_id is not None:
        kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
        if kpi is None:
            raise HTTPException(status_code=400, detail="KPI metric not found in venue")
    if payload.boost_department_id is not None:
        dep = db.execute(select(Department.id).where(Department.id == payload.boost_department_id, Department.venue_id == venue_id)).scalar_one_or_none()
        if dep is None:
            raise HTTPException(status_code=400, detail="Boost department not found in venue")
    department_ids = _normalize_int_ids(payload.department_ids)
    boost_department_ids = _normalize_int_ids(payload.boost_department_ids)
    _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=department_ids, detail="Departments not found in venue")
    _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=boost_department_ids, detail="Boost departments not found in venue")
    if payload.boost_kpi_metric_id is not None:
        kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.boost_kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
        if kpi is None:
            raise HTTPException(status_code=400, detail="Boost KPI metric not found in venue")
    _validate_pay_component_fields(
        component_type=component_type,
        amount_minor=payload.amount_minor,
        rate_minor=payload.rate_minor,
        percent_bps=payload.percent_bps,
        department_id=payload.department_id,
        department_ids=department_ids,
        kpi_metric_id=payload.kpi_metric_id,
        threshold_value=payload.threshold_value,
        steps_json=payload.steps_json,
        base_scope=payload.base_scope,
        boost_enabled=payload.boost_enabled,
        boost_percent_bps=payload.boost_percent_bps,
        boost_source_type=payload.boost_source_type,
        boost_recalc_mode=payload.boost_recalc_mode,
        boost_department_id=payload.boost_department_id,
        boost_department_ids=boost_department_ids,
        boost_kpi_metric_id=payload.boost_kpi_metric_id,
        boost_threshold_value=payload.boost_threshold_value,
        minimum_guarantee_minor=payload.minimum_guarantee_minor,
        minimum_guarantee_scope=payload.minimum_guarantee_scope,
        maximum_cap_minor=payload.maximum_cap_minor,
    )

    component = PayComponent(
        venue_id=venue_id,
        pay_profile_id=profile_id,
        component_type=component_type,
        title=payload.title.strip(),
        amount_minor=payload.amount_minor,
        rate_minor=payload.rate_minor,
        percent_bps=payload.percent_bps,
        department_id=payload.department_id or (department_ids[0] if department_ids else None),
        department_ids_json=_dump_int_ids(department_ids),
        kpi_metric_id=payload.kpi_metric_id,
        threshold_value=payload.threshold_value,
        steps_json=json.dumps(payload.steps_json, ensure_ascii=False) if payload.steps_json is not None else None,
        base_scope=(payload.base_scope or '').strip().upper() or None,
        boost_enabled=bool(payload.boost_enabled),
        boost_percent_bps=payload.boost_percent_bps,
        boost_source_type=(payload.boost_source_type or '').strip().upper() or None,
        boost_recalc_mode=(payload.boost_recalc_mode or '').strip().upper() or None,
        boost_department_id=payload.boost_department_id or (boost_department_ids[0] if boost_department_ids else None),
        boost_department_ids_json=_dump_int_ids(boost_department_ids),
        boost_kpi_metric_id=payload.boost_kpi_metric_id,
        boost_threshold_value=payload.boost_threshold_value,
        minimum_guarantee_minor=payload.minimum_guarantee_minor,
        minimum_guarantee_scope=_normalize_minimum_guarantee_scope(payload.minimum_guarantee_scope) if payload.minimum_guarantee_minor is not None else None,
        maximum_cap_minor=payload.maximum_cap_minor,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(component)
    db.commit()
    return _serialize_pay_component(component)


@router.patch("/{venue_id}/pay-components/{component_id}")
def update_pay_component(
    venue_id: int,
    component_id: int,
    payload: PayComponentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    component = _get_pay_component_or_404(db, venue_id=venue_id, component_id=component_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    if 'component_type' in fields_set and payload.component_type is not None:
        new_component_type = payload.component_type.strip().upper()
        if new_component_type not in PAY_COMPONENT_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported pay component type")
        component.component_type = new_component_type
    if 'title' in fields_set and payload.title is not None:
        component.title = payload.title.strip()
    if 'amount_minor' in fields_set:
        component.amount_minor = payload.amount_minor
    if 'rate_minor' in fields_set:
        component.rate_minor = payload.rate_minor
    if 'percent_bps' in fields_set:
        component.percent_bps = payload.percent_bps
    if 'department_id' in fields_set:
        if payload.department_id is None:
            component.department_id = None
        else:
            dep = db.execute(select(Department.id).where(Department.id == payload.department_id, Department.venue_id == venue_id)).scalar_one_or_none()
            if dep is None:
                raise HTTPException(status_code=400, detail="Department not found in venue")
            component.department_id = payload.department_id
    if 'department_ids' in fields_set:
        department_ids_payload = _normalize_int_ids(payload.department_ids)
        _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=department_ids_payload, detail="Departments not found in venue")
        component.department_ids_json = _dump_int_ids(department_ids_payload)
        if 'department_id' not in fields_set:
            component.department_id = department_ids_payload[0] if department_ids_payload else None
    if 'kpi_metric_id' in fields_set:
        if payload.kpi_metric_id is None:
            component.kpi_metric_id = None
        else:
            kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
            if kpi is None:
                raise HTTPException(status_code=400, detail="KPI metric not found in venue")
            component.kpi_metric_id = payload.kpi_metric_id
    if 'boost_department_id' in fields_set:
        if payload.boost_department_id is None:
            component.boost_department_id = None
        else:
            dep = db.execute(select(Department.id).where(Department.id == payload.boost_department_id, Department.venue_id == venue_id)).scalar_one_or_none()
            if dep is None:
                raise HTTPException(status_code=400, detail="Boost department not found in venue")
            component.boost_department_id = payload.boost_department_id
    if 'boost_department_ids' in fields_set:
        boost_department_ids_payload = _normalize_int_ids(payload.boost_department_ids)
        _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=boost_department_ids_payload, detail="Boost departments not found in venue")
        component.boost_department_ids_json = _dump_int_ids(boost_department_ids_payload)
        if 'boost_department_id' not in fields_set:
            component.boost_department_id = boost_department_ids_payload[0] if boost_department_ids_payload else None
    if 'boost_kpi_metric_id' in fields_set:
        if payload.boost_kpi_metric_id is None:
            component.boost_kpi_metric_id = None
        else:
            kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.boost_kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
            if kpi is None:
                raise HTTPException(status_code=400, detail="Boost KPI metric not found in venue")
            component.boost_kpi_metric_id = payload.boost_kpi_metric_id
    if 'threshold_value' in fields_set:
        component.threshold_value = payload.threshold_value
    if 'steps_json' in fields_set:
        component.steps_json = json.dumps(payload.steps_json, ensure_ascii=False) if payload.steps_json is not None else None
    if 'base_scope' in fields_set:
        component.base_scope = (payload.base_scope or '').strip().upper() or None
    if 'boost_enabled' in fields_set:
        component.boost_enabled = bool(payload.boost_enabled)
    if 'boost_percent_bps' in fields_set:
        component.boost_percent_bps = payload.boost_percent_bps
    if 'boost_source_type' in fields_set:
        component.boost_source_type = (payload.boost_source_type or '').strip().upper() or None
    if 'boost_recalc_mode' in fields_set:
        component.boost_recalc_mode = (payload.boost_recalc_mode or '').strip().upper() or None
    if 'boost_threshold_value' in fields_set:
        component.boost_threshold_value = payload.boost_threshold_value
    if 'minimum_guarantee_minor' in fields_set:
        component.minimum_guarantee_minor = payload.minimum_guarantee_minor
        if payload.minimum_guarantee_minor is None and 'minimum_guarantee_scope' not in fields_set:
            component.minimum_guarantee_scope = None
    if 'minimum_guarantee_scope' in fields_set:
        component.minimum_guarantee_scope = _normalize_minimum_guarantee_scope(payload.minimum_guarantee_scope) if component.minimum_guarantee_minor is not None else None
    elif component.minimum_guarantee_minor is not None and not component.minimum_guarantee_scope:
        component.minimum_guarantee_scope = MINIMUM_GUARANTEE_MONTH
    if 'maximum_cap_minor' in fields_set:
        component.maximum_cap_minor = payload.maximum_cap_minor
    if 'sort_order' in fields_set and payload.sort_order is not None:
        component.sort_order = payload.sort_order
    if 'is_active' in fields_set and payload.is_active is not None:
        component.is_active = payload.is_active
    _validate_pay_component_fields(
        component_type=component.component_type,
        amount_minor=component.amount_minor,
        rate_minor=component.rate_minor,
        percent_bps=component.percent_bps,
        department_id=component.department_id,
        department_ids=_component_department_ids(component),
        kpi_metric_id=component.kpi_metric_id,
        threshold_value=component.threshold_value,
        steps_json=_parse_json_text(component.steps_json),
        base_scope=component.base_scope,
        boost_enabled=bool(component.boost_enabled),
        boost_percent_bps=component.boost_percent_bps,
        boost_source_type=component.boost_source_type,
        boost_recalc_mode=component.boost_recalc_mode,
        boost_department_id=component.boost_department_id,
        boost_department_ids=_component_boost_department_ids(component),
        boost_kpi_metric_id=component.boost_kpi_metric_id,
        boost_threshold_value=component.boost_threshold_value,
        minimum_guarantee_minor=component.minimum_guarantee_minor,
        minimum_guarantee_scope=component.minimum_guarantee_scope,
        maximum_cap_minor=component.maximum_cap_minor,
    )
    component.updated_at = datetime.utcnow()
    db.commit()
    return _serialize_pay_component(component)


@router.delete("/{venue_id}/pay-components/{component_id}")
def delete_pay_component(
    venue_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    component = _get_pay_component_or_404(db, venue_id=venue_id, component_id=component_id)
    db.delete(component)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/payroll/calculate")
def calculate_payroll(
    venue_id: int,
    payload: PayrollCalculateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_calculate(db, venue_id=venue_id, user=user)

    try:
        calculate_payroll_for_month(
            db=db,
            venue_id=venue_id,
            month=payload.month,
            calculated_by_user_id=user.id,
        )
        _create_payroll_recalculation_log(
            db,
            venue_id=int(venue_id),
            period_month=parse_month_start(payload.month),
            trigger_reason="manual_calculation",
            triggered_by_user_id=int(user.id),
            target_dates=[],
            details={"source": "manual_payroll_calculate"},
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    return _load_payroll_payload(db, venue_id=venue_id, month=payload.month)


@router.get("/{venue_id}/payroll")
def get_payroll(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_view(db, venue_id=venue_id, user=user)

    try:
        period_start, period_end, period_meta = resolve_salary_period(month=month, date_from=date_from, date_to=date_to)
        if period_meta.get("mode") == "month":
            return _load_payroll_payload(db, venue_id=venue_id, month=str(period_meta.get("month") or month))
        return _build_venue_payroll_period_payload(
            db,
            venue_id=venue_id,
            period_start=period_start,
            period_end=period_end,
            period_meta=period_meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/payroll/recalculation-log")
def get_payroll_recalculation_log(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_view(db, venue_id=venue_id, user=user)

    try:
        month_start = parse_month_start(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not _payroll_recalculation_logs_table_exists(db):
        rows = []
    else:
        rows = db.execute(
            select(PayrollRecalculationLog)
            .where(
                PayrollRecalculationLog.venue_id == int(venue_id),
                PayrollRecalculationLog.period_month == month_start,
            )
            .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
            .limit(int(limit))
        ).scalars().all()

    return {
        "month": month,
        "items": [_serialize_payroll_recalculation_log(row) for row in rows],
    }


# ---------- Daily reports ----------

def _has_venue_permission(db: Session, *, venue_id: int, user: User, permission_code: str) -> bool:
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code=permission_code)
        return True
    except HTTPException:
        return False


def _resolve_report_shift_slot(query_value: str | None = None, body_value: str | None = None) -> str:
    # Query param is the public contract; body field is kept only for backwards/extra safety.
    return normalize_shift_slot(query_value if query_value is not None else body_value)


def _report_slot_filter(venue_id: int, report_date: date, shift_slot: str):
    return (
        DailyReport.venue_id == venue_id,
        DailyReport.date == report_date,
        DailyReport.shift_slot == normalize_shift_slot(shift_slot),
    )


def _load_daily_report_for_slot(db: Session, *, venue_id: int, report_date: date, shift_slot: str) -> DailyReport | None:
    return db.execute(
        select(DailyReport).where(*_report_slot_filter(venue_id, report_date, shift_slot))
    ).scalar_one_or_none()


def _load_report_values(db: Session, *, report_id: int) -> list[DailyReportValue]:
    return db.execute(
        select(DailyReportValue).where(DailyReportValue.report_id == report_id)
    ).scalars().all()


def _compute_report_totals(*, report: DailyReport, values: list[DailyReportValue], has_departments: bool) -> dict:
    payments_total = sum(int(v.value_numeric or 0) for v in values if v.kind == "PAYMENT")
    departments_total = sum(int(v.value_numeric or 0) for v in values if v.kind == "DEPT")
    # If there are no departments configured, compare payments to legacy revenue_total (manual input).
    base_total = departments_total if has_departments else int(report.revenue_total or 0)
    discrepancy = payments_total - base_total
    return {
        "payments_total": payments_total,
        "departments_total": departments_total,
        "discrepancy": discrepancy,
        "base_total": base_total,
    }


def _snapshot_report(db: Session, *, report: DailyReport) -> dict:
    values = _load_report_values(db, report_id=report.id)
    dept_cnt = int(db.execute(select(func.count(Department.id)).where(Department.venue_id == report.venue_id)).scalar() or 0)
    has_departments = bool(dept_cnt) or any(v.kind == "DEPT" for v in values)
    totals = _compute_report_totals(report=report, values=values, has_departments=has_departments)

    def _vals(kind: str) -> list[dict]:
        rows = [v for v in values if v.kind == kind]
        rows.sort(key=lambda x: (x.ref_id, x.id))
        return [{"ref_id": int(v.ref_id), "value": int(v.value_numeric or 0)} for v in rows]

    return {
        "id": report.id,
        "venue_id": int(report.venue_id),
        "date": report.date.isoformat(),
        "shift_slot": normalize_shift_slot(getattr(report, "shift_slot", None)),
        "status": report.status,
        "cash": int(report.cash or 0),
        "cashless": int(report.cashless or 0),
        "revenue_total": int(report.revenue_total or 0),
        "tips_total": int(report.tips_total or 0),
        "comment": report.comment,
        "closed_by_user_id": int(report.closed_by_user_id) if report.closed_by_user_id else None,
        "closed_at": report.closed_at.isoformat() if report.closed_at else None,
        "totals": {k: int(v) for k, v in totals.items() if k in ("payments_total", "departments_total", "discrepancy", "base_total")},
        "payments": _vals("PAYMENT"),
        "departments": _vals("DEPT"),
        "kpis": _vals("KPI"),
    }


def _build_dynamic_items(
    db: Session,
    *,
    venue_id: int,
    kind: str,
    report_values: list[DailyReportValue],
    show_numbers: bool,
) -> list[dict]:
    if kind == "PAYMENT":
        model = PaymentMethod
        value_kind = "PAYMENT"
        extra = lambda obj: {}
    elif kind == "DEPT":
        model = Department
        value_kind = "DEPT"
        extra = lambda obj: {}
    elif kind == "KPI":
        model = KpiMetric
        value_kind = "KPI"
        extra = lambda obj: {"unit": getattr(obj, "unit", None)}
    else:
        raise ValueError("Bad kind")

    vals_by_ref = {int(v.ref_id): int(v.value_numeric or 0) for v in report_values if v.kind == value_kind}
    referenced_ids = set(vals_by_ref.keys())

    rows = db.execute(
        select(model)
        .where(
            model.venue_id == venue_id,
            (model.is_active.is_(True)) | (model.id.in_(referenced_ids)) if referenced_ids else (model.is_active.is_(True)),
        )
        .order_by(model.sort_order.asc(), model.id.asc())
    ).scalars().all()

    out: list[dict] = []
    for obj in rows:
        out.append(
            {
                "id": int(obj.id),
                "code": getattr(obj, "code", None),
                "title": getattr(obj, "title", None),
                "is_active": bool(getattr(obj, "is_active", True)),
                "sort_order": int(getattr(obj, "sort_order", 0) or 0),
                "value": (int(vals_by_ref.get(int(obj.id), 0)) if show_numbers else None),
                **extra(obj),
            }
        )
    return out


@router.post("/{venue_id}/reports")
def upsert_daily_report(
    venue_id: int,
    payload: DailyReportUpsertIn,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    slot = _resolve_report_shift_slot(shift_slot, payload.shift_slot)
    if slot == "NIGHT" and not bool(getattr(venue, "night_shifts_enabled", False)):
        raise HTTPException(status_code=400, detail="Ночные смены не включены для заведения")
    tips_enabled = bool(getattr(venue, "tips_enabled", False))
    safe_tips_total = int(payload.tips_total or 0) if tips_enabled else 0


    obj = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=payload.date, shift_slot=slot)

    audited_before = None
    is_closed_edit = False

    if obj is None:
        obj = DailyReport(
            venue_id=venue_id,
            date=payload.date,
            shift_slot=slot,
            cash=payload.cash,
            cashless=payload.cashless,
            revenue_total=payload.revenue_total,
            tips_total=safe_tips_total,
            status="DRAFT",
            comment=payload.comment,
            created_by_user_id=user.id,
        )
        db.add(obj)
        db.flush()  # get obj.id
    else:
        if obj.status == "CLOSED":
            # Editing closed report requires dedicated permission and is logged.
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="SHIFT_REPORT_EDIT")
            audited_before = _snapshot_report(db, report=obj)
            is_closed_edit = True

        obj.cash = payload.cash
        obj.cashless = payload.cashless
        obj.revenue_total = payload.revenue_total
        obj.tips_total = safe_tips_total
        if payload.comment is not None:
            obj.comment = payload.comment
        obj.updated_by_user_id = user.id
        obj.updated_at = datetime.utcnow()

    # --- dynamic values (optional, to keep backwards compatibility with old frontend) ---
    def _validate_ids(model, ids: list[int]) -> None:
        if not ids:
            return
        found = db.execute(select(model.id).where(model.venue_id == venue_id, model.id.in_(ids))).scalars().all()
        if len(found) != len(set(ids)):
            raise HTTPException(status_code=400, detail="Invalid ref_id in payload")

    # payments
    if payload.payments is not None:
        ids = [int(x.ref_id) for x in payload.payments]
        _validate_ids(PaymentMethod, ids)
        db.execute(delete(DailyReportValue).where(DailyReportValue.report_id == obj.id, DailyReportValue.kind == "PAYMENT"))
        for it in payload.payments:
            v = int(it.value or 0)
            if v == 0:
                continue
            db.add(DailyReportValue(report_id=obj.id, kind="PAYMENT", ref_id=int(it.ref_id), value_numeric=v))

        # sync legacy cash/cashless from methods with codes 'cash'/'cashless' (if present)
        pm_rows = db.execute(
            select(PaymentMethod.id, PaymentMethod.code).where(
                PaymentMethod.venue_id == venue_id, PaymentMethod.code.in_(["cash", "cashless"])
            )
        ).all()
        code_to_id = {str(code): int(pid) for pid, code in pm_rows}
        vals_map = {int(it.ref_id): int(it.value or 0) for it in payload.payments}
        if "cash" in code_to_id:
            obj.cash = int(vals_map.get(code_to_id["cash"], 0))
        if "cashless" in code_to_id:
            obj.cashless = int(vals_map.get(code_to_id["cashless"], 0))

    # departments
    if payload.departments is not None:
        ids = [int(x.ref_id) for x in payload.departments]
        _validate_ids(Department, ids)
        db.execute(delete(DailyReportValue).where(DailyReportValue.report_id == obj.id, DailyReportValue.kind == "DEPT"))
        dep_total = 0
        for it in payload.departments:
            v = int(it.value or 0)
            dep_total += v
            if v == 0:
                continue
            db.add(DailyReportValue(report_id=obj.id, kind="DEPT", ref_id=int(it.ref_id), value_numeric=v))

        # if departments provided, treat revenue_total as computed from departments (transition rule)
        obj.revenue_total = int(dep_total)

    # kpis
    if payload.kpis is not None:
        ids = [int(x.ref_id) for x in payload.kpis]
        _validate_ids(KpiMetric, ids)
        db.execute(delete(DailyReportValue).where(DailyReportValue.report_id == obj.id, DailyReportValue.kind == "KPI"))
        for it in payload.kpis:
            v = int(it.value or 0)
            if v == 0:
                continue
            db.add(DailyReportValue(report_id=obj.id, kind="KPI", ref_id=int(it.ref_id), value_numeric=v))

    if is_closed_edit:
        db.flush()
        audited_after = _snapshot_report(db, report=obj)
        db.add(
            DailyReportAudit(
                report_id=obj.id,
                user_id=user.id,
                changed_at=datetime.utcnow(),
                diff_json={"before": audited_before, "after": audited_after},
            )
        )

    db.flush()
    if str(obj.status or "").upper() == "CLOSED":
        _rebuild_report_tip_allocations(db, report=obj, venue=venue)
        rebuild_revenue_entries_for_report(db=db, report=obj)
        _recalculate_payroll_for_dates(
            db,
            venue_id=venue_id,
            target_dates=[obj.date],
            calculated_by_user_id=user.id,
            force=True,
            trigger_reason="closed_report_updated",
        )

    db.commit()
    db.refresh(obj)
    return {
        "id": obj.id,
        "date": obj.date.isoformat(),
        "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None)),
        "mode": "updated" if obj.updated_at else "created",
    }



@router.get("/{venue_id}/reports")
def list_daily_reports(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)

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
        .where(
            DailyReport.venue_id == venue_id,
            DailyReport.date >= start,
            DailyReport.date < end,
            DailyReport.shift_slot == slot,
        )
        .order_by(DailyReport.date.asc(), DailyReport.id.asc())
    ).scalars().all()

    show_numbers = _has_revenue_view_access(db, venue_id=venue_id, user=user)
    return [
        {
            "id": r.id,
            "date": r.date.isoformat(),
            "shift_slot": normalize_shift_slot(getattr(r, "shift_slot", None)),
            "status": getattr(r, "status", "DRAFT"),
            "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
            "cash": r.cash if show_numbers else None,
            "cashless": r.cashless if show_numbers else None,
            "revenue_total": r.revenue_total if show_numbers else None,
            "tips_total": r.tips_total if show_numbers else None,
        }
        for r in rows
    ]


@router.get("/{venue_id}/reports/{report_date}")
def get_daily_report(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)
    r = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=report_date, shift_slot=slot)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")

    show_numbers = _has_revenue_view_access(db, venue_id=venue_id, user=user)
    values = _load_report_values(db, report_id=r.id)

    dept_cnt = int(db.execute(select(func.count(Department.id)).where(Department.venue_id == venue_id)).scalar() or 0)
    has_departments = bool(dept_cnt) or any(v.kind == "DEPT" for v in values)
    totals = _compute_report_totals(report=r, values=values, has_departments=has_departments)

    payments_items = _build_dynamic_items(db, venue_id=venue_id, kind="PAYMENT", report_values=values, show_numbers=show_numbers)
    departments_items = _build_dynamic_items(db, venue_id=venue_id, kind="DEPT", report_values=values, show_numbers=show_numbers)
    kpi_items = _build_dynamic_items(db, venue_id=venue_id, kind="KPI", report_values=values, show_numbers=show_numbers)

    return {
        "id": r.id,
        "date": r.date.isoformat(),
        "shift_slot": normalize_shift_slot(getattr(r, "shift_slot", None)),
        "status": getattr(r, "status", "DRAFT"),
        "closed_by_user_id": int(r.closed_by_user_id) if getattr(r, "closed_by_user_id", None) else None,
        "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
        "comment": getattr(r, "comment", None),

        # legacy numeric fields (still used by old UI)
        "cash": r.cash if show_numbers else None,
        "cashless": r.cashless if show_numbers else None,
        "revenue_total": r.revenue_total if show_numbers else None,
        "tips_total": r.tips_total if show_numbers else None,

        # dynamic values (A2)
        "payments": payments_items,
        "departments": departments_items,
        "kpis": kpi_items,

        # computed totals
        "payments_total": totals["payments_total"] if show_numbers else None,
        "departments_total": totals["departments_total"] if show_numbers else None,
        "discrepancy": totals["discrepancy"] if show_numbers else None,
        "tips_allocations": (
            [
                {"user_id": int(a.user_id), "amount": int(a.amount), "split_mode": str(a.split_mode)}
                for a in db.execute(
                    select(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == r.id).order_by(DailyReportTipAllocation.id.asc())
                ).scalars().all()
            ]
            if show_numbers else None
        ),
    }


def _load_assigned_members_for_report_date(db: Session, *, venue_id: int, report_date: date, shift_slot: str = "DAY") -> list[tuple[int, str | None]]:
    rows = db.execute(
        select(ShiftAssignment.member_user_id, VenuePosition.title)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .where(
            Shift.venue_id == venue_id,
            Shift.date == report_date,
            Shift.shift_slot == normalize_shift_slot(shift_slot),
            Shift.is_active.is_(True),
        )
        .order_by(ShiftAssignment.member_user_id.asc(), ShiftAssignment.id.asc())
    ).all()
    return [(int(user_id), title) for user_id, title in rows if user_id is not None]


def _rebuild_report_tip_allocations(
    db: Session,
    *,
    report: DailyReport,
    venue: Venue,
) -> list[DailyReportTipAllocation]:
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == report.id))

    if not bool(getattr(venue, "tips_enabled", False)):
        report.tips_total = 0
        return []

    tips_total = int(getattr(report, "tips_total", 0) or 0)
    if tips_total <= 0:
        return []

    tips_split_mode = str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL").upper()
    assigned_members = _load_assigned_members_for_report_date(
        db,
        venue_id=int(report.venue_id),
        report_date=report.date,
        shift_slot=normalize_shift_slot(getattr(report, "shift_slot", None)),
    )
    if not assigned_members:
        return []

    if tips_split_mode == "WEIGHTED_BY_POSITION":
        try:
            allocations = build_weighted_by_position_tip_allocations(
                report_id=int(report.id),
                tips_total=tips_total,
                assigned_members=assigned_members,
                tips_weights=getattr(venue, "tips_weights", None),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        allocations = build_equal_tip_allocations(
            report_id=int(report.id),
            tips_total=tips_total,
            assigned_user_ids=[user_id for user_id, _title in assigned_members],
        )

    for alloc in allocations:
        db.add(alloc)
    return allocations



@router.post("/{venue_id}/reports/{report_date}/close")
def close_daily_report(
    venue_id: int,
    report_date: date,
    payload: DailyReportCloseIn,
    background_tasks: BackgroundTasks,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = (
        _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
        or _is_report_maker(db, venue_id=venue_id, user=user)
        or _has_venue_permission(db, venue_id=venue_id, user=user, permission_code="SHIFT_REPORT_CLOSE")
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    slot = normalize_shift_slot(shift_slot)
    rep = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=report_date, shift_slot=slot)
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
            shift_slot=slot,
            cash=0,
            cashless=0,
            revenue_total=0,
            tips_total=0,
            status="DRAFT",
            created_by_user_id=user.id,
        )
        db.add(rep)
        db.flush()

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    if slot == "NIGHT" and not bool(getattr(venue, "night_shifts_enabled", False)):
        raise HTTPException(status_code=400, detail="Ночные смены не включены для заведения")
    if not bool(getattr(venue, "tips_enabled", False)):
        # when tips are disabled for venue, ignore any stored tips_total
        rep.tips_total = 0

    if rep.status == "CLOSED":
        return {"ok": True, "status": "CLOSED", "shift_slot": slot}

    values = _load_report_values(db, report_id=rep.id)
    dept_cnt = int(db.execute(select(func.count(Department.id)).where(Department.venue_id == venue_id)).scalar() or 0)
    has_departments = bool(dept_cnt) or any(v.kind == "DEPT" for v in values)
    totals = _compute_report_totals(report=rep, values=values, has_departments=has_departments)
    discrepancy = int(totals["discrepancy"])

    if discrepancy != 0:
        if not payload.comment or not payload.comment.strip():
            raise HTTPException(status_code=400, detail="Comment is required when discrepancy != 0")

    if payload.comment is not None:
        rep.comment = payload.comment


    _rebuild_report_tip_allocations(db, report=rep, venue=venue)

    rep.status = "CLOSED"
    rep.closed_by_user_id = user.id
    rep.closed_at = datetime.utcnow()
    rep.updated_by_user_id = user.id
    rep.updated_at = datetime.utcnow()

    rebuild_revenue_entries_for_report(db=db, report=rep, values=values)
    sync_daily_recurring_accruals_for_date(db=db, venue_id=venue_id, target_date=report_date)
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[report_date],
        calculated_by_user_id=user.id,
        force=True,
        trigger_reason="report_closed",
    )
    _enqueue_day_economics_summary_job(db, venue_id=venue_id, target_date=report_date, shift_slot=slot)
    _enqueue_salary_day_breakdown_job(db, venue_id=venue_id, target_date=report_date, shift_slot=slot)
    _enqueue_soft_alerts_job(db, venue_id=venue_id, target_date=report_date, shift_slot=slot)

    db.commit()
    background_tasks.add_task(process_pending_notification_jobs_once, 10)

    return {"ok": True, "status": "CLOSED", "shift_slot": slot, "discrepancy": discrepancy}


@router.post("/{venue_id}/reports/{report_date}/reopen")
def reopen_daily_report(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="SHIFT_REPORT_REOPEN"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    slot = normalize_shift_slot(shift_slot)
    rep = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=report_date, shift_slot=slot)
    if rep is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if rep.status != "CLOSED":
        return {"ok": True, "status": getattr(rep, "status", "DRAFT"), "shift_slot": slot}

    rep.status = "DRAFT"
    rep.closed_by_user_id = None
    rep.closed_at = None
    rep.updated_by_user_id = user.id
    rep.updated_at = datetime.utcnow()
    delete_revenue_entries_for_report(db=db, report_id=rep.id)
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == rep.id))
    delete_daily_recurring_accruals_for_date(db=db, venue_id=venue_id, target_date=report_date)
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[report_date],
        calculated_by_user_id=user.id,
        force=True,
        trigger_reason="report_reopened",
    )
    db.commit()
    return {"ok": True, "status": "DRAFT", "shift_slot": slot}


# ---------- Revenue aggregation (Stage 2) ----------

class RevenueRowOut(BaseModel):
    ref_id: int
    code: str | None = None
    title: str
    amount: int


class RevenueSummaryOut(BaseModel):
    month: str | None = None
    period_start: date
    period_end: date
    mode: str
    closed_reports: int
    total: int
    rows: list[RevenueRowOut]


def _parse_month_yyyy_mm(month: str) -> tuple[date, date]:
    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return start, end
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")



def _resolve_period(month: str | None, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Resolve requested period.

    Returns (start_date, end_date_inclusive).
    Priority:
    - explicit date_from/date_to
    - month=YYYY-MM
    - default: current month
    """
    if date_from and not date_to:
        date_to = date_from
    if date_to and not date_from:
        date_from = date_to

    if date_from and date_to:
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    if month:
        start, end_excl = _parse_month_yyyy_mm(month)
        return start, (end_excl - timedelta(days=1))

    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)
def _revenue_kind_and_catalog(mode: str):
    mm = (mode or "").upper().strip()
    if mm == "PAYMENTS":
        return "PAYMENT", PaymentMethod
    if mm == "DEPARTMENTS":
        return "DEPT", Department
    raise HTTPException(status_code=400, detail="Bad mode, expected DEPARTMENTS or PAYMENTS")


def _compute_revenue_summary(*, venue_id: int, month: str | None, date_from: date | None, date_to: date | None, mode: str, db: Session):
    try:
        summary = compute_revenue_summary(
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    month_out = summary.get("month")
    if month_out is None and date_from is None and date_to is None:
        month_out = summary["period_start"].strftime("%Y-%m")

    return {
        "month": month_out,
        "period_start": summary["period_start"],
        "period_end": summary["period_end"],
        "mode": str(summary["mode"]).upper(),
        "closed_reports": int(summary["closed_reports"]),
        "total": int(summary["total"]),
        "rows": summary["rows"],
    }


def _load_export_venue_name(db: Session, *, venue_id: int) -> str:
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    return venue.name if venue is not None else f"venue_{venue_id}"


def _safe_export_venue_slug(venue_name: str, venue_id: int) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", venue_name).strip("_") or f"venue_{venue_id}"


def _build_revenue_export_details(*, db: Session, venue_id: int, period_start: date, period_end: date) -> tuple[list[dict], list[dict]]:
    report_rows = db.execute(
        select(DailyReport, User)
        .outerjoin(User, User.id == DailyReport.closed_by_user_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .order_by(DailyReport.date.asc(), DailyReport.id.asc())
    ).all()

    reports = [row[0] for row in report_rows]
    report_ids = [int(report.id) for report in reports if report.id is not None]
    values = []
    if report_ids:
        values = list(
            db.execute(
                select(DailyReportValue)
                .where(DailyReportValue.report_id.in_(report_ids))
                .order_by(DailyReportValue.report_id.asc(), DailyReportValue.kind.asc(), DailyReportValue.ref_id.asc())
            ).scalars().all()
        )

    payment_map = {
        int(row[0]): {"code": row[1], "title": row[2]}
        for row in db.execute(select(PaymentMethod.id, PaymentMethod.code, PaymentMethod.title).where(PaymentMethod.venue_id == int(venue_id))).all()
    }
    department_map = {
        int(row[0]): {"code": row[1], "title": row[2]}
        for row in db.execute(select(Department.id, Department.code, Department.title).where(Department.venue_id == int(venue_id))).all()
    }
    kpi_map = {
        int(row[0]): {"code": row[1], "title": row[2]}
        for row in db.execute(select(KpiMetric.id, KpiMetric.code, KpiMetric.title).where(KpiMetric.venue_id == int(venue_id))).all()
    }
    catalog_by_kind = {
        "PAYMENT": payment_map,
        "DEPT": department_map,
        "KPI": kpi_map,
    }

    values_by_report: dict[int, list[DailyReportValue]] = {}
    for value in values:
        values_by_report.setdefault(int(value.report_id), []).append(value)

    details_rows: list[dict] = []
    detail_values: list[dict] = []
    for report, closed_by in report_rows:
        report_values = values_by_report.get(int(report.id), [])
        payments_total_minor = sum(int(v.value_numeric or 0) for v in report_values if v.kind == "PAYMENT") * 100
        departments_total_minor = sum(int(v.value_numeric or 0) for v in report_values if v.kind == "DEPT") * 100
        discrepancy_minor = payments_total_minor - departments_total_minor if payments_total_minor and departments_total_minor else 0
        closed_by_label = None
        if closed_by is not None:
            closed_by_label = closed_by.short_name or closed_by.full_name or (f"@{closed_by.tg_username}" if closed_by.tg_username else f"user #{closed_by.id}")

        details_rows.append(
            {
                "date": report.date,
                "report_id": int(report.id),
                "status": str(report.status or "DRAFT").upper(),
                "revenue_total_minor": int(report.revenue_total or 0) * 100,
                "payments_total_minor": int(payments_total_minor),
                "departments_total_minor": int(departments_total_minor),
                "discrepancy_minor": int(discrepancy_minor),
                "tips_total_minor": int(report.tips_total or 0) * 100,
                "comment": report.comment,
                "closed_at": report.closed_at,
                "closed_by": closed_by_label,
            }
        )

        for value in report_values:
            catalog_item = (catalog_by_kind.get(str(value.kind).upper()) or {}).get(int(value.ref_id), {})
            detail_values.append(
                {
                    "date": report.date,
                    "report_id": int(report.id),
                    "kind": str(value.kind or "").upper(),
                    "code": catalog_item.get("code"),
                    "title": catalog_item.get("title") or f"ID {int(value.ref_id)}",
                    "value_numeric": int(value.value_numeric or 0),
                }
            )

    return details_rows, detail_values


def _load_expenses_for_export(
    *,
    db: Session,
    venue_id: int,
    month: str | None,
    category_id: int | None,
    supplier_id: int | None,
    statuses: str | None,
) -> list[dict]:
    stmt = (
        select(Expense, ExpenseCategory, Supplier, PaymentMethod)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .outerjoin(Supplier, Supplier.id == Expense.supplier_id)
        .outerjoin(PaymentMethod, PaymentMethod.id == Expense.payment_method_id)
        .where(Expense.venue_id == int(venue_id))
    )

    recognized_month = None
    period_start = None
    period_end = None
    if month:
        try:
            recognized_month = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        _, last_day = calendar.monthrange(recognized_month.year, recognized_month.month)
        period_start = recognized_month
        period_end = recognized_month.replace(day=last_day)
        stmt = stmt.outerjoin(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id).where(
            (ExpenseAllocation.month == recognized_month)
            | ((Expense.status != 'CONFIRMED') & (Expense.generated_for_month == recognized_month))
            | ((Expense.status != 'CONFIRMED') & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == int(category_id))
    if supplier_id is not None:
        stmt = stmt.where(Expense.supplier_id == int(supplier_id))

    rows = db.execute(stmt.distinct().order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    status_filter = _parse_expense_statuses_filter(statuses)
    if status_filter:
        rows = [row for row in rows if str(getattr(row[0], 'status', 'DRAFT') or 'DRAFT').upper() in status_filter]

    payload_rows: list[dict] = []
    for expense, category, supplier, payment_method in rows:
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        recognized_allocations = [a for a in allocations if recognized_month is not None and a.month == recognized_month]
        payload = _serialize_expense(expense, category, supplier, payment_method, allocations)
        payload["recognized_allocations"] = [_serialize_expense_allocation(a) for a in recognized_allocations]
        payload["recognized_amount_minor_for_month"] = int(sum(int(a.amount_minor or 0) for a in recognized_allocations))
        payload_rows.append(payload)
    return payload_rows


@router.get("/{venue_id}/revenue", response_model=RevenueSummaryOut)
def get_revenue_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    mode: str = Query("DEPARTMENTS", description="DEPARTMENTS | PAYMENTS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Агрегация доходов по CLOSED отчётам за месяц."""
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    return _compute_revenue_summary(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, mode=mode, db=db)




def _build_revenue_export_response(*, venue_id: int, month: str | None, date_from: date | None, date_to: date | None, mode: str, fmt: str, db: Session, user: User | None = None):
    """Build streaming export response.

    If user is provided, permissions are checked before export.
    Signed-link exports pass user=None and rely on token validation done by caller.
    """
    if user is not None:
        _require_active_member_or_admin(db, venue_id=venue_id, user=user)
        _require_report_viewer(db, venue_id=venue_id, user=user)
        _require_revenue_exporter(db, venue_id=venue_id, user=user)

    summary = _compute_revenue_summary(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, mode=mode, db=db)
    venue_name = _load_export_venue_name(db, venue_id=venue_id)

    mode_label = "payments" if summary["mode"] == "PAYMENTS" else "departments"
    period_label = summary.get("month") or f"{summary['period_start'].isoformat()}_{summary['period_end'].isoformat()}"
    safe_venue = _safe_export_venue_slug(venue_name, venue_id)

    if (fmt or "").lower() == "csv":
        content = build_revenue_csv(
            month=period_label,
            mode=summary["mode"],
            venue_name=venue_name,
            rows=summary["rows"],
            total=int(summary["total"]),
            closed_reports=int(summary["closed_reports"]),
        )
        filename = f"revenue_{safe_venue}_{period_label}_{mode_label}.csv"
        return StreamingResponse(
            BytesIO(content.encode("utf-8-sig")),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"; '
                    f"filename*=UTF-8''{quote(filename)}"
                )
            },
        )

    report_rows, value_rows = _build_revenue_export_details(
        db=db,
        venue_id=venue_id,
        period_start=summary["period_start"],
        period_end=summary["period_end"],
    )
    xlsx_bytes = build_revenue_xlsx(
        month=period_label,
        mode=summary["mode"],
        venue_name=venue_name,
        rows=summary["rows"],
        total=int(summary["total"]),
        closed_reports=int(summary["closed_reports"]),
        report_rows=report_rows,
        value_rows=value_rows,
    )
    filename = f"revenue_{safe_venue}_{period_label}_{mode_label}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/{venue_id}/revenue/export-link")
def get_revenue_export_link(
    venue_id: int,
    request: Request,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    mode: str = Query("DEPARTMENTS", description="DEPARTMENTS | PAYMENTS"),
    fmt: str = Query("xlsx", description="xlsx | csv"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    _require_revenue_exporter(db, venue_id=venue_id, user=user)

    mode_norm = (mode or "DEPARTMENTS").upper().strip()
    fmt_norm = (fmt or "xlsx").lower().strip()
    if fmt_norm not in {"xlsx", "csv"}:
        raise HTTPException(status_code=400, detail="Bad fmt, expected xlsx or csv")
    _revenue_kind_and_catalog(mode_norm)

    token_payload = {
        "action": "revenue_export",
        "venue_id": int(venue_id),
        "month": month or None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "mode": mode_norm,
        "fmt": fmt_norm,
        "user_id": int(user.id),
    }
    token = make_signed_token(token_payload)

    q = []
    if month:
        q.append(f"month={quote(month)}")
    if date_from:
        q.append(f"date_from={quote(date_from.isoformat())}")
    if date_to:
        q.append(f"date_to={quote(date_to.isoformat())}")
    q.append(f"mode={quote(mode_norm)}")
    q.append(f"fmt={quote(fmt_norm)}")
    q.append(f"token={quote(token)}")

    base = str(request.base_url).rstrip("/")
    export_path = f"/venues/{venue_id}/revenue/export?{'&'.join(q)}"
    return {
        "export_path": export_path,
        "export_link": f"{base}{export_path}",
        "expires_in": int(getattr(settings, 'EXPORT_LINK_TTL_SECONDS', 600) or 600),
    }


@router.get("/{venue_id}/revenue/export")
def export_revenue(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    mode: str = Query("DEPARTMENTS", description="DEPARTMENTS | PAYMENTS"),
    fmt: str = Query("xlsx", description="xlsx | csv"),
    token: str | None = Query(None, description="Signed export token for external browser"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Экспорт доходов за месяц (CLOSED) в XLSX (по умолчанию) или CSV.

    Supports either regular authenticated access or a signed short-lived token for
    opening the export in an external browser.
    """
    if token:
        try:
            payload = verify_signed_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid export token")

        if str(payload.get("action") or "") != "revenue_export":
            raise HTTPException(status_code=401, detail="Invalid export token")
        if int(payload.get("venue_id") or 0) != int(venue_id):
            raise HTTPException(status_code=401, detail="Invalid export token")

        month = payload.get("month") or None
        date_from_raw = payload.get("date_from") or None
        date_to_raw = payload.get("date_to") or None
        date_from = date.fromisoformat(date_from_raw) if date_from_raw else None
        date_to = date.fromisoformat(date_to_raw) if date_to_raw else None
        mode = str(payload.get("mode") or mode or "DEPARTMENTS").upper().strip()
        fmt = str(payload.get("fmt") or fmt or "xlsx").lower().strip()

        return _build_revenue_export_response(
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            fmt=fmt,
            db=db,
            user=None,
        )

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return _build_revenue_export_response(
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        mode=mode,
        fmt=fmt,
        db=db,
        user=user,
    )



def _build_expenses_export_response(*, venue_id: int, month: str | None, category_id: int | None, supplier_id: int | None, statuses: str | None, db: Session, user: User | None = None):
    if user is not None:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")

    period_label = month or datetime.utcnow().strftime("%Y-%m")
    venue_name = _load_export_venue_name(db, venue_id=venue_id)
    safe_venue = _safe_export_venue_slug(venue_name, venue_id)
    rows = _load_expenses_for_export(
        db=db,
        venue_id=venue_id,
        month=month,
        category_id=category_id,
        supplier_id=supplier_id,
        statuses=statuses,
    )
    total_minor = sum(int(item.get("recognized_amount_minor_for_month") or 0) for item in rows)
    xlsx_bytes = build_expenses_xlsx(
        month=period_label,
        venue_name=venue_name,
        rows=rows,
        total_minor=total_minor,
    )
    filename = f"expenses_{safe_venue}_{period_label}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/{venue_id}/expenses/export-link")
def get_expenses_export_link(
    venue_id: int,
    request: Request,
    month: str | None = Query(None, description="YYYY-MM"),
    category_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    statuses: str | None = Query(None, description="Comma-separated statuses"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")
    token = make_signed_token({
        "action": "expenses_export",
        "venue_id": int(venue_id),
        "month": month or None,
        "category_id": int(category_id) if category_id is not None else None,
        "supplier_id": int(supplier_id) if supplier_id is not None else None,
        "statuses": statuses or None,
        "user_id": int(user.id),
    })

    q = []
    if month:
        q.append(f"month={quote(month)}")
    if category_id is not None:
        q.append(f"category_id={int(category_id)}")
    if supplier_id is not None:
        q.append(f"supplier_id={int(supplier_id)}")
    if statuses:
        q.append(f"statuses={quote(statuses)}")
    q.append(f"token={quote(token)}")

    base = str(request.base_url).rstrip("/")
    export_path = f"/venues/{venue_id}/expenses/export?{'&'.join(q)}"
    return {
        "export_path": export_path,
        "export_link": f"{base}{export_path}",
        "expires_in": int(getattr(settings, 'EXPORT_LINK_TTL_SECONDS', 600) or 600),
    }


@router.get("/{venue_id}/expenses/export")
def export_expenses(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    category_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    statuses: str | None = Query(None, description="Comma-separated statuses"),
    token: str | None = Query(None, description="Signed export token for external browser"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if token:
        try:
            payload = verify_signed_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid export token")
        if str(payload.get("action") or "") != "expenses_export" or int(payload.get("venue_id") or 0) != int(venue_id):
            raise HTTPException(status_code=401, detail="Invalid export token")
        month = payload.get("month") or None
        category_id = int(payload.get("category_id")) if payload.get("category_id") is not None else None
        supplier_id = int(payload.get("supplier_id")) if payload.get("supplier_id") is not None else None
        statuses = payload.get("statuses") or None
        return _build_expenses_export_response(
            venue_id=venue_id,
            month=month,
            category_id=category_id,
            supplier_id=supplier_id,
            statuses=statuses,
            db=db,
            user=None,
        )

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return _build_expenses_export_response(
        venue_id=venue_id,
        month=month,
        category_id=category_id,
        supplier_id=supplier_id,
        statuses=statuses,
        db=db,
        user=user,
    )


def _build_monthly_summary_export_response(
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session,
    user: User | None = None,
):
    if user is not None:
        _require_active_member_or_admin(db, venue_id=venue_id, user=user)
        _require_revenue_viewer(db, venue_id=venue_id, user=user)
        _require_report_viewer(db, venue_id=venue_id, user=user)

    venue_name = _load_export_venue_name(db, venue_id=venue_id)
    safe_venue = _safe_export_venue_slug(venue_name, venue_id)
    payments_summary = get_monthly_finance_summary(
        db=db,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        income_mode='PAYMENTS',
    )
    departments_summary = get_monthly_finance_summary(
        db=db,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        income_mode='DEPARTMENTS',
    )
    period_start = payments_summary.get("period_start")
    period_end = payments_summary.get("period_end")
    period_label = month or f"{period_start.isoformat()}_{period_end.isoformat()}"
    xlsx_bytes = build_monthly_summary_xlsx(
        month=payments_summary.get("month") or month,
        period_start=period_start,
        period_end=period_end,
        venue_name=venue_name,
        payments_summary=payments_summary,
        departments_summary=departments_summary,
    )
    filename = f"summary_{safe_venue}_{period_label}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/{venue_id}/summary/monthly/export-link")
def get_monthly_summary_export_link(
    venue_id: int,
    request: Request,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    token = make_signed_token({
        "action": "monthly_summary_export",
        "venue_id": int(venue_id),
        "month": month or None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "user_id": int(user.id),
    })
    q = []
    if month:
        q.append(f"month={quote(month)}")
    if date_from:
        q.append(f"date_from={quote(date_from.isoformat())}")
    if date_to:
        q.append(f"date_to={quote(date_to.isoformat())}")
    q.append(f"token={quote(token)}")
    base = str(request.base_url).rstrip("/")
    export_path = f"/venues/{venue_id}/summary/monthly/export?{'&'.join(q)}"
    return {
        "export_path": export_path,
        "export_link": f"{base}{export_path}",
        "expires_in": int(getattr(settings, 'EXPORT_LINK_TTL_SECONDS', 600) or 600),
    }


@router.get("/{venue_id}/summary/monthly/export")
def export_monthly_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    token: str | None = Query(None, description="Signed export token for external browser"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if token:
        try:
            payload = verify_signed_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid export token")
        if str(payload.get("action") or "") != "monthly_summary_export" or int(payload.get("venue_id") or 0) != int(venue_id):
            raise HTTPException(status_code=401, detail="Invalid export token")
        month = payload.get("month") or None
        raw_date_from = payload.get("date_from") or None
        raw_date_to = payload.get("date_to") or None
        date_from = date.fromisoformat(raw_date_from) if raw_date_from else None
        date_to = date.fromisoformat(raw_date_to) if raw_date_to else None
        return _build_monthly_summary_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=None)

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _build_monthly_summary_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=user)


def _build_payroll_export_response(
    *,
    venue_id: int,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session,
    user: User | None = None,
):
    if user is not None:
        _require_payroll_view(db, venue_id=venue_id, user=user)

    try:
        period_start, period_end, period_meta = resolve_salary_period(month=month, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    venue_name = _load_export_venue_name(db, venue_id=venue_id)
    safe_venue = _safe_export_venue_slug(venue_name, venue_id)

    if period_meta.get("mode") == "month":
        period_month = str(period_meta.get("month") or month)
        payload = _load_payroll_payload(db, venue_id=venue_id, month=period_month)
        period_label = period_month
        filename_period = period_month
    else:
        payload = _build_venue_payroll_period_payload(
            db,
            venue_id=venue_id,
            period_start=period_start,
            period_end=period_end,
            period_meta=period_meta,
        )
        period_label = f"{period_start.isoformat()} — {period_end.isoformat()}"
        filename_period = f"{period_start.isoformat()}_{period_end.isoformat()}"

    xlsx_bytes = build_payroll_xlsx(period_label=period_label, venue_name=venue_name, payload=payload)
    filename = f"payroll_{safe_venue}_{filename_period}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/{venue_id}/payroll/export-link")
def get_payroll_export_link(
    venue_id: int,
    request: Request,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payroll_view(db, venue_id=venue_id, user=user)
    try:
        resolve_salary_period(month=month, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = make_signed_token({
        "action": "payroll_export",
        "venue_id": int(venue_id),
        "month": month or None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "user_id": int(user.id),
    })
    q: list[str] = []
    if month:
        q.append(f"month={quote(month)}")
    if date_from:
        q.append(f"date_from={quote(date_from.isoformat())}")
    if date_to:
        q.append(f"date_to={quote(date_to.isoformat())}")
    q.append(f"token={quote(token)}")
    base = str(request.base_url).rstrip("/")
    export_path = f"/venues/{venue_id}/payroll/export?{'&'.join(q)}"
    return {
        "export_path": export_path,
        "export_link": f"{base}{export_path}",
        "expires_in": int(getattr(settings, 'EXPORT_LINK_TTL_SECONDS', 600) or 600),
    }


@router.get("/{venue_id}/payroll/export")
def export_payroll(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    token: str | None = Query(None, description="Signed export token for external browser"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if token:
        try:
            payload = verify_signed_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid export token")
        if str(payload.get("action") or "") != "payroll_export" or int(payload.get("venue_id") or 0) != int(venue_id):
            raise HTTPException(status_code=401, detail="Invalid export token")
        month = payload.get("month") or None
        raw_date_from = payload.get("date_from") or None
        raw_date_to = payload.get("date_to") or None
        date_from = date.fromisoformat(raw_date_from) if raw_date_from else None
        date_to = date.fromisoformat(raw_date_to) if raw_date_to else None
        return _build_payroll_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=None)

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _build_payroll_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=user)



@router.get("/{venue_id}/reports/{report_date}/audit")
def list_daily_report_audit(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)
    rep = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=report_date, shift_slot=slot)
    if rep is None:
        raise HTTPException(status_code=404, detail="Report not found")

    rows = db.execute(
        select(DailyReportAudit).where(DailyReportAudit.report_id == rep.id).order_by(DailyReportAudit.changed_at.desc())
    ).scalars().all()

    return [
        {
            "id": a.id,
            "changed_at": a.changed_at.isoformat() if a.changed_at else None,
            "user_id": a.user_id,
            "user_tg_username": getattr(a.user, "tg_username", None) if getattr(a, "user", None) else None,
            "diff": a.diff_json,
        }
        for a in rows
    ]


@router.get("/{venue_id}/reports/{report_date}/attachments")
def list_report_attachments(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)

    rows = db.execute(
        select(DailyReportAttachment)
        .where(
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == slot,
            DailyReportAttachment.is_active.is_(True),
        )
        .order_by(DailyReportAttachment.id.asc())
    ).scalars().all()

    return {
        "items": [
            {
                "id": a.id,
                "file_name": a.file_name,
                "content_type": a.content_type,
                "shift_slot": normalize_shift_slot(getattr(a, "shift_slot", None)),
                # NOTE: frontend should prefix this path with API_BASE.
                "url": f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}?shift_slot={slot}",
            }
            for a in rows
        ]
    }


@router.get("/{venue_id}/reports/{report_date}/attachments/{attachment_id}")
def download_report_attachment(
    venue_id: int,
    report_date: date,
    attachment_id: int,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)

    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == slot,
            DailyReportAttachment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if not os.path.exists(a.storage_path):
        raise HTTPException(status_code=404, detail="File missing")

    return FileResponse(a.storage_path, media_type=a.content_type or "application/octet-stream", filename=a.file_name)



@router.delete("/{venue_id}/reports/{report_date}/attachments/{attachment_id}")
def delete_report_attachment(
    venue_id: int,
    report_date: date,
    attachment_id: int,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)

    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == slot,
            DailyReportAttachment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # soft delete in DB
    a.is_active = False
    db.commit()

    # best-effort remove file
    try:
        if a.storage_path and os.path.exists(a.storage_path):
            os.remove(a.storage_path)
    except Exception:
        pass

    return {"ok": True}


@router.post("/{venue_id}/reports/{report_date}/attachments")
def upload_report_attachments(
    venue_id: int,
    report_date: date,
    files: list[UploadFile] = File(...),
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)
    if slot == "NIGHT":
        venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
        if venue is None:
            raise HTTPException(status_code=404, detail="Venue not found")
        if not bool(getattr(venue, "night_shifts_enabled", False)):
            raise HTTPException(status_code=400, detail="Ночные смены не включены для заведения")

    # ensure report exists (or create empty one)
    rep = _load_daily_report_for_slot(db, venue_id=venue_id, report_date=report_date, shift_slot=slot)
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
            shift_slot=slot,
            cash=0,
            cashless=0,
            revenue_total=0,
            tips_total=0,
            created_by_user_id=user.id,
        )
        db.add(rep)
        db.commit()

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "reports"))
    os.makedirs(base_dir, exist_ok=True)

    allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
    max_bytes = 12 * 1024 * 1024  # 12MB per file

    created = []
    for f in files:
        if f is None:
            continue

        safe_name = os.path.basename(f.filename or "file")
        ext = os.path.splitext(safe_name.lower())[1]
        if ext not in allowed_ext:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {ext}")
        if f.content_type and not str(f.content_type).startswith("image/"):
            raise HTTPException(status_code=415, detail=f"Unsupported content_type: {f.content_type}")

        uid = uuid.uuid4().hex
        dst = os.path.join(base_dir, f"{venue_id}_{report_date.isoformat()}_{slot}_{uid}_{safe_name}")
        with open(dst, "wb") as out:
            total = 0
            while True:
                chunk = f.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    try:
                        out.close()
                        os.remove(dst)
                    except Exception:
                        pass
                    raise HTTPException(status_code=413, detail="File too large (max 12MB)")
                out.write(chunk)

        obj = DailyReportAttachment(
            venue_id=venue_id,
            report_date=report_date,
            shift_slot=slot,
            file_name=safe_name,
            content_type=f.content_type,
            storage_path=dst,
            uploaded_by_user_id=user.id,
            is_active=True,
        )
        db.add(obj)
        db.flush()
        created.append(obj)

    db.commit()
    return {
        "ok": True,
        "items": [
            {
                "id": a.id,
                "file_name": a.file_name,
                "content_type": a.content_type,
                "shift_slot": normalize_shift_slot(getattr(a, "shift_slot", None)),
                "url": f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}?shift_slot={slot}",
            }
            for a in created
        ],
    }


# ---------- Adjustments (penalties/writeoffs/bonuses) ----------


@router.get("/{venue_id}/adjustments")
def list_adjustments(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    mine: int = Query(0, description="1 => only my items"),
    type: str | None = Query(default=None, description="penalty|writeoff|bonus|tip"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not mine:
        _require_adjustments_viewer(db, venue_id=venue_id, user=user)

    if month and (date_from is not None or date_to is not None):
        raise HTTPException(status_code=400, detail="Use either month or date_from/date_to")

    if month:
        try:
            y_s, m_s = month.split("-")
            y = int(y_s)
            m = int(m_s)
            start = date(y, m, 1)
            end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        except Exception:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    else:
        if date_from is None or date_to is None:
            raise HTTPException(status_code=400, detail="Provide month or both date_from/date_to")
        if date_from > date_to:
            raise HTTPException(status_code=400, detail="date_from must be <= date_to")
        start = date_from
        end = date_to + timedelta(days=1)

    stmt = select(Adjustment).where(
        Adjustment.venue_id == venue_id,
        Adjustment.is_active.is_(True),
        Adjustment.date >= start,
        Adjustment.date < end,
    )

    if type:
        stmt = stmt.where(Adjustment.type == type)
    else:
        stmt = stmt.where(Adjustment.type != "tip")
    if mine:
        stmt = stmt.where(Adjustment.member_user_id == user.id)

    rows = db.execute(stmt.order_by(Adjustment.date.asc(), Adjustment.id.asc())).scalars().all()

    # preload member users
    member_ids = {r.member_user_id for r in rows if r.member_user_id}
    users_by_id = {}
    if member_ids:
        urows = db.execute(select(User).where(User.id.in_(member_ids))).scalars().all()
        users_by_id = {u.id: u for u in urows}

    return {
        "items": [
            {
                "id": r.id,
                "type": r.type,
                "date": r.date.isoformat(),
            "status": getattr(r, "status", "DRAFT"),
            "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
                "amount": r.amount,
                "reason": r.reason,
                "member_user_id": r.member_user_id,
                "member": (
                    {
                        "user_id": u.id,
                        "tg_user_id": u.tg_user_id,
                        "tg_username": u.tg_username,
                        "full_name": u.full_name,
                        "short_name": u.short_name,
                    }
                    if (r.member_user_id and (u := users_by_id.get(r.member_user_id)))
                    else None
                ),
            }
            for r in rows
        ]
    }



# ---------- Adjustments helpers ----------

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


def _normalize_notification_shift_slot(value: str | None, *, allow_total: bool = False) -> str:
    raw = str(value or ("TOTAL" if allow_total else "DAY")).strip().upper()
    if allow_total and raw == "TOTAL":
        return "TOTAL"
    return normalize_shift_slot(raw)


def _shift_slot_title(value: str | None) -> str:
    slot = _normalize_notification_shift_slot(value, allow_total=True)
    if slot == "NIGHT":
        return "Ночь"
    if slot == "DAY":
        return "День"
    return "Итого"


def _build_owner_day_economics_link(*, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> str:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    suffix = f"&shift_slot={quote(slot)}" if slot != "TOTAL" else ""
    return f"{_frontend_base_url()}/owner-day-economics.html?venue_id={int(venue_id)}&date={quote(target_date.isoformat())}{suffix}"


def _build_staff_salary_day_link(*, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> str:
    month_value = target_date.strftime("%Y-%m")
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    suffix = f"&shift_slot={quote(slot)}" if slot != "TOTAL" else ""
    return (
        f"{_frontend_base_url()}/staff-salary.html?venue_id={int(venue_id)}"
        f"&month={quote(month_value)}&date={quote(target_date.isoformat())}&open_day=1{suffix}"
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
    existing_log = db.execute(
        select(NotificationDeliveryLog.id, NotificationDeliveryLog.status)
        .where(NotificationDeliveryLog.idempotency_key == idempotency_key)
        .order_by(NotificationDeliveryLog.id.desc())
    ).first()
    if existing_log is not None and str(existing_log.status or "").lower() in {"pending", "sent"}:
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
        pending_log.sent_at = planned_at if ok else None
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
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING]),
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
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING]),
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
        idempotency_key=f"adjustment_assigned:{int(adj.id)}:user:{int(recipient.id)}",
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
            idempotency_key=f"adjustment_dispute_event:{int(comment.id)}:user:{recipient_id}",
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


def _build_soft_alerts_notification_text(*, venue_name: str, target_date: date, economics: dict, alerts: list[dict], detail_level: str, shift_slot: str | None = "TOTAL") -> str:
    level = _notification_detail_level(detail_level)
    summary = economics.get("summary") or {}
    metrics = economics.get("metrics") or {}
    rules = economics.get("rules") or {}

    lines: list[str] = [
        f"⚠️ Мягкие алерты · {_format_ru_date(target_date)} · {_shift_slot_title(shift_slot)}",
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


def _build_day_economics_notification_text(*, venue_name: str, target_date: date, economics: dict, detail_level: str, shift_slot: str | None = "TOTAL") -> str:
    level = _notification_detail_level(detail_level)

    summary = economics.get("summary") or {}
    payment_breakdown = economics.get("payment_revenue_breakdown") or []
    department_breakdown = economics.get("department_revenue_breakdown") or []

    lines: list[str] = [
        f"📊 Экономика дня · {_format_ru_date(target_date)} · {_shift_slot_title(shift_slot)}",
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


def _build_salary_day_breakdown_text(*, venue_name: str, target_date: date, breakdown: dict, detail_level: str, shift_slot: str | None = None) -> str:
    level = _notification_detail_level(detail_level)

    summary = breakdown.get("summary") or {}
    context = breakdown.get("context") or {}
    items = breakdown.get("items") or []
    state = str(breakdown.get("state") or "ready")

    slot_title = _shift_slot_title(shift_slot or breakdown.get("shift_slot") or "TOTAL")
    lines: list[str] = [
        f"💸 Начисление за день · {_format_ru_date(target_date)} · {slot_title}",
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

    slot_note = str(context.get("slot_note") or "").strip()
    if slot_note and level in {"standard", "detailed"}:
        lines.append(slot_note)

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


def _collect_salary_day_notification_user_ids(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> list[int]:
    user_ids: set[int] = set()
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    shift_filters = [Shift.shift_slot == slot] if slot in {"DAY", "NIGHT"} else []
    report_filters = [DailyReport.shift_slot == slot] if slot in {"DAY", "NIGHT"} else []

    assignment_rows = db.execute(
        select(ShiftAssignment.member_user_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.date == target_date,
            Shift.is_active.is_(True),
            ShiftAssignment.member_user_id.is_not(None),
            *shift_filters,
        )
    ).all()
    for (member_user_id,) in assignment_rows:
        if member_user_id is not None:
            user_ids.add(int(member_user_id))

    adjustment_rows = []
    if slot == "TOTAL":
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
            *report_filters,
        )
    ).all()
    for (user_id,) in tip_rows:
        if user_id is not None:
            user_ids.add(int(user_id))

    return sorted(user_ids)


def _enqueue_salary_day_breakdown_job(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    idempotency_key = f"job:salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{slot}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat(), "shift_slot": slot}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_salary_day_breakdown_notifications(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> None:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    user_ids = _collect_salary_day_notification_user_ids(db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
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
    link = _build_staff_salary_day_link(venue_id=venue_id, target_date=target_date, shift_slot=slot)
    sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    seen_tg_user_ids: set[int] = set()

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
        dedupe_scope = f"tg:{chat_id}"
        idempotency_key = f"salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{slot}:{dedupe_scope}"
        existing_log = db.execute(
            select(NotificationDeliveryLog.id, NotificationDeliveryLog.status)
            .where(NotificationDeliveryLog.idempotency_key == idempotency_key)
            .order_by(NotificationDeliveryLog.id.desc())
        ).first()
        if existing_log is not None and str(existing_log.status or "").lower() in {"pending", "sent"}:
            seen_tg_user_ids.add(chat_id)
            continue

        breakdown = build_member_day_breakdown(
            db,
            member_user_id=int(recipient.id),
            venue_id=int(venue_id),
            target_date=target_date,
            shift_slot=slot,
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
            shift_slot=slot,
        )

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
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        seen_tg_user_ids.add(chat_id)

    db.commit()


def _enqueue_soft_alerts_job(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    idempotency_key = f"job:soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{slot}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat(), "shift_slot": slot}, ensure_ascii=False),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_soft_alert_notifications(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> None:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
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

    economics = get_day_economics(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
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
    link = _build_owner_day_economics_link(venue_id=venue_id, target_date=target_date, shift_slot=slot)
    sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    alert_signature = _soft_alert_signature(alerts)
    had_retryable_error = False
    delivered_any = False

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        idempotency_key = f"soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{slot}:{dedupe_scope}:{alert_signature}"
        existing_log = db.execute(
            select(NotificationDeliveryLog.id, NotificationDeliveryLog.status)
            .where(NotificationDeliveryLog.idempotency_key == idempotency_key)
            .order_by(NotificationDeliveryLog.id.desc())
        ).first()
        if existing_log is not None and str(existing_log.status or "").lower() in {"pending", "sent"}:
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        text = _build_soft_alerts_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            alerts=alerts,
            detail_level=detail_level,
            shift_slot=slot,
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


def _enqueue_day_economics_summary_job(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
    idempotency_key = f"job:day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{slot}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_([_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING]),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps({"venue_id": int(venue_id), "target_date": target_date.isoformat(), "shift_slot": slot}, ensure_ascii=False),
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
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN:
                    _send_salary_day_breakdown_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS:
                    _send_soft_alert_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
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


def _send_day_economics_summary_notifications(db: Session, *, venue_id: int, target_date: date, shift_slot: str | None = "TOTAL") -> None:
    slot = _normalize_notification_shift_slot(shift_slot, allow_total=True)
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

    economics = get_day_economics(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
    venue_name = _venue_name(db, venue_id)
    link = _build_owner_day_economics_link(venue_id=venue_id, target_date=target_date, shift_slot=slot)
    sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        idempotency_key = f"day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{slot}:{dedupe_scope}"
        existing_log = db.execute(
            select(NotificationDeliveryLog.id, NotificationDeliveryLog.status)
            .where(NotificationDeliveryLog.idempotency_key == idempotency_key)
            .order_by(NotificationDeliveryLog.id.desc())
        ).first()
        if existing_log is not None and str(existing_log.status or "").lower() in {"pending", "sent"}:
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        text = _build_day_economics_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            detail_level=detail_level,
            shift_slot=slot,
        )

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
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

    db.commit()


@router.post("/{venue_id}/adjustments")
def create_adjustment(
    venue_id: int,
    payload: AdjustmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    if payload.type not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad type")

    if payload.type in ("penalty", "bonus") and not payload.member_user_id:
        raise HTTPException(status_code=400, detail="member_user_id is required")

    if payload.member_user_id:
        vm = db.execute(
            select(VenueMember).where(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == payload.member_user_id,
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if vm is None:
            raise HTTPException(status_code=400, detail="Member not found in venue")

    obj = Adjustment(
        venue_id=venue_id,
        type=payload.type,
        member_user_id=payload.member_user_id,
        date=payload.date,
        amount=payload.amount,
        reason=(payload.reason or "").strip() or None,
        created_by_user_id=user.id,
        is_active=True,
    )
    db.add(obj)
    db.flush()

    if payload.member_user_id:
        _enqueue_adjustment_assigned_job(db, venue_id=venue_id, adjustment_id=int(obj.id))

    db.commit()
    db.refresh(obj)
    return {"id": obj.id}

import datetime as dt

class AdjustmentUpdateIn(BaseModel):
    type: Optional[str] = None          # "penalty" | "writeoff" | "bonus"
    member_user_id: Optional[int] = None
    date: Optional[dt.date] = None
    amount: Optional[int] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None



@router.patch("/{venue_id}/adjustments/{adjustment_id}")
def update_adjustment(
    venue_id: int,
    adjustment_id: int,
    payload: AdjustmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adjustment_id,
            Adjustment.venue_id == venue_id,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if payload.type is not None:
        t = payload.type.strip()
        if t not in ("penalty", "writeoff", "bonus"):
            raise HTTPException(status_code=400, detail="Bad type")
        adj.type = t

    if payload.date is not None:
        adj.date = payload.date

    if payload.amount is not None:
        adj.amount = int(payload.amount)

    if payload.reason is not None:
        adj.reason = payload.reason.strip() or None

    if payload.member_user_id is not None:
        # allow null only for writeoff
        if payload.member_user_id == 0:
            adj.member_user_id = None
        else:
            adj.member_user_id = int(payload.member_user_id)

    adj.updated_by_user_id = user.id
    adj.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/adjustments/{adjustment_id}")
def delete_adjustment(
    venue_id: int,
    adjustment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adjustment_id,
            Adjustment.venue_id == venue_id,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    adj.is_active = False
    adj.updated_by_user_id = user.id
    adj.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/adjustments/{adj_type}/{adj_id}/dispute")
def create_dispute(
    venue_id: int,
    adj_type: str,
    adj_id: int,
    payload: DisputeCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Employee disputes a specific adjustment.

    If there is an OPEN dispute thread for this adjustment, we append a comment.
    Otherwise we create a new dispute + first comment.
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adj_id,
            Adjustment.venue_id == venue_id,
            Adjustment.type == adj_type,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if adj.member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message is required")

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.adjustment_id == adj.id,
            AdjustmentDispute.is_active.is_(True),
            AdjustmentDispute.status == "OPEN",
        )
        .order_by(AdjustmentDispute.id.desc())
    ).scalar_one_or_none()

    created_new = False
    if dis is None:
        created_new = True
        dis = AdjustmentDispute(
            venue_id=venue_id,
            adjustment_id=adj.id,
            message=message,
            created_by_user_id=user.id,
            is_active=True,
            status="OPEN",
        )
        db.add(dis)
        db.flush()

    com = AdjustmentDisputeComment(
        dispute_id=dis.id,
        author_user_id=user.id,
        message=message,
        is_active=True,
    )
    db.add(com)
    db.flush()

    _enqueue_adjustment_dispute_event_job(
        db,
        venue_id=venue_id,
        dispute_id=int(dis.id),
        comment_id=int(com.id),
        event_kind="opened" if created_new else "comment",
    )

    db.commit()
    return {"ok": True, "dispute_id": dis.id}

@router.get("/{venue_id}/adjustments/{adj_type}/{adj_id}/dispute")
def get_dispute_thread(
    venue_id: int,
    adj_type: str,
    adj_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adj_id,
            Adjustment.venue_id == venue_id,
            Adjustment.type == adj_type,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Access: owner/managers OR employee owning the adjustment
    if not _has_adjustments_manage_access(db, venue_id=venue_id, user=user) and adj.member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.adjustment_id == adj.id,
            AdjustmentDispute.is_active.is_(True),
        ).order_by(AdjustmentDispute.id.desc())
    ).scalar_one_or_none()

    if dis is None:
        return {"dispute": None, "comments": []}

    comments = db.execute(
        select(AdjustmentDisputeComment)
        .where(
            AdjustmentDisputeComment.dispute_id == dis.id,
            AdjustmentDisputeComment.is_active.is_(True),
        )
        .order_by(AdjustmentDisputeComment.created_at.asc(), AdjustmentDisputeComment.id.asc())
    ).scalars().all()

    return {
        "dispute": {
            "id": dis.id,
            "status": dis.status,
            "created_by_user_id": dis.created_by_user_id,
            "created_at": dis.created_at.isoformat(),
            "resolved_by_user_id": dis.resolved_by_user_id,
            "resolved_at": dis.resolved_at.isoformat() if dis.resolved_at else None,
        },
        "comments": [
            {
                "id": c.id,
                "author_user_id": c.author_user_id,
                "message": c.message,
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
    }


@router.post("/{venue_id}/disputes/{dispute_id}/comments")
def add_dispute_comment(
    venue_id: int,
    dispute_id: int,
    payload: DisputeCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == dispute_id,
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        raise HTTPException(status_code=404, detail="Not found")

    adj = db.execute(select(Adjustment).where(Adjustment.id == dis.adjustment_id)).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=user)
    if not is_manager and adj.member_user_id != user.id and dis.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    msg = (payload.message or "").strip()
    if not msg:
        raise HTTPException(status_code=422, detail="Message is required")

    com = AdjustmentDisputeComment(
        dispute_id=dis.id,
        author_user_id=user.id,
        message=msg,
        is_active=True,
    )
    db.add(com)
    db.flush()

    _enqueue_adjustment_dispute_event_job(
        db,
        venue_id=venue_id,
        dispute_id=int(dis.id),
        comment_id=int(com.id),
        event_kind="comment",
    )

    db.commit()
    return {"ok": True}


@router.patch("/{venue_id}/disputes/{dispute_id}")
def set_dispute_status(
    venue_id: int,
    dispute_id: int,
    payload: DisputeStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_dispute_resolver(db, venue_id=venue_id, user=user)

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == dispute_id,
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        raise HTTPException(status_code=404, detail="Not found")

    st = (payload.status or "").upper()
    if st not in ("OPEN", "CLOSED"):
        raise HTTPException(status_code=422, detail="Invalid status")

    dis.status = st
    if st == "CLOSED":
        dis.resolved_by_user_id = user.id
        dis.resolved_at = datetime.utcnow()
    else:
        dis.resolved_by_user_id = None
        dis.resolved_at = None

    db.add(dis)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/disputes")
def list_disputes(
    venue_id: int,
    status: str | None = Query(None),
    month: str | None = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    stmt = select(AdjustmentDispute, Adjustment).join(Adjustment, Adjustment.id == AdjustmentDispute.adjustment_id).where(
        AdjustmentDispute.venue_id == venue_id,
        AdjustmentDispute.is_active.is_(True),
        Adjustment.is_active.is_(True),
    )

    if status:
        st = status.upper()
        if st in ("OPEN", "CLOSED"):
            stmt = stmt.where(AdjustmentDispute.status == st)

    if month:
        try:
            y, m = month.split("-")
            y = int(y); m = int(m)
            start = date(y, m, 1)
            end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
            stmt = stmt.where(Adjustment.date >= start, Adjustment.date < end)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid month")

    rows = db.execute(stmt.order_by(AdjustmentDispute.id.desc())).all()
    return {
        "items": [
            {
                "dispute_id": d.id,
                "status": d.status,
                "adjustment": {
                    "id": a.id,
                    "type": a.type,
                    "date": a.date.isoformat(),
                    "amount": a.amount,
                    "member_user_id": a.member_user_id,
                    "reason": a.reason,
                },
            }
            for d, a in rows
        ]
    }


@router.post("/{venue_id}/invites")
def create_invite(
    venue_id: int,
    payload: InviteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    role = str(payload.venue_role or "").strip().upper()
    if role not in ("OWNER", "STAFF"):
        raise HTTPException(status_code=400, detail="Bad venue_role")
    if role == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для приглашения владельца")

    channel = str(payload.invite_channel or "TELEGRAM").strip().upper()
    if channel not in ("TELEGRAM", "PHONE"):
        raise HTTPException(status_code=400, detail="Bad invite_channel")

    existing_user = None

    if channel == "TELEGRAM":
        username = normalize_tg_username(payload.tg_username)
        if not username:
            raise HTTPException(status_code=400, detail="Bad tg_username")

        existing_user = db.query(User).filter(User.tg_username == username).one_or_none()
        if existing_user:
            mem = db.query(VenueMember).filter(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == existing_user.id,
            ).one_or_none()

            if mem:
                if str(mem.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
                    raise HTTPException(status_code=403, detail="Недостаточно прав для изменения владельца")
                mem.venue_role = role
                mem.is_active = True
            else:
                db.add(VenueMember(venue_id=venue_id, user_id=existing_user.id, venue_role=role, is_active=True))

            db.commit()
            auth_map = _build_user_auth_snapshot_map(db, [existing_user.id])
            member_row = type("MemberRow", (), {
                "id": existing_user.id,
                "tg_user_id": existing_user.tg_user_id,
                "tg_username": existing_user.tg_username,
                "full_name": existing_user.full_name,
                "short_name": existing_user.short_name,
            })()
            return {
                "ok": True,
                "mode": "member_added",
                "channel": channel,
                "member": {
                    **_serialize_user_brief(member_row, auth_map),
                    "venue_role": role,
                },
            }

        try:
            inv = create_venue_invite(
                db,
                venue_id=venue_id,
                venue_role=role,
                invite_channel="TELEGRAM",
                tg_username=username,
                contact_label=payload.contact_label,
                created_by_user_id=user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    else:
        phone = normalize_phone_e164(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="Bad phone")

        phone_ident = db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == "PHONE",
                AuthIdentity.phone_e164 == phone,
                AuthIdentity.is_verified.is_(True),
            )
        ).scalar_one_or_none()
        if phone_ident is not None:
            existing_user = db.execute(select(User).where(User.id == phone_ident.user_id)).scalar_one_or_none()

        if existing_user:
            mem = db.query(VenueMember).filter(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == existing_user.id,
            ).one_or_none()
            if mem:
                if str(mem.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
                    raise HTTPException(status_code=403, detail="Недостаточно прав для изменения владельца")
                mem.venue_role = role
                mem.is_active = True
            else:
                db.add(VenueMember(venue_id=venue_id, user_id=existing_user.id, venue_role=role, is_active=True))

            db.commit()
            auth_map = _build_user_auth_snapshot_map(db, [existing_user.id])
            member_row = type("MemberRow", (), {
                "id": existing_user.id,
                "tg_user_id": existing_user.tg_user_id,
                "tg_username": existing_user.tg_username,
                "full_name": existing_user.full_name,
                "short_name": existing_user.short_name,
            })()
            return {
                "ok": True,
                "mode": "member_added",
                "channel": channel,
                "member": {
                    **_serialize_user_brief(member_row, auth_map),
                    "venue_role": role,
                },
            }

        try:
            inv = create_venue_invite(
                db,
                venue_id=venue_id,
                venue_role=role,
                invite_channel="PHONE",
                phone_e164=phone,
                contact_label=payload.contact_label,
                created_by_user_id=user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(inv)
    invite_meta = _build_pending_invite_target_map(db, [inv]).get(int(inv.id), {"target_status": "WAITING_SIGNUP", "target_user": None})
    return {
        "ok": True,
        "mode": "invited",
        "channel": inv.invite_channel,
        "invite_id": inv.id,
        "invite_link": build_invite_link(inv.invite_token),
        "token": inv.invite_token,
        "target_status": invite_meta.get("target_status", "WAITING_SIGNUP"),
        "target_user": invite_meta.get("target_user"),
    }


@router.patch("/{venue_id}/invites/{invite_id}/default_position")
def set_invite_default_position(
    venue_id: int,
    invite_id: int,
    payload: InviteDefaultPositionPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    # Changing preset position for an invite requires POSITIONS_ASSIGN (or owner/admin).
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")

    inv = db.query(VenueInvite).filter(
        VenueInvite.id == invite_id,
        VenueInvite.venue_id == venue_id,
    ).one_or_none()
    if not inv or not inv.is_active or inv.accepted_user_id is not None:
        raise HTTPException(status_code=404, detail="Invite not found")

    if payload.default_position is None:
        inv.default_position_json = None
    else:
        if payload.default_position.pay_profile_id is not None:
            profile_ok = db.execute(
                select(PayProfile.id).where(
                    PayProfile.id == int(payload.default_position.pay_profile_id),
                    PayProfile.venue_id == venue_id,
                )
            ).scalar_one_or_none()
            if profile_ok is None:
                raise HTTPException(status_code=400, detail="Pay profile not found in venue")
        inv.default_position_json = payload.default_position.dict()

    db.commit()
    return {"ok": True, "default_position": inv.default_position_json}


@router.delete("/{venue_id}/invites/{invite_id}")
def cancel_invite(
    venue_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    inv = db.query(VenueInvite).filter(VenueInvite.id == invite_id, VenueInvite.venue_id == venue_id).one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if str(inv.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для отмены приглашения владельца")

    inv.is_active = False
    inv.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/members/{member_user_id}")
def remove_member(
    venue_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if str(vm.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления владельца")

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

    affected_shift_dates = db.execute(
        select(Shift.date)
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .where(
            Shift.venue_id == venue_id,
            ShiftAssignment.member_user_id == member_user_id,
        )
        .distinct()
    ).scalars().all()

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

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=list(affected_shift_dates),
        calculated_by_user_id=user.id,
        trigger_reason="member_removed_from_venue",
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

    affected_shift_dates = db.execute(
        select(Shift.date)
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .where(
            Shift.venue_id == venue_id,
            ShiftAssignment.member_user_id == current_user.id,
        )
        .distinct()
    ).scalars().all()

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

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=list(affected_shift_dates),
        calculated_by_user_id=current_user.id,
        trigger_reason="member_left_venue",
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
    usage_rows = db.execute(
        select(Shift.interval_id, func.count(Shift.id))
        .where(Shift.venue_id == venue_id)
        .group_by(Shift.interval_id)
    ).all()
    usage_by_interval = {int(interval_id): int(count or 0) for interval_id, count in usage_rows}
    return [
        {
            "id": r.id,
            "title": r.title,
            "start_time": r.start_time.strftime("%H:%M"),
            "end_time": r.end_time.strftime("%H:%M"),
            "is_active": bool(r.is_active),
            "usage_count": usage_by_interval.get(r.id, 0),
            "can_delete": usage_by_interval.get(r.id, 0) == 0,
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

    obj = ShiftInterval(
        venue_id=venue_id,
        title=title,
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
    if usage_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Shift interval is already used in shifts and cannot be deleted. Archive it instead.",
        )

    db.delete(obj)
    db.commit()
    return {"ok": True}




_SCHEDULE_EXPORT_VIEW_LABELS = {
    "month": "Месяц",
    "week": "Неделя",
}

_MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def _month_period_bounds(month_value: str) -> tuple[date, date]:
    try:
        year_text, month_text = str(month_value or "").strip().split("-", 1)
        year = int(year_text)
        month = int(month_text)
        start = date(year, month, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    last_day = calendar.monthrange(start.year, start.month)[1]
    return start, date(start.year, start.month, last_day)


def _week_period_bounds(week_start_value: date) -> tuple[date, date]:
    start = week_start_value - timedelta(days=week_start_value.weekday())
    return start, start + timedelta(days=6)


def _format_schedule_period_label(*, view: str, period_start: date, period_end: date) -> str:
    if view == "week":
        return f"{period_start.strftime('%d.%m')}–{period_end.strftime('%d.%m.%Y')}"
    return f"{_MONTH_NAMES_RU.get(period_start.month, period_start.strftime('%m'))} {period_start.year}"


def _build_schedule_export_filters_text(
    *,
    view: str,
    interval_titles: list[str],
    staffing_state: str,
) -> str:
    parts = [_SCHEDULE_EXPORT_VIEW_LABELS.get(view, "График"), "Все сотрудники"]
    if interval_titles:
        parts.append(f"Интервалы: {', '.join(interval_titles)}")
    if staffing_state == "unstaffed":
        parts.append("Только без назначений")
    elif staffing_state == "staffed":
        parts.append("Только с назначениями")
    return " • ".join(parts)


def _build_staff_shifts_deep_link_path(
    *,
    venue_id: int,
    view: str,
    period_start: date,
    interval_ids: list[int],
    staffing_state: str,
    shift_slot: str = "DAY",
) -> str:
    slot = normalize_shift_slot(shift_slot)
    params: list[tuple[str, str]] = [
        ("venue_id", str(int(venue_id))),
        ("view", view),
    ]
    if view == "week":
        params.append(("week", period_start.isoformat()))
    else:
        params.append(("month", period_start.strftime("%Y-%m")))
    if interval_ids:
        params.append(("intervals", ",".join(str(int(x)) for x in interval_ids)))
    if slot == "NIGHT":
        params.append(("shift_slot", "NIGHT"))
    if staffing_state == "unstaffed":
        params.append(("unstaffed", "1"))
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params)
    return f"/staff-shifts.html?{query}"



def _build_staff_shifts_share_token(
    *,
    venue_id: int,
    view: str,
    period_start: date,
    interval_ids: list[int],
    staffing_state: str,
    shift_slot: str = "DAY",
) -> str:
    slot = normalize_shift_slot(shift_slot)
    return make_signed_token(
        {
            "action": "staff_shifts_share",
            "venue_id": int(venue_id),
            "view": str(view),
            "period_start": period_start.isoformat(),
            "interval_ids": [int(item) for item in (interval_ids or []) if int(item) > 0],
            "staffing_state": str(staffing_state or "all"),
            "shift_slot": slot,
        },
        ttl_seconds=_SCHEDULE_SHARE_TTL_SECONDS,
    )


def _build_staff_shifts_share_path(token: str) -> str:
    return f"/venues/share/staff-shifts/{quote(token)}"


def _build_staff_shifts_share_url(*, request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{_build_staff_shifts_share_path(token)}"


def _build_telegram_share_url(*, url: str, text: str) -> str:
    return f"https://t.me/share/url?url={quote(url)}&text={quote(text or '')}"


@router.get("/share/staff-shifts/{token}")
def open_staff_shifts_share_link(token: str):
    try:
        payload = verify_signed_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid share token")

    if str(payload.get("action") or "") != "staff_shifts_share":
        raise HTTPException(status_code=401, detail="Invalid share token")

    venue_id = int(payload.get("venue_id") or 0)
    if venue_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid share token")

    view = str(payload.get("view") or "month").strip().lower()
    if view not in {"month", "week"}:
        view = "month"

    raw_period_start = payload.get("period_start")
    try:
        period_start = date.fromisoformat(str(raw_period_start))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid share token")
    slot = normalize_shift_slot(payload.get("shift_slot"))

    raw_interval_ids = payload.get("interval_ids") or []
    interval_ids = [int(item) for item in raw_interval_ids if int(item) > 0]
    staffing_state = str(payload.get("staffing_state") or "all").strip().lower()
    if staffing_state not in {"all", "staffed", "unstaffed"}:
        staffing_state = "all"

    deep_link_path = _build_staff_shifts_deep_link_path(
        shift_slot=slot,
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        interval_ids=interval_ids,
        staffing_state=staffing_state,
    )
    return RedirectResponse(url=f"{_frontend_base_url()}{deep_link_path}", status_code=307)


@router.get("/{venue_id}/shifts/export-metadata")
def get_shifts_export_metadata(
    venue_id: int,
    request: Request,
    view: str = Query(default="month", pattern="^(month|week)$"),
    month: str | None = Query(default=None, description="YYYY-MM"),
    week_start: date | None = Query(default=None),
    interval_ids: list[int] | None = Query(default=None),
    staffing_state: str = Query(default="all", pattern="^(all|staffed|unstaffed)$"),
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Metadata for client-side schedule export, download and share flows."""
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    slot = normalize_shift_slot(shift_slot)
    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    if view == "week":
        if week_start is None:
            raise HTTPException(status_code=400, detail="week_start is required for week export metadata")
        period_start, period_end = _week_period_bounds(week_start)
    else:
        if not month:
            raise HTTPException(status_code=400, detail="month is required for month export metadata")
        period_start, period_end = _month_period_bounds(month)

    normalized_interval_ids = sorted({int(item) for item in (interval_ids or []) if int(item) > 0})
    interval_titles: list[str] = []
    if normalized_interval_ids:
        interval_rows = db.execute(
            select(ShiftInterval)
            .where(
                ShiftInterval.venue_id == venue_id,
                ShiftInterval.id.in_(normalized_interval_ids),
            )
            .order_by(ShiftInterval.start_time.asc(), ShiftInterval.id.asc())
        ).scalars().all()
        interval_titles = [str(row.title or "").strip() for row in interval_rows if str(row.title or "").strip()]
        normalized_interval_ids = [int(row.id) for row in interval_rows]

    period_label = _format_schedule_period_label(view=view, period_start=period_start, period_end=period_end)
    filters_text = _build_schedule_export_filters_text(
        view=view,
        interval_titles=interval_titles,
        staffing_state=staffing_state,
    )
    deep_link_path = _build_staff_shifts_deep_link_path(
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        interval_ids=normalized_interval_ids,
        staffing_state=staffing_state,
        shift_slot=slot,
    )
    share_title = f"График смен · {venue.name}"
    share_text = f"{venue.name}\n{period_label}\n{filters_text}"
    share_token = _build_staff_shifts_share_token(
        venue_id=venue_id,
        view=view,
        period_start=period_start,
        shift_slot=slot,
        interval_ids=normalized_interval_ids,
        staffing_state=staffing_state,
    )
    share_path = _build_staff_shifts_share_path(share_token)
    share_url = _build_staff_shifts_share_url(request=request, token=share_token)

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "view": view,
        "period_start": period_start.isoformat(),
        "shift_slot": slot,
        "period_end": period_end.isoformat(),
        "period_label": period_label,
        "filters_text": filters_text,
        "interval_titles": interval_titles,
        "staffing_state": staffing_state,
        "logo_url": None,
        "app_logo_url": "/logo.png",
        "deep_link_path": deep_link_path,
        "deep_link_url": f"{_frontend_base_url()}{deep_link_path}",
        "share_title": share_title,
        "share_text": share_text,
        "share_token": share_token,
        "share_path": share_path,
        "share_url": share_url,
        "telegram_share_url": _build_telegram_share_url(url=share_url, text=share_text),
        "share_expires_in": _SCHEDULE_SHARE_TTL_SECONDS,
    }


@router.get("/{venue_id}/shifts")
def list_shifts(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    interval_ids: list[int] | None = Query(default=None),
    staffing_state: str = Query(default="all", pattern="^(all|staffed|unstaffed)$"),
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List shifts for a venue.

    Accessible to any active member of the venue (or system admin roles).
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    slot = normalize_shift_slot(shift_slot)

    stmt = select(Shift).where(Shift.venue_id == venue_id, Shift.is_active.is_(True), Shift.shift_slot == slot)

    if interval_ids:
        normalized_ids = sorted({int(x) for x in interval_ids if int(x) > 0})
        if normalized_ids:
            stmt = stmt.where(Shift.interval_id.in_(normalized_ids))

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

    assignment_exists = sa.exists(
        select(1)
        .select_from(ShiftAssignment)
        .where(ShiftAssignment.shift_id == Shift.id)
    )
    if staffing_state == "staffed":
        stmt = stmt.where(assignment_exists)
    elif staffing_state == "unstaffed":
        stmt = stmt.where(sa.not_(assignment_exists))

    shifts = db.execute(stmt.order_by(Shift.date.asc(), Shift.id.asc())).scalars().all()

    # preload daily reports for these shift dates (for report_exists + salary calculation)
    shift_dates = {s.date for s in shifts}
    report_by_date: dict[date, DailyReport] = {}
    if shift_dates:
        rrows = db.execute(
            select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date.in_(shift_dates), DailyReport.shift_slot == slot)
        ).scalars().all()
        report_by_date = {r.date: r for r in rrows}

    show_revenue = _has_revenue_view_access(db, venue_id=venue_id, user=user)

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

    return [
        {
            "id": s.id,
            "shift_slot": normalize_shift_slot(getattr(s, "shift_slot", None)),
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
                (report_by_date.get(s.date).tips_total / max(1, len({a["member_user_id"] for a in assignments_by_shift.get(s.id, [])})))
                if (report_by_date.get(s.date) and my_assignment_by_shift.get(s.id) and report_by_date.get(s.date).tips_total)
                else 0
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
    slot = normalize_shift_slot(payload.shift_slot)
    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    if slot == "NIGHT" and not bool(getattr(venue, "night_shifts_enabled", False)):
        raise HTTPException(status_code=400, detail="Ночные смены не включены для заведения")


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
        shift_slot=slot,
        is_active=payload.is_active,
        created_by_user_id=user.id,
    )

    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # likely unique constraint
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")

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

    previous_date = obj.date
    date_changed = payload.date is not None and payload.date != obj.date
    interval_changed = payload.interval_id is not None and payload.interval_id != obj.interval_id
    active_changed = payload.is_active is not None and payload.is_active != obj.is_active

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
        # If shift start time changed - allow reminders to be re-sent.
        if date_changed or interval_changed:
            db.execute(
                update(ShiftAssignment)
                .where(ShiftAssignment.shift_id == shift_id)
                .values(reminder_sent_at=None)
            )
        if date_changed or interval_changed or active_changed:
            _recalculate_payroll_for_dates(
                db,
                venue_id=venue_id,
                target_dates=[previous_date, obj.date],
                calculated_by_user_id=user.id,
                trigger_reason="shift_updated",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shift already exists for this date, interval and slot")

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

    shift_date = obj.date
    obj.is_active = False
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[shift_date],
        calculated_by_user_id=user.id,
        trigger_reason="shift_deleted",
    )
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
        "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None)),
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

    closed_report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == shift.date,
            DailyReport.status == "CLOSED",
        )
    ).scalar_one_or_none()
    if closed_report is not None:
        venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
        if venue is not None:
            _rebuild_report_tip_allocations(db, report=closed_report, venue=venue)

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[shift.date],
        calculated_by_user_id=user.id,
        trigger_reason="shift_assignment_added",
    )
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

    shift_date = db.execute(
        select(Shift.date).where(Shift.id == shift_id, Shift.venue_id == venue_id)
    ).scalar_one_or_none()
    db.delete(a)
    if shift_date is not None:
        closed_report = db.execute(
            select(DailyReport).where(
                DailyReport.venue_id == venue_id,
                DailyReport.date == shift_date,
                DailyReport.status == "CLOSED",
            )
        ).scalar_one_or_none()
        if closed_report is not None:
            venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
            if venue is not None:
                _rebuild_report_tip_allocations(db, report=closed_report, venue=venue)
        _recalculate_payroll_for_dates(
            db,
            venue_id=venue_id,
            target_dates=[shift_date],
            calculated_by_user_id=user.id,
            trigger_reason="shift_assignment_removed",
        )
    db.commit()
    return {"ok": True}



class ShiftCommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/{venue_id}/shifts/{shift_id}/comments")
def list_shift_comments(
    venue_id: int,
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    rows = db.execute(
        select(ShiftComment, User)
        .join(User, User.id == ShiftComment.author_user_id)
        .where(ShiftComment.shift_id == shift_id)
        .order_by(ShiftComment.created_at.asc(), ShiftComment.id.asc())
    ).all()

    return [
        {
            "id": c.id,
            "shift_id": c.shift_id,
            "text": c.text,
            "created_at": c.created_at.isoformat(),
            "author": {
                "id": u.id,
                "tg_username": u.tg_username,
                "full_name": u.full_name,
                "short_name": u.short_name,
            },
        }
        for (c, u) in rows
    ]


@router.post("/{venue_id}/shifts/{shift_id}/comments")
def add_shift_comment(
    venue_id: int,
    shift_id: int,
    payload: ShiftCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_shift_comments_allowed(db, venue_id=venue_id, shift_id=shift_id, user=user)

    shift = db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id, Shift.is_active.is_(True))).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")

    c = ShiftComment(shift_id=shift_id, author_user_id=user.id, text=text)
    db.add(c)
    db.commit()
    db.refresh(c)

    return {
        "id": c.id,
        "shift_id": c.shift_id,
        "text": c.text,
        "created_at": c.created_at.isoformat(),
        "author": {
            "id": user.id,
            "tg_username": user.tg_username,
            "full_name": user.full_name,
            "short_name": user.short_name,
        },
    }


# ---------------- Catalogs: Departments / Payment Methods / KPI Metrics ----------------


@router.get("/{venue_id}/departments")
def list_departments(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_VIEW")
    stmt = select(Department).where(Department.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(Department.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Department.sort_order.asc(), Department.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/departments")
def create_department(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_CREATE")
    obj = Department(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/departments/{department_id}")
def update_department(
    venue_id: int,
    department_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_EDIT")
    obj = db.execute(
        select(Department).where(Department.id == department_id, Department.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Department not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_ARCHIVE")
        obj.is_active = bool(payload.is_active)

    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department code already exists")
    return {"ok": True}


def _ensure_default_payment_methods(db: Session, venue_id: int) -> None:
    cnt = db.scalar(select(func.count()).select_from(PaymentMethod).where(PaymentMethod.venue_id == venue_id)) or 0
    if cnt:
        return
    defaults = [
        ("cash", "Наличные", 0),
        ("cashless", "Безналичные", 10),
        ("sbp", "СБП", 20),
        ("other", "Прочее", 90),
    ]
    for code, title, order in defaults:
        db.add(
            PaymentMethod(
                venue_id=venue_id,
                code=code,
                title=title,
                is_active=True,
                sort_order=order,
                created_at=datetime.utcnow(),
            )
        )
    db.commit()


@router.get("/{venue_id}/payment-methods")
def list_payment_methods(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_VIEW")
    _ensure_default_payment_methods(db, venue_id)
    stmt = select(PaymentMethod).where(PaymentMethod.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    rows = db.scalars(stmt.order_by(PaymentMethod.sort_order.asc(), PaymentMethod.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/payment-methods")
def create_payment_method(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_CREATE")
    obj = PaymentMethod(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment method code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/payment-methods/{payment_method_id}")
def update_payment_method(
    venue_id: int,
    payment_method_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_EDIT")
    obj = db.execute(
        select(PaymentMethod).where(PaymentMethod.id == payment_method_id, PaymentMethod.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_ARCHIVE")
        obj.is_active = bool(payload.is_active)
    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment method code already exists")
    return {"ok": True}


@router.get("/{venue_id}/kpi-metrics")
def list_kpi_metrics(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_VIEW")
    stmt = select(KpiMetric).where(KpiMetric.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(KpiMetric.is_active.is_(True))
    rows = db.scalars(stmt.order_by(KpiMetric.sort_order.asc(), KpiMetric.id.asc())).all()
    usage_by_metric = _build_kpi_usage_map(db, venue_id=venue_id)
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "unit": r.unit,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
            **usage_by_metric.get(int(r.id), {
                "usage_component_count": 0,
                "usage_bonus_component_count": 0,
                "usage_boost_component_count": 0,
                "usage_bonus_profile_count": 0,
                "usage_boost_profile_count": 0,
            }),
        }
        for r in rows
    ]


@router.post("/{venue_id}/kpi-metrics")
def create_kpi_metric(
    venue_id: int,
    payload: KpiMetricCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_CREATE")
    unit = (payload.unit or "QTY").strip().upper()
    obj = KpiMetric(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        unit=unit,
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="KPI code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/kpi-metrics/{kpi_metric_id}")
def update_kpi_metric(
    venue_id: int,
    kpi_metric_id: int,
    payload: KpiMetricUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_EDIT")
    obj = db.execute(
        select(KpiMetric).where(KpiMetric.id == kpi_metric_id, KpiMetric.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="KPI metric not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_ARCHIVE")
        obj.is_active = bool(payload.is_active)
    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.unit is not None:
        obj.unit = (payload.unit or "QTY").strip().upper()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="KPI code already exists")
    return {"ok": True}


@router.get("/{venue_id}/expense-categories")
def list_expense_categories(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    stmt = select(ExpenseCategory).where(ExpenseCategory.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(ExpenseCategory.is_active.is_(True))
    rows = db.scalars(stmt.order_by(ExpenseCategory.sort_order.asc(), ExpenseCategory.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/expense-categories")
def create_expense_category(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = ExpenseCategory(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Expense category code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/expense-categories/{category_id}")
def update_expense_category(
    venue_id: int,
    category_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = _get_expense_category_or_404(db, venue_id=venue_id, category_id=category_id)

    if payload.code is not None:
        obj.code = _normalize_code(payload.code)
    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.is_active is not None:
        obj.is_active = bool(payload.is_active)
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Expense category code already exists")
    return {"ok": True}


@router.get("/{venue_id}/suppliers")
def list_suppliers(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    stmt = select(Supplier).where(Supplier.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(Supplier.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Supplier.sort_order.asc(), Supplier.id.asc())).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "contact": r.contact,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/suppliers")
def create_supplier(
    venue_id: int,
    payload: SupplierCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = Supplier(
        venue_id=venue_id,
        title=payload.title.strip(),
        contact=(payload.contact or None),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supplier title already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/suppliers/{supplier_id}")
def update_supplier(
    venue_id: int,
    supplier_id: int,
    payload: SupplierUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=supplier_id)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.contact is not None:
        obj.contact = payload.contact or None
    if payload.is_active is not None:
        obj.is_active = bool(payload.is_active)
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supplier title already exists")
    return {"ok": True}


def _parse_expense_statuses_filter(statuses: str | None) -> list[str] | None:
    if statuses is None:
        return None
    normalized = []
    for raw in str(statuses).split(','):
        value = raw.strip().upper()
        if not value:
            continue
        if value not in {'DRAFT', 'CONFIRMED', 'CANCELLED'}:
            raise HTTPException(status_code=400, detail='Bad status filter, expected DRAFT, CONFIRMED, CANCELLED')
        if value not in normalized:
            normalized.append(value)
    return normalized or None


def _collect_expense_status_stats(*, rows: list[tuple[Expense, ExpenseCategory, Supplier | None, PaymentMethod | None]], statuses: list[str] | None = None) -> dict:
    counts: dict[str, int] = {'DRAFT': 0, 'CONFIRMED': 0, 'CANCELLED': 0}
    totals: dict[str, int] = {'DRAFT': 0, 'CONFIRMED': 0, 'CANCELLED': 0}
    filtered_count = 0
    filtered_total = 0
    for expense, *_ in rows:
        status = str(getattr(expense, 'status', 'DRAFT') or 'DRAFT').upper()
        counts[status] = counts.get(status, 0) + 1
        totals[status] = totals.get(status, 0) + int(getattr(expense, 'amount_minor', 0) or 0)
        if statuses is None or status in statuses:
            filtered_count += 1
            filtered_total += int(getattr(expense, 'amount_minor', 0) or 0)
    return {
        'count': filtered_count,
        'total_minor': filtered_total,
        'draft_count': counts.get('DRAFT', 0),
        'draft_total_minor': totals.get('DRAFT', 0),
        'confirmed_count': counts.get('CONFIRMED', 0),
        'confirmed_total_minor': totals.get('CONFIRMED', 0),
        'cancelled_count': counts.get('CANCELLED', 0),
        'cancelled_total_minor': totals.get('CANCELLED', 0),
    }


@router.get("/{venue_id}/expenses")
def list_expenses(
    venue_id: int,
    month: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    statuses: str | None = Query(default=None, description='Comma-separated statuses: DRAFT,CONFIRMED,CANCELLED'),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")

    stmt = select(Expense, ExpenseCategory, Supplier, PaymentMethod).join(
        ExpenseCategory, ExpenseCategory.id == Expense.category_id
    ).outerjoin(
        Supplier, Supplier.id == Expense.supplier_id
    ).outerjoin(
        PaymentMethod, PaymentMethod.id == Expense.payment_method_id
    ).where(Expense.venue_id == venue_id)

    recognized_month = None
    period_start = None
    period_end = None
    if month:
        try:
            recognized_month = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        _, last_day = calendar.monthrange(recognized_month.year, recognized_month.month)
        period_start = recognized_month
        period_end = recognized_month.replace(day=last_day)
        stmt = stmt.outerjoin(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id).where(
            (ExpenseAllocation.month == recognized_month)
            | ((Expense.status != 'CONFIRMED') & (Expense.generated_for_month == recognized_month))
            | ((Expense.status != 'CONFIRMED') & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if supplier_id is not None:
        stmt = stmt.where(Expense.supplier_id == supplier_id)

    rows = db.execute(stmt.distinct().order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    status_filter = _parse_expense_statuses_filter(statuses)
    if status_filter:
        rows = [row for row in rows if str(getattr(row[0], 'status', 'DRAFT') or 'DRAFT').upper() in status_filter]
    result = []
    for expense, category, supplier, payment_method in rows:
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        recognized_allocations = [a for a in allocations if recognized_month is not None and a.month == recognized_month]
        payload = _serialize_expense(expense, category, supplier, payment_method, allocations)
        payload["recognized_allocations"] = [_serialize_expense_allocation(a) for a in recognized_allocations]
        payload["recognized_amount_minor_for_month"] = int(sum(int(a.amount_minor or 0) for a in recognized_allocations))
        result.append(payload)
    return result


@router.get("/{venue_id}/expenses/stats")
def get_expense_stats(
    venue_id: int,
    month: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    statuses: str | None = Query(default=None, description='Comma-separated statuses: DRAFT,CONFIRMED,CANCELLED'),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")

    stmt = select(Expense, ExpenseCategory, Supplier, PaymentMethod).join(
        ExpenseCategory, ExpenseCategory.id == Expense.category_id
    ).outerjoin(
        Supplier, Supplier.id == Expense.supplier_id
    ).outerjoin(
        PaymentMethod, PaymentMethod.id == Expense.payment_method_id
    ).where(Expense.venue_id == venue_id)

    recognized_month = None
    period_start = None
    period_end = None
    if month:
        try:
            recognized_month = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        _, last_day = calendar.monthrange(recognized_month.year, recognized_month.month)
        period_start = recognized_month
        period_end = recognized_month.replace(day=last_day)
        stmt = stmt.outerjoin(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id).where(
            (ExpenseAllocation.month == recognized_month)
            | ((Expense.status != 'CONFIRMED') & (Expense.generated_for_month == recognized_month))
            | ((Expense.status != 'CONFIRMED') & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if supplier_id is not None:
        stmt = stmt.where(Expense.supplier_id == supplier_id)

    rows = db.execute(stmt.distinct().order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    status_filter = _parse_expense_statuses_filter(statuses)
    stats = _collect_expense_status_stats(rows=rows, statuses=status_filter)
    return {
        'month': recognized_month.isoformat() if recognized_month is not None else None,
        'statuses': status_filter or ['DRAFT', 'CONFIRMED', 'CANCELLED'],
        **stats,
    }


@router.post("/{venue_id}/expenses")
def create_expense(
    venue_id: int,
    payload: ExpenseCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
    if payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)

    obj = Expense(
        venue_id=venue_id,
        category_id=int(payload.category_id),
        supplier_id=int(payload.supplier_id) if payload.supplier_id is not None else None,
        payment_method_id=int(payload.payment_method_id) if payload.payment_method_id is not None else None,
        amount_minor=int(payload.amount_minor),
        expense_date=payload.expense_date,
        spread_months=int(payload.spread_months or 1),
        status=str(payload.status or 'DRAFT').upper(),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    allocations = rebuild_expense_allocations_for_expense(db=db, expense=obj)
    db.commit()
    db.refresh(obj)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=obj.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=obj.supplier_id) if obj.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id) if obj.payment_method_id else None
    return _serialize_expense(obj, category, supplier, payment_method, allocations)


@router.patch("/{venue_id}/expenses/{expense_id}")
def update_expense(
    venue_id: int,
    expense_id: int,
    payload: ExpenseUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(Expense).where(Expense.id == expense_id, Expense.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    if payload.category_id is not None:
        _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
        obj.category_id = int(payload.category_id)

    if payload.clear_supplier:
        obj.supplier_id = None
    elif payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
        obj.supplier_id = int(payload.supplier_id)

    if payload.clear_payment_method:
        obj.payment_method_id = None
    elif payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        obj.payment_method_id = int(payload.payment_method_id)

    if payload.amount_minor is not None:
        obj.amount_minor = int(payload.amount_minor)
    if payload.expense_date is not None:
        obj.expense_date = payload.expense_date
    if payload.spread_months is not None:
        obj.spread_months = int(payload.spread_months)
    if payload.comment is not None:
        obj.comment = payload.comment or None
    if payload.status is not None:
        obj.status = str(payload.status or 'DRAFT').upper()
    obj.updated_at = datetime.utcnow()

    allocations = rebuild_expense_allocations_for_expense(db=db, expense=obj)
    db.commit()
    db.refresh(obj)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=obj.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=obj.supplier_id) if obj.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id) if obj.payment_method_id else None
    return _serialize_expense(obj, category, supplier, payment_method, allocations)


@router.delete("/{venue_id}/expenses/{expense_id}")
def delete_expense(
    venue_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(Expense).where(Expense.id == expense_id, Expense.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    delete_expense_allocations_for_expense(db=db, expense_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/balance-adjustments")
def list_balance_adjustments(
    venue_id: int,
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    stmt = select(BalanceAdjustment, PaymentMethod).join(
        PaymentMethod, PaymentMethod.id == BalanceAdjustment.payment_method_id
    ).where(BalanceAdjustment.venue_id == venue_id)

    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        start = dt.replace(day=1)
        _, last_day = calendar.monthrange(dt.year, dt.month)
        end = dt.replace(day=last_day)
        stmt = stmt.where(BalanceAdjustment.adjustment_date >= start, BalanceAdjustment.adjustment_date <= end)

    rows = db.execute(stmt.order_by(BalanceAdjustment.adjustment_date.desc(), BalanceAdjustment.id.desc())).all()
    return [_serialize_balance_adjustment(adjustment, payment_method) for adjustment, payment_method in rows]


@router.post("/{venue_id}/balance-adjustments")
def create_balance_adjustment(
    venue_id: int,
    payload: BalanceAdjustmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
    if int(payload.delta_minor) == 0:
        raise HTTPException(status_code=400, detail="delta_minor must be non-zero")

    obj = BalanceAdjustment(
        venue_id=venue_id,
        payment_method_id=int(payload.payment_method_id),
        adjustment_date=payload.adjustment_date,
        delta_minor=int(payload.delta_minor),
        status=str(payload.status or 'CONFIRMED').upper(),
        reason=(payload.reason or None),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    rebuild_balance_adjustment_entries(db=db, adjustment=obj)
    db.commit()
    db.refresh(obj)
    return _serialize_balance_adjustment(obj, payment_method)


@router.patch("/{venue_id}/balance-adjustments/{adjustment_id}")
def update_balance_adjustment(
    venue_id: int,
    adjustment_id: int,
    payload: BalanceAdjustmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(BalanceAdjustment).where(BalanceAdjustment.id == adjustment_id, BalanceAdjustment.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Balance adjustment not found")

    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        obj.payment_method_id = int(payload.payment_method_id)
    if payload.adjustment_date is not None:
        obj.adjustment_date = payload.adjustment_date
    if payload.delta_minor is not None:
        if int(payload.delta_minor) == 0:
            raise HTTPException(status_code=400, detail="delta_minor must be non-zero")
        obj.delta_minor = int(payload.delta_minor)
    if payload.status is not None:
        obj.status = str(payload.status or 'CONFIRMED').upper()
    if payload.reason is not None:
        obj.reason = payload.reason or None
    if payload.comment is not None:
        obj.comment = payload.comment or None
    obj.updated_at = datetime.utcnow()

    rebuild_balance_adjustment_entries(db=db, adjustment=obj)
    db.commit()
    db.refresh(obj)
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id)
    return _serialize_balance_adjustment(obj, payment_method)


@router.delete("/{venue_id}/balance-adjustments/{adjustment_id}")
def delete_balance_adjustment(
    venue_id: int,
    adjustment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(BalanceAdjustment).where(BalanceAdjustment.id == adjustment_id, BalanceAdjustment.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Balance adjustment not found")
    delete_balance_adjustment_entries(db=db, adjustment_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/finance/entries")
def list_finance_entries(
    venue_id: int,
    month: str | None = Query(default=None),
    payment_method_id: int | None = Query(default=None),
    direction: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)

    stmt = select(FinanceEntry, PaymentMethod, Department).outerjoin(
        PaymentMethod, PaymentMethod.id == FinanceEntry.payment_method_id
    ).outerjoin(
        Department, Department.id == FinanceEntry.department_id
    ).where(FinanceEntry.venue_id == venue_id)

    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        start = dt.replace(day=1)
        _, last_day = calendar.monthrange(dt.year, dt.month)
        end = dt.replace(day=last_day)
        stmt = stmt.where(FinanceEntry.entry_date >= start, FinanceEntry.entry_date <= end)

    if payment_method_id is not None:
        stmt = stmt.where(FinanceEntry.payment_method_id == int(payment_method_id))
    if direction:
        stmt = stmt.where(FinanceEntry.direction == str(direction).upper())
    if kind:
        stmt = stmt.where(FinanceEntry.kind == str(kind).upper())
    if source_type:
        stmt = stmt.where(FinanceEntry.source_type == str(source_type).lower())

    rows = db.execute(stmt.order_by(FinanceEntry.entry_date.desc(), FinanceEntry.id.desc())).all()
    return [_serialize_finance_entry(entry, payment_method, department) for entry, payment_method, department in rows]


@router.get("/{venue_id}/payment-method-transfers")
def list_payment_method_transfers(
    venue_id: int,
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)

    from_pm = PaymentMethod.__table__.alias('from_pm')
    to_pm = PaymentMethod.__table__.alias('to_pm')
    stmt = select(PaymentMethodTransfer, from_pm.c.id, from_pm.c.code, from_pm.c.title, to_pm.c.id, to_pm.c.code, to_pm.c.title).join(
        from_pm, from_pm.c.id == PaymentMethodTransfer.from_payment_method_id
    ).join(
        to_pm, to_pm.c.id == PaymentMethodTransfer.to_payment_method_id
    ).where(PaymentMethodTransfer.venue_id == venue_id)

    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        start = dt.replace(day=1)
        _, last_day = calendar.monthrange(dt.year, dt.month)
        end = dt.replace(day=last_day)
        stmt = stmt.where(PaymentMethodTransfer.transfer_date >= start, PaymentMethodTransfer.transfer_date <= end)

    rows = db.execute(stmt.order_by(PaymentMethodTransfer.transfer_date.desc(), PaymentMethodTransfer.id.desc())).all()
    out = []
    for row in rows:
        transfer = row[0]
        from_payment_method = type('PM', (), {'id': row[1], 'code': row[2], 'title': row[3]})()
        to_payment_method = type('PM', (), {'id': row[4], 'code': row[5], 'title': row[6]})()
        out.append(_serialize_payment_method_transfer(transfer, from_payment_method, to_payment_method))
    return out


@router.post("/{venue_id}/payment-method-transfers")
def create_payment_method_transfer(
    venue_id: int,
    payload: PaymentMethodTransferCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    from_payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.from_payment_method_id)
    to_payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.to_payment_method_id)
    if int(payload.from_payment_method_id) == int(payload.to_payment_method_id):
        raise HTTPException(status_code=400, detail="Transfer methods must be different")

    obj = PaymentMethodTransfer(
        venue_id=venue_id,
        from_payment_method_id=int(payload.from_payment_method_id),
        to_payment_method_id=int(payload.to_payment_method_id),
        transfer_date=payload.transfer_date,
        amount_minor=int(payload.amount_minor),
        status=str(payload.status or 'CONFIRMED').upper(),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    rebuild_payment_method_transfer_entries(db=db, transfer=obj)
    db.commit()
    db.refresh(obj)
    return _serialize_payment_method_transfer(obj, from_payment_method, to_payment_method)


@router.patch("/{venue_id}/payment-method-transfers/{transfer_id}")
def update_payment_method_transfer(
    venue_id: int,
    transfer_id: int,
    payload: PaymentMethodTransferUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    obj = db.execute(
        select(PaymentMethodTransfer).where(PaymentMethodTransfer.id == transfer_id, PaymentMethodTransfer.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method transfer not found")

    if payload.from_payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.from_payment_method_id)
        obj.from_payment_method_id = int(payload.from_payment_method_id)
    if payload.to_payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.to_payment_method_id)
        obj.to_payment_method_id = int(payload.to_payment_method_id)
    if int(obj.from_payment_method_id) == int(obj.to_payment_method_id):
        raise HTTPException(status_code=400, detail="Transfer methods must be different")
    if payload.transfer_date is not None:
        obj.transfer_date = payload.transfer_date
    if payload.amount_minor is not None:
        obj.amount_minor = int(payload.amount_minor)
    if payload.status is not None:
        obj.status = str(payload.status or 'CONFIRMED').upper()
    if payload.comment is not None:
        obj.comment = payload.comment or None
    obj.updated_at = datetime.utcnow()

    rebuild_payment_method_transfer_entries(db=db, transfer=obj)
    db.commit()
    db.refresh(obj)
    from_payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.from_payment_method_id)
    to_payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.to_payment_method_id)
    return _serialize_payment_method_transfer(obj, from_payment_method, to_payment_method)


@router.delete("/{venue_id}/payment-method-transfers/{transfer_id}")
def delete_payment_method_transfer(
    venue_id: int,
    transfer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    obj = db.execute(
        select(PaymentMethodTransfer).where(PaymentMethodTransfer.id == transfer_id, PaymentMethodTransfer.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method transfer not found")
    delete_payment_method_transfer_entries(db=db, transfer_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/recurring-expense-rules")
def list_recurring_expense_rules(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_recurring_expenses_view(db, venue_id=venue_id, user=user)

    rows = db.execute(
        select(RecurringExpenseRule)
        .where(RecurringExpenseRule.venue_id == venue_id)
        .order_by(RecurringExpenseRule.is_active.desc(), RecurringExpenseRule.title.asc(), RecurringExpenseRule.id.asc())
    ).scalars().all()

    out = []
    for rule in rows:
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
        supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
        payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id) if rule.payment_method_id else None
        basis_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
        basis_payment_methods = []
        if basis_ids:
            basis_payment_methods = db.execute(
                select(PaymentMethod).where(PaymentMethod.id.in_(basis_ids)).order_by(PaymentMethod.title.asc())
            ).scalars().all()
        out.append(_serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods))
    return out


@router.post("/{venue_id}/recurring-expense-rules")
def create_recurring_expense_rule(
    venue_id: int,
    payload: RecurringExpenseRuleCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
    if payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
    for payment_method_id in payload.payment_method_ids:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payment_method_id)

    mode, freq, amount_minor, percent_bps = normalize_rule_fields(
        generation_mode=payload.generation_mode,
        frequency=payload.frequency,
        amount_minor=payload.amount_minor,
        percent_bps=payload.percent_bps,
    )
    rule = RecurringExpenseRule(
        venue_id=venue_id,
        title=payload.title.strip(),
        category_id=int(payload.category_id),
        supplier_id=int(payload.supplier_id) if payload.supplier_id is not None else None,
        payment_method_id=int(payload.payment_method_id) if payload.payment_method_id is not None else None,
        is_active=bool(payload.is_active),
        start_date=payload.start_date,
        end_date=payload.end_date,
        frequency=freq,
        day_of_month=int(payload.day_of_month or 1),
        generation_mode=mode,
        amount_minor=amount_minor,
        percent_bps=percent_bps,
        spread_months=int(payload.spread_months or 1),
        description=(payload.description or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(rule)
    db.flush()
    replace_rule_payment_methods(db=db, rule_id=rule.id, payment_method_ids=payload.payment_method_ids)
    db.commit()
    db.refresh(rule)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id) if rule.payment_method_id else None
    basis_payment_methods = db.execute(select(PaymentMethod).where(PaymentMethod.id.in_(payload.payment_method_ids)).order_by(PaymentMethod.title.asc())).scalars().all() if payload.payment_method_ids else []
    return _serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods)


@router.patch("/{venue_id}/recurring-expense-rules/{rule_id}")
def update_recurring_expense_rule(
    venue_id: int,
    rule_id: int,
    payload: RecurringExpenseRuleUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    rule = db.execute(
        select(RecurringExpenseRule).where(RecurringExpenseRule.id == rule_id, RecurringExpenseRule.venue_id == venue_id)
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring expense rule not found")

    if payload.title is not None:
        rule.title = payload.title.strip()
    if payload.category_id is not None:
        _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
        rule.category_id = int(payload.category_id)
    if payload.clear_supplier:
        rule.supplier_id = None
    elif payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
        rule.supplier_id = int(payload.supplier_id)
    if payload.clear_payment_method:
        rule.payment_method_id = None
    elif payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        rule.payment_method_id = int(payload.payment_method_id)
    if payload.is_active is not None:
        rule.is_active = bool(payload.is_active)
    if payload.start_date is not None:
        rule.start_date = payload.start_date
    if payload.clear_end_date:
        rule.end_date = None
    elif payload.end_date is not None:
        rule.end_date = payload.end_date
    if payload.day_of_month is not None:
        rule.day_of_month = int(payload.day_of_month)
    if payload.spread_months is not None:
        rule.spread_months = int(payload.spread_months)
    if payload.description is not None:
        rule.description = payload.description or None

    mode_value = payload.generation_mode if payload.generation_mode is not None else rule.generation_mode
    freq_value = payload.frequency if payload.frequency is not None else rule.frequency
    amount_value = payload.amount_minor if payload.amount_minor is not None else rule.amount_minor
    percent_value = payload.percent_bps if payload.percent_bps is not None else rule.percent_bps
    mode, freq, amount_minor, percent_bps = normalize_rule_fields(
        generation_mode=mode_value,
        frequency=freq_value,
        amount_minor=amount_value,
        percent_bps=percent_value,
    )
    rule.generation_mode = mode
    rule.frequency = freq
    rule.amount_minor = amount_minor
    rule.percent_bps = percent_bps
    rule.updated_at = datetime.utcnow()

    if payload.payment_method_ids is not None:
        for payment_method_id in payload.payment_method_ids:
            _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payment_method_id)
        replace_rule_payment_methods(db=db, rule_id=rule.id, payment_method_ids=payload.payment_method_ids)

    db.commit()
    db.refresh(rule)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id) if rule.payment_method_id else None
    basis_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
    basis_payment_methods = db.execute(select(PaymentMethod).where(PaymentMethod.id.in_(basis_ids)).order_by(PaymentMethod.title.asc())).scalars().all() if basis_ids else []
    return _serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods)


@router.delete("/{venue_id}/recurring-expense-rules/{rule_id}")
def delete_recurring_expense_rule(
    venue_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    rule = db.execute(
        select(RecurringExpenseRule).where(RecurringExpenseRule.id == rule_id, RecurringExpenseRule.venue_id == venue_id)
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring expense rule not found")
    db.execute(
        update(Expense)
        .where(Expense.venue_id == venue_id, Expense.recurring_rule_id == int(rule.id))
        .values(recurring_rule_id=None)
    )
    db.execute(delete(RecurringExpenseAccrual).where(RecurringExpenseAccrual.rule_id == int(rule.id)))
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/recurring-expense-rules/generate")
def generate_recurring_expense_drafts(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    rule_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    try:
        result = generate_draft_expenses_for_month(
            db=db,
            venue_id=venue_id,
            month=month,
            created_by_user_id=user.id,
            rule_id=rule_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    created_payload = []
    for expense in result["created"]:
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=expense.category_id)
        supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=expense.supplier_id) if expense.supplier_id else None
        payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=expense.payment_method_id) if expense.payment_method_id else None
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        created_payload.append(_serialize_expense(expense, category, supplier, payment_method, allocations))

    updated_payload = []
    for expense in result.get("updated", []):
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=expense.category_id)
        supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=expense.supplier_id) if expense.supplier_id else None
        payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=expense.payment_method_id) if expense.payment_method_id else None
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        updated_payload.append(_serialize_expense(expense, category, supplier, payment_method, allocations))

    db.commit()
    return {
        "month": result["month"],
        "created_count": result["created_count"],
        "updated_count": result.get("updated_count", 0),
        "skipped_count": result["skipped_count"],
        "created": created_payload,
        "updated": updated_payload,
        "skipped": result["skipped"],
    }


@router.get("/{venue_id}/summary/monthly", response_model=MonthlyFinanceSummaryOut)
def get_venue_monthly_finance_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    income_mode: str = Query("PAYMENTS", description="PAYMENTS|DEPARTMENTS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        return get_monthly_finance_summary(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            income_mode=income_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/summary/day", response_model=DailyFinanceSummaryOut)
def get_venue_day_finance_summary(
    venue_id: int,
    summary_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    income_mode: str = Query("PAYMENTS", description="PAYMENTS|DEPARTMENTS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        return get_day_finance_summary(
            db=db,
            venue_id=venue_id,
            target_date=summary_date,
            income_mode=income_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/economics/day", response_model=DayEconomicsOut)
def get_venue_day_economics(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    shift_slot: str = Query(default="TOTAL", pattern="^(TOTAL|DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        slot = str(shift_slot or "TOTAL").strip().upper()
        if slot not in {"TOTAL", "DAY", "NIGHT"}:
            slot = "TOTAL"
        return get_day_economics(db=db, venue_id=venue_id, target_date=economics_date, shift_slot=slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/economics/plan", response_model=DayEconomicsPlanOut)
def get_venue_day_economics_plan_route(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = get_day_economics_plan(db=db, venue_id=venue_id, target_date=economics_date)
    return _attach_usage_to_day_plan(plan, _usage_counts_for_effective_plan(plan, usage_map))


@router.get("/{venue_id}/economics/plan-month", response_model=DayEconomicsMonthPlanOut)
def get_venue_day_economics_month_plan_route(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(
        get_day_economics_month_plan(db=db, venue_id=venue_id, month_value=month),
        usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN),
    )
    return {
        'month': month,
        **plan,
    }


@router.get("/{venue_id}/economics/plan/override", response_model=DayEconomicsPlanOut)
def get_venue_day_economics_plan_override_route(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = get_day_economics_plan_override(db=db, venue_id=venue_id, target_date=economics_date)
    return _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_DAY_PLAN))


@router.put("/{venue_id}/economics/plan", response_model=DayEconomicsPlanOut)
def put_venue_day_economics_plan(
    venue_id: int,
    payload: DayEconomicsPlanIn,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    plan = upsert_day_economics_plan(
        db=db,
        venue_id=venue_id,
        target_date=economics_date,
        revenue_plan_minor=payload.revenue_plan_minor,
        profit_plan_minor=payload.profit_plan_minor,
        revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
        assigned_user_target=payload.assigned_user_target,
        day_kind=payload.day_kind,
        title=payload.title,
        notes=payload.notes,
    )
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_DAY_PLAN))


@router.put("/{venue_id}/economics/plan-month", response_model=DayEconomicsMonthPlanOut)
def put_venue_day_economics_month_plan(
    venue_id: int,
    payload: DayEconomicsMonthPlanIn,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    plan = upsert_day_economics_month_plan(
        db=db,
        venue_id=venue_id,
        month_value=month,
        revenue_plan_minor=payload.revenue_plan_minor,
        profit_plan_minor=payload.profit_plan_minor,
        revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
        assigned_user_target=payload.assigned_user_target,
        notes=payload.notes,
    )
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN))
    return {
        'month': month,
        **plan,
    }


@router.post("/{venue_id}/economics/plan-month/copy-previous", response_model=DayEconomicsMonthPlanCopyOut)
def post_venue_day_economics_month_plan_copy_previous(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_day_economics_month_plan_from_previous_month(
            db=db,
            venue_id=venue_id,
            month_value=month,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(result.get('plan') or {}, usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN))
    return {
        'copied': bool(result['copied']),
        'copied_from_month': result['copied_from_month'],
        'plan': {
            'month': month,
            **plan,
        },
    }


@router.get("/{venue_id}/economics/plan-templates", response_model=list[DayEconomicsPlanTemplateOut])
def get_venue_day_economics_plan_templates_route(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    return list_day_economics_plan_templates(db=db, venue_id=venue_id)


@router.put("/{venue_id}/economics/plan-templates/{weekday}", response_model=DayEconomicsPlanTemplateOut)
def put_venue_day_economics_plan_template(
    venue_id: int,
    weekday: int,
    payload: DayEconomicsPlanTemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        row = upsert_day_economics_plan_template(
            db=db,
            venue_id=venue_id,
            weekday=weekday,
            revenue_plan_minor=payload.revenue_plan_minor,
            profit_plan_minor=payload.profit_plan_minor,
            revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
            assigned_user_target=payload.assigned_user_target,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return row


@router.post("/{venue_id}/economics/plan-templates/copy", response_model=DayEconomicsTemplateCopyOut)
def post_venue_day_economics_plan_templates_copy(
    venue_id: int,
    payload: DayEconomicsTemplateCopyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_day_economics_plan_templates(
            db=db,
            venue_id=venue_id,
            source_weekday=payload.source_weekday,
            target_weekdays=payload.target_weekdays,
            overwrite=payload.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return result


@router.get("/{venue_id}/economics/department-plan-month", response_model=DepartmentPlanMonthOut)
def get_venue_department_month_plans(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        payload = list_department_month_plans(db=db, venue_id=venue_id, month_value=month)
        usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
        return _attach_usage_to_department_plan_payload(payload, usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{venue_id}/economics/department-plan-month", response_model=DepartmentPlanMonthOut)
def put_venue_department_month_plans(
    venue_id: int,
    payload: DepartmentPlanBulkIn,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = upsert_department_month_plans(db=db, venue_id=venue_id, month_value=month, items=[item.model_dump() for item in payload.items])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_department_plan_payload(result, usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN))


@router.post("/{venue_id}/economics/department-plan-month/autofill-from-last-month", response_model=DepartmentPlanAutofillOut)
def post_venue_department_month_plans_autofill(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = autofill_department_month_plans_from_last_month(db=db, venue_id=venue_id, month_value=month, overwrite=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(result.get("plan") or {}, usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN))
    return result


@router.post("/{venue_id}/economics/department-plan-month/distribute-from-venue-plan", response_model=DepartmentPlanAutofillOut)
def post_venue_department_month_plans_distribute(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = distribute_department_month_plans_from_venue_plan(db=db, venue_id=venue_id, month_value=month, overwrite=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(result.get("plan") or {}, usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN))
    return result


@router.get("/{venue_id}/economics/department-plan-day", response_model=DepartmentPlanDayOut)
def get_venue_department_day_plans(
    venue_id: int,
    date: date = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        payload = list_department_day_plans(db=db, venue_id=venue_id, target_date=date)
        usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
        return _attach_usage_to_department_plan_payload(payload, usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{venue_id}/economics/department-plan-day", response_model=DepartmentPlanDayOut)
def put_venue_department_day_plans(
    venue_id: int,
    payload: DepartmentPlanBulkIn,
    date: date = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = upsert_department_day_plans(db=db, venue_id=venue_id, target_date=date, items=[item.model_dump() for item in payload.items])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_department_plan_payload(result, usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN))


@router.post("/{venue_id}/economics/department-plan-day/copy-from-date", response_model=DepartmentPlanCopyOut)
def post_venue_department_day_plans_copy_from_date(
    venue_id: int,
    source_date: date = Query(..., description="YYYY-MM-DD"),
    target_date: date = Query(..., description="YYYY-MM-DD"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_department_day_plans_from_date(db=db, venue_id=venue_id, source_date=source_date, target_date=target_date, overwrite=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(result.get("plan") or {}, usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN))
    return result


@router.post("/{venue_id}/economics/department-plan-day/autofill-from-history", response_model=DepartmentPlanAutofillOut)
def post_venue_department_day_plans_autofill_from_history(
    venue_id: int,
    target_date: date = Query(..., description="YYYY-MM-DD"),
    mode: str = Query('SAME_WEEKDAY_AVG'),
    overwrite: bool = Query(True),
    lookback_weeks: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = autofill_department_day_plans_from_history(
            db=db,
            venue_id=venue_id,
            target_date=target_date,
            mode=mode,
            overwrite=overwrite,
            lookback_weeks=lookback_weeks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(result.get("plan") or {}, usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN))
    return result


@router.get("/{venue_id}/economics/rules", response_model=VenueEconomicsRulesOut)
def get_venue_day_economics_rules_route(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    return get_venue_economics_rules(db=db, venue_id=venue_id)


@router.put("/{venue_id}/economics/rules", response_model=VenueEconomicsRulesOut)
def put_venue_day_economics_rules(
    venue_id: int,
    payload: VenueEconomicsRulesIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    rules = upsert_venue_economics_rules(
        db=db,
        venue_id=venue_id,
        max_expense_ratio_bps=payload.max_expense_ratio_bps,
        max_payroll_ratio_bps=payload.max_payroll_ratio_bps,
        min_revenue_per_assigned_minor=payload.min_revenue_per_assigned_minor,
        min_assigned_shift_coverage_bps=payload.min_assigned_shift_coverage_bps,
        min_profit_minor=payload.min_profit_minor,
        warn_on_draft_expenses=payload.warn_on_draft_expenses,
    )
    db.commit()
    return rules


@router.get("/{venue_id}/finance/summary", response_model=FinanceSummaryOut)
def get_venue_finance_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        return get_finance_summary(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
