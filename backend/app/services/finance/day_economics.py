from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, KpiMetric, Shift, ShiftAssignment
from app.models.day_economics_plan import DayEconomicsPlan
from app.models.day_economics_plan_template import DayEconomicsPlanTemplate
from app.models.venue_economics_rule import VenueEconomicsRule
from app.services.finance.summary import get_day_finance_summary, _group_revenue_breakdown


WEEKDAY_TITLES = {
    0: 'Понедельник',
    1: 'Вторник',
    2: 'Среда',
    3: 'Четверг',
    4: 'Пятница',
    5: 'Суббота',
    6: 'Воскресенье',
}


def _format_minor_as_rub_text(value_minor: int | None) -> str:
    minor = int(value_minor or 0)
    sign = '-' if minor < 0 else ''
    rub = abs(minor) / 100
    return f'{sign}{rub:,.2f} ₽'.replace(',', ' ')


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
    total_shift_count = int(
        db.execute(
            select(func.count(Shift.id)).where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
            )
        ).scalar()
        or 0
    )
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
    unassigned_shift_count = max(total_shift_count - assigned_shift_count, 0)
    return {
        'total_shift_count': total_shift_count,
        'assignment_count': assignment_count,
        'assigned_user_count': assigned_user_count,
        'assigned_shift_count': assigned_shift_count,
        'unassigned_shift_count': unassigned_shift_count,
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


def _build_share_breakdown(rows: list[dict]) -> list[dict]:
    total_minor = int(sum(int(item.get('amount_minor') or 0) for item in rows))
    out: list[dict] = []
    for item in rows:
        amount_minor = int(item.get('amount_minor') or 0)
        share_bps = int((amount_minor * 10000) / total_minor) if total_minor > 0 else None
        out.append({
            'title': item.get('title'),
            'code': item.get('code'),
            'amount_minor': amount_minor,
            'share_bps': share_bps,
        })
    return out


def _build_kpi_summary(kpi_breakdown: list[dict]) -> dict:
    metric_count = len(kpi_breakdown)
    nonzero_metric_count = sum(1 for item in kpi_breakdown if int(item.get('value_numeric') or 0) != 0)
    total_value_numeric = int(sum(int(item.get('value_numeric') or 0) for item in kpi_breakdown))
    return {
        'metric_count': metric_count,
        'nonzero_metric_count': nonzero_metric_count,
        'total_value_numeric': total_value_numeric,
    }


def _empty_plan(*, target_date: date, source: str = 'NONE', template_weekday: int | None = None) -> dict:
    return {
        'date': target_date,
        'source': source,
        'template_weekday': template_weekday,
        'template_weekday_title': WEEKDAY_TITLES.get(template_weekday) if template_weekday is not None else None,
        'revenue_plan_minor': None,
        'profit_plan_minor': None,
        'revenue_per_assigned_plan_minor': None,
        'assigned_user_target': None,
        'notes': None,
    }


def _serialize_plan(plan: DayEconomicsPlan | DayEconomicsPlanTemplate | None, *, target_date: date, source: str = 'DATE_OVERRIDE', template_weekday: int | None = None) -> dict:
    if plan is None:
        return _empty_plan(target_date=target_date, source=source, template_weekday=template_weekday)
    weekday = template_weekday if template_weekday is not None else (int(plan.weekday) if hasattr(plan, 'weekday') else None)
    return {
        'date': target_date,
        'source': source,
        'template_weekday': weekday,
        'template_weekday_title': WEEKDAY_TITLES.get(weekday) if weekday is not None else None,
        'revenue_plan_minor': int(plan.revenue_plan_minor) if plan.revenue_plan_minor is not None else None,
        'profit_plan_minor': int(plan.profit_plan_minor) if plan.profit_plan_minor is not None else None,
        'revenue_per_assigned_plan_minor': int(plan.revenue_per_assigned_plan_minor) if plan.revenue_per_assigned_plan_minor is not None else None,
        'assigned_user_target': int(plan.assigned_user_target) if plan.assigned_user_target is not None else None,
        'notes': plan.notes,
    }


def _get_date_override_plan_model(*, db: Session, venue_id: int, target_date: date) -> DayEconomicsPlan | None:
    return db.execute(
        select(DayEconomicsPlan).where(
            DayEconomicsPlan.venue_id == int(venue_id),
            DayEconomicsPlan.target_date == target_date,
        )
    ).scalar_one_or_none()


def _get_weekday_template_model(*, db: Session, venue_id: int, weekday: int) -> DayEconomicsPlanTemplate | None:
    return db.execute(
        select(DayEconomicsPlanTemplate).where(
            DayEconomicsPlanTemplate.venue_id == int(venue_id),
            DayEconomicsPlanTemplate.weekday == int(weekday),
        )
    ).scalar_one_or_none()


def get_day_economics_plan(*, db: Session, venue_id: int, target_date: date) -> dict:
    override = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if override is not None:
        return _serialize_plan(override, target_date=target_date, source='DATE_OVERRIDE')
    template = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=target_date.weekday())
    if template is not None:
        return _serialize_plan(template, target_date=target_date, source='WEEKDAY_TEMPLATE', template_weekday=target_date.weekday())
    return _empty_plan(target_date=target_date, source='NONE', template_weekday=target_date.weekday())


