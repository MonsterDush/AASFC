from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
import os
import calendar
import json
import uuid
import re
from typing import Optional, List
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, update, func
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.core.tg import normalize_tg_username, send_telegram_message
from app.core.permissions_registry import PERMISSIONS
from app.services import tg_notify
from app.services.xlsx_export import build_revenue_xlsx, build_revenue_csv
from app.services.signed_links import make_signed_token, verify_signed_token
from app.services.finance.expenses import rebuild_expense_allocations_for_expense, delete_expense_allocations_for_expense, list_expense_allocations
from app.services.finance.revenue import rebuild_revenue_entries_for_report, delete_revenue_entries_for_report, compute_revenue_summary
from app.services.finance.summary import get_day_finance_summary, get_finance_summary, get_monthly_finance_summary
from app.services.finance.day_economics import (
    get_day_economics,
    get_day_economics_plan,
    get_venue_economics_rules,
    upsert_day_economics_plan,
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

from app.auth.venue_permissions import require_venue_permission

from app.services.venues import create_venue
from app.settings import settings

router = APIRouter(prefix="/venues", tags=["venues"])


_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalize_code(code: str) -> str:
    c = (code or "").strip().lower().replace(" ", "_")
    if not _CODE_RE.match(c):
        raise HTTPException(
            status_code=400,
            detail="Bad code format. Use латиницу/цифры и символы _- (пример: hookah, cashless, fruit_bowl)",
        )
    return c


# ---------- Schemas ----------

class VenueCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    owner_usernames: Optional[List[str]] = None  # ["owner1", "@owner2"]


class VenueUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class InviteCreateIn(BaseModel):
    tg_username: str
    venue_role: str = "STAFF"  # "OWNER" | "STAFF"



class InviteDefaultPositionIn(BaseModel):
    # preset position data to apply after invite is accepted
    title: str = Field(..., min_length=1, max_length=100)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None



class InviteDefaultPositionPatchIn(BaseModel):
    default_position: InviteDefaultPositionIn | None = None


class VenueSettingsOut(BaseModel):
    tips_enabled: bool = False
    tips_split_mode: str = "EQUAL"
    tips_weights: dict | None = None


class VenueSettingsPatchIn(BaseModel):
    tips_enabled: bool | None = None
    tips_split_mode: str | None = None
    tips_weights: dict | None = None


class PositionCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    member_user_id: int = Field(..., gt=0)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    is_active: bool = True
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


class PositionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    member_user_id: int | None = Field(default=None, gt=0)
    rate: int | None = Field(default=None, ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


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
    payroll_minor: int
    adjustments_minor: int
    refunds_minor: int
    profit_minor: int
    margin_bps: int | None = None


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
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    notes: str | None = None


class DayEconomicsPlanIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


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


def _user_can_manage_adjustments(db: Session, *, venue_id: int, user: User) -> bool:
    return _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_adjustments_manager(db, venue_id=venue_id, user=user)


def _require_dispute_resolver(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DISPUTES_RESOLVE")
        return
    except HTTPException:
        raise HTTPException(status_code=403, detail="Forbidden")

def _can_view_revenue(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW")
        return True
    except HTTPException:
        return False


def _require_revenue_viewer(db: Session, *, venue_id: int, user: User) -> None:
    if not _can_view_revenue(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _can_export_revenue(db: Session, *, venue_id: int, user: User) -> bool:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return True
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_EXPORT")
        return True
    except HTTPException:
        return False


def _require_revenue_exporter(db: Session, *, venue_id: int, user: User) -> None:
    if not _can_export_revenue(db, venue_id=venue_id, user=user):
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

    invites = (
        db.query(
            VenueInvite.id,
            VenueInvite.invited_tg_username,
            VenueInvite.venue_role,
            VenueInvite.created_at,
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

    return {
        "members": [
            {
                "user_id": r.id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
            }
            for r in members
        ],
        "pending_invites": [
            {
                "id": r.id,
                "tg_username": r.invited_tg_username,
                "venue_role": r.venue_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "default_position": r.default_position_json,
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
        tips_split_mode=str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL"),
        tips_weights=getattr(venue, "tips_weights", None),
    )


# ---------- Positions (job roles inside venue) ----------

def _parse_position_permission_codes(raw: str | None) -> list[str]:
    """Parse VenuePosition.permission_codes stored as JSON list (preferred) or tolerate legacy formats.

    Legacy formats that we tolerate:
    - python-like list string: "['A', 'B']"
    - comma/space separated string: "A,B C"
    """
    if not raw:
        return []
    s = str(raw).strip()
    if not s:
        return []

    # 1) JSON list (preferred)
    try:
        data = json.loads(s)
        if isinstance(data, list):
            out: list[str] = []
            for x in data:
                v = str(x or "").strip().upper()
                if v and v not in out:
                    out.append(v)
            return out
    except Exception:
        pass

    # 2) fallback: comma/space separated list or python-like list string
    cleaned = s.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
    out: list[str] = []
    for part in re.split(r"[\s,;]+", cleaned):
        v = str(part or "").strip().upper()
        if v and v not in out:
            out.append(v)
    return out

def _normalize_permission_codes(db: Session, codes: list[str] | None) -> list[str]:
    if not codes:
        return []
    cleaned = []
    seen = set()
    for c in codes:
        s = str(c or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)

    if not cleaned:
        return []

    active = set(
        db.execute(select(Permission.code).where(Permission.code.in_(cleaned), Permission.is_active.is_(True))).scalars().all()
    )
    registry = {p.code.strip().upper() for p in PERMISSIONS}
    # Keep codes that exist in DB as active OR are defined in code registry (even if sync wasn't run yet).
    return [c for c in cleaned if c in active or c in registry]




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

    return [
        {
            "id": r.id,
            "title": r.title,
            "member_user_id": r.member_user_id,
            "rate": r.rate,
            "percent": r.percent,
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
        db.commit()
        db.refresh(pos)
        return {"id": pos.id}

    # update-in-place
    existing.title = payload.title.strip()
    existing.rate = payload.rate
    existing.percent = payload.percent
    if codes_provided:
        existing.permission_codes = json.dumps(norm_codes)
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

    db.commit()
    db.refresh(pos)

    return {
        "ok": True,
        "id": pos.id,
        "title": pos.title,
        "member_user_id": pos.member_user_id,
        "rate": pos.rate,
        "percent": pos.percent,
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


# ---------- Daily reports ----------

def _has_venue_permission(db: Session, *, venue_id: int, user: User, permission_code: str) -> bool:
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code=permission_code)
        return True
    except HTTPException:
        return False


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    venue = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    tips_enabled = bool(getattr(venue, "tips_enabled", False))
    safe_tips_total = int(payload.tips_total or 0) if tips_enabled else 0


    obj = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == payload.date)
    ).scalar_one_or_none()

    audited_before = None
    is_closed_edit = False

    if obj is None:
        obj = DailyReport(
            venue_id=venue_id,
            date=payload.date,
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
        rebuild_revenue_entries_for_report(db=db, report=obj)

    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "date": obj.date.isoformat(), "mode": "updated" if obj.updated_at else "created"}



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





@router.post("/{venue_id}/reports/{report_date}/close")
def close_daily_report(
    venue_id: int,
    report_date: date,
    payload: DailyReportCloseIn,
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

    rep = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
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
    tips_enabled = bool(getattr(venue, "tips_enabled", False))
    tips_split_mode = str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL").upper()
    if not tips_enabled:
        # when tips are disabled for venue, ignore any stored tips_total
        rep.tips_total = 0

    if rep.status == "CLOSED":
        return {"ok": True, "status": "CLOSED"}

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


    # --- tips allocation (optional) ---
    # If venue has tips enabled, distribute daily report tips_total across all assigned members of this date.
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == rep.id))

    if tips_enabled:
        tips_total = int(rep.tips_total or 0)
        if tips_total > 0:
            if tips_split_mode != "EQUAL":
                raise HTTPException(status_code=400, detail="Tips split mode not implemented yet")
            assigned_user_ids = db.execute(
                select(ShiftAssignment.member_user_id)
                .join(Shift, Shift.id == ShiftAssignment.shift_id)
                .where(
                    Shift.venue_id == venue_id,
                    Shift.date == report_date,
                    Shift.is_active.is_(True),
                )
            ).scalars().all()
            uniq = sorted({int(x) for x in assigned_user_ids if x is not None})
            n = len(uniq)
            if n > 0:
                share = tips_total // n
                remainder = tips_total - share * n
                for i, uid in enumerate(uniq):
                    amount = share + (1 if i < remainder else 0)
                    db.add(
                        DailyReportTipAllocation(
                            report_id=rep.id,
                            user_id=uid,
                            amount=int(amount),
                            split_mode="EQUAL",
                        )
                    )

    rep.status = "CLOSED"
    rep.closed_by_user_id = user.id
    rep.closed_at = datetime.utcnow()
    rep.updated_by_user_id = user.id
    rep.updated_at = datetime.utcnow()

    rebuild_revenue_entries_for_report(db=db, report=rep, values=values)
    sync_daily_recurring_accruals_for_date(db=db, venue_id=venue_id, target_date=report_date)

    db.commit()
    return {"ok": True, "status": "CLOSED", "discrepancy": discrepancy}


@router.post("/{venue_id}/reports/{report_date}/reopen")
def reopen_daily_report(
    venue_id: int,
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="SHIFT_REPORT_REOPEN"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    rep = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
    if rep is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if rep.status != "CLOSED":
        return {"ok": True, "status": getattr(rep, "status", "DRAFT")}

    rep.status = "DRAFT"
    rep.closed_by_user_id = None
    rep.closed_at = None
    rep.updated_by_user_id = user.id
    rep.updated_at = datetime.utcnow()
    delete_revenue_entries_for_report(db=db, report_id=rep.id)
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == rep.id))
    delete_daily_recurring_accruals_for_date(db=db, venue_id=venue_id, target_date=report_date)
    db.commit()
    return {"ok": True, "status": "DRAFT"}


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

    v = db.execute(select(Venue).where(Venue.id == venue_id)).scalar_one_or_none()
    venue_name = v.name if v else f"venue_{venue_id}"

    mode_label = "payments" if summary["mode"] == "PAYMENTS" else "departments"
    period_label = summary.get("month") or f"{summary['period_start'].isoformat()}_{summary['period_end'].isoformat()}"
    safe_venue = re.sub(r"[^a-zA-Z0-9_-]+", "_", venue_name).strip("_") or f"venue_{venue_id}"

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

    xlsx_bytes = build_revenue_xlsx(
        month=period_label,
        mode=summary["mode"],
        venue_name=venue_name,
        rows=summary["rows"],
        total=int(summary["total"]),
        closed_reports=int(summary["closed_reports"]),
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



@router.get("/{venue_id}/reports/{report_date}/audit")
def list_daily_report_audit(
    venue_id: int,
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    rep = db.execute(
        select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)
    ).scalar_one_or_none()
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    rows = db.execute(
        select(DailyReportAttachment)
        .where(
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
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
                # NOTE: frontend should prefix this path with API_BASE.
                "url": f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}",
            }
            for a in rows
        ]
    }


@router.get("/{venue_id}/reports/{report_date}/attachments/{attachment_id}")
def download_report_attachment(
    venue_id: int,
    report_date: date,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    # ensure report exists (or create empty one)
    rep = db.execute(select(DailyReport).where(DailyReport.venue_id == venue_id, DailyReport.date == report_date)).scalar_one_or_none()
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
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
        dst = os.path.join(base_dir, f"{venue_id}_{report_date.isoformat()}_{uid}_{safe_name}")
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
                "url": f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}",
            }
            for a in created
        ],
    }


# ---------- Adjustments (penalties/writeoffs/bonuses) ----------


@router.get("/{venue_id}/adjustments")
def list_adjustments(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    mine: int = Query(0, description="1 => only my items"),
    type: str | None = Query(default=None, description="penalty|writeoff|bonus"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not mine:
        _require_adjustments_viewer(db, venue_id=venue_id, user=user)

    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")

    stmt = select(Adjustment).where(
        Adjustment.venue_id == venue_id,
        Adjustment.is_active.is_(True),
        Adjustment.date >= start,
        Adjustment.date < end,
    )

    if type:
        stmt = stmt.where(Adjustment.type == type)
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
    "ru": {"penalty": "Штраф", "writeoff": "Списание", "bonus": "Премия"},
    "en": {"penalty": "Penalty", "writeoff": "Write-off", "bonus": "Bonus"},
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

    kind: 'adjustments' | 'shifts'
    """
    if not u:
        return False
    if not getattr(u, "notify_enabled", True):
        return False
    if kind == "adjustments":
        return bool(getattr(u, "notify_adjustments", True))
    if kind == "shifts":
        return bool(getattr(u, "notify_shifts", True))
    return True



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
    db.commit()
    db.refresh(obj)

    # notify target member

    # notify target member (best-effort)
    if payload.member_user_id:
        target = db.execute(select(User).where(User.id == payload.member_user_id)).scalar_one_or_none()
        if target and target.tg_user_id:
            vname = _venue_name(db, venue_id=venue_id)
            label = _adj_type_label(payload.type)
            link = (
                f"https://app-dev.axelio.ru/staff-adjustments.html?"
                f"venue_id={venue_id}&open={obj.id}&tab={payload.type}"
            )
            if _should_notify_user(target, "adjustments"):
                tg_notify.notify(
                                chat_id=int(target.tg_user_id),
                                text=(
                                    f"{vname}: вам добавлен(а) {label} на {payload.date.isoformat()} "
                                    f"на сумму {payload.amount}. Причина: {(payload.reason or '—')}"
                                ),
                                url=link,
                                button_text="Открыть",
                            )

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
        db.flush()  # get dis.id

    com = AdjustmentDisputeComment(
        dispute_id=dis.id,
        author_user_id=user.id,
        message=message,
        is_active=True,
    )
    db.add(com)
    db.commit()
    # notify all managers/owners (best-effort)
    owners = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == venue_id,
            VenueMember.is_active.is_(True),
            VenueMember.venue_role == "OWNER",
            User.tg_user_id.is_not(None),
        )
    ).scalars().all()

    # Managers = users who have ADJUSTMENTS_MANAGE in position.permission_codes
    mgr_rows = db.execute(
        select(User, VenuePosition.permission_codes)
        .join(VenuePosition, VenuePosition.member_user_id == User.id)
        .where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.is_active.is_(True),
            User.tg_user_id.is_not(None),
        )
    ).all()
    managers: list[User] = []
    for u, pc in mgr_rows:
        codes = {c.strip().upper() for c in _parse_position_permission_codes(pc)}
        if "ADJUSTMENTS_MANAGE" in codes:
            managers.append(u)

    uniq = {u.id: u for u in (owners + managers)}
    who = user.short_name or user.full_name or (user.tg_username or str(user.id))
    link = f"https://app-dev.axelio.ru/app-adjustments.html?venue_id={venue_id}&open={adj.id}&tab=disputes"
    prefix = "Новый спор" if created_new else "Новый комментарий"
    vname = _venue_name(db, venue_id=venue_id)
    label = _adj_type_label(adj.type)
    for u in uniq.values():
        if _should_notify_user(u, "adjustments"):
            tg_notify.notify(
                        chat_id=int(u.tg_user_id),
                        text=(
                            f"{vname}: {prefix}. {who} оспорил {label} #{adj.id} на {adj.date.isoformat()} (сумма {adj.amount}).\n"
                            f"Комментарий: {message}"
                        ),
                        url=link,
                        button_text="Открыть спор",
                    )
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
    if not _user_can_manage_adjustments(db, venue_id=venue_id, user=user) and adj.member_user_id != user.id:
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

    is_manager = _user_can_manage_adjustments(db, venue_id=venue_id, user=user)
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
    db.commit()

    # notify the other side (best effort)
    recipients = []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if token:
        if is_manager:
            # notify employee
            if adj.member_user_id:
                emp = db.execute(select(User).where(User.id == adj.member_user_id, User.tg_user_id.is_not(None))).scalar_one_or_none()
                if emp:
                    recipients.append(emp)
        else:
            # notify managers/owners
            owners = db.execute(
                select(User)
                .join(VenueMember, VenueMember.user_id == User.id)
                .where(
                    VenueMember.venue_id == venue_id,
                    VenueMember.is_active.is_(True),
                    VenueMember.venue_role == "OWNER",
                    User.tg_user_id.is_not(None),
                )
            ).scalars().all()
            mgr_rows = db.execute(
                select(User, VenuePosition.permission_codes)
                .join(VenuePosition, VenuePosition.member_user_id == User.id)
                .where(
                    VenuePosition.venue_id == venue_id,
                    VenuePosition.is_active.is_(True),
                    User.tg_user_id.is_not(None),
                )
            ).all()
            managers: list[User] = []
            for u, pc in mgr_rows:
                codes = {c.strip().upper() for c in _parse_position_permission_codes(pc)}
                if "ADJUSTMENTS_MANAGE" in codes:
                    managers.append(u)
            uniq = {u.id: u for u in (owners + managers)}
            recipients = list(uniq.values())

    who = user.short_name or user.full_name or (user.tg_username or str(user.id))
    vname = _venue_name(db, venue_id=venue_id)
    label = _adj_type_label(adj.type)
    link = f"https://app-dev.axelio.ru/app-adjustments.html?venue_id={venue_id}&open={adj.id}&tab=disputes"
    if token and recipients:
        for r in recipients:
            if _should_notify_user(r, "adjustments"):
                tg_notify.notify(
                    chat_id=int(r.tg_user_id),
                    text=f"{vname}: новый комментарий в споре по {label} #{adj.id} от {who}.\n{msg}",
                    url=link,
                    button_text="Открыть спор",
                )


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

    start_changed = payload.start_time is not None and payload.start_time != obj.start_time

    if payload.title is not None:
        obj.title = payload.title.strip()
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

    date_changed = payload.date is not None and payload.date != obj.date
    interval_changed = payload.interval_id is not None and payload.interval_id != obj.interval_id

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
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "unit": r.unit,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        return get_day_economics(db=db, venue_id=venue_id, target_date=economics_date)
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
    return get_day_economics_plan(db=db, venue_id=venue_id, target_date=economics_date)


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
        notes=payload.notes,
    )
    db.commit()
    return plan


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
