from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.payroll import period_summary


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _RowsSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _statement):
        return _RowsResult(self._rows)


class PayrollPeriodSummaryTests(TestCase):
    def test_payroll_calendar_dates_cover_requested_part_of_stored_month(self):
        db = _RowsSession([SimpleNamespace(venue_id=5, period_month=date(2026, 3, 1))])

        result = period_summary._collect_member_payroll_calendar_dates(
            db,
            member_user_id=17,
            period_start=date(2026, 3, 10),
            period_end=date(2026, 3, 12),
        )

        self.assertEqual(result, {5: {date(2026, 3, 10), date(2026, 3, 11), date(2026, 3, 12)}})

    def test_month_summary_keeps_full_fixed_salary_and_activity_day_count(self):
        month_start = date(2026, 3, 1)
        month_end = date(2026, 3, 31)
        payroll_dates = {month_start + timedelta(days=offset) for offset in range(31)}
        db = _RowsSession([SimpleNamespace(id=5, name="Test")])

        def build_day(_db, *, target_date, **_kwargs):
            return {
                "state": "ready",
                "summary": {
                    "earnings_minor": 1_000,
                    "tips_minor": 0,
                    "bonuses_minor": 0,
                    "penalties_minor": 0,
                    "total_minor": 1_000,
                },
                "context": {"has_payroll_line": True},
                "date": target_date.isoformat(),
            }

        with (
            patch.object(
                period_summary,
                "_collect_member_candidate_dates",
                return_value={5: {date(2026, 3, 10)}},
            ),
            patch.object(
                period_summary,
                "_collect_member_payroll_calendar_dates",
                return_value={5: payroll_dates},
            ),
            patch.object(period_summary, "_latest_recalculation_by_venue", return_value={5: None}),
            patch.object(period_summary, "build_member_day_breakdown", side_effect=build_day),
        ):
            result = period_summary.build_member_period_summary(
                db,
                member_user_id=17,
                period_start=month_start,
                period_end=month_end,
            )

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["earned_minor"], 31_000)
        self.assertEqual(result["items"][0]["net_minor"], 31_000)
        self.assertEqual(result["items"][0]["days_count"], 1)
        self.assertEqual(result["items"][0]["source"], "payroll")
