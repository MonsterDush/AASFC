from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, Expense, FinanceEntry, PayrollLine, PayrollPaymentSettings, PayrollRun
from app.services.finance.summary import get_finance_summary, resolve_finance_period


def _ledger_source_totals(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    direction: str,
    kind: str,
) -> tuple[int, dict[tuple[str, int | None], dict]]:
    rows = db.execute(
        select(
            FinanceEntry.source_type,
            FinanceEntry.source_id,
            func.coalesce(func.sum(FinanceEntry.amount_minor), 0),
            func.count(FinanceEntry.id),
        )
        .where(
            FinanceEntry.venue_id == int(venue_id),
            FinanceEntry.entry_date >= period_start,
            FinanceEntry.entry_date <= period_end,
            FinanceEntry.direction == str(direction).upper(),
            FinanceEntry.kind == str(kind).upper(),
        )
        .group_by(FinanceEntry.source_type, FinanceEntry.source_id)
    ).all()
    by_source: dict[tuple[str, int | None], dict] = {}
    total_minor = 0
    for source_type, source_id, amount_minor, entry_count in rows:
        source_key = (
            str(source_type or "").strip().lower(),
            int(source_id) if source_id is not None else None,
        )
        amount = int(amount_minor or 0)
        by_source[source_key] = {
            "amount_minor": amount,
            "entry_count": int(entry_count or 0),
        }
        total_minor += amount
    return total_minor, by_source


def _source_issue(
    *,
    check_key: str,
    source_type: str,
    source_id: int | None,
    source_date: date | None,
    expected_minor: int,
    ledger_minor: int,
    entry_count: int,
    direction: str,
    kind: str,
) -> dict:
    delta_minor = int(ledger_minor or 0) - int(expected_minor or 0)
    if expected_minor and not ledger_minor:
        reason = "MISSING_LEDGER_ENTRY"
    elif ledger_minor and not expected_minor:
        reason = "EXTRA_LEDGER_ENTRY"
    else:
        reason = "AMOUNT_MISMATCH"
    return {
        "check_key": check_key,
        "source_type": source_type,
        "source_id": int(source_id) if source_id is not None else None,
        "source_date": source_date,
        "expected_minor": int(expected_minor or 0),
        "ledger_minor": int(ledger_minor or 0),
        "delta_minor": delta_minor,
        "entry_count": int(entry_count or 0),
        "reason": reason,
        "direction": direction,
        "kind": kind,
    }


def _compare_sources(
    *,
    check_key: str,
    source_type: str,
    expected: dict[int, dict],
    ledger: dict[tuple[str, int | None], dict],
    direction: str,
    kind: str,
) -> list[dict]:
    issues: list[dict] = []
    expected_ids = set(expected)
    actual_ids = {
        source_id
        for (actual_source_type, source_id) in ledger
        if actual_source_type == source_type and source_id is not None
    }
    for source_id in sorted(expected_ids | actual_ids):
        source = expected.get(int(source_id), {})
        actual = ledger.get((source_type, int(source_id)), {})
        expected_minor = int(source.get("amount_minor") or 0)
        ledger_minor = int(actual.get("amount_minor") or 0)
        if expected_minor == ledger_minor:
            continue
        issues.append(
            _source_issue(
                check_key=check_key,
                source_type=source_type,
                source_id=int(source_id),
                source_date=source.get("source_date"),
                expected_minor=expected_minor,
                ledger_minor=ledger_minor,
                entry_count=int(actual.get("entry_count") or 0),
                direction=direction,
                kind=kind,
            )
        )

    for (actual_source_type, source_id), actual in ledger.items():
        if actual_source_type == source_type and source_id is not None:
            continue
        issues.append(
            _source_issue(
                check_key=check_key,
                source_type=actual_source_type or "unknown",
                source_id=source_id,
                source_date=None,
                expected_minor=0,
                ledger_minor=int(actual.get("amount_minor") or 0),
                entry_count=int(actual.get("entry_count") or 0),
                direction=direction,
                kind=kind,
            )
        )
    return issues


def _is_complete_calendar_month_range(period_start: date, period_end: date) -> bool:
    if period_start.day != 1:
        return False
    return period_end.day == calendar.monthrange(period_end.year, period_end.month)[1]


