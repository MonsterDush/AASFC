from __future__ import annotations

from datetime import date
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from app.services.finance.summary import _sum_daily_payroll_allocated_minor


class FinancePayrollFallbackTests(TestCase):
    @staticmethod
    def _daily_amount(*, target_date: date, breakdown: dict, line_amount_minor: int) -> int:
        db = Mock()
        db.execute.return_value.all.return_value = [(line_amount_minor, json.dumps(breakdown))]
        with patch("app.services.finance.summary._active_finance_shift_slots", return_value=["DAY"]):
            return _sum_daily_payroll_allocated_minor(
                db,
                venue_id=7,
                target_date=target_date,
            )

    def test_merged_components_use_their_side_specific_worked_dates(self):
        breakdown = {
            "metrics": {"worked_dates": ["2026-08-01", "2026-08-02", "2026-08-03"]},
            "components": [
                {
                    "component_type": "PER_SHIFT",
                    "amount_minor": 101,
                    "account_merge_worked_dates": ["2026-08-01"],
                },
                {
                    "component_type": "HOURLY",
                    "amount_minor": 302,
                    "account_merge_worked_dates": ["2026-08-02", "2026-08-03"],
                },
            ],
        }

        amounts = [
            self._daily_amount(target_date=date(2026, 8, day), breakdown=breakdown, line_amount_minor=403)
            for day in range(1, 4)
        ]

        self.assertEqual(amounts, [101, 151, 151])
        self.assertEqual(sum(amounts), 403)

    def test_ordinary_component_keeps_line_level_worked_date_fallback(self):
        breakdown = {
            "metrics": {"worked_dates": ["2026-08-01", "2026-08-02"]},
            "components": [{"component_type": "HOURLY", "amount_minor": 101}],
        }

        first_day = self._daily_amount(
            target_date=date(2026, 8, 1),
            breakdown=breakdown,
            line_amount_minor=101,
        )
        second_day = self._daily_amount(
            target_date=date(2026, 8, 2),
            breakdown=breakdown,
            line_amount_minor=101,
        )

        self.assertEqual((first_day, second_day), (51, 50))

    def test_explicit_empty_or_invalid_component_dates_fail_closed(self):
        for account_merge_worked_dates in ([], [None, "not-a-date"]):
            with self.subTest(account_merge_worked_dates=account_merge_worked_dates):
                breakdown = {
                    "metrics": {"worked_dates": ["2026-08-01", "2026-08-02"]},
                    "components": [
                        {
                            "component_type": "PER_SHIFT",
                            "amount_minor": 100,
                            "account_merge_worked_dates": account_merge_worked_dates,
                        }
                    ],
                }

                amount = self._daily_amount(
                    target_date=date(2026, 8, 2),
                    breakdown=breakdown,
                    line_amount_minor=100,
                )

                self.assertEqual(amount, 0)

    def test_non_list_component_dates_fail_closed(self):
        breakdown = {
            "metrics": {"worked_dates": ["2026-08-01", "2026-08-02"]},
            "components": [
                {
                    "component_type": "PER_SHIFT",
                    "amount_minor": 100,
                    "account_merge_worked_dates": "2026-08-01",
                }
            ],
        }

        amount = self._daily_amount(
            target_date=date(2026, 8, 2),
            breakdown=breakdown,
            line_amount_minor=100,
        )

        self.assertEqual(amount, 0)

    def test_fixed_month_component_ignores_account_merge_worked_dates(self):
        breakdown = {
            "metrics": {"worked_dates": ["2026-08-01"]},
            "components": [
                {
                    "component_type": "SALARY_FIXED_MONTH",
                    "amount_minor": 31_000,
                    "account_merge_worked_dates": [],
                }
            ],
        }

        amount = self._daily_amount(
            target_date=date(2026, 8, 2),
            breakdown=breakdown,
            line_amount_minor=31_000,
        )

        self.assertEqual(amount, 1_000)
