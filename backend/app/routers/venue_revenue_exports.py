from fastapi import APIRouter

from app.routers.venue_core import (
    BaseModel,
    Field,
    BytesIO,
    DailyReport,
    DailyReportValue,
    Department,
    Depends,
    Expense,
    ExpenseAllocation,
    ExpenseCategory,
    HTTPException,
    KpiMetric,
    PaymentMethod,
    Query,
    Request,
    Session,
    StreamingResponse,
    Supplier,
    User,
    Venue,
    _require_active_member_or_admin,
    _require_report_viewer,
    _require_revenue_viewer,
    build_expenses_xlsx,
    build_monthly_summary_xlsx,
    build_payroll_xlsx,
    build_revenue_csv,
    build_revenue_xlsx,
    calendar,
    compute_revenue_summary,
    date,
    datetime,
    get_current_user,
    get_current_user_optional,
    get_db,
    get_monthly_finance_summary,
    list_expense_allocations,
    make_signed_token,
    quote,
    re,
    require_venue_permission,
    resolve_salary_period,
    sanitize_financial_payload_for_user,
    select,
    settings,
    timedelta,
    verify_signed_token,
)
from app.routers.venue_common import (
    _load_user_for_signed_export,
    _require_financial_values_export_allowed,
)
from app.routers.venue_permissions import (
    _require_revenue_exporter,
)
from app.routers.venue_payroll_support import (
    _build_venue_payroll_period_payload,
    _load_payroll_payload,
    _require_payroll_view,
)


router = APIRouter()


class RevenueRowOut(BaseModel):
    ref_id: int
    code: str | None = None
    title: str
    amount: int


class RevenueDailyPointOut(BaseModel):
    date: date
    amount: int


class RevenueSummaryOut(BaseModel):
    financial_values_hidden: bool = False
    can_view_financial_values: bool = True
    financial_values_hidden_reason: str | None = None
    month: str | None = None
    period_start: date
    period_end: date
    mode: str
    closed_reports: int
    total: int
    rows: list[RevenueRowOut]
    daily_series: list[RevenueDailyPointOut] = Field(default_factory=list)


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


def _compute_revenue_summary(
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    mode: str,
    db: Session,
    include_series: bool = False,
):
    try:
        summary = compute_revenue_summary(
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            db=db,
            include_series=include_series,
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
        "daily_series": summary.get("daily_series") or [],
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
                "shift_slot": str(getattr(report, "shift_slot", None) or "DAY").upper(),
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
                    "shift_slot": str(getattr(report, "shift_slot", None) or "DAY").upper(),
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
    base_url: str | None = None,
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
        if base_url:
            for attachment_payload in payload.get("attachments") or []:
                try:
                    attachment_id = int(attachment_payload.get("id") or 0)
                    attachment_obj = next((a for a in getattr(expense, "attachments", []) if int(getattr(a, "id", 0) or 0) == attachment_id), None)
                    if attachment_obj is None:
                        attachment_obj = _get_expense_attachment_or_404(db, venue_id=venue_id, expense_id=int(expense.id), attachment_id=attachment_id)
                    attachment_payload["download_url"] = _expense_attachment_signed_url(base_url, attachment_obj)
                except Exception:
                    pass
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
    include_series: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Агрегация доходов по CLOSED отчётам за месяц."""
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    summary = _compute_revenue_summary(
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        mode=mode,
        db=db,
        include_series=include_series,
    )
    return sanitize_financial_payload_for_user(user, summary)




def _build_revenue_export_response(*, venue_id: int, month: str | None, date_from: date | None, date_to: date | None, mode: str, fmt: str, db: Session, user: User | None = None, base_url: str | None = None):
    """Build streaming export response.

    If user is provided, permissions are checked before export.
    Signed-link exports pass user=None and rely on token validation done by caller.
    """
    if user is not None:
        _require_active_member_or_admin(db, venue_id=venue_id, user=user)
        _require_report_viewer(db, venue_id=venue_id, user=user)
        _require_revenue_exporter(db, venue_id=venue_id, user=user)
        _require_financial_values_export_allowed(user)

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
    _require_financial_values_export_allowed(user)

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
    request: Request,
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
        _require_financial_values_export_allowed(_load_user_for_signed_export(db, payload))

        return _build_revenue_export_response(
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            fmt=fmt,
            db=db,
            user=None,
            base_url=str(request.base_url).rstrip("/"),
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



def _build_expenses_export_response(*, venue_id: int, month: str | None, category_id: int | None, supplier_id: int | None, statuses: str | None, db: Session, user: User | None = None, base_url: str | None = None):
    if user is not None:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")
        _require_financial_values_export_allowed(user)

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
        base_url=base_url,
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
    _require_financial_values_export_allowed(user)
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
    request: Request,
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
        _require_financial_values_export_allowed(_load_user_for_signed_export(db, payload))
        return _build_expenses_export_response(
            venue_id=venue_id,
            month=month,
            category_id=category_id,
            supplier_id=supplier_id,
            statuses=statuses,
            db=db,
            user=None,
            base_url=str(request.base_url).rstrip("/"),
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
        base_url=str(request.base_url).rstrip("/"),
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
        _require_financial_values_export_allowed(user)

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
    _require_financial_values_export_allowed(user)
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
        _require_financial_values_export_allowed(_load_user_for_signed_export(db, payload))
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
        _require_financial_values_export_allowed(user)

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
    _require_financial_values_export_allowed(user)
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
        _require_financial_values_export_allowed(_load_user_for_signed_export(db, payload))
        return _build_payroll_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=None)

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _build_payroll_export_response(venue_id=venue_id, month=month, date_from=date_from, date_to=date_to, db=db, user=user)
