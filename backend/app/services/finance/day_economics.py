from __future__ import annotations

from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, KpiMetric, Shift, ShiftAssignment
from app.services.finance.summary import get_day_finance_summary, _group_revenue_breakdown


def _get_report_state(*, db: Session, venue_id: int, target_date: date) -> dict:
    report = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date == target_date,
        )
    ).scalar_one_or_none()
    if report is None:
        return {
            'exists': False,
            'report_id': None,
            'status': 'MISSING',
            'closed_at': None,
            'closed_by_user_id': None,
            'comment': None,
            'revenue_total_minor': 0,
            'tips_total_minor': 0,
        }
    return {
        'exists': True,
        'report_id': int(report.id),
        'status': str(report.status or 'DRAFT').upper(),
        'closed_at': report.closed_at,
        'closed_by_user_id': int(report.closed_by_user_id) if report.closed_by_user_id is not None else None,
        'comment': report.comment,
        'revenue_total_minor': int(report.revenue_total or 0) * 100,
        'tips_total_minor': int(report.tips_total or 0) * 100,
    }


def _get_team_snapshot(*, db: Session, venue_id: int, target_date: date) -> dict:
    assignment_count = int(
        db.execute(
            select(func.count(ShiftAssignment.id))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
            )
        ).scalar()
        or 0
    )
    assigned_user_count = int(
        db.execute(
            select(func.count(distinct(ShiftAssignment.member_user_id)))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
            )
        ).scalar()
        or 0
    )
    assigned_shift_count = int(
        db.execute(
            select(func.count(distinct(ShiftAssignment.shift_id)))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
            )
        ).scalar()
        or 0
    )
    return {
        'assignment_count': assignment_count,
        'assigned_user_count': assigned_user_count,
        'assigned_shift_count': assigned_shift_count,
    }


def _get_kpi_breakdown(*, db: Session, venue_id: int, target_date: date) -> list[dict]:
    report_ids = db.execute(
        select(DailyReport.id).where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date == target_date,
            DailyReport.status == 'CLOSED',
        )
    ).scalars().all()
    if not report_ids:
        return []

    rows = db.execute(
        select(DailyReportValue.ref_id, func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .where(
            DailyReportValue.report_id.in_([int(x) for x in report_ids]),
            DailyReportValue.kind == 'KPI',
        )
        .group_by(DailyReportValue.ref_id)
    ).all()
    if not rows:
        return []

    metric_rows = db.execute(
        select(KpiMetric.id, KpiMetric.code, KpiMetric.title, KpiMetric.unit)
        .where(KpiMetric.venue_id == int(venue_id))
    ).all()
    metric_map = {int(row[0]): row for row in metric_rows}
    out = []
    for row in rows:
        ref_id = int(row[0])
        metric = metric_map.get(ref_id)
        out.append({
            'metric_id': ref_id,
            'code': metric[1] if metric else None,
            'title': metric[2] if metric else f'KPI {ref_id}',
            'unit': metric[3] if metric else 'QTY',
            'value_numeric': int(row[1] or 0),
        })
    out.sort(key=lambda item: str(item['title']))
    return out


def _safe_ratio_bps(*, numerator_minor: int, denominator_minor: int) -> int | None:
    if int(denominator_minor or 0) <= 0:
        return None
    return int((int(numerator_minor or 0) * 10000) / int(denominator_minor))


def _build_metrics(*, summary: dict, report: dict, team: dict) -> dict:
    revenue_minor = int(summary.get('revenue_minor') or 0)
    point_expense_minor = int(summary.get('point_expense_minor') or 0)
    recurring_expense_minor = int(summary.get('recurring_expense_minor') or 0)
    expense_minor = int(summary.get('expense_minor') or 0)
    payroll_minor = int(summary.get('payroll_minor') or 0)
    profit_minor = int(summary.get('profit_minor') or 0)
    assigned_user_count = int(team.get('assigned_user_count') or 0)
    tips_total_minor = int(report.get('tips_total_minor') or 0)

    if profit_minor > 0:
        result_status = 'PROFIT'
    elif profit_minor < 0:
        result_status = 'LOSS'
    else:
        result_status = 'BREAKEVEN'

    return {
        'result_status': result_status,
        'revenue_per_assigned_minor': int(revenue_minor / assigned_user_count) if assigned_user_count > 0 else None,
        'tips_per_assigned_minor': int(tips_total_minor / assigned_user_count) if assigned_user_count > 0 else None,
        'expense_ratio_bps': _safe_ratio_bps(numerator_minor=expense_minor, denominator_minor=revenue_minor),
        'point_expense_ratio_bps': _safe_ratio_bps(numerator_minor=point_expense_minor, denominator_minor=revenue_minor),
        'recurring_expense_ratio_bps': _safe_ratio_bps(numerator_minor=recurring_expense_minor, denominator_minor=revenue_minor),
        'payroll_ratio_bps': _safe_ratio_bps(numerator_minor=payroll_minor, denominator_minor=revenue_minor),
    }


def get_day_economics(*, db: Session, venue_id: int, target_date: date) -> dict:
    summary = get_day_finance_summary(db=db, venue_id=venue_id, target_date=target_date, income_mode='PAYMENTS')
    report = _get_report_state(db=db, venue_id=venue_id, target_date=target_date)
    team = _get_team_snapshot(db=db, venue_id=venue_id, target_date=target_date)
    metrics = _build_metrics(summary=summary, report=report, team=team)
    return {
        'date': target_date,
        'report': report,
        'team': team,
        'metrics': metrics,
        'summary': summary,
        'payment_revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode='PAYMENTS'),
        'department_revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode='DEPARTMENTS'),
        'kpi_breakdown': _get_kpi_breakdown(db=db, venue_id=venue_id, target_date=target_date),
    }
