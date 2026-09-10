from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles

from app.core.db import Base
from app.models import (
    User,
    Venue,
    Department,
    DailyReport,
    DailyReportValue,
    DepartmentDayPlan,
    DepartmentMonthPlan,
    PayProfile,
    PayComponent,
    KpiMetric,
)
from app.models.pay_component import PayComponentPercentTier
from app.routers.venue_pay_profiles import create_pay_component, update_pay_component
from app.routers import venue_department_plans
from app.schemas.department_plans import DepartmentDaysBulkIn, DepartmentPlanValueIn
from app.schemas.venue_payroll import PayComponentCreateIn, PayComponentUpdateIn
from app.services.finance.department_plans import bulk_day_plans, plan_calendar, save_plan
from app.services.payroll.percent_calculations import (
    _build_percent_component_decision,
    _build_percent_component_snapshot,
)
from app.services.payroll.payroll_types import (
    PayrollMemberMetrics,
    PayrollRevenueMetrics,
    PayrollKpiMetrics,
    PayrollVenuePlanMetrics,
)


@compiles(JSONB, "sqlite")
@compiles(ARRAY, "sqlite")
def _sqlite_json(_type, _compiler, **_kwargs):
    return "JSON"


class DepartmentPlansAndTiersTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(
            self.engine,
            tables=[
                model.__table__
                for model in (
                    User,
                    Venue,
                    Department,
                    DailyReport,
                    DailyReportValue,
                    DepartmentDayPlan,
                    DepartmentMonthPlan,
                    PayProfile,
                    KpiMetric,
                    PayComponent,
                    PayComponentPercentTier,
                )
            ],
        )
        self.db = Session(self.engine)
        self.db.add_all([User(id=1, short_name="Owner"), Venue(id=1, name="Bar"), Venue(id=2, name="Other")])
        self.db.flush()
        self.db.add_all(
            [
                Department(id=1, venue_id=1, title="Бар", code="BAR"),
                Department(id=3, venue_id=1, title="Кухня", code="KITCHEN"),
                Department(id=2, venue_id=2, title="Other", code="BAR"),
                PayProfile(id=1, venue_id=1, title="Percent"),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def bulk(self, start="2026-09-01", end="2026-09-30", **kwargs):
        return DepartmentDaysBulkIn(
            department_id=1,
            date_from=start,
            date_to=end,
            weekdays=[{"weekday": weekday, "revenue_plan_minor": (weekday + 1) * 10000} for weekday in range(7)],
            **kwargs,
        )

    def test_calendar_lengths_and_real_weekdays(self):
        for month, count in [("2026-02", 28), ("2028-02", 29), ("2026-09", 30), ("2026-12", 31)]:
            with self.subTest(month=month):
                result = bulk_day_plans(self.db, 1, self.bulk(f"{month}-01", f"{month}-{count}"))
                self.assertEqual(result["changed_count"], count)
                data = plan_calendar(self.db, 1, 1, month)
                self.assertEqual(len(data["days"]), count)
                self.assertIsNone(data["revenue_plan_minor"])
                for row in data["days"]:
                    self.assertEqual(row["revenue_plan_minor"], (date.fromisoformat(row["date"]).weekday() + 1) * 10000)
                    self.assertIsNone(row["actual_minor"])

    def test_bulk_overwrite_preview_and_manual_override(self):
        save_plan(self.db, 1, 1, date(2026, 9, 4), 990000)
        result = bulk_day_plans(self.db, 1, self.bulk("2026-09-01", "2026-09-07"))
        self.assertEqual((result["changed_count"], result["skipped_count"]), (6, 1))
        preview = bulk_day_plans(
            self.db, 1, self.bulk("2026-09-01", "2026-09-07", overwrite_existing=True, dry_run=True)
        )
        self.assertEqual(preview["overwritten_count"], 1)
        self.assertEqual(
            self.db.scalar(
                select(DepartmentDayPlan).where(DepartmentDayPlan.target_date == date(2026, 9, 4))
            ).revenue_plan_minor,
            990000,
        )
        with self.assertRaises(HTTPException) as error:
            bulk_day_plans(self.db, 1, self.bulk("2026-09-01", "2026-09-07", overwrite_existing=True))
        self.assertEqual(error.exception.status_code, 409)
        save_plan(self.db, 1, 1, date(2026, 9, 4), 880000)
        with self.assertRaises(HTTPException):
            bulk_day_plans(
                self.db,
                1,
                self.bulk("2026-09-01", "2026-09-07", overwrite_existing=True, preview_token=preview["preview_token"]),
            )
        preview = bulk_day_plans(
            self.db, 1, self.bulk("2026-09-01", "2026-09-07", overwrite_existing=True, dry_run=True)
        )
        bulk_day_plans(
            self.db,
            1,
            self.bulk("2026-09-01", "2026-09-07", overwrite_existing=True, preview_token=preview["preview_token"]),
        )
        save_plan(self.db, 1, 1, date(2026, 9, 4), 777000)
        self.assertEqual(plan_calendar(self.db, 1, 1, "2026-09")["days"][3]["revenue_plan_minor"], 777000)

    def test_bulk_clear_range_requires_preview_and_deletes_plans(self):
        bulk_day_plans(self.db, 1, self.bulk("2026-09-01", "2026-09-07"))
        clear_payload = DepartmentDaysBulkIn(
            department_id=1,
            date_from="2026-09-01",
            date_to="2026-09-07",
            weekdays=[{"weekday": weekday, "revenue_plan_minor": None} for weekday in range(7)],
            overwrite_existing=True,
            clear_existing=True,
            dry_run=True,
        )
        preview = bulk_day_plans(self.db, 1, clear_payload)
        self.assertEqual(preview["changed_count"], 7)
        self.assertEqual(preview["deleted_count"], 7)
        self.assertEqual(self.db.scalar(select(DepartmentDayPlan).where(DepartmentDayPlan.venue_id == 1)).venue_id, 1)

        clear_payload.dry_run = False
        with self.assertRaises(HTTPException) as error:
            bulk_day_plans(self.db, 1, clear_payload)
        self.assertEqual(error.exception.status_code, 409)

        clear_payload.preview_token = preview["preview_token"]
        result = bulk_day_plans(self.db, 1, clear_payload)
        self.assertEqual(result["deleted_count"], 7)
        self.assertIsNone(self.db.scalar(select(DepartmentDayPlan).where(DepartmentDayPlan.venue_id == 1)))
        self.assertTrue(
            all(row["revenue_plan_minor"] is None for row in plan_calendar(self.db, 1, 1, "2026-09")["days"])
        )

    def test_plan_routes_recalculate_changed_month_and_day(self):
        user = SimpleNamespace(id=1, system_role="NONE")
        with (
            patch.object(venue_department_plans, "require_active_member_or_admin"),
            patch.object(venue_department_plans, "_require_pay_profiles_manage"),
            patch.object(
                venue_department_plans,
                "sanitize_financial_payload_for_user",
                side_effect=lambda _user, payload: payload,
            ),
            patch.object(venue_department_plans, "_recalculate_payroll_for_dates") as recalculate,
        ):
            venue_department_plans.put_department_month_plan(
                1,
                1,
                "2026-09",
                DepartmentPlanValueIn(revenue_plan_minor=1_000_000),
                self.db,
                user,
            )
            month_call = recalculate.call_args
            self.assertEqual(month_call.kwargs["trigger_reason"], "department_month_plan_updated")
            self.assertEqual(len(month_call.kwargs["target_dates"]), 30)

            recalculate.reset_mock()
            venue_department_plans.put_department_month_plan(
                1,
                1,
                "2026-09",
                DepartmentPlanValueIn(revenue_plan_minor=1_000_000),
                self.db,
                user,
            )
            recalculate.assert_not_called()

            venue_department_plans.put_department_day_plan(
                1,
                1,
                date(2026, 9, 4),
                DepartmentPlanValueIn(revenue_plan_minor=50_000),
                self.db,
                user,
            )
            self.assertEqual(recalculate.call_args.kwargs["target_dates"], [date(2026, 9, 4)])
            self.assertEqual(recalculate.call_args.kwargs["trigger_reason"], "department_day_plan_updated")

    def test_calendar_only_closed_reports_and_independent_targets(self):
        for day, slot, status, amount in [
            (1, "DAY", "CLOSED", 47500),
            (1, "NIGHT", "CLOSED", 2500),
            (2, "DAY", "DRAFT", 999999),
            (3, "DAY", "CLOSED", 0),
        ]:
            report = DailyReport(
                venue_id=1, date=date(2026, 9, day), shift_slot=slot, status=status, created_by_user_id=1
            )
            self.db.add(report)
            self.db.flush()
            self.db.add(DailyReportValue(report_id=report.id, kind="DEPT", ref_id=1, value_numeric=amount))
        save_plan(self.db, 1, 1, date(2026, 9, 1), 10000000, monthly=True)
        save_plan(self.db, 1, 1, date(2026, 9, 1), 5000000)
        result = plan_calendar(self.db, 1, 1, "2026-09")
        self.assertEqual(result["actual_minor"], 5000000)
        self.assertEqual(result["revenue_achievement_bps"], 5000)
        self.assertEqual([row["actual_minor"] for row in result["days"][:3]], [5000000, None, 0])
        self.assertEqual(result["days"][0]["revenue_achievement_bps"], 10000)
        self.assertIsNone(result["days"][1]["revenue_plan_minor"])
        save_plan(self.db, 1, 1, date(2026, 9, 1), None)
        self.assertIsNone(plan_calendar(self.db, 1, 1, "2026-09")["days"][0]["revenue_plan_minor"])
        with self.assertRaises(HTTPException):
            plan_calendar(self.db, 1, 2, "2026-09")

    def test_bulk_validation(self):
        for value in [0, -1]:
            with self.assertRaises(ValidationError):
                DepartmentPlanValueIn(revenue_plan_minor=value)
        for overrides in [
            {"date_to": "2026-08-01"},
            {"date_to": "2028-01-01"},
            {"weekdays": [{"weekday": 0, "revenue_plan_minor": None}]},
            {"weekdays": [{"weekday": 0, "revenue_plan_minor": 1}] * 2},
        ]:
            payload = self.bulk().model_dump()
            payload.update(overrides)
            with self.assertRaises(ValidationError):
                DepartmentDaysBulkIn(**payload)
        clear_payload = self.bulk().model_dump()
        clear_payload.update(
            {
                "weekdays": [{"weekday": weekday, "revenue_plan_minor": None} for weekday in range(7)],
                "clear_existing": True,
            }
        )
        self.assertTrue(DepartmentDaysBulkIn(**clear_payload).clear_existing)

    def create_component(self, **overrides):
        values = dict(
            component_type="PERCENT_DEPARTMENT_REVENUE",
            title="Bar tiers",
            percent_bps=300,
            department_id=1,
            base_scope="FULL_PERIOD",
            boost_source_type="DEPARTMENT_MONTH_PLAN",
            boost_department_id=1,
            percent_tiers=[
                {"threshold_value": threshold, "percent_bps": rate}
                for threshold, rate in [(100, 400), (110, 500), (120, 600)]
            ],
        )
        values.update(overrides)
        with (
            patch("app.routers.venue_pay_profiles._require_active_member_or_admin"),
            patch("app.routers.venue_pay_profiles._require_pay_profiles_manage"),
        ):
            result = create_pay_component(1, 1, PayComponentCreateIn(**values), self.db, SimpleNamespace(id=1))
        return self.db.get(PayComponent, result["id"])

    def decision(self, component, actual=117000000, target=100000000, daily=None, kpi=0):
        by_date = daily or {date(2026, 9, 4): actual}
        return _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(worked_dates=set(by_date)),
            revenue_metrics=PayrollRevenueMetrics(
                total_revenue_minor=sum(by_date.values()),
                total_revenue_by_date_minor=by_date,
                department_revenue_minor={1: sum(by_date.values())},
                department_revenue_by_date_minor={1: by_date},
            ),
            kpi_metrics=PayrollKpiMetrics(totals_by_metric_id={1: kpi}),
            venue_plan_metrics=PayrollVenuePlanMetrics(
                month_revenue_target_minor=target,
                day_revenue_target_by_date_minor={day: target for day in by_date},
                department_month_revenue_target_minor={1: target},
                department_day_revenue_target_by_date_minor={1: {day: target for day in by_date}},
            ),
        )

    def test_threshold_boundaries_and_missing_plan(self):
        component = self.create_component()
        for actual, rate in [
            (99990000, 300),
            (100000000, 400),
            (109990000, 400),
            (110000000, 500),
            (119990000, 500),
            (120000000, 600),
            (200000000, 600),
            (0, 300),
        ]:
            with self.subTest(actual=actual):
                result = self.decision(component, actual)
                self.assertEqual(result.applied_percent_bps, rate)
                self.assertEqual(result.amount_minor, actual * rate // 10000)
        for target in [None, 0]:
            self.assertEqual(self.decision(component, target=target).amount_minor, 3510000)
        snapshot = _build_percent_component_snapshot(component, self.decision(component))
        self.assertEqual(
            (
                snapshot["achievement_percent"],
                snapshot["matched_tier"]["threshold_value"],
                snapshot["final_amount_minor"],
            ),
            (117, 110, 5850000),
        )
        self.assertEqual(len(snapshot["percent_tiers"]), 3)

    def test_excess_daily_monthly_and_limits(self):
        component = self.create_component(boost_recalc_mode="EXCESS_ONLY")
        result = self.decision(component)
        self.assertEqual(result.amount_minor, 3750000)
        self.assertEqual(sum(row["amount_minor"] for row in result.tier_details["segments"]), 3750000)
        component.boost_source_type = "DEPARTMENT_DAY_PLAN"
        result = self.decision(component, daily={date(2026, 9, 4): 117000000, date(2026, 9, 5): 99000000})
        self.assertEqual([row["percent_bps"] for row in result.day_rows], [500, 300])
        self.assertEqual(result.amount_minor, 3750000 + 2970000)
        component.boost_recalc_mode = "REPLACE_ALL"
        component.minimum_guarantee_minor = 4000000
        component.minimum_guarantee_scope = "DAY"
        result = self.decision(component, daily={date(2026, 9, 4): 117000000, date(2026, 9, 5): 99000000})
        self.assertEqual(result.amount_minor, 5850000 + 4000000)
        component.maximum_cap_minor = 8000000
        self.assertEqual(
            self.decision(component, daily={date(2026, 9, 4): 117000000, date(2026, 9, 5): 99000000}).amount_minor,
            8000000,
        )

    def test_venue_and_multiple_department_sources(self):
        venue_component = self.create_component(
            component_type="PERCENT_TOTAL_REVENUE",
            department_id=None,
            department_ids=None,
            boost_source_type="VENUE_MONTH_PLAN",
            boost_department_id=None,
            boost_department_ids=None,
        )
        self.assertEqual(self.decision(venue_component).applied_percent_bps, 500)

        departments_component = self.create_component(
            department_ids=[1, 3],
            boost_department_ids=[1, 3],
        )
        decision = _build_percent_component_decision(
            departments_component,
            metrics=PayrollMemberMetrics(worked_dates={date(2026, 9, 4)}),
            revenue_metrics=PayrollRevenueMetrics(
                department_revenue_minor={1: 60000000, 3: 57000000},
                department_revenue_by_date_minor={
                    1: {date(2026, 9, 4): 60000000},
                    3: {date(2026, 9, 4): 57000000},
                },
            ),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(
                department_month_revenue_target_minor={1: 50000000, 3: 50000000},
            ),
        )
        self.assertEqual(decision.base_amount_minor, 117000000)
        self.assertEqual(decision.applied_percent_bps, 500)
        self.assertEqual(decision.boost_department_ids, [1, 3])

        departments_component.boost_source_type = "DEPARTMENT_DAY_PLAN"
        missing_day_plan = _build_percent_component_decision(
            departments_component,
            metrics=PayrollMemberMetrics(worked_dates={date(2026, 9, 4), date(2026, 9, 5)}),
            revenue_metrics=PayrollRevenueMetrics(
                department_revenue_minor={1: 120000000, 3: 114000000},
                department_revenue_by_date_minor={
                    1: {date(2026, 9, 4): 60000000, date(2026, 9, 5): 60000000},
                    3: {date(2026, 9, 4): 57000000, date(2026, 9, 5): 57000000},
                },
            ),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(
                department_day_revenue_target_by_date_minor={
                    1: {date(2026, 9, 4): 50000000},
                    3: {date(2026, 9, 4): 50000000},
                },
            ),
        )
        self.assertEqual([row["percent_bps"] for row in missing_day_plan.day_rows], [500, 300])

    def test_kpi_absolute_thresholds(self):
        self.db.add(KpiMetric(id=1, venue_id=1, code="HOOKAH", title="Hookahs", unit="QTY"))
        self.db.commit()
        component = self.create_component(
            boost_source_type="KPI_METRIC",
            boost_kpi_metric_id=1,
            percent_tiers=[{"threshold_value": 100, "percent_bps": 400}, {"threshold_value": 150, "percent_bps": 500}],
        )
        self.assertEqual(self.decision(component, kpi=149).applied_percent_bps, 400)
        self.assertEqual(self.decision(component, kpi=150).applied_percent_bps, 500)

    def test_tier_validation_updates_and_delete_preserve_component(self):
        for tiers in [
            [{"threshold_value": 100, "percent_bps": 400}] * 2,
            [{"threshold_value": 100, "percent_bps": 200}],
            [{"threshold_value": 100, "percent_bps": 500}, {"threshold_value": 110, "percent_bps": 400}],
        ]:
            with self.assertRaises(HTTPException):
                self.create_component(percent_tiers=tiers)
            self.db.rollback()
        with self.assertRaises(HTTPException):
            self.create_component(base_scope="WORKED_DATES", boost_recalc_mode="EXCESS_ONLY")
        self.db.rollback()
        component = self.create_component()
        with (
            patch("app.routers.venue_pay_profiles._require_active_member_or_admin"),
            patch("app.routers.venue_pay_profiles._require_pay_profiles_manage"),
        ):
            payload = PayComponentUpdateIn(percent_tiers=[{"threshold_value": 110, "percent_bps": 550}])
            update_pay_component(1, component.id, payload, self.db, SimpleNamespace(id=1))
            self.assertEqual(len(component.percent_tiers), 1)
            self.assertEqual(component.percent_tiers[0].percent_bps, 550)
            update_pay_component(
                1, component.id, PayComponentUpdateIn(percent_tiers=[]), self.db, SimpleNamespace(id=1)
            )
        self.assertIsNotNone(self.db.get(PayComponent, component.id))
        self.assertFalse(component.boost_enabled)
        self.assertEqual(self.decision(component).amount_minor, 3510000)

    def test_legacy_boost_becomes_equivalent_tier(self):
        component = self.create_component(percent_tiers=None, boost_enabled=True, boost_percent_bps=500)
        # An explicit empty/null tier list disables thresholds; omitted list supports old clients.
        self.assertFalse(component.boost_enabled)
        with (
            patch("app.routers.venue_pay_profiles._require_active_member_or_admin"),
            patch("app.routers.venue_pay_profiles._require_pay_profiles_manage"),
        ):
            update_pay_component(
                1,
                component.id,
                PayComponentUpdateIn(boost_enabled=True, boost_percent_bps=500),
                self.db,
                SimpleNamespace(id=1),
            )
        self.assertEqual(component.percent_tiers[0].threshold_value, Decimal(100))
        self.assertEqual(self.decision(component).amount_minor, 5850000)
