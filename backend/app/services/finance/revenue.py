from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, Department, PaymentMethod
from app.services.integrations.report_facts import ReportFactValue, load_period_report_facts, load_report_facts
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


def load_report_values(*, db: Session, report_id: int) -> list[ReportFactValue]:
    report = db.get(DailyReport, int(report_id))
    if report is None:
        return []
    return list(load_report_facts(db, report=report).values)


def build_report_revenue_plan(
    *,
    report: DailyReport,
    values: list[DailyReportValue] | list[ReportFactValue],
    revenue_total: int | None = None,
    unallocated_revenue_total: int | None = None,
) -> list[dict]:
    shift_slot = str(getattr(report, "shift_slot", "DAY") or "DAY").upper()
    payment_values = [v for v in values if v.kind == "PAYMENT" and int(v.value_numeric or 0) > 0]
    if payment_values:
        return [
            {
                "amount_minor": int(v.value_numeric or 0) * 100,
                "department_id": None,
                "payment_method_id": int(v.ref_id),
                "meta_json": {
                    "report_date": report.date.isoformat(),
                    "shift_slot": shift_slot,
                    "dimension": "payment_method",
                    "ref_id": int(v.ref_id),
                },
            }
            for v in payment_values
        ]

    dept_values = [v for v in values if v.kind == "DEPT" and int(v.value_numeric or 0) > 0]
    if dept_values:
        plan = [
            {
                "amount_minor": int(v.value_numeric or 0) * 100,
                "department_id": None,
                "payment_method_id": None,
                "meta_json": {
                    "report_date": report.date.isoformat(),
                    "shift_slot": shift_slot,
                    "dimension": "department_only_fallback",
                    "ref_id": int(v.ref_id),
                },
            }
            for v in dept_values
        ]
        unallocated_total_minor = (
            int(
                getattr(report, "unallocated_revenue_total", 0)
                if unallocated_revenue_total is None
                else unallocated_revenue_total
            )
            * 100
        )
        if unallocated_total_minor > 0:
            plan.append(
                {
                    "amount_minor": unallocated_total_minor,
                    "department_id": None,
                    "payment_method_id": None,
                    "meta_json": {
                        "report_date": report.date.isoformat(),
                        "shift_slot": shift_slot,
                        "dimension": "kpi_unallocated_fallback",
                    },
                }
            )
        return plan

    total_minor = int(report.revenue_total if revenue_total is None else revenue_total) * 100
    if total_minor <= 0:
        return []

    return [
        {
            "amount_minor": total_minor,
            "department_id": None,
            "payment_method_id": None,
            "meta_json": {
                "report_date": report.date.isoformat(),
                "shift_slot": shift_slot,
                "dimension": "report_total",
            },
        }
    ]


def rebuild_revenue_entries_for_report(
    *, db: Session, report: DailyReport, values: list[DailyReportValue] | None = None
) -> int:
    if report.id is None:
        raise ValueError("Report must be flushed before revenue rebuild")

    delete_finance_entries_for_source(db=db, source_type="daily_report", source_id=int(report.id))

    if str(report.status or "").upper() != "CLOSED":
        return 0

    facts = load_report_facts(db, report=report)
    report_values = values if values is not None and facts.source_mode == "MANUAL" else list(facts.values)
    plan = build_report_revenue_plan(
        report=report,
        values=report_values,
        revenue_total=facts.revenue_total,
        unallocated_revenue_total=facts.unallocated_revenue_total,
    )

    created = 0
    for item in plan:
        create_finance_entry(
            db=db,
            venue_id=int(report.venue_id),
            entry_date=report.date,
            amount_minor=int(item["amount_minor"]),
            direction="INCOME",
            kind="REVENUE",
            source_type="daily_report",
            source_id=int(report.id),
            department_id=item.get("department_id"),
            payment_method_id=item.get("payment_method_id"),
            meta_json=item.get("meta_json"),
        )
        created += 1
    return created


def delete_revenue_entries_for_report(*, db: Session, report_id: int) -> int:
    return delete_finance_entries_for_source(db=db, source_type="daily_report", source_id=int(report_id))


