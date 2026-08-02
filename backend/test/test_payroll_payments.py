from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.finance import expenses as expense_service
from app.services.payroll.adjustments import (
    group_payroll_adjustment_net_by_date,
    load_member_payroll_adjustments,
    payroll_adjustment_signed_minor,
)
from app.services.payroll.payments import build_payment_windows, normalize_monthly_rules


class PayrollPaymentWindowTests(TestCase):
    def test_default_twice_monthly_windows_cover_explicit_periods(self):
        windows = build_payment_windows(
            schedule_month=date(2026, 7, 1),
            cadence="MONTHLY",
            monthly_rules=[
                {"payment_day": 5, "period_start_day": 16, "period_end_day": 31, "period_month_offset": -1},
                {"payment_day": 20, "period_start_day": 1, "period_end_day": 15, "period_month_offset": 0},
            ],
        )

        self.assertEqual(
            [(row.payment_date, row.period_start, row.period_end) for row in windows],
            [
                (date(2026, 7, 5), date(2026, 6, 16), date(2026, 6, 30)),
                (date(2026, 7, 20), date(2026, 7, 1), date(2026, 7, 15)),
            ],
        )

    def test_monthly_day_31_is_clamped_to_calendar_month(self):
        windows = build_payment_windows(
            schedule_month=date(2027, 2, 1),
            cadence="MONTHLY",
            monthly_rules=[
                {"payment_day": 31, "period_start_day": 1, "period_end_day": 31, "period_month_offset": 0},
            ],
        )
        self.assertEqual(windows[0].payment_date, date(2027, 2, 28))
        self.assertEqual(windows[0].period_end, date(2027, 2, 28))

    def test_daily_window_uses_previous_calendar_day(self):
        windows = build_payment_windows(schedule_month=date(2026, 1, 1), cadence="DAILY")
        self.assertEqual(windows[0].payment_date, date(2026, 1, 1))
        self.assertEqual(windows[0].period_start, date(2025, 12, 31))
        self.assertEqual(windows[0].period_end, date(2025, 12, 31))

    def test_weekly_window_uses_previous_seven_days(self):
        windows = build_payment_windows(
            schedule_month=date(2026, 7, 1),
            cadence="WEEKLY",
            weekly_payment_weekday=0,
        )
        self.assertEqual(windows[0].payment_date.weekday(), 0)
        self.assertEqual((windows[0].period_end - windows[0].period_start).days, 6)
        self.assertEqual(windows[0].period_end, windows[0].payment_date - timedelta(days=1))

    def test_duplicate_monthly_payment_days_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "не должны повторяться"):
            normalize_monthly_rules(
                [
                    {"payment_day": 5, "period_start_day": 1, "period_end_day": 10, "period_month_offset": 0},
                    {"payment_day": 5, "period_start_day": 11, "period_end_day": 20, "period_month_offset": 0},
                ]
            )

    def test_overlapping_monthly_periods_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "не должны пересекаться"):
            build_payment_windows(
                schedule_month=date(2026, 7, 1),
                cadence="MONTHLY",
                monthly_rules=[
                    {"payment_day": 10, "period_start_day": 1, "period_end_day": 15, "period_month_offset": 0},
                    {"payment_day": 20, "period_start_day": 15, "period_end_day": 31, "period_month_offset": 0},
                ],
            )


class PayrollAdjustmentTests(TestCase):
    class _Db:
        def execute(self, _statement):
            return SimpleNamespace(
                all=lambda: [
                    (1, 7, "bonus", 1500, date(2026, 7, 5), "Премия месяца"),
                    (2, 7, "penalty", 400, date(2026, 7, 5), "Опоздание"),
                    (3, 7, "writeoff", 100, date(2026, 7, 6), "Инвентарь"),
                    (4, None, "writeoff", 900, date(2026, 7, 6), "Расход заведения"),
                ]
            )

    def test_bonus_is_added_and_employee_deductions_are_subtracted(self):
        self.assertEqual(payroll_adjustment_signed_minor("bonus", 1500), 150_000)
        self.assertEqual(payroll_adjustment_signed_minor("penalty", 400), -40_000)
        self.assertEqual(payroll_adjustment_signed_minor("writeoff", 100), -10_000)

    def test_only_member_adjustments_are_included_in_payroll(self):
        grouped = load_member_payroll_adjustments(
            self._Db(),
            venue_id=3,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )
        self.assertEqual(set(grouped), {7})
        self.assertEqual(sum(item["amount_minor"] for item in grouped[7]), 100_000)

        by_date = group_payroll_adjustment_net_by_date(
            self._Db(),
            venue_id=3,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )
        self.assertEqual(by_date[date(2026, 7, 5)], 110_000)
        self.assertEqual(by_date[date(2026, 7, 6)], -10_000)

class PayrollExpenseLedgerTests(TestCase):
    def test_confirmed_payroll_expense_creates_payroll_ledger_only(self):
        expense = SimpleNamespace(
            id=41,
            venue_id=3,
            amount_minor=250_000,
            expense_date=date(2026, 7, 20),
            payment_method_id=7,
            payroll_run_id=11,
            payroll_period_start=date(2026, 7, 1),
            payroll_period_end=date(2026, 7, 15),
            payroll_payout_key="payroll:3:test",
            expense_kind="PAYROLL",
            status="CONFIRMED",
        )
        db = SimpleNamespace(execute=lambda _statement: SimpleNamespace(rowcount=0))

        with (
            patch.object(expense_service, "delete_finance_entries_for_source", return_value=0),
            patch.object(expense_service, "delete_expense_recognition_entries_for_expense", return_value=0),
            patch.object(expense_service, "create_finance_entry") as create_entry,
            patch.object(expense_service, "rebuild_expense_recognition_entries_for_expense") as rebuild_recognition,
        ):
            allocations = expense_service.rebuild_expense_allocations_for_expense(db=db, expense=expense)

        self.assertEqual(allocations, [])
        create_entry.assert_called_once()
        self.assertEqual(create_entry.call_args.kwargs["kind"], "PAYROLL")
        self.assertEqual(create_entry.call_args.kwargs["source_type"], "payroll_expense")
        self.assertEqual(create_entry.call_args.kwargs["payment_method_id"], 7)
        rebuild_recognition.assert_not_called()
