from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase

from fastapi import HTTPException

from app.routers.venue_pay_profile_support import _validate_pay_component_fields
from app.services.payroll.day_breakdown import DayAllocationContext, _component_allocation_for_day
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
    PayrollWorkedShift,
    _component_shift_allocations,
    _build_percent_component_decision,
    _sum_kpi_for_worked_shifts,
    calculate_component_amount_minor,
    calculate_kpi_bonus,
    interval_duration_minutes,
    parse_month_start,
)
from app.services.payroll.weekday_rates import calculate_weekday_rate_amount_minor


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

    def test_hourly_weekday_rates_override_only_selected_days(self):
        shifts = [
            PayrollWorkedShift(shift_id=1, shift_date=date(2026, 8, 17), shift_slot="DAY", minutes=480),
            PayrollWorkedShift(shift_id=2, shift_date=date(2026, 8, 18), shift_slot="DAY", minutes=480),
        ]
        component = SimpleNamespace(
            component_type="SALARY_HOURLY",
            amount_minor=None,
            rate_minor=50_000,
            weekday_rates_json='[{"weekday": 0, "rate_minor": 65000}]',
        )

        amount_minor = calculate_weekday_rate_amount_minor(component, shifts)

        self.assertEqual(amount_minor, 920_000)

    def test_per_shift_weekday_rates_are_used_in_shift_allocations(self):
        shifts = [
            PayrollWorkedShift(shift_id=10, shift_date=date(2026, 8, 21), shift_slot="DAY", minutes=480),
            PayrollWorkedShift(shift_id=11, shift_date=date(2026, 8, 22), shift_slot="DAY", minutes=480),
            PayrollWorkedShift(shift_id=12, shift_date=date(2026, 8, 23), shift_slot="DAY", minutes=480),
        ]
        metrics = PayrollMemberMetrics(minutes_total=1440, shifts_count=3, worked_shifts=shifts)
        component = SimpleNamespace(
            component_type="SALARY_PER_SHIFT",
            amount_minor=200_000,
            rate_minor=None,
            weekday_rates_json='[{"weekday": 5, "rate_minor": 300000}, {"weekday": 6, "rate_minor": 350000}]',
        )

        amount_minor = calculate_weekday_rate_amount_minor(component, shifts)
        allocations = _component_shift_allocations(
            component=component,
            amount_minor=amount_minor,
            metrics=metrics,
            month_start=date(2026, 8, 1),
            month_end_excl=date(2026, 9, 1),
            revenue_metrics=PayrollRevenueMetrics(),
        )

        self.assertEqual(amount_minor, 850_000)
        self.assertEqual(allocations, {10: 200_000, 11: 300_000, 12: 350_000})

    def test_calculate_component_amount_minor_for_percent_total_revenue(self):
        component = SimpleNamespace(
            component_type="PERCENT_TOTAL_REVENUE", percent_bps=750, amount_minor=None, rate_minor=None
        )
        amount_minor = calculate_component_amount_minor(
            component, minutes_total=0, shifts_count=0, total_revenue_minor=1234567
        )
        self.assertEqual(amount_minor, 92593)

    def test_calculate_component_amount_minor_for_percent_department_revenue(self):
        component = SimpleNamespace(
            component_type="PERCENT_DEPARTMENT_REVENUE",
            percent_bps=1250,
            department_id=3,
            amount_minor=None,
            rate_minor=None,
        )
        amount_minor = calculate_component_amount_minor(
            component, minutes_total=0, shifts_count=0, department_revenue_minor=800000
        )
        self.assertEqual(amount_minor, 100000)

    def test_calculate_kpi_bonus_with_threshold(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS", amount_minor=150000, threshold_value=20, steps_json=None
        )
        decision = calculate_kpi_bonus(component, kpi_metric_value=24)
        self.assertEqual(decision.amount_minor, 150000)
        self.assertEqual(decision.metric_value, 24)
        self.assertEqual(decision.threshold_value, 20)
        self.assertIsNone(decision.matched_step)

    def test_calculate_kpi_bonus_below_threshold(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS", amount_minor=150000, threshold_value=20, steps_json=None
        )
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

    def test_calculate_percentage_kpi_bonus_from_ruble_metric(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            kpi_calculation_mode="PERCENT",
            percent_bps=500,
            amount_minor=None,
            threshold_value=None,
            steps_json=None,
        )
        decision = calculate_kpi_bonus(component, kpi_metric_value=100_000)
        self.assertEqual(decision.amount_minor, 500_000)
        self.assertEqual(decision.base_amount_minor, 10_000_000)
        self.assertEqual(decision.percent_bps, 500)
        self.assertEqual(decision.calculation_mode, "PERCENT")

    def test_percentage_kpi_bonus_respects_optional_threshold(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            kpi_calculation_mode="PERCENT",
            percent_bps=500,
            amount_minor=None,
            threshold_value=50_000,
            steps_json=None,
        )
        decision = calculate_kpi_bonus(component, kpi_metric_value=49_999)
        self.assertEqual(decision.amount_minor, 0)

    def test_per_unit_kpi_bonus_multiplies_quantity_by_rate(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            kpi_calculation_mode="PER_UNIT",
            rate_minor=22_000,
            threshold_value=None,
            steps_json=None,
        )
        decision = calculate_kpi_bonus(component, kpi_metric_value=2)
        self.assertEqual(decision.amount_minor, 44_000)
        self.assertEqual(decision.calculation_mode, "PER_UNIT")

    def test_per_unit_kpi_bonus_respects_optional_threshold(self):
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            kpi_calculation_mode="PER_UNIT",
            rate_minor=22_000,
            threshold_value=3,
            steps_json=None,
        )
        self.assertEqual(calculate_kpi_bonus(component, kpi_metric_value=2).amount_minor, 0)
        self.assertEqual(calculate_kpi_bonus(component, kpi_metric_value=3).amount_minor, 66_000)

    def test_percentage_kpi_uses_only_unique_worked_report_slots(self):
        d1 = date(2026, 7, 10)
        metrics = PayrollMemberMetrics(
            worked_shifts=[
                PayrollWorkedShift(shift_id=1, shift_date=d1, shift_slot="DAY", minutes=480),
                PayrollWorkedShift(shift_id=2, shift_date=d1, shift_slot="DAY", minutes=120),
                PayrollWorkedShift(shift_id=3, shift_date=d1, shift_slot="NIGHT", minutes=480),
            ]
        )
        kpi_metrics = PayrollKpiMetrics(
            values_by_metric_date_slot={
                9: {
                    (d1, "DAY"): 100_000,
                    (d1, "NIGHT"): 40_000,
                }
            }
        )
        self.assertEqual(
            _sum_kpi_for_worked_shifts(kpi_metrics, metric_id=9, metrics=metrics),
            140_000,
        )

    def test_percentage_kpi_shift_allocation_follows_report_values(self):
        d1 = date(2026, 7, 10)
        metrics = PayrollMemberMetrics(
            worked_shifts=[
                PayrollWorkedShift(shift_id=1, shift_date=d1, shift_slot="DAY", minutes=480),
                PayrollWorkedShift(shift_id=2, shift_date=d1, shift_slot="NIGHT", minutes=480),
            ]
        )
        component = SimpleNamespace(
            component_type="KPI_BONUS",
            kpi_calculation_mode="PERCENT",
            kpi_metric_id=9,
        )
        allocations = _component_shift_allocations(
            component=component,
            amount_minor=700_000,
            metrics=metrics,
            month_start=date(2026, 7, 1),
            month_end_excl=date(2026, 8, 1),
            revenue_metrics=PayrollRevenueMetrics(),
            kpi_values_by_metric_date_slot={
                9: {
                    (d1, "DAY"): 100_000,
                    (d1, "NIGHT"): 40_000,
                }
            },
        )
        self.assertEqual(allocations, {1: 500_000, 2: 200_000})

    def test_per_unit_kpi_shift_allocation_follows_report_values(self):
        d1 = date(2026, 7, 10)
        metrics = PayrollMemberMetrics(
            worked_shifts=[
                PayrollWorkedShift(shift_id=1, shift_date=d1, shift_slot="DAY", minutes=480),
                PayrollWorkedShift(shift_id=2, shift_date=d1, shift_slot="NIGHT", minutes=480),
            ]
        )
        component = SimpleNamespace(component_type="KPI_BONUS", kpi_calculation_mode="PER_UNIT", kpi_metric_id=9)
        allocations = _component_shift_allocations(
            component=component,
            amount_minor=66_000,
            metrics=metrics,
            month_start=date(2026, 7, 1),
            month_end_excl=date(2026, 8, 1),
            revenue_metrics=PayrollRevenueMetrics(),
            kpi_values_by_metric_date_slot={9: {(d1, "DAY"): 2, (d1, "NIGHT"): 1}},
        )
        self.assertEqual(allocations, {1: 44_000, 2: 22_000})

    def test_per_unit_kpi_day_breakdown_uses_employee_scoped_values(self):
        d1, d2 = date(2026, 7, 10), date(2026, 7, 11)
        context = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1, d2],
            minutes_by_date={d1: 480, d2: 480},
            shifts_by_date={d1: 1, d2: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={9: {d1: 10, d2: 10}},
        )
        component = {
            "component_type": "KPI_BONUS",
            "title": "Допродажи",
            "amount_minor": 66_000,
            "kpi_metric_id": 9,
            "kpi_metric_title": "Допродажи",
            "kpi_calculation_mode": "PER_UNIT",
            "source_rate_minor": 22_000,
            "metric_values_by_date_slot": {
                d1.isoformat(): {"DAY": 1},
                d2.isoformat(): {"DAY": 2},
            },
        }
        row = _component_allocation_for_day(component=component, target_date=d1, context=context)
        self.assertIsNotNone(row)
        self.assertEqual(row["amount_minor"], 22_000)
        self.assertIn("220 ₽ × 1 ед.", row["formula_text"])