def _parse_month_yyyy_mm(month: str) -> tuple[date, date]:
    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return start, end
    except Exception:
        raise ValueError("Bad month format, expected YYYY-MM")


def resolve_revenue_period(month: str | None, date_from: date | None, date_to: date | None) -> tuple[date, date]:
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


def build_revenue_daily_series(*, period_start: date, period_end: date, rows: list) -> list[dict]:
    amounts_by_date: dict[date, int] = {}
    for row in rows:
        if hasattr(row, "date") and hasattr(row, "amount"):
            row_date = getattr(row, "date")
            amount = getattr(row, "amount")
        else:
            row_date, amount = row
        amounts_by_date[row_date] = int(amount or 0)

    result: list[dict] = []
    current = period_start
    while current <= period_end:
        result.append({"date": current, "amount": amounts_by_date.get(current, 0)})
        current += timedelta(days=1)
    return result


def compute_revenue_summary(
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    mode: str,
    db: Session,
    include_series: bool = False,
) -> dict:
    period_start, period_end = resolve_revenue_period(month, date_from, date_to)
    mode_norm = (mode or "payments").strip().lower()
    if mode_norm not in {"payments", "departments"}:
        raise ValueError("Bad mode, expected payments or departments")

    Catalog = PaymentMethod if mode_norm == "payments" else Department
    kind = "PAYMENT" if mode_norm == "payments" else "DEPT"

    facts = load_period_report_facts(
        db,
        venue_id=int(venue_id),
        period_start=period_start,
        period_end_exclusive=period_end + timedelta(days=1),
    )
    closed_reports = len(facts)
    amounts_by_ref: dict[int, int] = {}
    for fact in facts:
        for value in fact.values_for(kind):
            amounts_by_ref[int(value.ref_id)] = int(amounts_by_ref.get(int(value.ref_id), 0)) + int(value.value_numeric)
    rows = sorted(amounts_by_ref.items())

    catalog_rows = db.execute(
        select(Catalog.id, getattr(Catalog, "code", None), Catalog.title).where(Catalog.venue_id == int(venue_id))
    ).all()
    unallocated_total = 0
    if mode_norm == "departments":
        unallocated_total = sum(int(fact.unallocated_revenue_total) for fact in facts)

    def _row_value(row, idx: int, attr: str):
        if hasattr(row, attr):
            return getattr(row, attr)
        return row[idx]

    catalog_map = {int(_row_value(r, 0, "id")): r for r in catalog_rows}

    out_rows = []
    total = 0
    for row in rows:
        if hasattr(row, "ref_id") and hasattr(row, "amount"):
            ref_id = getattr(row, "ref_id")
            amount = getattr(row, "amount")
        else:
            ref_id, amount = row
        cat = catalog_map.get(int(ref_id))
        title = _row_value(cat, 2, "title") if cat else f"ID {int(ref_id)}"
        code = _row_value(cat, 1, "code") if cat else None
        amount_int = int(amount or 0)
        total += amount_int
        out_rows.append({"ref_id": int(ref_id), "code": code, "title": title, "amount": amount_int})

    if unallocated_total:
        total += unallocated_total
        out_rows.append(
            {
                "ref_id": 0,
                "code": "KPI_UNALLOCATED",
                "title": "Вне департаментов (KPI)",
                "amount": unallocated_total,
            }
        )

    out_rows.sort(key=lambda x: (-x["amount"], x["title"]))
    daily_series: list[dict] = []
    if include_series:
        daily_amounts: dict[date, int] = {}
        for fact in facts:
            if mode_norm == "departments":
                amount = int(fact.revenue_total)
            else:
                amount = sum(int(value.value_numeric) for value in fact.values_for(kind))
            daily_amounts[fact.report_date] = int(daily_amounts.get(fact.report_date, 0)) + amount
        daily_rows = sorted(daily_amounts.items())
        daily_series = build_revenue_daily_series(
            period_start=period_start,
            period_end=period_end,
            rows=daily_rows,
        )

    return {
        "month": month,
        "period_start": period_start,
        "period_end": period_end,
        "mode": mode_norm,
        "closed_reports": closed_reports,
        "total": total,
        "rows": out_rows,
        "daily_series": daily_series,
    }
