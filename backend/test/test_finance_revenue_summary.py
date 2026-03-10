from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.finance.revenue import build_report_revenue_plan
from app.services.finance.summary import get_finance_summary


class FinanceRevenueServiceTests(TestCase):
    def test_build_report_revenue_plan_prefers_departments_over_payments(self):
        report = SimpleNamespace(id=1, venue_id=5, date=date(2026, 3, 10), revenue_total=1500)
        values = [
            SimpleNamespace(kind="PAYMENT", ref_id=11, value_numeric=700),
            SimpleNamespace(kind="DEPT", ref_id=21, value_numeric=1000),
            SimpleNamespace(kind="DEPT", ref_id=22, value_numeric=500),
        ]

        plan = build_report_revenue_plan(report=report, values=values)

        self.assertEqual(len(plan), 2)
        self.assertEqual(sum(item["amount_minor"] for item in plan), 150000)
        self.assertEqual(plan[0]["department_id"], 21)
        self.assertIsNone(plan[0]["payment_method_id"])

    def test_get_finance_summary_calculates_profit_and_margin(self):
        amounts = {
            ("INCOME", "REVENUE"): 500000,
            ("EXPENSE", "EXPENSE"): 120000,
            ("EXPENSE", "PAYROLL"): 80000,
            ("EXPENSE", "ADJUSTMENT"): 10000,
            ("INCOME", "ADJUSTMENT"): 0,
            ("INCOME", "REFUND"): 0,
            ("EXPENSE", "REFUND"): 0,
        }

        def fake_sum(db, *, venue_id, period_start, period_end, direction, kind):
            return amounts[(direction, kind)]

        with patch("app.services.finance.summary._sum_amount", side_effect=fake_sum):
            summary = get_finance_summary(db=object(), venue_id=5, month="2026-03")

        self.assertEqual(summary["revenue_minor"], 500000)
        self.assertEqual(summary["expense_minor"], 120000)
        self.assertEqual(summary["payroll_minor"], 80000)
        self.assertEqual(summary["adjustments_minor"], -10000)
        self.assertEqual(summary["profit_minor"], 290000)
        self.assertEqual(summary["margin_bps"], 5800)
