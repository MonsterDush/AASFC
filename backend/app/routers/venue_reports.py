from fastapi import APIRouter

from app.routers.venue_core import (
    BackgroundTasks,
    DailyReport,
    DailyReportAttachment,
    DailyReportAudit,
    DailyReportTipAllocation,
    DailyReportValue,
    Department,
    Depends,
    File,
    FileResponse,
    HTTPException,
    KpiMetric,
    PaymentMethod,
    Query,
    Session,
    Shift,
    ShiftAssignment,
    UploadFile,
    User,
    Venue,
    VenuePosition,
    _has_revenue_view_access,
    _is_owner_or_super_admin,
    _require_active_member_or_admin,
    _require_report_viewer,
    build_equal_tip_allocations,
    build_weighted_by_position_tip_allocations,
    date,
    datetime,
    delete,
    delete_daily_recurring_accruals_for_date,
    delete_revenue_entries_for_report,
    financial_visibility_payload,
    func,
    get_current_user,
    get_db,
    os,
    rebuild_revenue_entries_for_report,
    require_venue_permission,
    sanitize_financial_payload_for_user,
    select,
    sync_daily_recurring_accruals_for_date,
    normalize_shift_slot,
    uuid,
)
from app.routers.venue_common import (
    _can_show_financial_values_for_user,
)
from app.schemas.venue_reports import (
    DailyReportCloseIn,
    DailyReportUpsertIn,
)
from app.routers.venue_permissions import (
    _is_report_maker,
    _require_report_maker,
)
from app.routers.venue_payroll_support import (
    _recalculate_payroll_for_dates,
)
from app.routers.venue_economics_notifications import (
    _enqueue_day_economics_summary_job,
    _enqueue_salary_day_breakdown_job,
    _enqueue_soft_alerts_job,
    process_pending_notification_jobs_once,
)


