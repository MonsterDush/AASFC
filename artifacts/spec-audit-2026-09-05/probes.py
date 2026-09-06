"""Read-only audit probes. Uses in-memory SQLite and mocks side effects.

Run from backend:
DATABASE_URL=sqlite:// .venv/bin/python ../artifacts/spec-audit-2026-09-05/probes.py
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import json
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import User, VenueMember, VenuePosition, ShiftInterval, Shift, ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.routers import venue_shifts
from app.schemas.venue_shifts import ShiftUpdateIn
from app.schemas.venue_economics import DepartmentPlanItemIn
from app.services.venue_member_names import load_member_display_names, owner_display_name
from app.services.finance.day_economics import _department_actuals_for_day
from app.services.payroll.percent_calculations import _build_percent_component_decision, _build_percent_component_snapshot
from app.services.payroll.payroll_types import PayrollMemberMetrics, PayrollRevenueMetrics, PayrollKpiMetrics, PayrollVenuePlanMetrics

results = {}
engine = create_engine("sqlite://")
with engine.begin() as conn:
    conn.exec_driver_sql("CREATE TABLE venues (id INTEGER PRIMARY KEY, name TEXT, is_archived BOOLEAN)")
    conn.exec_driver_sql("INSERT INTO venues VALUES (5, 'Synthetic audit venue', 0)")
for model in (User, VenueMember, VenuePosition, ShiftInterval, Shift, ShiftAssignment, DailyReport, DailyReportValue):
    model.__table__.create(engine)

with Session(engine) as db:
    owner = User(id=1, short_name="Owner")
    employee = User(id=2, short_name="Михаил Иванов")
    manager = User(id=3, short_name="Manager")
    catalog = VenuePosition(id=10, venue_id=5, member_user_id=None, title="Менеджер")
    position = VenuePosition(id=20, venue_id=5, member_user_id=2, title="Бармен")
    db.add_all([owner, employee, manager, catalog, position])
    db.add_all([
        VenueMember(venue_id=5, user_id=1, venue_role="OWNER", is_active=True),
        VenueMember(venue_id=5, user_id=2, venue_role="STAFF", owner_note="Миша старший", is_active=True),
        VenueMember(venue_id=5, user_id=3, venue_role="STAFF", is_active=True),
        ShiftInterval(id=1, venue_id=5, title="Общий", start_time=time(10), end_time=time(22)),
        ShiftInterval(id=2, venue_id=5, title="Менеджер", position_id=10, start_time=time(10), end_time=time(22)),
        Shift(id=1, venue_id=5, date=date(2026,9,4), interval_id=1, is_active=True),
        ShiftAssignment(id=1, shift_id=1, member_user_id=2, venue_position_id=20),
    ])
    db.commit()
    names = load_member_display_names(db, venue_id=5, member_user_ids=[2])
    assert names[2] == "Миша старший"
    with patch.object(venue_shifts, "_require_active_member_or_admin"):
        owner_detail = venue_shifts.get_shift(5, 1, db, owner)
        manager_detail = venue_shifts.get_shift(5, 1, db, manager)
    results["names"] = {
        "shared_loader": names[2],
        "owner_shift_detail": owner_detail["assignments"][0]["member"]["display_name"],
        "manager_shift_detail": manager_detail["assignments"][0]["member"]["display_name"],
        "fallback_without_note": owner_display_name(short_name=employee.short_name),
        "local_after_global_rename": owner_display_name(owner_note=names[2], short_name="Changed global name"),
    }
    assert results["names"]["manager_shift_detail"] == "Михаил Иванов"
    with patch.object(venue_shifts, "_require_schedule_editor"), patch.object(venue_shifts, "_recalculate_payroll_for_dates"):
        venue_shifts.update_shift(5, 1, ShiftUpdateIn(interval_id=2), db, owner)
    updated = db.get(Shift, 1)
    assert updated.interval_id == 2 and db.get(ShiftAssignment, 1).venue_position_id == 20
    try:
        venue_shifts._require_shift_position_match(db, venue_id=5, shift=updated, position=position)
    except HTTPException as exc:
        results["interval_update"] = {
            "patch_keeps_incompatible_assignment": True,
            "same_assignment_validation_status": exc.status_code,
            "error_detail": exc.detail,
        }
    else:
        raise AssertionError("Expected direct assignment validation to reject the position")
    db.add_all([
        DailyReport(id=1, venue_id=5, date=date(2026,9,4), status="CLOSED", shift_slot="DAY", created_by_user_id=1),
        DailyReport(id=2, venue_id=5, date=date(2026,9,4), status="DRAFT", shift_slot="NIGHT", created_by_user_id=1),
        DailyReportValue(report_id=1, kind="DEPT", ref_id=7, value_numeric=116_000),
        DailyReportValue(report_id=2, kind="DEPT", ref_id=7, value_numeric=1_000_000),
    ])
    db.commit()
    actuals = _department_actuals_for_day(db, venue_id=5, target_date=date(2026,9,4))
    assert actuals == {7: 11_600_000}
    results["closed_only_actuals_minor"] = actuals

day = date(2026,9,4)
component = SimpleNamespace(
    component_type="PERCENT_DEPARTMENT_REVENUE", percent_bps=300, department_id=7,
    base_scope="FULL_PERIOD", boost_enabled=True, boost_percent_bps=500,
    boost_source_type="DEPARTMENT_DAY_PLAN", boost_department_id=7,
    boost_recalc_mode="REPLACE_ALL",
)
revenue = PayrollRevenueMetrics(
    department_revenue_minor={7:11_600_000},
    department_revenue_by_date_minor={7:{day:11_600_000}},
)
results["daily_plans"] = []
for target in (None, 0, 10_000_000, 12_000_000):
    payload = DepartmentPlanItemIn(department_id=7, revenue_plan_minor=target)
    decision = _build_percent_component_decision(
        component, metrics=PayrollMemberMetrics(), revenue_metrics=revenue, kpi_metrics=PayrollKpiMetrics(),
        venue_plan_metrics=PayrollVenuePlanMetrics(department_day_revenue_target_by_date_minor={7:{day:target}}),
    )
    row = decision.day_rows[0]
    results["daily_plans"].append({"target_minor":payload.revenue_plan_minor, "percent_bps":row["percent_bps"], "amount_minor":row["amount_minor"]})
assert [r["percent_bps"] for r in results["daily_plans"]] == [300,500,500,300]
snapshot = _build_percent_component_snapshot(component, decision)
results["snapshot_missing_tier_fields"] = sorted({"percent_tiers", "matched_tier", "achievement"} - set(snapshot))
print(json.dumps(results, ensure_ascii=False, indent=2))