def build_finance_reconciliation(
    *,
    db: Session,
    venue_id: int,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    period_start, period_end = resolve_finance_period(month, date_from, date_to)
    summary = get_finance_summary(
        db=db,
        venue_id=int(venue_id),
        month=month,
        date_from=date_from,
        date_to=date_to,
        include_series=False,
    )

    revenue_total, revenue_ledger = _ledger_source_totals(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction="INCOME",
        kind="REVENUE",
    )
    report_rows = db.execute(
        select(DailyReport.id, DailyReport.date, DailyReport.revenue_total)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .order_by(DailyReport.date.asc(), DailyReport.id.asc())
    ).all()
    revenue_expected = {
        int(report_id): {
            "source_date": report_date,
            "amount_minor": int(revenue_total_major or 0) * 100,
        }
        for report_id, report_date, revenue_total_major in report_rows
    }
    revenue_issues = _compare_sources(
        check_key="revenue",
        source_type="daily_report",
        expected=revenue_expected,
        ledger=revenue_ledger,
        direction="INCOME",
        kind="REVENUE",
    )
    revenue_delta = int(revenue_total) - int(summary.get("revenue_minor") or 0)

    expense_total, expense_ledger = _ledger_source_totals(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction="EXPENSE",
        kind="EXPENSE",
    )
    expense_rows = db.execute(
        select(Expense.id, Expense.expense_date, Expense.amount_minor)
        .where(
            Expense.venue_id == int(venue_id),
            Expense.status == "CONFIRMED",
            Expense.expense_kind == "OPERATING",
            Expense.expense_date >= period_start,
            Expense.expense_date <= period_end,
        )
        .order_by(Expense.expense_date.asc(), Expense.id.asc())
    ).all()
    expense_expected = {
        int(expense_id): {"source_date": expense_date, "amount_minor": int(amount_minor or 0)}
        for expense_id, expense_date, amount_minor in expense_rows
    }
    expense_expected_total = sum(int(item["amount_minor"]) for item in expense_expected.values())
    expense_issues = _compare_sources(
        check_key="expense",
        source_type="expense",
        expected=expense_expected,
        ledger=expense_ledger,
        direction="EXPENSE",
        kind="EXPENSE",
    )

    payroll_total, payroll_ledger = _ledger_source_totals(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction="EXPENSE",
        kind="PAYROLL",
    )
    full_months = _is_complete_calendar_month_range(period_start, period_end)
    payment_settings_enabled = db.execute(
        select(PayrollPaymentSettings.id).where(
            PayrollPaymentSettings.venue_id == int(venue_id),
        )
    ).scalar_one_or_none() is not None
    payroll_expected: dict[int, dict] = {}
    payroll_issues: list[dict] = []
    payroll_source_type = "payroll_expense" if payment_settings_enabled else "payroll_run"
    if payment_settings_enabled:
        payout_rows = db.execute(
            select(Expense.id, Expense.expense_date, Expense.amount_minor)
            .where(
                Expense.venue_id == int(venue_id),
                Expense.expense_kind == "PAYROLL",
                Expense.status == "CONFIRMED",
                Expense.expense_date >= period_start,
                Expense.expense_date <= period_end,
            )
            .order_by(Expense.expense_date.asc(), Expense.id.asc())
        ).all()
        payroll_expected = {
            int(expense_id): {"source_date": expense_date, "amount_minor": int(amount_minor or 0)}
            for expense_id, expense_date, amount_minor in payout_rows
        }
        payroll_issues = _compare_sources(
            check_key="payroll",
            source_type="payroll_expense",
            expected=payroll_expected,
            ledger=payroll_ledger,
            direction="EXPENSE",
            kind="PAYROLL",
        )
    elif full_months:
        payroll_rows = db.execute(
            select(
                PayrollRun.id,
                PayrollRun.period_month,
                func.coalesce(func.sum(PayrollLine.amount_minor), 0),
            )
            .outerjoin(PayrollLine, PayrollLine.payroll_run_id == PayrollRun.id)
            .where(
                PayrollRun.venue_id == int(venue_id),
                PayrollRun.period_month >= period_start.replace(day=1),
                PayrollRun.period_month <= period_end.replace(day=1),
            )
            .group_by(PayrollRun.id, PayrollRun.period_month)
            .order_by(PayrollRun.period_month.asc(), PayrollRun.id.asc())
        ).all()
        payroll_expected = {
            int(run_id): {"source_date": period_month, "amount_minor": int(amount_minor or 0)}
            for run_id, period_month, amount_minor in payroll_rows
        }
        payroll_issues = _compare_sources(
            check_key="payroll",
            source_type="payroll_run",
            expected=payroll_expected,
            ledger=payroll_ledger,
            direction="EXPENSE",
            kind="PAYROLL",
        )

    payroll_expected_total = sum(int(item["amount_minor"]) for item in payroll_expected.values())
    all_issues = revenue_issues + expense_issues + payroll_issues
    all_issues.sort(key=lambda item: (-abs(int(item.get("delta_minor") or 0)), str(item.get("check_key") or "")))

    checks = [
        {
            "key": "revenue",
            "title": "Выручка",
            "status": "WARNING" if revenue_delta or revenue_issues else "OK",
            "comparable_to_summary": True,
            "summary_minor": int(summary.get("revenue_minor") or 0),
            "ledger_minor": int(revenue_total),
            "delta_minor": int(revenue_delta),
            "source_expected_minor": int(sum(item["amount_minor"] for item in revenue_expected.values())),
            "source_ledger_minor": int(revenue_total),
            "issue_count": len(revenue_issues),
            "source_type": "daily_report",
            "direction": "INCOME",
            "kind": "REVENUE",
            "note": "Сравниваются итоги закрытых отчётов и проводки выручки журнала.",
        },
        {
            "key": "expense",
            "title": "Расходы",
            "status": "WARNING" if expense_issues else "OK",
            "comparable_to_summary": False,
            "summary_minor": int(summary.get("expense_without_payroll_minor") or 0),
            "ledger_minor": int(expense_total),
            "delta_minor": int(expense_total - expense_expected_total),
            "source_expected_minor": int(expense_expected_total),
            "source_ledger_minor": int(expense_total),
            "issue_count": len(expense_issues),
            "source_type": "expense",
            "direction": "EXPENSE",
            "kind": "EXPENSE",
            "note": "Сводка отражает признание расходов, журнал — дату оплаты. Проверяется связь каждой оплаты с расходом.",
        },
        {
            "key": "payroll",
            "title": "ФОТ",
            "status": (
                "WARNING"
                if payroll_issues
                or (not payment_settings_enabled and full_months and payroll_total != int(summary.get("payroll_minor") or 0))
                else "INFO"
                if not payment_settings_enabled and not full_months
                else "OK"
            ),
            "comparable_to_summary": bool(full_months and not payment_settings_enabled),
            "summary_minor": int(summary.get("payroll_minor") or 0),
            "ledger_minor": int(payroll_total),
            "delta_minor": (
                int(payroll_total - int(summary.get("payroll_minor") or 0))
                if full_months and not payment_settings_enabled
                else None
            ),
            "source_expected_minor": int(payroll_expected_total) if payment_settings_enabled or full_months else None,
            "source_ledger_minor": int(payroll_total),
            "issue_count": len(payroll_issues),
            "source_type": payroll_source_type,
            "direction": "EXPENSE",
            "kind": "PAYROLL",
            "note": (
                "Начисления отражаются в сводке, а подтверждённые выплаты сверяются с проводками выбранного способа оплаты."
                if payment_settings_enabled
                else
                "За полный месяц сверяются начисления и проводки ФОТ."
                if full_months
                else "Для части месяца ФОТ распределяется по дням, а проводка создаётся на месяц; прямое сравнение отключено."
            ),
        },
    ]
    warning_checks = [check for check in checks if check["status"] == "WARNING"]
    return {
        "period_start": period_start,
        "period_end": period_end,
        "status": "WARNING" if warning_checks else "OK",
        "warning_count": len(warning_checks),
        "issue_count": len(all_issues),
        "checks": checks,
        "issues": all_issues[:50],
        "issues_truncated": len(all_issues) > 50,
    }
