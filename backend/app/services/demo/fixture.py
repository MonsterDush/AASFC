from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import sqltypes

from app.core.config import settings
from app.models import (
    Adjustment,
    AdjustmentDispute,
    AdjustmentDisputeComment,
    BalanceAdjustment,
    BillingReconciliationIssue,
    DailyReport,
    DailyReportAttachment,
    DailyReportAudit,
    DailyReportTipAllocation,
    DailyReportValue,
    DayEconomicsMonthPlan,
    DayEconomicsPlan,
    DayEconomicsPlanTemplate,
    Department,
    DepartmentDayPlan,
    DepartmentMonthPlan,
    Expense,
    ExpenseAllocation,
    ExpenseCategory,
    ExpenseRecognitionEntry,
    FinanceEntry,
    KpiMetric,
    NotificationDeliveryLog,
    PayComponent,
    PayProfile,
    PayProfileAssignment,
    PaymentMethod,
    PaymentMethodTransfer,
    PayrollLine,
    PayrollRecalculationLog,
    PayrollRun,
    RecurringExpenseAccrual,
    RecurringExpenseRule,
    RecurringExpenseRulePaymentMethod,
    Shift,
    ShiftAssignment,
    ShiftComment,
    ShiftCommentMention,
    ShiftInterval,
    Supplier,
    User,
    Venue,
    VenueBillingEvent,
    VenueBillingState,
    VenueBillingTransaction,
    VenueEconomicsRule,
    VenueInvite,
    VenueMember,
    VenuePosition,
)
from app.services.demo.session import DEMO_PERSONA_OWNER


BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEMO_FIXTURE_PATH = 'app/demo/demo_fixture.json'
USER_REFERENCE_COLUMNS = {
    'accepted_user_id',
    'author_user_id',
    'calculated_by_user_id',
    'closed_by_user_id',
    'created_by_user_id',
    'member_user_id',
    'mentioned_user_id',
    'resolved_by_user_id',
    'triggered_by_user_id',
    'updated_by_user_id',
    'uploaded_by_user_id',
    'user_id',
}


@dataclass(frozen=True)
class FixtureTablePlan:
    name: str
    model: Any
    export_where: Callable[[dict[str, Any], Any], Any]
    delete_where: Callable[[dict[str, Any], Any], Any]


@dataclass
class DemoFixtureExportResult:
    fixture_path: str
    venue_id: int
    venue_name: str
    counts: dict[str, int]
    warnings: list[str]


@dataclass
class DemoFixtureResetResult:
    fixture_path: str
    venue_id: int
    venue_name: str | None
    counts: dict[str, int]
    warnings: list[str]


def _resolve_fixture_path(fixture_path: str | None = None) -> Path:
    raw = str(fixture_path or getattr(settings, 'DEMO_FIXTURE_PATH', '') or DEFAULT_DEMO_FIXTURE_PATH).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = (BACKEND_ROOT / path).resolve()
    return path


def _in_ids(column, values: set[int] | list[int] | tuple[int, ...]):
    ids = [int(v) for v in values if v is not None]
    if not ids:
        return column.in_([-1])
    return column.in_(ids)


def _serialize_scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_serialize_scalar(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_scalar(v) for k, v in value.items()}
    return value


