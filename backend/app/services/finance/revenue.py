from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, Department, PaymentMethod
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


def load_report_values(*, db: Session, report_id: int) -> list[DailyReportValue]:
    return list(
        db.execute(
            select(DailyReportValue).where(DailyReportValue.report_id == int(report_id))
        ).scalars().all()
    )


def build_report_revenue_plan(*, report: DailyReport, values: list[DailyReportValue]) -> list[dict]:
    dept_values = [v for v in values if v.kind == "DEPT" and int(v.value_numeric or 0) > 0]
    if dept_values:
        return [
            {
                "amount_minor": int(v.value_numeric or 0) * 100,
                "department_id": int(v.ref_id),
                "payment_method_id": None,
                "meta_json": {
                    "report_date": report.date.isoformat(),
                    "dimension": "department",
                    "ref_id": int(v.ref_id),
                },
            }
            for v in dept_values
        ]

    payment_values = [v for v in values if v.kind == "PAYMENT" and int(v.value_numeric or 0) > 0]
    if payment_values:
        return [
            {
                "amount_minor": int(v.value_numeric or 0) * 100,
                "department_id": None,
                "payment_method_id": int(v.ref_id),
                "meta_json": {
                    "report_date": report.date.isoformat(),
                    "dimension": "payment_method",
                    "ref_id": int(v.ref_id),
                },
            }
            for v in payment_values
        ]

    total_minor = int(report.revenue_total or 0) * 100
    if total_minor <= 0:
        return []

    return [
        {
            "amount_minor": total_minor,
            "department_id": None,
            "payment_method_id": None,
            "meta_json": {
                "report_date": report.date.isoformat(),
                "dimension": "report_total",
            },
        }
    ]


def rebuild_revenue_entries_for_report(*, db: Session, report: DailyReport, values: list[DailyReportValue] | None = None) -> int:
    if report.id is None:
        raise ValueError("Report must be flushed before revenue rebuild")

    delete_finance_entries_for_source(db=db, source_type="daily_report", source_id=int(report.id))

    if str(report.status or "").upper() != "CLOSED":
        return 0

    report_values = values if values is not None else load_report_values(db=db, report_id=int(report.id))
    plan = build_report_revenue_plan(report=report, values=report_values)

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


def compute_revenue_summary(*, venue_id: int, month: str | None, date_from: date | None, date_to: date | None, mode: str, db: Session) -> dict:
    period_start, period_end = resolve_revenue_period(month, date_from, date_to)
    mode_norm = (mode or "payments").strip().lower()
    if mode_norm not in {"payments", "departments"}:
        raise ValueError("Bad mode, expected payments or departments")

    Catalog = PaymentMethod if mode_norm == "payments" else Department
    kind = "PAYMENT" if mode_norm == "payments" else "DEPT"

    closed_reports_subq = (
        select(DailyReport.id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .subquery()
    )

    closed_reports = int(
        db.execute(select(func.count()).select_from(closed_reports_subq)).scalar() or 0
    )

    rows = db.execute(
        select(
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("amount"),
        )
        .where(
            DailyReportValue.kind == kind,
            DailyReportValue.report_id.in_(select(closed_reports_subq.c.id)),
        )
        .group_by(DailyReportValue.ref_id)
    ).all()

    catalog_rows = db.execute(
        select(Catalog.id, getattr(Catalog, "code", None), Catalog.title).where(Catalog.venue_id == int(venue_id))
    ).all()
    catalog_map = {int(r[0]): r for r in catalog_rows}

    out_rows = []
    total = 0
    for ref_id, amount in rows:
        cat = catalog_map.get(int(ref_id))
        title = cat[2] if cat else f"ID {int(ref_id)}"
        code = cat[1] if cat else None
        amount_int = int(amount or 0)
        total += amount_int
        out_rows.append({"ref_id": int(ref_id), "code": code, "title": title, "amount": amount_int})

    out_rows.sort(key=lambda x: (-x["amount"], x["title"]))
    return {
        "month": month,
        "period_start": period_start,
        "period_end": period_end,
        "mode": mode_norm,
        "closed_reports": closed_reports,
        "total": total,
        "rows": out_rows,
    }
