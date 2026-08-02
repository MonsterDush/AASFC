from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.routers import venue_payroll_support
from app.services.finance import summary as finance_summary


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = list(rows or [])

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, results):
        self.results = list(results)

    def execute(self, _statement):
        return self.results.pop(0)


class PayrollAdjustmentIntegrationTests(TestCase):
    def test_month_payload_adds_bonus_and_deductions_to_employee_total(self):
        run = SimpleNamespace(
            id=10,
            venue_id=3,
            period_month=date(2026, 7, 1),
            calculated_by_user_id=9,
            calculated_at=None,
            total_amount_minor=200_000,
            lines_count=1,
        )
        line = SimpleNamespace(
            id=20,
            member_user_id=7,
            amount_minor=200_000,
            pay_profile_id=5,
            breakdown_json=json.dumps({"metrics": {"shifts_count": 10}, "components": []}),
        )
        member = SimpleNamespace(
            id=7,
            tg_user_id=None,
            tg_username="petya",
            full_name="Пётр",
            short_name="Петя",
        )
        profile = SimpleNamespace(title="Основной")
        db = _Session([_Result(scalar=run), _Result(rows=[(line, member, profile)])])
        adjustments = {
            7: [
                {"component_type": "BONUS", "amount_minor": 50_000},
                {"component_type": "PENALTY", "amount_minor": -20_000},
                {"component_type": "WRITEOFF", "amount_minor": -10_000},
            ]
        }

        with (
            patch.object(venue_payroll_support, "_latest_payroll_recalculation_log", return_value=None),
            patch.object(venue_payroll_support, "load_member_payroll_adjustments", return_value=adjustments),
        ):
            payload = venue_payroll_support._load_payroll_payload(db, venue_id=3, month="2026-07")

        self.assertEqual(payload["total_amount_minor"], 220_000)
        self.assertEqual(payload["run"]["base_total_amount_minor"], 200_000)
        self.assertEqual(payload["lines"][0]["amount_minor"], 220_000)
        self.assertEqual(len(payload["lines"][0]["breakdown"]["components"]), 3)

    def test_finance_daily_payroll_includes_adjustments_only_for_total_slot(self):
        adjustment_rows = {date(2026, 7, 5): 25_000}
        with (
            patch.object(finance_summary, "_sum_daily_payroll_allocated_minor", return_value=100_000),
            patch(
                "app.services.payroll.adjustments.group_payroll_adjustment_net_by_date",
                return_value=adjustment_rows,
            ) as adjustment_loader,
        ):
            total = finance_summary._group_daily_payroll_allocated_minor(
                SimpleNamespace(),
                venue_id=3,
                period_start=date(2026, 7, 5),
                period_end=date(2026, 7, 5),
            )
            slot = finance_summary._group_daily_payroll_allocated_minor(
                SimpleNamespace(),
                venue_id=3,
                period_start=date(2026, 7, 5),
                period_end=date(2026, 7, 5),
                shift_slot="DAY",
            )

        self.assertEqual(total[date(2026, 7, 5)], 125_000)
        self.assertEqual(slot[date(2026, 7, 5)], 100_000)
        adjustment_loader.assert_called_once()