def get_day_economics_plan_override(*, db: Session, venue_id: int, target_date: date) -> dict:
    override = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if override is None:
        return _empty_plan(target_date=target_date, source='DATE_OVERRIDE', template_weekday=target_date.weekday())
    return _serialize_plan(override, target_date=target_date, source='DATE_OVERRIDE')


def upsert_day_economics_plan(
    *,
    db: Session,
    venue_id: int,
    target_date: date,
    revenue_plan_minor: int | None,
    profit_plan_minor: int | None,
    revenue_per_assigned_plan_minor: int | None,
    assigned_user_target: int | None,
    notes: str | None,
) -> dict:
    plan = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if plan is None:
        plan = DayEconomicsPlan(venue_id=int(venue_id), target_date=target_date)
        db.add(plan)
    plan.revenue_plan_minor = revenue_plan_minor
    plan.profit_plan_minor = profit_plan_minor
    plan.revenue_per_assigned_plan_minor = revenue_per_assigned_plan_minor
    plan.assigned_user_target = assigned_user_target
    plan.notes = notes or None
    db.flush()
    return _serialize_plan(plan, target_date=target_date, source='DATE_OVERRIDE')


def list_day_economics_plan_templates(*, db: Session, venue_id: int) -> list[dict]:
    rows = db.execute(
        select(DayEconomicsPlanTemplate).where(DayEconomicsPlanTemplate.venue_id == int(venue_id))
    ).scalars().all()
    by_weekday = {int(item.weekday): item for item in rows}
    result: list[dict] = []
    for weekday in range(7):
        template = by_weekday.get(weekday)
        result.append({
            'weekday': weekday,
            'weekday_title': WEEKDAY_TITLES[weekday],
            **_serialize_plan(template, target_date=date(2000, 1, 3) + timedelta(days=weekday), source='WEEKDAY_TEMPLATE', template_weekday=weekday),
        })
    return result


def upsert_day_economics_plan_template(
    *,
    db: Session,
    venue_id: int,
    weekday: int,
    revenue_plan_minor: int | None,
    profit_plan_minor: int | None,
    revenue_per_assigned_plan_minor: int | None,
    assigned_user_target: int | None,
    notes: str | None,
) -> dict:
    if int(weekday) < 0 or int(weekday) > 6:
        raise ValueError('Bad weekday, expected 0..6')
    template = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=weekday)
    if template is None:
        template = DayEconomicsPlanTemplate(venue_id=int(venue_id), weekday=int(weekday))
        db.add(template)
    template.revenue_plan_minor = revenue_plan_minor
    template.profit_plan_minor = profit_plan_minor
    template.revenue_per_assigned_plan_minor = revenue_per_assigned_plan_minor
    template.assigned_user_target = assigned_user_target
    template.notes = notes or None
    db.flush()
    return {
        'weekday': int(weekday),
        'weekday_title': WEEKDAY_TITLES[int(weekday)],
        **_serialize_plan(template, target_date=date(2000, 1, 3) + timedelta(days=int(weekday)), source='WEEKDAY_TEMPLATE', template_weekday=int(weekday)),
    }


