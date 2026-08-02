from __future__ import annotations

import unittest
from datetime import date

from app.services.demo.bootstrap import (
    _daily_base_minor,
    _history_periods,
    _seasonal_factor,
)


class DemoBootstrapPeriodTests(unittest.TestCase):
    def test_builds_rolling_year_ending_at_reference_month(self):
        periods = _history_periods(2026, 3, 12)

        self.assertEqual(periods[0], (2025, 4))
        self.assertEqual(periods[-1], (2026, 3))
        self.assertEqual(len(periods), 12)

    def test_rejects_history_longer_than_supported_window(self):
        with self.assertRaisesRegex(ValueError, "history_months"):
            _history_periods(2026, 3, 25)


class DemoBootstrapSeasonalityTests(unittest.TestCase):
    def test_winter_is_stronger_than_summer(self):
        winter = [_seasonal_factor(month) for month in (12, 1, 2)]
        summer = [_seasonal_factor(month) for month in (6, 7, 8)]

        self.assertGreater(min(winter), max(summer))

    def test_decline_becomes_pronounced_in_may(self):
        self.assertGreater(_seasonal_factor(4), _seasonal_factor(5))
        self.assertGreater(_seasonal_factor(5), _seasonal_factor(6))
        self.assertGreater(_seasonal_factor(6), _seasonal_factor(7))

    def test_existing_march_peak_value_remains_the_anchor(self):
        self.assertEqual(_daily_base_minor(date(2026, 3, 8)), 11_800_000)


if __name__ == "__main__":
    unittest.main()
