from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest import TestCase

from app.services.payroll.calculator import (
    BASE_SCOPE_FULL_PERIOD,
    BASE_SCOPE_WORKED_DATES,
    BOOST_RECALC_EXCESS_ONLY,
    BOOST_SOURCE_KPI_METRIC,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
    PayrollKpiMetrics,
    PayrollMemberMetrics,
    PayrollRevenueMetrics,
    PayrollVenuePlanMetrics,
    _build_percent_component_decision,
    calculate_component_amount_minor,
    calculate_kpi_bonus,
    interval_duration_minutes,
    parse_month_start,
)


class PayrollCalculationHelpersTests(TestCase):
    def test_parse_month_start_accepts_yyyy_mm(self):
        month_start = parse_month_start("2026-03")
        self.assertEqual(month_start.isoformat(), "2026-03-01")

    def test_parse_month_start_rejects_bad_format(self):
        with self.assertRaisesRegex(ValueError, "expected YYYY-MM"):
            parse_month_start("03-2026")

    def test_interval_duration_minutes_supports_overnight_shift(self):
        minutes = interval_duration_minutes(time(22, 0), time(6, 0))
        self.assertEqual(minutes, 8 * 60)

    def test_calculate_component_amount_minor_for_fixed_month(self):
        component = SimpleNamespace(component_type="SALARY_FIXED_MONTH", amount_minor=150000, rate_minor=None)
        amount_minor = calculate_component_amount_minor(component, minutes_total=0, shifts_count=0)
        self.assertEqual(amount_minor, 150000)

    def test_calculate_component_amount_minor_for_hourly(self):
        component = SimpleNamespace(component_type="SALARY_HOURLY", amount_minor=None, rate_minor=12500)
        amount_minor = calculate_component_amount_minor(component, minutes_total=9 * 60 + 30, shifts_count=0)
        self.assertEqual(amount_minor, 118750)

    def test_calculate_component_amount_minor_for_per_shift(self):
        component = SimpleNamespace(component_type="SALARY_PER_SHIFT", amount_minor=32000, rate_minor=None)
        amount_minor = calculate_component_amount_minor(component, minutes_total=0, shifts_count=7)
        self.assertEqual(amount_minor, 224000)

    def test_calculate_component_amount_minor_for_percent_total_revenue(self):
        component = SimpleNamespace(component_type="PERCENT_TOTAL_REVENUE", percent_bps=750, amount_minor=None, rate_minor=None)
        amount_minor = calculate_component_amount_minor(component, minutes_total=0, shifts_count=0, total_revenue_minor=1234567)
        self.assertEqual(amount_minor, 92593)

    def test_calculate_component_amount_minor_for_percent_department_revenue(self):
        component = SimpleNamespace(component_type="PERCENT_DEPARTMENT_REVENUE", percent_bps=1250, department_id=3, amount_minor=None, rate_minor=None)
        amount_minor = calculate_component_amount_minor(component, minutes_total=0, shifts_count=0, department_revenue_minor=800000)
        self.assertEqual(amount_minor, 100000)

    def test_calculate_kpi_bonus_with_threshold(self):
        component = SimpleNamespace(component_type="KPI_BONUS", amount_minor=150000, threshold_value=20, steps_json=None)
        decision = calculate_kpi_bonus(component, kpi_metric_value=24)
        self.assertEqual(decision.amount_minor, 150000)
        self.assertEqual(decision.metric_value, 24)
        self.assertEqual(decision.threshold_value, 20)
        self.assertIsNone(decision.matched_step)

    def test_calculate_kpi_bonus_below_threshold(self):
        component = SimpleNamespace(component_type="KPI_BONUS", amount_minor=150000, threshold_value=20, steps_json=None)
        decision = calculate_kpi_bonus(component, kpi_metric_value=19)
        self.assertEqual(decision.amount_minor, 0)

    def test_calculate_kpi_bonus_with_steps_uses_highest_matched_step(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            amount_minor=None,
            threshold_value=None,
            steps_json=[
                {"threshold_value": 10, "amount_minor": 10000},
                {"threshold_value": 20, "amount_minor": 25000},
                {"threshold_value": 30, "amount_minor": 45000},
            ],
        )
        decision = calculate_kpi_bonus(component, kpi_metric_value=27)
        self.assertEqual(decision.amount_minor, 25000)
        self.assertEqual(decision.matched_step, {"threshold_value": 20, "amount_minor": 25000})
        self.assertEqual(len(decision.steps), 3)

    def test_calculate_component_amount_minor_for_kpi_bonus(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            amount_minor=90000,
            threshold_value=15,
            steps_json=None,
        )
        amount_minor = calculate_component_amount_minor(component, minutes_total=0, shifts_count=0, kpi_metric_value=15)
        self.assertEqual(amount_minor, 90000)