def _serialize_rules(rule: VenueEconomicsRule | None) -> dict:
    if rule is None:
        return {
            'max_expense_ratio_bps': None,
            'max_payroll_ratio_bps': None,
            'min_revenue_per_assigned_minor': None,
            'min_assigned_shift_coverage_bps': None,
            'min_profit_minor': None,
            'warn_on_draft_expenses': True,
        }
    return {
        'max_expense_ratio_bps': int(rule.max_expense_ratio_bps) if rule.max_expense_ratio_bps is not None else None,
        'max_payroll_ratio_bps': int(rule.max_payroll_ratio_bps) if rule.max_payroll_ratio_bps is not None else None,
        'min_revenue_per_assigned_minor': int(rule.min_revenue_per_assigned_minor) if rule.min_revenue_per_assigned_minor is not None else None,
        'min_assigned_shift_coverage_bps': int(rule.min_assigned_shift_coverage_bps) if rule.min_assigned_shift_coverage_bps is not None else None,
        'min_profit_minor': int(rule.min_profit_minor) if rule.min_profit_minor is not None else None,
        'warn_on_draft_expenses': bool(rule.warn_on_draft_expenses),
    }


def get_venue_economics_rules(*, db: Session, venue_id: int) -> dict:
    rule = db.execute(
        select(VenueEconomicsRule).where(VenueEconomicsRule.venue_id == int(venue_id))
    ).scalar_one_or_none()
    return _serialize_rules(rule)