def _restore_scalar(column, value: Any) -> Any:
    if value is None:
        return None
    col_type = getattr(column, 'type', None)
    if isinstance(col_type, sqltypes.DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(col_type, sqltypes.Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(col_type, sqltypes.Time) and isinstance(value, str):
        return time.fromisoformat(value)
    if isinstance(col_type, sqltypes.Integer) and value != '':
        return int(value)
    if isinstance(col_type, sqltypes.Numeric) and value != '':
        return Decimal(str(value))
    if isinstance(col_type, sqltypes.Boolean):
        return bool(value)
    return value


def _sanitize_export_row(plan: FixtureTablePlan, raw: dict[str, Any], *, allowed_user_ids: set[int], demo_owner_user_id: int | None, warnings: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in plan.model.__table__.columns:
        value = raw.get(column.name)
        if column.name in USER_REFERENCE_COLUMNS and value is not None and int(value) not in allowed_user_ids:
            if demo_owner_user_id is not None:
                warnings.append(f'{plan.name}.{column.name}: заменён внешний user_id={value} на demo owner {demo_owner_user_id}')
                value = demo_owner_user_id
        out[column.name] = _serialize_scalar(value)
    return out


def _deserialize_row(plan: FixtureTablePlan, raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in plan.model.__table__.columns:
        if column.name not in raw:
            continue
        out[column.name] = _restore_scalar(column, raw.get(column.name))
    return out


def _collect_live_context(db: Session, venue_id: int) -> dict[str, Any]:
    venue_tbl = Venue.__table__
    user_tbl = User.__table__
    member_tbl = VenueMember.__table__
    shift_tbl = Shift.__table__
    report_tbl = DailyReport.__table__
    expense_tbl = Expense.__table__
    recurring_tbl = RecurringExpenseRule.__table__
    pay_profile_tbl = PayProfile.__table__
    payroll_run_tbl = PayrollRun.__table__
    adjustment_tbl = Adjustment.__table__

    venue_row = db.execute(select(venue_tbl).where(venue_tbl.c.id == int(venue_id))).mappings().first()
    if venue_row is None:
        raise ValueError(f'Venue #{int(venue_id)} not found')

    demo_user_ids = {
        int(row[0])
        for row in db.execute(
            select(user_tbl.c.id)
            .select_from(member_tbl.join(user_tbl, user_tbl.c.id == member_tbl.c.user_id))
            .where(member_tbl.c.venue_id == int(venue_id), user_tbl.c.is_demo_user.is_(True))
        ).all()
    }
    owner_row = db.execute(
        select(user_tbl.c.id)
        .select_from(member_tbl.join(user_tbl, user_tbl.c.id == member_tbl.c.user_id))
        .where(
            member_tbl.c.venue_id == int(venue_id),
            member_tbl.c.is_active.is_(True),
            user_tbl.c.is_demo_user.is_(True),
            user_tbl.c.demo_persona == DEMO_PERSONA_OWNER,
        )
        .order_by(user_tbl.c.id.asc())
    ).first()
    demo_owner_user_id = int(owner_row[0]) if owner_row else (min(demo_user_ids) if demo_user_ids else None)

    ctx = {
        'venue_id': int(venue_id),
        'venue_name': str(venue_row.get('name') or ''),
        'fixture_user_ids': set(demo_user_ids),
        'live_demo_user_ids': set(demo_user_ids),
        'all_demo_user_ids': set(demo_user_ids),
        'demo_owner_user_id': demo_owner_user_id,
    }

    def load_ids(table, where_clause):
        return {int(row[0]) for row in db.execute(select(table.c.id).where(where_clause)).all()}

    ctx['venue_position_ids'] = load_ids(VenuePosition.__table__, VenuePosition.__table__.c.venue_id == int(venue_id))
    ctx['shift_interval_ids'] = load_ids(ShiftInterval.__table__, ShiftInterval.__table__.c.venue_id == int(venue_id))
    ctx['shift_ids'] = load_ids(shift_tbl, shift_tbl.c.venue_id == int(venue_id))
    ctx['shift_assignment_ids'] = load_ids(ShiftAssignment.__table__, _in_ids(ShiftAssignment.__table__.c.shift_id, ctx['shift_ids']))
    ctx['shift_comment_ids'] = load_ids(ShiftComment.__table__, _in_ids(ShiftComment.__table__.c.shift_id, ctx['shift_ids']))
    ctx['daily_report_ids'] = load_ids(report_tbl, report_tbl.c.venue_id == int(venue_id))
    ctx['expense_ids'] = load_ids(expense_tbl, expense_tbl.c.venue_id == int(venue_id))
    ctx['recurring_rule_ids'] = load_ids(recurring_tbl, recurring_tbl.c.venue_id == int(venue_id))
    ctx['pay_profile_ids'] = load_ids(pay_profile_tbl, pay_profile_tbl.c.venue_id == int(venue_id))
    ctx['payroll_run_ids'] = load_ids(payroll_run_tbl, payroll_run_tbl.c.venue_id == int(venue_id))
    ctx['adjustment_ids'] = load_ids(adjustment_tbl, adjustment_tbl.c.venue_id == int(venue_id))
    ctx['adjustment_dispute_ids'] = load_ids(AdjustmentDispute.__table__, AdjustmentDispute.__table__.c.venue_id == int(venue_id))
    return ctx


def _collect_reset_context(db: Session, fixture: dict[str, Any], venue_id: int) -> dict[str, Any]:
    ctx = _collect_live_context(db, venue_id)
    fixture_user_ids = {int(row['id']) for row in fixture.get('tables', {}).get('users', []) if row.get('id') is not None}
    ctx['fixture_user_ids'] = fixture_user_ids
    ctx['all_demo_user_ids'] = set(ctx.get('live_demo_user_ids', set())) | fixture_user_ids
    if ctx.get('demo_owner_user_id') is None:
        owner_rows = [row for row in fixture.get('tables', {}).get('users', []) if str(row.get('demo_persona') or '').upper() == DEMO_PERSONA_OWNER]
        if owner_rows:
            ctx['demo_owner_user_id'] = int(owner_rows[0]['id'])
    return ctx


def _fixture_table_plans() -> list[FixtureTablePlan]:
    return [
        FixtureTablePlan('venues', Venue, lambda c, t: t.c.id == c['venue_id'], lambda c, t: t.c.id == c['venue_id']),
        FixtureTablePlan('users', User, lambda c, t: _in_ids(t.c.id, c['fixture_user_ids']), lambda c, t: t.c.is_demo_user.is_(True) & _in_ids(t.c.id, c['all_demo_user_ids'])),
        FixtureTablePlan('venue_members', VenueMember, lambda c, t: (t.c.venue_id == c['venue_id']) & _in_ids(t.c.user_id, c['fixture_user_ids']), lambda c, t: (t.c.venue_id == c['venue_id']) & _in_ids(t.c.user_id, c['all_demo_user_ids'])),
        FixtureTablePlan('venue_positions', VenuePosition, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('venue_invites', VenueInvite, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('departments', Department, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('payment_methods', PaymentMethod, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('kpi_metrics', KpiMetric, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('shift_intervals', ShiftInterval, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('shifts', Shift, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('shift_assignments', ShiftAssignment, lambda c, t: _in_ids(t.c.shift_id, c['shift_ids']), lambda c, t: _in_ids(t.c.shift_id, c['shift_ids'])),
        FixtureTablePlan('shift_comments', ShiftComment, lambda c, t: _in_ids(t.c.shift_id, c['shift_ids']), lambda c, t: _in_ids(t.c.shift_id, c['shift_ids'])),
        FixtureTablePlan('shift_comment_mentions', ShiftCommentMention, lambda c, t: _in_ids(t.c.comment_id, c['shift_comment_ids']), lambda c, t: _in_ids(t.c.comment_id, c['shift_comment_ids'])),
        FixtureTablePlan('daily_reports', DailyReport, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('daily_report_values', DailyReportValue, lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids']), lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids'])),
        FixtureTablePlan('daily_report_audits', DailyReportAudit, lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids']), lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids'])),
        FixtureTablePlan('daily_report_tip_allocations', DailyReportTipAllocation, lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids']), lambda c, t: _in_ids(t.c.report_id, c['daily_report_ids'])),
        FixtureTablePlan('daily_report_attachments', DailyReportAttachment, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('expense_categories', ExpenseCategory, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('suppliers', Supplier, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('recurring_expense_rules', RecurringExpenseRule, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('recurring_expense_rule_payment_methods', RecurringExpenseRulePaymentMethod, lambda c, t: _in_ids(t.c.rule_id, c['recurring_rule_ids']), lambda c, t: _in_ids(t.c.rule_id, c['recurring_rule_ids'])),
        FixtureTablePlan('recurring_expense_accruals', RecurringExpenseAccrual, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('expenses', Expense, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('expense_allocations', ExpenseAllocation, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('expense_recognition_entries', ExpenseRecognitionEntry, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('finance_entries', FinanceEntry, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('balance_adjustments', BalanceAdjustment, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('payment_method_transfers', PaymentMethodTransfer, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('day_economics_month_plans', DayEconomicsMonthPlan, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('day_economics_plan_templates', DayEconomicsPlanTemplate, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('day_economics_plans', DayEconomicsPlan, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('department_month_plans', DepartmentMonthPlan, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('department_day_plans', DepartmentDayPlan, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('venue_economics_rules', VenueEconomicsRule, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('pay_profiles', PayProfile, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('pay_profile_assignments', PayProfileAssignment, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('pay_components', PayComponent, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('payroll_runs', PayrollRun, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('payroll_lines', PayrollLine, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('payroll_recalculation_logs', PayrollRecalculationLog, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('adjustments', Adjustment, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('adjustment_disputes', AdjustmentDispute, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('adjustment_dispute_comments', AdjustmentDisputeComment, lambda c, t: _in_ids(t.c.dispute_id, c['adjustment_dispute_ids']), lambda c, t: _in_ids(t.c.dispute_id, c['adjustment_dispute_ids'])),
        FixtureTablePlan('venue_billing_state', VenueBillingState, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('venue_billing_transactions', VenueBillingTransaction, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('venue_billing_events', VenueBillingEvent, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
        FixtureTablePlan('billing_reconciliation_issue', BillingReconciliationIssue, lambda c, t: t.c.venue_id == c['venue_id'], lambda c, t: t.c.venue_id == c['venue_id']),
    ]


def export_demo_fixture(db: Session, *, venue_id: int, fixture_path: str | None = None) -> DemoFixtureExportResult:
    ctx = _collect_live_context(db, int(venue_id))
    plans = _fixture_table_plans()
    warnings: list[str] = []
    tables: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}

    for plan in plans:
        table = plan.model.__table__
        rows = db.execute(select(table).where(plan.export_where(ctx, table)).order_by(table.c.id.asc())).mappings().all()
        serialized = [
            _sanitize_export_row(plan, dict(row), allowed_user_ids=set(ctx['fixture_user_ids']), demo_owner_user_id=ctx.get('demo_owner_user_id'), warnings=warnings)
            for row in rows
        ]
        tables[plan.name] = serialized
        counts[plan.name] = len(serialized)

    payload = {
        'meta': {
            'version': 1,
            'exported_at': datetime.utcnow().isoformat(),
            'venue_id': int(ctx['venue_id']),
            'venue_name': ctx.get('venue_name'),
            'reference_year': None,
            'reference_month': None,
            'table_order': [plan.name for plan in plans],
            'counts': counts,
            'warnings': warnings,
        },
        'tables': tables,
    }
    venue_rows = tables.get('venues') or []
    if venue_rows:
        payload['meta']['reference_year'] = venue_rows[0].get('demo_reference_year')
        payload['meta']['reference_month'] = venue_rows[0].get('demo_reference_month')

    path = _resolve_fixture_path(fixture_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return DemoFixtureExportResult(
        fixture_path=str(path),
        venue_id=int(ctx['venue_id']),
        venue_name=str(ctx.get('venue_name') or ''),
        counts=counts,
        warnings=warnings,
    )


def load_demo_fixture(*, fixture_path: str | None = None) -> dict[str, Any]:
    path = _resolve_fixture_path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f'DEMO fixture not found: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def clear_demo_venue_data(db: Session, *, venue_id: int) -> dict[str, int]:
    ctx = _collect_live_context(db, int(venue_id))
    plans = [plan for plan in _fixture_table_plans() if plan.name != 'venues']
    deleted: dict[str, int] = {}
    for plan in reversed(plans):
        table = plan.model.__table__
        result = db.execute(delete(table).where(plan.delete_where(ctx, table)))
        deleted[plan.name] = int(result.rowcount or 0)
    return deleted


def reset_demo_fixture(db: Session, *, fixture_path: str | None = None, venue_id: int | None = None) -> DemoFixtureResetResult:
    fixture = load_demo_fixture(fixture_path=fixture_path)
    meta = fixture.get('meta', {}) or {}
    fixture_venue_id = meta.get('venue_id')
    target_venue_id = int(venue_id if venue_id is not None else fixture_venue_id)
    if not target_venue_id:
        raise ValueError('Fixture does not contain venue_id and venue_id was not provided')
    if fixture_venue_id is not None and int(fixture_venue_id) != int(target_venue_id):
        raise ValueError('Fixture venue_id does not match target venue_id')

    ctx = _collect_reset_context(db, fixture, int(target_venue_id))
    plans = _fixture_table_plans()
    tables = fixture.get('tables', {}) or {}
    warnings = list(meta.get('warnings') or [])
    counts: dict[str, int] = {}

    for plan in reversed(plans):
        table = plan.model.__table__
        db.execute(delete(table).where(plan.delete_where(ctx, table)))

    for plan in plans:
        raw_rows = list(tables.get(plan.name) or [])
        counts[plan.name] = len(raw_rows)
        if not raw_rows:
            continue
        rows = [_deserialize_row(plan, raw) for raw in raw_rows]
        db.execute(plan.model.__table__.insert(), rows)

    _reseed_fixture_sequences(db, plans)
    venue_name = None
    venue_rows = tables.get('venues') or []
    if venue_rows:
        venue_name = venue_rows[0].get('name')

    return DemoFixtureResetResult(
        fixture_path=str(_resolve_fixture_path(fixture_path)),
        venue_id=int(target_venue_id),
        venue_name=venue_name,
        counts=counts,
        warnings=warnings,
    )


def _reseed_fixture_sequences(db: Session, plans: list[FixtureTablePlan]) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != 'postgresql':
        return
    for plan in plans:
        table = plan.model.__table__
        pk_cols = [col for col in table.columns if col.primary_key and isinstance(col.type, sqltypes.Integer)]
        if not pk_cols:
            continue
        pk = pk_cols[0]
        db.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), COALESCE((SELECT MAX({pk.name}) FROM {table.name}), 1), true)"
        ))


def get_demo_fixture_status(db: Session, *, fixture_path: str | None = None) -> dict[str, Any]:
    path = _resolve_fixture_path(fixture_path)
    exists = path.exists()
    meta: dict[str, Any] = {}
    if exists:
        try:
            meta = (json.loads(path.read_text(encoding='utf-8')).get('meta', {}) or {})
        except Exception as exc:
            meta = {'error': str(exc)}

    venue = db.execute(select(Venue.__table__).where(Venue.__table__.c.is_demo.is_(True)).order_by(Venue.__table__.c.id.asc()).limit(1)).mappings().first()
    venue_id = int(venue['id']) if venue else None
    owner_exists = False
    staff_exists = False
    demo_users_total = 0
    if venue_id is not None:
        user_tbl = User.__table__
        member_tbl = VenueMember.__table__
        demo_users_total = int(db.execute(
            select(text('count(*)'))
            .select_from(member_tbl.join(user_tbl, user_tbl.c.id == member_tbl.c.user_id))
            .where(member_tbl.c.venue_id == venue_id, user_tbl.c.is_demo_user.is_(True))
        ).scalar() or 0)
        owner_exists = db.execute(
            select(user_tbl.c.id)
            .select_from(member_tbl.join(user_tbl, user_tbl.c.id == member_tbl.c.user_id))
            .where(member_tbl.c.venue_id == venue_id, user_tbl.c.is_demo_user.is_(True), user_tbl.c.demo_persona == 'OWNER')
            .limit(1)
        ).first() is not None
        staff_exists = db.execute(
            select(user_tbl.c.id)
            .select_from(member_tbl.join(user_tbl, user_tbl.c.id == member_tbl.c.user_id))
            .where(member_tbl.c.venue_id == venue_id, user_tbl.c.is_demo_user.is_(True), user_tbl.c.demo_persona == 'STAFF')
            .limit(1)
        ).first() is not None

    return {
        'fixture_path': str(path),
        'fixture_exists': exists,
        'fixture_meta': meta,
        'enabled': venue is not None,
        'venue': dict(venue) if venue is not None else None,
        'personas': {
            'OWNER': owner_exists,
            'STAFF': staff_exists,
        },
        'demo_users_total': demo_users_total,
    }