router = APIRouter()


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
    elif kind == "DEPT":
        model = Department
        value_kind = "DEPT"
    elif kind == "KPI":
        model = KpiMetric
        value_kind = "KPI"
    else:
        raise ValueError("Bad kind")

    def extra(obj) -> dict:
        return {"unit": getattr(obj, "unit", None)} if kind == "KPI" else {}

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
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
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
    normalized_shift_slot = normalize_shift_slot(shift_slot)


    obj = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == payload.date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
    ).scalar_one_or_none()

    audited_before = None
    is_closed_edit = False

    if obj is None:
        obj = DailyReport(
            venue_id=venue_id,
            date=payload.date,
            shift_slot=normalized_shift_slot,
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
        _rebuild_report_tip_allocations(db, report=obj, venue=venue)
        rebuild_revenue_entries_for_report(db=db, report=obj)
        _recalculate_payroll_for_dates(
            db,
            venue_id=venue_id,
            target_dates=[obj.date],
            calculated_by_user_id=user.id,
            force=True,
            trigger_reason="closed_report_updated",
        )

    db.commit()
    db.refresh(obj)
    return {
        "id": obj.id,
        "date": obj.date.isoformat(),
        "shift_slot": normalize_shift_slot(getattr(obj, "shift_slot", None)),
        "mode": "updated" if obj.updated_at else "created",
    }



@router.get("/{venue_id}/reports")
def list_daily_reports(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
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

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rows = db.execute(
        select(DailyReport)
        .where(
            DailyReport.venue_id == venue_id,
            DailyReport.date >= start,
            DailyReport.date < end,
            DailyReport.shift_slot == normalized_shift_slot,
        )
        .order_by(DailyReport.date.asc())
    ).scalars().all()

    show_numbers = _has_revenue_view_access(db, venue_id=venue_id, user=user) and _can_show_financial_values_for_user(user)
    hidden_meta = financial_visibility_payload(user)
    return [
        {
            "id": r.id,
            "date": r.date.isoformat(),
            "shift_slot": normalize_shift_slot(getattr(r, "shift_slot", None)),
            "status": getattr(r, "status", "DRAFT"),
            "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
            "cash": r.cash if show_numbers else None,
            "cashless": r.cashless if show_numbers else None,
            "revenue_total": r.revenue_total if show_numbers else None,
            "tips_total": r.tips_total if show_numbers else None,
            **hidden_meta,
        }
        for r in rows
    ]


@router.get("/{venue_id}/reports/{report_date}")
def get_daily_report(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    r = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == report_date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")

    show_numbers = _has_revenue_view_access(db, venue_id=venue_id, user=user) and _can_show_financial_values_for_user(user)
    hidden_meta = financial_visibility_payload(user)
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
        "shift_slot": normalize_shift_slot(getattr(r, "shift_slot", None)),
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
        **hidden_meta,
    }


def _load_assigned_members_for_report_date(
    db: Session,
    *,
    venue_id: int,
    report_date: date,
    shift_slot: str,
) -> list[tuple[int, str | None]]:
    normalized_slot = normalize_shift_slot(shift_slot)
    rows = db.execute(
        select(ShiftAssignment.member_user_id, VenuePosition.title)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .where(
            Shift.venue_id == venue_id,
            Shift.date == report_date,
            Shift.shift_slot == normalized_slot,
            Shift.is_active.is_(True),
        )
        .order_by(ShiftAssignment.member_user_id.asc(), ShiftAssignment.id.asc())
    ).all()
    return [(int(user_id), title) for user_id, title in rows if user_id is not None]


def _rebuild_report_tip_allocations(
    db: Session,
    *,
    report: DailyReport,
    venue: Venue,
) -> list[DailyReportTipAllocation]:
    db.execute(delete(DailyReportTipAllocation).where(DailyReportTipAllocation.report_id == report.id))

    if not bool(getattr(venue, "tips_enabled", False)):
        report.tips_total = 0
        return []

    tips_total = int(getattr(report, "tips_total", 0) or 0)
    if tips_total <= 0:
        return []

    tips_split_mode = str(getattr(venue, "tips_split_mode", "EQUAL") or "EQUAL").upper()
    assigned_members = _load_assigned_members_for_report_date(
        db,
        venue_id=int(report.venue_id),
        report_date=report.date,
        shift_slot=normalize_shift_slot(getattr(report, "shift_slot", None)),
    )
    if not assigned_members:
        return []

    if tips_split_mode == "WEIGHTED_BY_POSITION":
        try:
            allocations = build_weighted_by_position_tip_allocations(
                report_id=int(report.id),
                tips_total=tips_total,
                assigned_members=assigned_members,
                tips_weights=getattr(venue, "tips_weights", None),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        allocations = build_equal_tip_allocations(
            report_id=int(report.id),
            tips_total=tips_total,
            assigned_user_ids=[user_id for user_id, _title in assigned_members],
        )

    for alloc in allocations:
        db.add(alloc)
    return allocations


def _rebuild_closed_report_tip_allocations_for_keys(
    db: Session,
    *,
    venue_id: int,
    report_keys: set[tuple[date, str]] | list[tuple[date, str]] | tuple[tuple[date, str], ...],
) -> int:
    normalized_keys = {
        (report_date, normalize_shift_slot(shift_slot))
        for report_date, shift_slot in report_keys
        if isinstance(report_date, date)
    }
    if not normalized_keys:
        return 0

    venue = db.execute(
        select(Venue).where(Venue.id == int(venue_id))
    ).scalar_one_or_none()
    if venue is None:
        return 0

    reports = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date.in_(sorted({report_date for report_date, _slot in normalized_keys})),
            DailyReport.status == "CLOSED",
        )
    ).scalars().all()

    rebuilt = 0
    for report in reports:
        key = (
            report.date,
            normalize_shift_slot(getattr(report, "shift_slot", None)),
        )
        if key not in normalized_keys:
            continue
        _rebuild_report_tip_allocations(db, report=report, venue=venue)
        rebuilt += 1
    return rebuilt


def _sync_recurring_accruals_after_report_reopen(
    db: Session,
    *,
    report: DailyReport,
) -> str:
    other_closed_report_id = db.execute(
        select(DailyReport.id).where(
            DailyReport.venue_id == int(report.venue_id),
            DailyReport.date == report.date,
            DailyReport.id != int(report.id),
            DailyReport.status == "CLOSED",
        ).limit(1)
    ).scalar_one_or_none()
    if other_closed_report_id is not None:
        sync_daily_recurring_accruals_for_date(
            db=db,
            venue_id=int(report.venue_id),
            target_date=report.date,
        )
        return "synced"

    delete_daily_recurring_accruals_for_date(
        db=db,
        venue_id=int(report.venue_id),
        target_date=report.date,
    )
    return "deleted"



@router.post("/{venue_id}/reports/{report_date}/close")
def close_daily_report(
    venue_id: int,
    report_date: date,
    payload: DailyReportCloseIn,
    background_tasks: BackgroundTasks,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
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

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rep = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == report_date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
    ).scalar_one_or_none()
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
            shift_slot=normalized_shift_slot,
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
    if not bool(getattr(venue, "tips_enabled", False)):
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


    _rebuild_report_tip_allocations(db, report=rep, venue=venue)

    rep.status = "CLOSED"
    rep.closed_by_user_id = user.id
    rep.closed_at = datetime.utcnow()
    rep.updated_by_user_id = user.id
    rep.updated_at = datetime.utcnow()

    rebuild_revenue_entries_for_report(db=db, report=rep, values=values)
    sync_daily_recurring_accruals_for_date(db=db, venue_id=venue_id, target_date=report_date)
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[report_date],
        calculated_by_user_id=user.id,
        force=True,
        trigger_reason="report_closed",
    )
    notification_event_key = (
        f"report:{int(rep.id)}:closed:{rep.closed_at.isoformat(timespec='microseconds')}"
    )
    notification_job_args = {
        "venue_id": venue_id,
        "target_date": report_date,
        "shift_slot": normalized_shift_slot,
        "event_key": notification_event_key,
    }
    _enqueue_day_economics_summary_job(db, **notification_job_args)
    _enqueue_salary_day_breakdown_job(db, **notification_job_args)
    _enqueue_soft_alerts_job(db, **notification_job_args)

    db.commit()
    background_tasks.add_task(process_pending_notification_jobs_once, 10)

    return {"ok": True, "status": "CLOSED", "discrepancy": discrepancy}