def upsert_venue_economics_rules(
    *,
    db: Session,
    venue_id: int,
    max_expense_ratio_bps: int | None,
    max_payroll_ratio_bps: int | None,
    min_revenue_per_assigned_minor: int | None,
    min_assigned_shift_coverage_bps: int | None,
    min_profit_minor: int | None,
    warn_on_draft_expenses: bool,
) -> dict:
    rule = db.execute(
        select(VenueEconomicsRule).where(VenueEconomicsRule.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if rule is None:
        rule = VenueEconomicsRule(venue_id=int(venue_id))
        db.add(rule)
    rule.max_expense_ratio_bps = max_expense_ratio_bps
    rule.max_payroll_ratio_bps = max_payroll_ratio_bps
    rule.min_revenue_per_assigned_minor = min_revenue_per_assigned_minor
    rule.min_assigned_shift_coverage_bps = min_assigned_shift_coverage_bps
    rule.min_profit_minor = min_profit_minor
    rule.warn_on_draft_expenses = bool(warn_on_draft_expenses)
    db.flush()
    return _serialize_rules(rule)


def _build_plan_fact(*, summary: dict, metrics: dict, team: dict, plan: dict) -> dict:
    revenue_fact_minor = int(summary.get('revenue_minor') or 0)
    profit_fact_minor = int(summary.get('profit_minor') or 0)
    revenue_per_assigned_fact_minor = metrics.get('revenue_per_assigned_minor')
    assigned_user_fact = int(team.get('assigned_user_count') or 0)

    revenue_plan_minor = plan.get('revenue_plan_minor')
    profit_plan_minor = plan.get('profit_plan_minor')
    revenue_per_assigned_plan_minor = plan.get('revenue_per_assigned_plan_minor')
    assigned_user_target = plan.get('assigned_user_target')

    return {
        'revenue_fact_minor': revenue_fact_minor,
        'revenue_plan_minor': revenue_plan_minor,
        'revenue_delta_minor': (revenue_fact_minor - int(revenue_plan_minor)) if revenue_plan_minor is not None else None,
        'revenue_progress_bps': _safe_ratio_bps(numerator_minor=revenue_fact_minor, denominator_minor=int(revenue_plan_minor)) if revenue_plan_minor else None,
        'profit_fact_minor': profit_fact_minor,
        'profit_plan_minor': profit_plan_minor,
        'profit_delta_minor': (profit_fact_minor - int(profit_plan_minor)) if profit_plan_minor is not None else None,
        'revenue_per_assigned_fact_minor': revenue_per_assigned_fact_minor,
        'revenue_per_assigned_plan_minor': revenue_per_assigned_plan_minor,
        'revenue_per_assigned_delta_minor': (int(revenue_per_assigned_fact_minor) - int(revenue_per_assigned_plan_minor)) if revenue_per_assigned_fact_minor is not None and revenue_per_assigned_plan_minor is not None else None,
        'assigned_user_fact': assigned_user_fact,
        'assigned_user_target': assigned_user_target,
        'assigned_user_delta': (assigned_user_fact - int(assigned_user_target)) if assigned_user_target is not None else None,
    }


def _build_alerts(*, report: dict, summary: dict, metrics: dict, plan_fact: dict, rules: dict) -> list[dict]:
    alerts: list[dict] = []

    report_status = str(report.get('status') or 'MISSING').upper()
    if report_status != 'CLOSED':
        alerts.append({
            'severity': 'WARN',
            'code': 'REPORT_NOT_CLOSED',
            'title': 'День не закрыт',
            'detail': 'Экономика дня может быть неполной, пока отчёт не закрыт.',
        })

    if bool(rules.get('warn_on_draft_expenses', True)) and int(summary.get('draft_expense_count') or 0) > 0:
        alerts.append({
            'severity': 'WARN',
            'code': 'DRAFT_EXPENSES',
            'title': 'Есть черновые расходы',
            'detail': f"{int(summary.get('draft_expense_count') or 0)} черновик(ов) на сумму {_format_minor_as_rub_text(summary.get('draft_expense_total_minor'))}.",
        })

    if int(summary.get('profit_minor') or 0) < 0:
        alerts.append({
            'severity': 'CRITICAL',
            'code': 'LOSS_DAY',
            'title': 'День убыточный',
            'detail': 'Фактическая прибыль дня ушла в минус.',
        })

    max_expense_ratio_bps = rules.get('max_expense_ratio_bps')
    expense_ratio_bps = metrics.get('expense_ratio_bps')
    if max_expense_ratio_bps is not None and expense_ratio_bps is not None and int(expense_ratio_bps) > int(max_expense_ratio_bps):
        alerts.append({
            'severity': 'WARN',
            'code': 'EXPENSE_RATIO_HIGH',
            'title': 'Расходы выше нормы',
            'detail': f'Расходы к выручке: {expense_ratio_bps / 100:.2f}% при лимите {int(max_expense_ratio_bps) / 100:.2f}%.',
        })

    max_payroll_ratio_bps = rules.get('max_payroll_ratio_bps')
    payroll_ratio_bps = metrics.get('payroll_ratio_bps')
    if max_payroll_ratio_bps is not None and payroll_ratio_bps is not None and int(payroll_ratio_bps) > int(max_payroll_ratio_bps):
        alerts.append({
            'severity': 'WARN',
            'code': 'PAYROLL_RATIO_HIGH',
            'title': 'ФОТ выше нормы',
            'detail': f'ФОТ к выручке: {payroll_ratio_bps / 100:.2f}% при лимите {int(max_payroll_ratio_bps) / 100:.2f}%.',
        })

    min_revenue_per_assigned_minor = rules.get('min_revenue_per_assigned_minor')
    revenue_per_assigned_minor = metrics.get('revenue_per_assigned_minor')
    if min_revenue_per_assigned_minor is not None and revenue_per_assigned_minor is not None and int(revenue_per_assigned_minor) < int(min_revenue_per_assigned_minor):
        alerts.append({
            'severity': 'WARN',
            'code': 'REVENUE_PER_ASSIGNED_LOW',
            'title': 'Низкая выручка на сотрудника',
            'detail': 'Выручка на сотрудника ниже заданной нормы.',
        })

    min_assigned_shift_coverage_bps = rules.get('min_assigned_shift_coverage_bps')
    coverage_bps = metrics.get('assigned_shift_coverage_bps')
    if min_assigned_shift_coverage_bps is not None and coverage_bps is not None and int(coverage_bps) < int(min_assigned_shift_coverage_bps):
        alerts.append({
            'severity': 'WARN',
            'code': 'SHIFT_COVERAGE_LOW',
            'title': 'Низкое покрытие смен',
            'detail': f'Покрытие смен: {coverage_bps / 100:.2f}% при целевом значении {int(min_assigned_shift_coverage_bps) / 100:.2f}%.',
        })

    min_profit_minor = rules.get('min_profit_minor')
    if min_profit_minor is not None and int(summary.get('profit_minor') or 0) < int(min_profit_minor):
        alerts.append({
            'severity': 'WARN',
            'code': 'PROFIT_BELOW_TARGET',
            'title': 'Прибыль ниже порога',
            'detail': 'Фактическая прибыль дня ниже заданного минимального порога.',
        })

    if plan_fact.get('revenue_delta_minor') is not None and int(plan_fact['revenue_delta_minor']) < 0:
        alerts.append({
            'severity': 'INFO',
            'code': 'REVENUE_PLAN_MISSED',
            'title': 'План по выручке не выполнен',
            'detail': 'Фактическая выручка ниже плана дня.',
        })

    if plan_fact.get('profit_delta_minor') is not None and int(plan_fact['profit_delta_minor']) < 0:
        alerts.append({
            'severity': 'INFO',
            'code': 'PROFIT_PLAN_MISSED',
            'title': 'План по прибыли не выполнен',
            'detail': 'Фактическая прибыль ниже плана дня.',
        })

    return alerts


def _build_rollup(*, db: Session, venue_id: int, target_date: date) -> dict:
    month_start = target_date.replace(day=1)
    cursor = month_start
    days: list[dict] = []
    avg_revenue_per_assigned_parts: list[int] = []
    closed_day_count = 0

    while cursor <= target_date:
        summary = get_day_finance_summary(db=db, venue_id=venue_id, target_date=cursor, income_mode='PAYMENTS')
        team = _get_team_snapshot(db=db, venue_id=venue_id, target_date=cursor)
        report = _get_report_state(db=db, venue_id=venue_id, target_date=cursor)
        if str(report.get('status') or '').upper() == 'CLOSED':
            closed_day_count += 1
        if int(summary.get('revenue_minor') or 0) > 0 or int(summary.get('expense_minor') or 0) > 0 or report.get('exists'):
            profit_minor = int(summary.get('profit_minor') or 0)
            revenue_minor = int(summary.get('revenue_minor') or 0)
            assigned_users = int(team.get('assigned_user_count') or 0)
            if assigned_users > 0:
                avg_revenue_per_assigned_parts.append(int(revenue_minor / assigned_users))
            days.append({
                'date': cursor,
                'profit_minor': profit_minor,
                'revenue_minor': revenue_minor,
            })
        cursor += timedelta(days=1)

    profit_total_minor = int(sum(int(item['profit_minor']) for item in days)) if days else 0
    avg_profit_minor = int(profit_total_minor / len(days)) if days else None
    avg_revenue_per_assigned_minor = int(sum(avg_revenue_per_assigned_parts) / len(avg_revenue_per_assigned_parts)) if avg_revenue_per_assigned_parts else None
    profitable_day_count = sum(1 for item in days if int(item['profit_minor']) > 0)
    loss_day_count = sum(1 for item in days if int(item['profit_minor']) < 0)
    best_day = max(days, key=lambda item: int(item['profit_minor'])) if days else None
    worst_day = min(days, key=lambda item: int(item['profit_minor'])) if days else None

    return {
        'month': month_start.strftime('%Y-%m'),
        'days_in_period': (target_date - month_start).days + 1,
        'evaluated_day_count': len(days),
        'closed_day_count': closed_day_count,
        'profit_total_minor': profit_total_minor,
        'avg_profit_minor': avg_profit_minor,
        'avg_revenue_per_assigned_minor': avg_revenue_per_assigned_minor,
        'profitable_day_count': profitable_day_count,
        'loss_day_count': loss_day_count,
        'best_day': best_day,
        'worst_day': worst_day,
    }


def _build_metrics(*, summary: dict, report: dict, team: dict, department_share_breakdown: list[dict], kpi_breakdown: list[dict]) -> dict:
    revenue_minor = int(summary.get('revenue_minor') or 0)
    point_expense_minor = int(summary.get('point_expense_minor') or 0)
    recurring_expense_minor = int(summary.get('recurring_expense_minor') or 0)
    expense_minor = int(summary.get('expense_minor') or 0)
    payroll_minor = int(summary.get('payroll_minor') or 0)
    profit_minor = int(summary.get('profit_minor') or 0)
    assigned_user_count = int(team.get('assigned_user_count') or 0)
    total_shift_count = int(team.get('total_shift_count') or 0)
    assigned_shift_count = int(team.get('assigned_shift_count') or 0)
    assignment_count = int(team.get('assignment_count') or 0)
    tips_total_minor = int(report.get('tips_total_minor') or 0)

    if profit_minor > 0:
        result_status = 'PROFIT'
    elif profit_minor < 0:
        result_status = 'LOSS'
    else:
        result_status = 'BREAKEVEN'

    top_department = department_share_breakdown[0] if department_share_breakdown else None
    kpi_summary = _build_kpi_summary(kpi_breakdown)

    return {
        'result_status': result_status,
        'revenue_per_assigned_minor': int(revenue_minor / assigned_user_count) if assigned_user_count > 0 else None,
        'tips_per_assigned_minor': int(tips_total_minor / assigned_user_count) if assigned_user_count > 0 else None,
        'profit_per_assigned_minor': int(profit_minor / assigned_user_count) if assigned_user_count > 0 else None,
        'revenue_per_shift_minor': int(revenue_minor / total_shift_count) if total_shift_count > 0 else None,
        'profit_per_shift_minor': int(profit_minor / total_shift_count) if total_shift_count > 0 else None,
        'assignments_per_shift': round(assignment_count / total_shift_count, 2) if total_shift_count > 0 else None,
        'assigned_shift_coverage_bps': _safe_ratio_bps(numerator_minor=assigned_shift_count, denominator_minor=total_shift_count),
        'expense_ratio_bps': _safe_ratio_bps(numerator_minor=expense_minor, denominator_minor=revenue_minor),
        'point_expense_ratio_bps': _safe_ratio_bps(numerator_minor=point_expense_minor, denominator_minor=revenue_minor),
        'recurring_expense_ratio_bps': _safe_ratio_bps(numerator_minor=recurring_expense_minor, denominator_minor=revenue_minor),
        'payroll_ratio_bps': _safe_ratio_bps(numerator_minor=payroll_minor, denominator_minor=revenue_minor),
        'top_department_title': top_department.get('title') if top_department else None,
        'top_department_share_bps': top_department.get('share_bps') if top_department else None,
        'kpi_metric_count': int(kpi_summary['metric_count']),
        'nonzero_kpi_metric_count': int(kpi_summary['nonzero_metric_count']),
        'kpi_total_value_numeric': int(kpi_summary['total_value_numeric']),
    }


def get_day_economics(*, db: Session, venue_id: int, target_date: date) -> dict:
    summary = get_day_finance_summary(db=db, venue_id=venue_id, target_date=target_date, income_mode='PAYMENTS')
    report = _get_report_state(db=db, venue_id=venue_id, target_date=target_date)
    team = _get_team_snapshot(db=db, venue_id=venue_id, target_date=target_date)
    payment_revenue_breakdown = _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode='PAYMENTS')
    department_revenue_breakdown = _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode='DEPARTMENTS')
    department_share_breakdown = _build_share_breakdown(department_revenue_breakdown)
    kpi_breakdown = _get_kpi_breakdown(db=db, venue_id=venue_id, target_date=target_date)
    metrics = _build_metrics(summary=summary, report=report, team=team, department_share_breakdown=department_share_breakdown, kpi_breakdown=kpi_breakdown)
    plan = get_day_economics_plan(db=db, venue_id=venue_id, target_date=target_date)
    rules = get_venue_economics_rules(db=db, venue_id=venue_id)
    plan_fact = _build_plan_fact(summary=summary, metrics=metrics, team=team, plan=plan)
    alerts = _build_alerts(report=report, summary=summary, metrics=metrics, plan_fact=plan_fact, rules=rules)
    rollup = _build_rollup(db=db, venue_id=venue_id, target_date=target_date)
    return {
        'date': target_date,
        'report': report,
        'team': team,
        'metrics': metrics,
        'summary': summary,
        'payment_revenue_breakdown': payment_revenue_breakdown,
        'department_revenue_breakdown': department_revenue_breakdown,
        'department_share_breakdown': department_share_breakdown,
        'kpi_breakdown': kpi_breakdown,
        'kpi_summary': _build_kpi_summary(kpi_breakdown),
        'plan': plan,
        'rules': rules,
        'plan_fact': plan_fact,
        'alerts': alerts,
        'rollup': rollup,
    }