class PayrollPercentDecisionTests(TestCase):
    def test_percent_department_defaults_to_worked_dates_scope(self):
        component = SimpleNamespace(
            component_type="PERCENT_DEPARTMENT_REVENUE",
            percent_bps=500,
            department_id=3,
            base_scope=None,
            boost_enabled=False,
            boost_percent_bps=None,
            boost_source_type=None,
            boost_recalc_mode=None,
            minimum_guarantee_minor=None,
            maximum_cap_minor=None,
        )
        decision = _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(worked_dates={__import__("datetime").date(2026, 3, 2)}),
            revenue_metrics=PayrollRevenueMetrics(
                department_revenue_minor={3: 900000},
                department_revenue_by_date_minor={3: {__import__("datetime").date(2026, 3, 2): 300000, __import__("datetime").date(2026, 3, 3): 600000}},
            ),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(),
        )
        self.assertEqual(decision.base_scope, BASE_SCOPE_WORKED_DATES)
        self.assertEqual(decision.base_amount_minor, 300000)
        self.assertEqual(decision.amount_minor, 15000)

    def test_percent_total_with_month_plan_boost_replace_all(self):
        component = SimpleNamespace(
            component_type="PERCENT_TOTAL_REVENUE",
            percent_bps=300,
            base_scope=BASE_SCOPE_FULL_PERIOD,
            boost_enabled=True,
            boost_percent_bps=450,
            boost_source_type=BOOST_SOURCE_VENUE_MONTH_PLAN,
            boost_recalc_mode=None,
            boost_kpi_metric_id=None,
            boost_threshold_value=None,
            minimum_guarantee_minor=None,
            maximum_cap_minor=None,
        )
        decision = _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(),
            revenue_metrics=PayrollRevenueMetrics(total_revenue_minor=1_500_000, total_revenue_by_date_minor={}),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(month_revenue_target_minor=1_200_000),
        )
        self.assertTrue(decision.boost_applied)
        self.assertEqual(decision.amount_minor, 67500)
        self.assertEqual(decision.applied_percent_bps, 450)

    def test_percent_total_with_day_plan_excess_only(self):
        from datetime import date
        component = SimpleNamespace(
            component_type="PERCENT_TOTAL_REVENUE",
            percent_bps=500,
            base_scope=BASE_SCOPE_FULL_PERIOD,
            boost_enabled=True,
            boost_percent_bps=700,
            boost_source_type=BOOST_SOURCE_VENUE_DAY_PLAN,
            boost_recalc_mode=BOOST_RECALC_EXCESS_ONLY,
            boost_kpi_metric_id=None,
            boost_threshold_value=None,
            minimum_guarantee_minor=None,
            maximum_cap_minor=None,
        )
        decision = _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(),
            revenue_metrics=PayrollRevenueMetrics(
                total_revenue_minor=400000,
                total_revenue_by_date_minor={date(2026, 3, 2): 400000},
            ),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(day_revenue_target_by_date_minor={date(2026, 3, 2): 300000}),
        )
        self.assertTrue(decision.boost_applied)
        self.assertEqual(decision.amount_minor, 27000)

    def test_percent_total_applies_minimum_and_cap(self):
        component = SimpleNamespace(
            component_type="PERCENT_TOTAL_REVENUE",
            percent_bps=300,
            base_scope=BASE_SCOPE_FULL_PERIOD,
            boost_enabled=False,
            boost_percent_bps=None,
            boost_source_type=None,
            boost_recalc_mode=None,
            boost_kpi_metric_id=None,
            boost_threshold_value=None,
            minimum_guarantee_minor=40000,
            maximum_cap_minor=45000,
        )
        decision = _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(),
            revenue_metrics=PayrollRevenueMetrics(total_revenue_minor=1_000_000),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(),
        )
        self.assertTrue(decision.minimum_applied)
        self.assertEqual(decision.amount_minor, 40000)

    def test_percent_total_with_kpi_boost(self):
        component = SimpleNamespace(
            component_type="PERCENT_TOTAL_REVENUE",
            percent_bps=300,
            base_scope=BASE_SCOPE_FULL_PERIOD,
            boost_enabled=True,
            boost_percent_bps=450,
            boost_source_type=BOOST_SOURCE_KPI_METRIC,
            boost_recalc_mode=None,
            boost_kpi_metric_id=8,
            boost_threshold_value=20,
            minimum_guarantee_minor=None,
            maximum_cap_minor=None,
        )
        decision = _build_percent_component_decision(
            component,
            metrics=PayrollMemberMetrics(),
            revenue_metrics=PayrollRevenueMetrics(total_revenue_minor=1_000_000),
            kpi_metrics=PayrollKpiMetrics(totals_by_metric_id={8: 24}),
            venue_plan_metrics=PayrollVenuePlanMetrics(),
        )
        self.assertTrue(decision.boost_applied)
        self.assertEqual(decision.amount_minor, 45000)
