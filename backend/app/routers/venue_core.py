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

from app.routers.venue_common import _require_super_admin_or_moderator
from app.routers.venue_membership_support import (
    _build_owner_summary_by_venue,
    _build_pending_invite_target_map,
    _build_user_auth_snapshot_map,
    _serialize_user_brief,
)
from app.schemas.venue_core import (
    VenueCreateIn,
    VenueSelfServiceCreateIn,
    VenueSettingsOut,
    VenueSettingsPatchIn,
    VenueUpdateIn,
)


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
