from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.finance.revenue import build_report_revenue_plan
from app.services.finance.summary import get_finance_summary, get_monthly_finance_summary


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSummaryDb:
    def execute(self, statement):
        return _RowsResult([
            (7, "rent", "Аренда", 120000),
            (8, "tax", "Налоги", 50000),
        ])


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

    def test_get_monthly_finance_summary_adds_breakdowns(self):
        fake_db = _FakeSummaryDb()
        with patch("app.services.finance.summary.get_finance_summary", return_value={
            "month": "2026-03",
            "period_start": date(2026, 3, 1),
            "period_end": date(2026, 3, 31),
            "revenue_minor": 500000,
            "expense_minor": 170000,
            "payroll_minor": 0,
            "adjustments_minor": 0,
            "refunds_minor": 0,
            "profit_minor": 330000,
            "margin_bps": 6600,
        }), patch("app.services.finance.summary.compute_revenue_summary", return_value={
            "rows": [
                {"ref_id": 1, "code": "cash", "title": "Наличные", "amount": 3000},
                {"ref_id": 2, "code": "card", "title": "Карта", "amount": 2000},
            ]
        }):
            summary = get_monthly_finance_summary(db=fake_db, venue_id=5, month="2026-03", income_mode="PAYMENTS")

        self.assertEqual(summary["income_mode"], "PAYMENTS")
        self.assertEqual(summary["revenue_breakdown"][0]["amount_minor"], 300000)
        self.assertEqual(summary["expense_categories"][0]["title"], "Аренда")
