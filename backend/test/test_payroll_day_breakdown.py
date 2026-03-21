from __future__ import annotations

from datetime import date
from unittest import TestCase

from app.services.payroll.day_breakdown import DayAllocationContext, _allocate_minor_by_keys, _component_allocation_for_day


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

    def test_component_allocation_for_fixed_month_uses_worked_dates(self):
        d1 = date(2026, 3, 5)
        d2 = date(2026, 3, 7)
        ctx = DayAllocationContext(
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
        self.assertIn("рабочих дней", item["formula_text"])
