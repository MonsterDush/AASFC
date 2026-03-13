from __future__ import annotations

from datetime import date, datetime
import calendar

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    DailyReportValue,
    Expense,
    ExpenseCategory,
    PaymentMethod,
    RecurringExpenseAccrual,
    RecurringExpenseRule,
    RecurringExpenseRulePaymentMethod,
)
from app.services.finance.expenses import rebuild_expense_allocations_for_expense


VALID_GENERATION_MODES = {"FIXED", "PERCENT"}
VALID_FREQUENCIES = {"MONTHLY"}


def parse_month_start(month: str) -> date:
    try:
        year_s, month_s = str(month or "").split("-")
        year = int(year_s)
        month_num = int(month_s)
        return date(year, month_num, 1)
    except Exception:
        raise ValueError("Bad month format, expected YYYY-MM")


def month_bounds(month: str) -> tuple[date, date]:
    month_start = parse_month_start(month)
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start, month_start.replace(day=last_day)


def replace_rule_payment_methods(*, db: Session, rule_id: int, payment_method_ids: list[int]) -> None:
    normalized = sorted({int(x) for x in payment_method_ids or []})
    db.execute(delete(RecurringExpenseRulePaymentMethod).where(RecurringExpenseRulePaymentMethod.rule_id == int(rule_id)))
    for payment_method_id in normalized:
        db.add(
            RecurringExpenseRulePaymentMethod(
                rule_id=int(rule_id),
                payment_method_id=payment_method_id,
            )
        )


def list_rule_payment_method_ids(*, db: Session, rule_id: int) -> list[int]:
    rows = db.execute(
        select(RecurringExpenseRulePaymentMethod.payment_method_id)
        .where(RecurringExpenseRulePaymentMethod.rule_id == int(rule_id))
        .order_by(RecurringExpenseRulePaymentMethod.id.asc())
    ).scalars().all()
    return [int(x) for x in rows]


def normalize_rule_fields(*, generation_mode: str, frequency: str, amount_minor: int | None, percent_bps: int | None) -> tuple[str, str, int | None, int | None]:
    mode = str(generation_mode or "FIXED").strip().upper()
    if mode not in VALID_GENERATION_MODES:
        raise ValueError("Bad generation_mode, expected FIXED or PERCENT")

    freq = str(frequency or "MONTHLY").strip().upper()
    if freq not in VALID_FREQUENCIES:
        raise ValueError("Bad frequency, expected MONTHLY")

    amt = int(amount_minor) if amount_minor is not None else None
    pct = int(percent_bps) if percent_bps is not None else None

    if mode == "FIXED":
        if amt is None or amt < 0:
            raise ValueError("amount_minor is required for FIXED mode")
        pct = None
    else:
        if pct is None or pct < 0:
            raise ValueError("percent_bps is required for PERCENT mode")
        amt = None

    return mode, freq, amt, pct


def rule_applies_to_month(*, rule: RecurringExpenseRule, month_start: date, month_end: date) -> bool:
    if not bool(rule.is_active):
        return False
    if rule.start_date and rule.start_date > month_end:
        return False
    if rule.end_date and rule.end_date < month_start:
        return False
    return True


def rule_applies_to_date(*, rule: RecurringExpenseRule, target_date: date) -> bool:
    if not bool(rule.is_active):
        return False
    if rule.start_date and rule.start_date > target_date:
        return False
    if rule.end_date and rule.end_date < target_date:
        return False
    return True


def build_generated_expense_date(*, month_start: date, day_of_month: int) -> date:
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(max(int(day_of_month or 1), 1), last_day))


def _sum_closed_payment_base_minor(*, db: Session, venue_id: int, period_start: date, period_end: date, payment_method_ids: list[int] | None = None) -> int:
    stmt = (
        select(func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .select_from(DailyReportValue)
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == 'CLOSED',
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
            DailyReportValue.kind == 'PAYMENT',
        )
    )
    if payment_method_ids:
        stmt = stmt.where(DailyReportValue.ref_id.in_([int(x) for x in payment_method_ids]))
    return int(db.execute(stmt).scalar() or 0) * 100