@router.post("/{venue_id}/reports/{report_date}/reopen")
def reopen_daily_report(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="SHIFT_REPORT_REOPEN"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rep = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == report_date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
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
    _sync_recurring_accruals_after_report_reopen(db, report=rep)
    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=[report_date],
        calculated_by_user_id=user.id,
        force=True,
        trigger_reason="report_reopened",
    )
    db.commit()
    return {"ok": True, "status": "DRAFT"}


# ---------- Revenue aggregation (Stage 2) ----------


@router.get("/{venue_id}/reports/{report_date}/audit")
def list_daily_report_audit(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rep = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == report_date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
    ).scalar_one_or_none()
    if rep is None:
        raise HTTPException(status_code=404, detail="Report not found")

    rows = db.execute(
        select(DailyReportAudit).where(DailyReportAudit.report_id == rep.id).order_by(DailyReportAudit.changed_at.desc())
    ).scalars().all()

    payload = [
        {
            "id": a.id,
            "changed_at": a.changed_at.isoformat() if a.changed_at else None,
            "user_id": a.user_id,
            "user_tg_username": getattr(a.user, "tg_username", None) if getattr(a, "user", None) else None,
            "diff": a.diff_json,
        }
        for a in rows
    ]
    return sanitize_financial_payload_for_user(user, payload)


@router.get("/{venue_id}/reports/{report_date}/attachments")
def list_report_attachments(
    venue_id: int,
    report_date: date,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rows = db.execute(
        select(DailyReportAttachment)
        .where(
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == normalized_shift_slot,
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
                "url": (
                    f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}"
                    f"?shift_slot={normalized_shift_slot}"
                ),
            }
            for a in rows
        ]
    }


@router.get("/{venue_id}/reports/{report_date}/attachments/{attachment_id}")
def download_report_attachment(
    venue_id: int,
    report_date: date,
    attachment_id: int,
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == normalized_shift_slot,
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
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    normalized_shift_slot = normalize_shift_slot(shift_slot)
    a = db.execute(
        select(DailyReportAttachment).where(
            DailyReportAttachment.id == attachment_id,
            DailyReportAttachment.venue_id == venue_id,
            DailyReportAttachment.report_date == report_date,
            DailyReportAttachment.shift_slot == normalized_shift_slot,
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
    shift_slot: str = Query(default="DAY", pattern="^(DAY|NIGHT)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_report_maker(db, venue_id=venue_id, user=user)

    # ensure report exists (or create empty one)
    normalized_shift_slot = normalize_shift_slot(shift_slot)
    rep = db.execute(
        select(DailyReport).where(
            DailyReport.venue_id == venue_id,
            DailyReport.date == report_date,
            DailyReport.shift_slot == normalized_shift_slot,
        )
    ).scalar_one_or_none()
    if rep is None:
        rep = DailyReport(
            venue_id=venue_id,
            date=report_date,
            shift_slot=normalized_shift_slot,
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
        dst = os.path.join(
            base_dir,
            f"{venue_id}_{report_date.isoformat()}_{normalized_shift_slot}_{uid}_{safe_name}",
        )
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
            shift_slot=normalized_shift_slot,
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
                "url": (
                    f"/venues/{venue_id}/reports/{report_date.isoformat()}/attachments/{a.id}"
                    f"?shift_slot={normalized_shift_slot}"
                ),
            }
            for a in created
        ],
    }


# ---------- Adjustments (penalties/writeoffs/bonuses) ----------