class PayComponentValidationTests(TestCase):
    def test_weekday_rates_are_supported_only_for_hourly_and_per_shift_components(self):
        _validate_pay_component_fields(
            component_type="SALARY_HOURLY",
            amount_minor=None,
            rate_minor=50_000,
            percent_bps=None,
            department_id=None,
            weekday_rates=[{"weekday": 5, "rate_minor": 65_000}],
        )
        with self.assertRaises(HTTPException):
            _validate_pay_component_fields(
                component_type="SALARY_FIXED_MONTH",
                amount_minor=5_000_000,
                rate_minor=None,
                percent_bps=None,
                department_id=None,
                weekday_rates=[{"weekday": 5, "rate_minor": 65_000}],
            )

    def test_weekday_rates_reject_duplicate_weekdays(self):
        with self.assertRaises(HTTPException):
            _validate_pay_component_fields(
                component_type="SALARY_PER_SHIFT",
                amount_minor=200_000,
                rate_minor=None,
                percent_bps=None,
                department_id=None,
                weekday_rates=[
                    {"weekday": 5, "rate_minor": 300_000},
                    {"weekday": 5, "rate_minor": 350_000},
                ],
            )

    def test_percentage_kpi_requires_ruble_metric(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_pay_component_fields(
                component_type="KPI_BONUS",
                amount_minor=None,
                rate_minor=None,
                percent_bps=500,
                department_id=None,
                kpi_metric_id=9,
                kpi_calculation_mode="PERCENT",
                kpi_metric_unit="QTY",
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_percentage_kpi_accepts_ruble_metric(self):
        _validate_pay_component_fields(
            component_type="KPI_BONUS",
            amount_minor=None,
            rate_minor=None,
            percent_bps=500,
            department_id=None,
            kpi_metric_id=9,
            kpi_calculation_mode="PERCENT",
            kpi_metric_unit="RUB",
        )

    def test_per_unit_kpi_accepts_qty_metric_and_rate(self):
        _validate_pay_component_fields(
            component_type="KPI_BONUS",
            amount_minor=None,
            rate_minor=22_000,
            percent_bps=None,
            department_id=None,
            kpi_metric_id=9,
            kpi_calculation_mode="PER_UNIT",
            kpi_metric_unit="QTY",
        )

    def test_per_unit_kpi_rejects_wrong_unit_or_missing_rate(self):
        for unit, rate_minor in (("RUB", 22_000), ("QTY", None)):
            with self.subTest(unit=unit, rate_minor=rate_minor), self.assertRaises(HTTPException):
                _validate_pay_component_fields(
                    component_type="KPI_BONUS",
                    amount_minor=None,
                    rate_minor=rate_minor,
                    percent_bps=None,
                    department_id=None,
                    kpi_metric_id=9,
                    kpi_calculation_mode="PER_UNIT",
                    kpi_metric_unit=unit,
                )

    def test_salary_accrual_day_is_only_metadata_for_fixed_month(self):
        _validate_pay_component_fields(
            component_type="SALARY_FIXED_MONTH",
            amount_minor=100_000,
            rate_minor=None,
            percent_bps=None,
            department_id=None,
            salary_accrual_day=15,
        )
        with self.assertRaises(HTTPException):
            _validate_pay_component_fields(
                component_type="SALARY_HOURLY",
                amount_minor=None,
                rate_minor=10_000,
                percent_bps=None,
                department_id=None,
                salary_accrual_day=15,
            )


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
                department_revenue_by_date_minor={
                    3: {
                        __import__("datetime").date(2026, 3, 2): 300000,
                        __import__("datetime").date(2026, 3, 3): 600000,
                    }
                },
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
            revenue_metrics=PayrollRevenueMetrics(
                total_revenue_minor=1_500_000,
                total_revenue_by_date_minor={date(2026, 3, 1): 1_500_000},
            ),
            kpi_metrics=PayrollKpiMetrics(),
            venue_plan_metrics=PayrollVenuePlanMetrics(month_revenue_target_minor=1_200_000),
        )
        self.assertTrue(decision.boost_applied)
        self.assertEqual(decision.amount_minor, 67500)
        self.assertEqual(decision.applied_percent_bps, 450)

    def test_percent_total_with_day_plan_excess_only(self):
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
        self.assertEqual(decision.amount_minor, 22000)

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
            revenue_metrics=PayrollRevenueMetrics(
                total_revenue_minor=1_000_000,
                total_revenue_by_date_minor={date(2026, 3, 1): 1_000_000},
            ),
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
            revenue_metrics=PayrollRevenueMetrics(
                total_revenue_minor=1_000_000,
                total_revenue_by_date_minor={date(2026, 3, 1): 1_000_000},
            ),
            kpi_metrics=PayrollKpiMetrics(totals_by_metric_id={8: 24}),
            venue_plan_metrics=PayrollVenuePlanMetrics(),
        )
        self.assertTrue(decision.boost_applied)
        self.assertEqual(decision.amount_minor, 45000)
