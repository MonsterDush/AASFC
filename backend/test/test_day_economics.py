from __future__ import annotations

from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

from app.services.finance.day_economics import get_day_economics


class DayEconomicsServiceTests(TestCase):
    def test_get_day_economics_builds_metrics_and_sections(self):
        with patch("app.services.finance.day_economics.get_day_finance_summary", return_value={
            "date": date(2026, 3, 13),
            "period_start": date(2026, 3, 13),
            "period_end": date(2026, 3, 13),
            "month": "2026-03",
            "revenue_minor": 100000,
            "expense_minor": 25000,
            "payroll_minor": 10000,
            "adjustments_minor": 0,
            "refunds_minor": 0,
            "profit_minor": 75000,
            "margin_bps": 7500,
            "income_mode": "PAYMENTS",
            "revenue_breakdown": [],
            "point_expenses": [],
            "point_expense_minor": 15000,
            "recurring_expenses": [],
            "recurring_expense_minor": 10000,
            "payment_method_balances": [],
            "draft_expense_count": 1,
            "draft_expense_total_minor": 5000,
        }), patch("app.services.finance.day_economics._get_report_state", return_value={
            "exists": True,
            "report_id": 7,
            "status": "CLOSED",
            "closed_at": datetime(2026, 3, 13, 23, 30),
            "closed_by_user_id": 3,
            "comment": None,
            "revenue_total_minor": 100000,
            "tips_total_minor": 12000,
        }), patch("app.services.finance.day_economics._get_team_snapshot", return_value={
            "assignment_count": 5,
            "assigned_user_count": 4,
            "assigned_shift_count": 2,
        }), patch("app.services.finance.day_economics._group_revenue_breakdown", side_effect=[[{"title": "Наличные", "code": "cash", "subtitle": None, "amount_minor": 60000}], [{"title": "Бар", "code": "bar", "subtitle": None, "amount_minor": 70000}]]), patch("app.services.finance.day_economics._get_kpi_breakdown", return_value=[{"metric_id": 1, "title": "Апселл", "code": "upsell", "unit": "QTY", "value_numeric": 7}]):
            result = get_day_economics(db=object(), venue_id=5, target_date=date(2026, 3, 13))

        self.assertEqual(result["metrics"]["result_status"], "PROFIT")
        self.assertEqual(result["metrics"]["revenue_per_assigned_minor"], 25000)
        self.assertEqual(result["metrics"]["tips_per_assigned_minor"], 3000)
        self.assertEqual(result["metrics"]["expense_ratio_bps"], 2500)
        self.assertEqual(result["payment_revenue_breakdown"][0]["title"], "Наличные")
        self.assertEqual(result["department_revenue_breakdown"][0]["title"], "Бар")
        self.assertEqual(result["kpi_breakdown"][0]["code"], "upsell")

    def test_get_day_economics_without_team_keeps_per_employee_metrics_empty(self):
        with patch("app.services.finance.day_economics.get_day_finance_summary", return_value={
            "date": date(2026, 3, 13),
            "period_start": date(2026, 3, 13),
            "period_end": date(2026, 3, 13),
            "month": "2026-03",
            "revenue_minor": 0,
            "expense_minor": 0,
            "payroll_minor": 0,
            "adjustments_minor": 0,
            "refunds_minor": 0,
            "profit_minor": 0,
            "margin_bps": None,
            "income_mode": "PAYMENTS",
            "revenue_breakdown": [],
            "point_expenses": [],
            "point_expense_minor": 0,
            "recurring_expenses": [],
            "recurring_expense_minor": 0,
            "payment_method_balances": [],
            "draft_expense_count": 0,
            "draft_expense_total_minor": 0,
        }), patch("app.services.finance.day_economics._get_report_state", return_value={
            "exists": False,
            "report_id": None,
            "status": "MISSING",
            "closed_at": None,
            "closed_by_user_id": None,
            "comment": None,
            "revenue_total_minor": 0,
            "tips_total_minor": 0,
        }), patch("app.services.finance.day_economics._get_team_snapshot", return_value={
            "assignment_count": 0,
            "assigned_user_count": 0,
            "assigned_shift_count": 0,
        }), patch("app.services.finance.day_economics._group_revenue_breakdown", side_effect=[[], []]), patch("app.services.finance.day_economics._get_kpi_breakdown", return_value=[]):
            result = get_day_economics(db=object(), venue_id=5, target_date=date(2026, 3, 13))

        self.assertEqual(result["metrics"]["result_status"], "BREAKEVEN")
        self.assertIsNone(result["metrics"]["revenue_per_assigned_minor"])
        self.assertIsNone(result["metrics"]["tips_per_assigned_minor"])
