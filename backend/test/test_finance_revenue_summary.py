from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.finance.revenue import build_report_revenue_plan
from app.services.finance.summary import get_day_finance_summary, get_finance_summary, get_monthly_finance_summary


class FinanceRevenueServiceTests(TestCase):
    def test_build_report_revenue_plan_prefers_payments_for_money_axis(self):
        report = SimpleNamespace(id=1, venue_id=5, date=date(2026, 3, 10), revenue_total=1500)
        values = [
            SimpleNamespace(kind="PAYMENT", ref_id=11, value_numeric=700),
            SimpleNamespace(kind="PAYMENT", ref_id=12, value_numeric=800),
            SimpleNamespace(kind="DEPT", ref_id=21, value_numeric=1000),
        ]

        plan = build_report_revenue_plan(report=report, values=values)

        self.assertEqual(len(plan), 2)
        self.assertEqual(sum(item["amount_minor"] for item in plan), 150000)
        self.assertEqual(plan[0]["payment_method_id"], 11)
        self.assertIsNone(plan[0]["department_id"])

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
        }), patch("app.services.finance.summary._group_revenue_breakdown", return_value=[
            {"title": "Наличные", "code": "cash", "subtitle": None, "amount_minor": 300000},
            {"title": "Карта", "code": "card", "subtitle": None, "amount_minor": 200000},
        ]), patch("app.services.finance.summary._group_expense_categories", return_value=[
            {"title": "Аренда", "code": "rent", "subtitle": None, "amount_minor": 120000},
        ]), patch("app.services.finance.summary._group_payment_method_balances", return_value=[]):
            summary = get_monthly_finance_summary(db=object(), venue_id=5, month="2026-03", income_mode="PAYMENTS")

        self.assertEqual(summary["income_mode"], "PAYMENTS")
        self.assertEqual(summary["revenue_breakdown"][0]["amount_minor"], 300000)
        self.assertEqual(summary["expense_categories"][0]["title"], "Аренда")

    def test_get_day_finance_summary_includes_point_and_recurring(self):
        with patch("app.services.finance.summary._sum_closed_report_revenue_minor", return_value=100000), \
             patch("app.services.finance.summary._group_daily_point_expenses", return_value=[{"title": "Закупка", "code": "supply", "subtitle": "Разовые расходы дня", "amount_minor": 15000}]), \
             patch("app.services.finance.summary.get_daily_recurring_expense_summary", return_value={"rows": [{"title": "Эквайринг", "code": "fee", "subtitle": "Комиссия", "amount_minor": 2500}], "total_minor": 2500}), \
             patch("app.services.finance.summary._sum_amount", return_value=0), \
             patch("app.services.finance.summary._group_revenue_breakdown", return_value=[]), \
             patch("app.services.finance.summary._group_payment_method_balances", return_value=[]):
            summary = get_day_finance_summary(db=object(), venue_id=5, target_date=date(2026, 3, 12), income_mode="PAYMENTS")

        self.assertEqual(summary["expense_minor"], 17500)
        self.assertEqual(summary["point_expense_minor"], 15000)
        self.assertEqual(summary["recurring_expense_minor"], 2500)
        self.assertEqual(summary["profit_minor"], 82500)
