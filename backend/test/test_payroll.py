from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest import TestCase

from app.services.payroll.calculator import (
    calculate_component_amount_minor,
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
