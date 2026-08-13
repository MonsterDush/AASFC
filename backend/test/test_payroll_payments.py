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
from app.services.payroll import notifications as payroll_notifications


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


class PayrollNotificationTests(TestCase):
    def setUp(self):
        self.window = build_payment_windows(
            schedule_month=date(2026, 7, 1),
            cadence="WEEKLY",
            weekly_payment_weekday=0,
        )[0]

    def test_notification_texts_show_period_amount_and_adjustments(self):
        manager_text = payroll_notifications.build_payroll_draft_ready_text(
            venue_name="Тестовый бар",
            window=self.window,
            amount_minor=245_000,
        )
        employee_text = payroll_notifications.build_employee_payroll_period_text(
            venue_name="Тестовый бар",
            window=self.window,
            summary={
                "items": [{"days_count": 4}],
                "totals": {"net_minor": 220_000, "bonuses_minor": 30_000, "penalties_minor": 10_000},
            },
        )

        self.assertIn("ФОТ рассчитан", manager_text)
        self.assertIn("2 450 ₽", manager_text)
        self.assertIn("Начислено: 2 200 ₽", employee_text)
        self.assertIn("Смен: 4", employee_text)
        self.assertIn("Премии: +300 ₽", employee_text)
        self.assertIn("Штрафы и списания: −100 ₽", employee_text)

    def test_weekly_window_notifies_managers_and_all_active_employees(self):
        manager = SimpleNamespace(id=1, tg_user_id=101)
        employees = [
            SimpleNamespace(id=2, tg_user_id=102, notify_salary=True),
            SimpleNamespace(id=3, tg_user_id=103, notify_salary=True),
        ]
        settings_row = SimpleNamespace(venue_id=7, cadence="WEEKLY")

        with (
            patch.object(payroll_notifications, "_venue_name", return_value="Тестовый бар"),
            patch.object(payroll_notifications, "list_expense_notification_recipients", return_value=[manager]),
            patch.object(
                payroll_notifications, "_active_venue_users", return_value=[(item, "STAFF") for item in employees]
            ),
            patch.object(
                payroll_notifications,
                "build_member_period_summary",
                return_value={"items": [], "totals": {"net_minor": 0}},
            ),
            patch.object(payroll_notifications, "_send_once", return_value=True) as send_once,
        ):
            result = payroll_notifications.send_payroll_window_notifications(
                SimpleNamespace(),
                settings_row=settings_row,
                window=self.window,
                amount_minor=245_000,
            )

        self.assertEqual(result, {"managers_sent": 1, "employees_sent": 2})
        self.assertEqual(send_once.call_count, 3)
        self.assertEqual(
            [call.kwargs["notification_type"] for call in send_once.call_args_list],
            ["payroll_draft_ready", "payroll_period_summary", "payroll_period_summary"],
        )

    def test_daily_window_does_not_send_employee_period_summary(self):
        settings_row = SimpleNamespace(venue_id=7, cadence="DAILY")
        with (
            patch.object(payroll_notifications, "_venue_name", return_value="Тестовый бар"),
            patch.object(payroll_notifications, "list_expense_notification_recipients", return_value=[]),
            patch.object(payroll_notifications, "_active_venue_users") as active_users,
            patch.object(payroll_notifications, "_send_once") as send_once,
        ):
            result = payroll_notifications.send_payroll_window_notifications(
                SimpleNamespace(),
                settings_row=settings_row,
                window=self.window,
                amount_minor=245_000,
            )

        self.assertEqual(result, {"managers_sent": 0, "employees_sent": 0})
        active_users.assert_not_called()
        send_once.assert_not_called()

    def test_due_draft_expense_reminder_is_grouped_per_venue(self):
        db = SimpleNamespace(execute=lambda _statement: SimpleNamespace(all=lambda: [(7, 3, 450_000)]))
        recipient = SimpleNamespace(id=1, tg_user_id=101)
        with (
            patch.object(payroll_notifications, "_venue_name", return_value="Тестовый бар"),
            patch.object(payroll_notifications, "list_expense_notification_recipients", return_value=[recipient]),
            patch.object(payroll_notifications, "_send_once", return_value=True) as send_once,
        ):
            sent = payroll_notifications.send_due_draft_expense_reminders_once(db, today=date(2026, 7, 20))

        self.assertEqual(sent, 1)
        self.assertEqual(send_once.call_args.kwargs["notification_type"], "draft_expense_reminder")
        self.assertIn("Расходов: 3", send_once.call_args.kwargs["text"])
        self.assertIn("4 500 ₽", send_once.call_args.kwargs["text"])