def calculate_rule_amount_minor(*, db: Session, rule: RecurringExpenseRule, month_start: date, month_end: date) -> int:
    mode = str(rule.generation_mode or "FIXED").upper()
    if mode == "FIXED":
        return int(rule.amount_minor or 0)

    payment_method_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
    base_minor = _sum_closed_payment_base_minor(
        db=db,
        venue_id=int(rule.venue_id),
        period_start=month_start,
        period_end=month_end,
        payment_method_ids=payment_method_ids,
    )
    percent_bps = int(rule.percent_bps or 0)
    return int((base_minor * percent_bps + 5000) // 10000)


def build_generated_comment(*, db: Session, rule: RecurringExpenseRule, month: str) -> str:
    base = f"[REGULAR] {rule.title} · {month}"
    if str(rule.generation_mode or "FIXED").upper() == "FIXED":
        return f"{base} · фикс"
    payment_method_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
    if payment_method_ids:
        names = db.execute(
            select(PaymentMethod.title)
            .where(PaymentMethod.id.in_(payment_method_ids))
            .order_by(PaymentMethod.title.asc())
        ).scalars().all()
        joined = ", ".join(str(x) for x in names)
    else:
        joined = "всех оплат"
    percent_value = (int(rule.percent_bps or 0) / 100)
    return f"{base} · {percent_value:.2f}% от {joined}"


def _fixed_rule_daily_minor(*, rule: RecurringExpenseRule, target_date: date) -> int:
    month_start = target_date.replace(day=1)
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    month_end = target_date.replace(day=last_day)
    active_start = max(month_start, rule.start_date or month_start)
    active_end = min(month_end, rule.end_date or month_end)
    if target_date < active_start or target_date > active_end:
        return 0
    active_days = (active_end - active_start).days + 1
    if active_days <= 0:
        return 0
    total_minor = int(rule.amount_minor or 0)
    base = total_minor // active_days
    remainder = total_minor % active_days
    day_index = (target_date - active_start).days
    return base + (1 if day_index < remainder else 0)


def _percent_rule_daily_minor(*, db: Session, rule: RecurringExpenseRule, target_date: date) -> tuple[int, int]:
    payment_method_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
    base_minor = _sum_closed_payment_base_minor(
        db=db,
        venue_id=int(rule.venue_id),
        period_start=target_date,
        period_end=target_date,
        payment_method_ids=payment_method_ids,
    )
    percent_bps = int(rule.percent_bps or 0)
    amount_minor = int((base_minor * percent_bps + 5000) // 10000)
    return base_minor, amount_minor


def sync_daily_recurring_accruals_for_date(*, db: Session, venue_id: int, target_date: date) -> dict:
    rules = db.execute(
        select(RecurringExpenseRule)
        .where(RecurringExpenseRule.venue_id == int(venue_id))
        .order_by(RecurringExpenseRule.id.asc())
    ).scalars().all()

    created = 0
    updated = 0
    deleted = 0
    kept_ids: set[int] = set()

    for rule in rules:
        if not rule_applies_to_date(rule=rule, target_date=target_date):
            continue
        mode = str(rule.generation_mode or 'FIXED').upper()
        basis_minor = None
        if mode == 'FIXED':
            amount_minor = _fixed_rule_daily_minor(rule=rule, target_date=target_date)
        else:
            basis_minor, amount_minor = _percent_rule_daily_minor(db=db, rule=rule, target_date=target_date)

        existing = db.execute(
            select(RecurringExpenseAccrual).where(
                RecurringExpenseAccrual.rule_id == int(rule.id),
                RecurringExpenseAccrual.accrual_date == target_date,
            )
        ).scalar_one_or_none()

        if amount_minor <= 0:
            if existing is not None:
                db.delete(existing)
                deleted += 1
            continue

        meta_json = {
            'generation_mode': mode,
            'payment_method_id': int(rule.payment_method_id) if rule.payment_method_id is not None else None,
            'category_id': int(rule.category_id),
            'supplier_id': int(rule.supplier_id) if rule.supplier_id is not None else None,
        }
        if basis_minor is not None:
            meta_json['basis_minor'] = int(basis_minor)
            meta_json['basis_payment_method_ids'] = list_rule_payment_method_ids(db=db, rule_id=rule.id)

        if existing is None:
            db.add(
                RecurringExpenseAccrual(
                    rule_id=int(rule.id),
                    venue_id=int(venue_id),
                    accrual_date=target_date,
                    amount_minor=int(amount_minor),
                    basis_minor=int(basis_minor) if basis_minor is not None else None,
                    meta_json=meta_json,
                    created_at=datetime.utcnow(),
                )
            )
            created += 1
        else:
            existing.amount_minor = int(amount_minor)
            existing.basis_minor = int(basis_minor) if basis_minor is not None else None
            existing.meta_json = meta_json
            existing.updated_at = datetime.utcnow()
            updated += 1
            kept_ids.add(int(existing.id))

    return {
        'date': target_date,
        'created': created,
        'updated': updated,
        'deleted': deleted,
    }


def delete_daily_recurring_accruals_for_date(*, db: Session, venue_id: int, target_date: date) -> int:
    deleted = db.execute(
        delete(RecurringExpenseAccrual).where(
            RecurringExpenseAccrual.venue_id == int(venue_id),
            RecurringExpenseAccrual.accrual_date == target_date,
        )
    )
    return int(deleted.rowcount or 0)


def get_daily_recurring_expense_summary(*, db: Session, venue_id: int, target_date: date) -> dict:
    rows = db.execute(
        select(
            RecurringExpenseRule.title,
            ExpenseCategory.code,
            ExpenseCategory.title,
            func.coalesce(func.sum(RecurringExpenseAccrual.amount_minor), 0),
        )
        .select_from(RecurringExpenseAccrual)
        .join(RecurringExpenseRule, RecurringExpenseRule.id == RecurringExpenseAccrual.rule_id)
        .join(ExpenseCategory, ExpenseCategory.id == RecurringExpenseRule.category_id)
        .where(
            RecurringExpenseAccrual.venue_id == int(venue_id),
            RecurringExpenseAccrual.accrual_date == target_date,
        )
        .group_by(RecurringExpenseRule.title, ExpenseCategory.code, ExpenseCategory.title)
        .order_by(func.coalesce(func.sum(RecurringExpenseAccrual.amount_minor), 0).desc(), RecurringExpenseRule.title.asc())
    ).all()
    out = [
        {
            'title': row[0],
            'code': row[1],
            'subtitle': row[2],
            'amount_minor': int(row[3] or 0),
        }
        for row in rows
    ]
    total_minor = int(sum(int(item['amount_minor']) for item in out))
    return {
        'date': target_date,
        'rows': out,
        'total_minor': int(total_minor),
    }


def generate_draft_expenses_for_month(
    *,
    db: Session,
    venue_id: int,
    month: str,
    created_by_user_id: int | None = None,
    rule_id: int | None = None,
) -> dict:
    month_start, month_end = month_bounds(month)
    stmt = select(RecurringExpenseRule).where(RecurringExpenseRule.venue_id == int(venue_id))
    if rule_id is not None:
        stmt = stmt.where(RecurringExpenseRule.id == int(rule_id))
    rules = db.execute(stmt.order_by(RecurringExpenseRule.id.asc())).scalars().all()

    created: list[Expense] = []
    updated: list[Expense] = []
    skipped: list[dict] = []

    for rule in rules:
        if not rule_applies_to_month(rule=rule, month_start=month_start, month_end=month_end):
            skipped.append({"rule_id": int(rule.id), "title": rule.title, "reason": "inactive_for_month"})
            continue

        existing = db.execute(
            select(Expense).where(
                Expense.venue_id == int(venue_id),
                Expense.recurring_rule_id == int(rule.id),
                Expense.generated_for_month == month_start,
            )
        ).scalar_one_or_none()

        amount_minor = calculate_rule_amount_minor(db=db, rule=rule, month_start=month_start, month_end=month_end)
        if existing is not None:
            existing_status = str(getattr(existing, 'status', 'DRAFT') or 'DRAFT').upper()
            if existing_status != 'DRAFT':
                skipped.append({
                    "rule_id": int(rule.id),
                    "title": rule.title,
                    "reason": f"already_{existing_status.lower()}",
                    "expense_id": int(existing.id),
                })
                continue
            if amount_minor <= 0:
                skipped.append({
                    "rule_id": int(rule.id),
                    "title": rule.title,
                    "reason": "zero_amount",
                    "expense_id": int(existing.id),
                })
                continue
            existing.category_id = int(rule.category_id)
            existing.supplier_id = int(rule.supplier_id) if rule.supplier_id is not None else None
            existing.payment_method_id = int(rule.payment_method_id) if rule.payment_method_id is not None else None
            existing.amount_minor = int(amount_minor)
            existing.expense_date = build_generated_expense_date(month_start=month_start, day_of_month=int(rule.day_of_month or 1))
            existing.generated_for_month = month_start
            existing.spread_months = int(rule.spread_months or 1)
            existing.comment = build_generated_comment(db=db, rule=rule, month=month)
            existing.updated_at = datetime.utcnow()
            rebuild_expense_allocations_for_expense(db=db, expense=existing)
            updated.append(existing)
            continue

        if amount_minor <= 0:
            skipped.append({"rule_id": int(rule.id), "title": rule.title, "reason": "zero_amount"})
            continue

        expense = Expense(
            venue_id=int(venue_id),
            category_id=int(rule.category_id),
            supplier_id=int(rule.supplier_id) if rule.supplier_id is not None else None,
            payment_method_id=int(rule.payment_method_id) if rule.payment_method_id is not None else None,
            recurring_rule_id=int(rule.id),
            amount_minor=int(amount_minor),
            expense_date=build_generated_expense_date(month_start=month_start, day_of_month=int(rule.day_of_month or 1)),
            generated_for_month=month_start,
            spread_months=int(rule.spread_months or 1),
            comment=build_generated_comment(db=db, rule=rule, month=month),
            status="DRAFT",
            created_by_user_id=created_by_user_id,
            created_at=datetime.utcnow(),
        )
        db.add(expense)
        db.flush()
        rebuild_expense_allocations_for_expense(db=db, expense=expense)
        created.append(expense)

    return {
        "month": month,
        "created": created,
        "created_count": len(created),
        "updated": updated,
        "updated_count": len(updated),
        "skipped": skipped,
        "skipped_count": len(skipped),
    }
