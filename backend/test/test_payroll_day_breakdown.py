from __future__ import annotations

from datetime import date
from unittest import TestCase

from app.services.payroll.day_breakdown import (
    DayAllocationContext,
    _allocate_minor_by_keys,
    _component_allocation_for_day,
)


class PayrollDayBreakdownHelpersTests(TestCase):
    def test_allocate_minor_by_keys_distributes_remainder_deterministically(self):
        d1 = date(2026, 3, 1)
        d2 = date(2026, 3, 2)
        d3 = date(2026, 3, 3)
        out = _allocate_minor_by_keys(100, [d1, d2, d3], {d1: 1, d2: 1, d3: 1})
        self.assertEqual(out[d1], 34)
        self.assertEqual(out[d2], 33)
        self.assertEqual(out[d3], 33)
        self.assertEqual(sum(out.values()), 100)

    def test_allocate_minor_by_keys_keeps_sign_for_negative_totals(self):
        d1 = date(2026, 3, 1)
        d2 = date(2026, 3, 2)
        out = _allocate_minor_by_keys(-5, [d1, d2], {d1: 1, d2: 1})
        self.assertEqual(sum(out.values()), -5)
        self.assertEqual(out[d1], -3)
        self.assertEqual(out[d2], -2)

    def test_component_allocation_for_fixed_month_uses_calendar_dates(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1, d2],
            minutes_by_date={d1: 300, d2: 300},
            shifts_by_date={d1: 1, d2: 1},
            revenue_by_date_minor={d1: 100_000, d2: 120_000},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        item = _component_allocation_for_day(
            component={
                "component_type": "SALARY_FIXED_MONTH",
                "title": "Оклад",
                "amount_minor": 10_001,
                "source_amount_minor": 10_001,
            },
            target_date=d1,
            context=ctx,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "Оклад")
        self.assertEqual(item["amount_minor"], 5001)
        self.assertIn("дней месяца", item["formula_text"])

    def test_fixed_month_allocation_shows_accrual_day_without_changing_split(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1],
            minutes_by_date={d1: 300},
            shifts_by_date={d1: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        item = _component_allocation_for_day(
            component={
                "component_type": "SALARY_FIXED_MONTH",
                "title": "Оклад",
                "amount_minor": 10_000,
                "source_amount_minor": 10_000,
                "salary_accrual_day": 15,
            },
            target_date=d1,
            context=ctx,
        )
        self.assertEqual(item["amount_minor"], 5_000)
        self.assertIn("начисление 15-го числа", item["formula_text"])

    def test_prorated_fixed_month_is_visible_only_on_profile_active_dates(self):
        d1, d2, d3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2, d3],
            worked_dates=[],
            minutes_by_date={},
            shifts_by_date={},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "SALARY_FIXED_MONTH",
            "title": "Новый оклад",
            "amount_minor": 20_000,
            "source_amount_minor": 30_000,
            "profile_active_dates": [d2.isoformat(), d3.isoformat()],
            "month_dates_count": 3,
        }

        self.assertIsNone(_component_allocation_for_day(component=component, target_date=d1, context=ctx))
        active_day = _component_allocation_for_day(component=component, target_date=d2, context=ctx)
        self.assertEqual(active_day["amount_minor"], 10_000)
        self.assertIn("2 дней действия профиля", active_day["base_text"])
        self.assertIn("/ 3 дней месяца", active_day["formula_text"])

    def test_account_merge_worked_dates_keep_component_on_its_origin_dates(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1, d2],
            minutes_by_date={d1: 300, d2: 600},
            shifts_by_date={d1: 1, d2: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "SALARY_HOURLY",
            "title": "Почасовая ставка исходного аккаунта",
            "amount_minor": 90_000,
            "account_merge_worked_dates": [d1.isoformat()],
        }

        origin_day = _component_allocation_for_day(component=component, target_date=d1, context=ctx)
        other_account_day = _component_allocation_for_day(component=component, target_date=d2, context=ctx)

        self.assertIsNotNone(origin_day)
        self.assertEqual(origin_day["amount_minor"], 90_000)
        self.assertIsNone(other_account_day)

    def test_component_without_account_merge_scope_keeps_legacy_allocation(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1, d2],
            minutes_by_date={d1: 300, d2: 600},
            shifts_by_date={d1: 1, d2: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "SALARY_HOURLY",
            "title": "Обычная почасовая ставка",
            "amount_minor": 90_000,
        }

        d1_item = _component_allocation_for_day(component=component, target_date=d1, context=ctx)
        d2_item = _component_allocation_for_day(component=component, target_date=d2, context=ctx)

        self.assertEqual(d1_item["amount_minor"], 30_000)
        self.assertEqual(d2_item["amount_minor"], 60_000)

    def test_shift_component_with_explicit_rows_does_not_leak_to_another_profile_date(self):
        waiter_day = date(2026, 3, 5)
        hookah_day = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[waiter_day, hookah_day],
            worked_dates=[waiter_day, hookah_day],
            minutes_by_date={waiter_day: 300, hookah_day: 600},
            shifts_by_date={waiter_day: 1, hookah_day: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "SALARY_PER_SHIFT",
            "title": "Ставка официанта",
            "pay_profile_title": "Официант",
            "amount_minor": 65_000,
            "shift_rows": [
                {
                    "date": waiter_day.isoformat(),
                    "amount_minor": 65_000,
                    "applied_rate_minor": 65_000,
                }
            ],
        }

        waiter_item = _component_allocation_for_day(component=component, target_date=waiter_day, context=ctx)
        hookah_item = _component_allocation_for_day(component=component, target_date=hookah_day, context=ctx)

        self.assertEqual(waiter_item["amount_minor"], 65_000)
        self.assertIsNone(hookah_item)

    def test_hourly_component_with_explicit_rows_does_not_leak_to_another_profile_date(self):
        waiter_day = date(2026, 3, 5)
        hookah_day = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[waiter_day, hookah_day],
            worked_dates=[waiter_day, hookah_day],
            minutes_by_date={waiter_day: 300, hookah_day: 600},
            shifts_by_date={waiter_day: 1, hookah_day: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "SALARY_HOURLY",
            "title": "Почасовая ставка официанта",
            "pay_profile_title": "Официант",
            "amount_minor": 90_000,
            "shift_rows": [
                {
                    "date": waiter_day.isoformat(),
                    "amount_minor": 90_000,
                    "applied_rate_minor": 18_000,
                }
            ],
        }

        waiter_item = _component_allocation_for_day(component=component, target_date=waiter_day, context=ctx)
        hookah_item = _component_allocation_for_day(component=component, target_date=hookah_day, context=ctx)

        self.assertEqual(waiter_item["amount_minor"], 90_000)
        self.assertIsNone(hookah_item)

    def test_percent_component_with_explicit_rows_does_not_leak_to_another_profile_date(self):
        waiter_day = date(2026, 3, 5)
        hookah_day = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[waiter_day, hookah_day],
            worked_dates=[waiter_day, hookah_day],
            minutes_by_date={waiter_day: 300, hookah_day: 600},
            shifts_by_date={waiter_day: 1, hookah_day: 1},
            revenue_by_date_minor={waiter_day: 1_000_000, hookah_day: 2_000_000},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "PERCENT_TOTAL_REVENUE",
            "title": "Процент официанта",
            "pay_profile_title": "Официант",
            "amount_minor": 50_000,
            "percent_bps": 500,
            "day_rows": [
                {
                    "date": waiter_day.isoformat(),
                    "base_amount_minor": 1_000_000,
                    "amount_minor": 50_000,
                    "percent_bps": 500,
                }
            ],
        }

        waiter_item = _component_allocation_for_day(component=component, target_date=waiter_day, context=ctx)
        hookah_item = _component_allocation_for_day(component=component, target_date=hookah_day, context=ctx)

        self.assertEqual(waiter_item["amount_minor"], 50_000)
        self.assertIsNone(hookah_item)

    def test_department_percent_with_explicit_rows_does_not_leak_to_another_profile_date(self):
        waiter_day = date(2026, 3, 5)
        hookah_day = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[waiter_day, hookah_day],
            worked_dates=[waiter_day, hookah_day],
            minutes_by_date={waiter_day: 300, hookah_day: 600},
            shifts_by_date={waiter_day: 1, hookah_day: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={7: {waiter_day: 1_000_000, hookah_day: 2_000_000}},
            kpi_by_date={},
        )
        component = {
            "component_type": "PERCENT_DEPARTMENT_REVENUE",
            "title": "Процент официанта от зала",
            "pay_profile_title": "Официант",
            "amount_minor": 50_000,
            "percent_bps": 500,
            "department_id": 7,
            "department_title": "Зал",
            "day_rows": [
                {
                    "date": waiter_day.isoformat(),
                    "base_amount_minor": 1_000_000,
                    "amount_minor": 50_000,
                    "percent_bps": 500,
                }
            ],
        }

        waiter_item = _component_allocation_for_day(component=component, target_date=waiter_day, context=ctx)
        hookah_item = _component_allocation_for_day(component=component, target_date=hookah_day, context=ctx)

        self.assertEqual(waiter_item["amount_minor"], 50_000)
        self.assertIsNone(hookah_item)

    def test_percent_component_without_day_rows_keeps_legacy_allocation(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[d1, d2],
            worked_dates=[d1, d2],
            minutes_by_date={d1: 300, d2: 600},
            shifts_by_date={d1: 1, d2: 1},
            revenue_by_date_minor={d1: 1_000_000, d2: 3_000_000},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        component = {
            "component_type": "PERCENT_TOTAL_REVENUE",
            "title": "Legacy процент",
            "amount_minor": 40_000,
        }

        d1_item = _component_allocation_for_day(component=component, target_date=d1, context=ctx)
        d2_item = _component_allocation_for_day(component=component, target_date=d2, context=ctx)

        self.assertEqual(d1_item["amount_minor"], 10_000)
        self.assertEqual(d2_item["amount_minor"], 30_000)

    def test_explicit_empty_account_merge_scope_does_not_use_other_line_dates(self):
        target_day = date(2026, 3, 5)
        ctx = DayAllocationContext(
            shift_slot="TOTAL",
            month_dates=[target_day],
            worked_dates=[target_day],
            minutes_by_date={target_day: 300},
            shifts_by_date={target_day: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )

        item = _component_allocation_for_day(
            component={
                "component_type": "SALARY_HOURLY",
                "amount_minor": 90_000,
                "account_merge_worked_dates": [],
            },
            target_date=target_day,
            context=ctx,
        )

        self.assertIsNone(item)

    def test_percentage_kpi_day_breakdown_explains_shift_scope(self):
        d1 = date(2026, 3, 5)
        ctx = DayAllocationContext(
            shift_slot="DAY",
            month_dates=[d1],
            worked_dates=[d1],
            minutes_by_date={d1: 300},
            shifts_by_date={d1: 1},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={9: {d1: 100_000}},
        )
        item = _component_allocation_for_day(
            component={
                "component_type": "KPI_BONUS",
                "title": "% VIP",
                "amount_minor": 500_000,
                "kpi_metric_id": 9,
                "kpi_metric_title": "Выручка VIP",
                "kpi_calculation_mode": "PERCENT",
                "percent_bps": 500,
            },
            target_date=d1,
            context=ctx,
        )
        self.assertEqual(item["amount_minor"], 500_000)
        self.assertIn("5.00%", item["formula_text"])
        self.assertIn("закрытым сменам сотрудника", item["formula_text"])
