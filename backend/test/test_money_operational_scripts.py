from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.billing import alerts as billing_alerts
from app.services.billing import notifications as billing_notifications
from app.scripts import (
    cleanup_notification_delivery_logs,
    generate_payroll_payment_drafts,
    operational_snapshot,
    process_billing_jobs,
    process_notification_jobs,
)


def _session_context(db: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__enter__.return_value = db
    context.__exit__.return_value = False
    return context


class MoneyOperationalScriptTests(unittest.TestCase):
    def test_billing_delivery_filters_deduplicates_localizes_and_records_results(self):
        disabled = SimpleNamespace(id=1, tg_user_id=101, notify_enabled=False, preferred_locale="ru")
        no_chat = SimpleNamespace(id=2, tg_user_id=None, notify_enabled=True, preferred_locale="ru")
        english = SimpleNamespace(id=3, tg_user_id=303, notify_enabled=True, preferred_locale="en")
        duplicate = SimpleNamespace(id=4, tg_user_id=303, notify_enabled=True, preferred_locale="ru")
        failed = SimpleNamespace(id=5, tg_user_id=505, notify_enabled=True, preferred_locale="ru")
        already_sent = SimpleNamespace(id=6, tg_user_id=606, notify_enabled=True, preferred_locale="ru")
        recipients = [disabled, no_chat, english, duplicate, failed, already_sent]

        db = MagicMock()
        success_entry = SimpleNamespace(status="pending", sent_at=None, error_text=None)
        failed_entry = SimpleNamespace(status="pending", sent_at=None, error_text=None)
        with (
            patch.object(billing_notifications, "_delivery_exists", side_effect=[False, False, True]),
            patch.object(
                billing_notifications,
                "log_notification_attempt",
                side_effect=[success_entry, failed_entry],
            ),
            patch.object(
                billing_notifications.tg_notify,
                "notify_result",
                side_effect=[
                    {"ok": True, "retryable": False},
                    {"ok": False, "retryable": False, "error": "blocked"},
                ],
            ) as notify,
            patch.object(billing_notifications, "disable_unreachable_telegram_recipient") as disable,
        ):
            sent = billing_notifications.send_owner_billing_notification_once(
                db,
                venue_id=7,
                notification_type="renewal",
                event_key="event-1",
                text="Русский текст",
                text_en="English text",
                users=recipients,
            )

        self.assertEqual(sent, 1)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(notify.call_args_list[0].kwargs["text"], "English text")
        self.assertEqual(notify.call_args_list[0].kwargs["button_text"], "Open Axelio")
        self.assertEqual(notify.call_args_list[1].kwargs["text"], "Русский текст")
        self.assertEqual(success_entry.status, "sent")
        self.assertIsNotNone(success_entry.sent_at)
        self.assertEqual(failed_entry.status, "failed")
        self.assertEqual(failed_entry.error_text, "blocked")
        self.assertEqual(disable.call_count, 2)
        self.assertEqual(db.commit.call_count, 4)
        self.assertEqual(
            billing_notifications.send_owner_billing_notification_once(
                db,
                venue_id=7,
                notification_type="renewal",
                event_key="empty",
                text="none",
                users=[],
            ),
            0,
        )

        admin_success = SimpleNamespace(status="pending", sent_at=None, error_text=None)
        with (
            patch.object(billing_alerts, "_delivery_exists", return_value=False),
            patch.object(billing_alerts, "log_notification_attempt", return_value=admin_success),
            patch.object(
                billing_alerts.tg_notify,
                "notify_result",
                return_value={"ok": True, "retryable": False},
            ) as admin_notify,
            patch.object(billing_alerts, "disable_unreachable_telegram_recipient"),
        ):
            sent = billing_alerts.send_super_admin_billing_alert_once(
                db,
                notification_type="failed_threshold",
                event_key="2026-09-24",
                text="Проблема оплаты",
                text_en="Payment problem",
                venue_id=7,
                users=[disabled, no_chat, english, duplicate],
            )

        self.assertEqual(sent, 1)
        self.assertEqual(admin_notify.call_count, 1)
        self.assertEqual(admin_notify.call_args.kwargs["text"], "Payment problem")
        self.assertEqual(admin_notify.call_args.kwargs["button_text"], "Open billing")
        self.assertEqual(admin_success.status, "sent")
        self.assertTrue(billing_alerts.admin_billing_open_url().endswith("/admin-billing.html"))
        self.assertTrue(billing_alerts.admin_billing_open_url(venue_id=7).endswith("?venue_id=7"))

    def test_billing_jobs_cover_refunds_transitions_reminders_and_health(self):
        now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
        db = MagicMock()

        venue_lookup = MagicMock()
        venue_lookup.scalar_one_or_none.return_value = "Axelio QA"

        active = SimpleNamespace(venue_id=1)
        grace = SimpleNamespace(venue_id=2)
        suspended = SimpleNamespace(venue_id=3)
        billing_rows = MagicMock()
        billing_rows.all.return_value = [
            (active, "Active venue"),
            (grace, "Grace venue"),
            (suspended, "Suspended venue"),
        ]

        failed_payments = MagicMock()
        failed_payments.all.return_value = [(1,), (2,), (3,), (4,), (5,)]
        db.execute.side_effect = [venue_lookup, billing_rows, failed_payments]

        stale_event = SimpleNamespace(id=21, venue_id=1)
        missing_request = SimpleNamespace(id=30, venue_id=1, provider_payment_id="")
        failed_refund = SimpleNamespace(id=31, venue_id=2, provider_payment_id="refund-error")
        completed_refund = SimpleNamespace(
            id=32,
            venue_id=1,
            provider_payment_id="refund-ok",
            amount_minor=12_345,
            status="PROCESSING",
        )
        refund_event = SimpleNamespace(id=41)
        completed_refund_result = SimpleNamespace(**completed_refund.__dict__)
        completed_refund_result.status = "SUCCEEDED"

        grace_event = SimpleNamespace(id=51)
        suspended_event = SimpleNamespace(id=52)
        active_snapshot = SimpleNamespace(
            status="ACTIVE",
            paid_until=now + timedelta(days=7),
            grace_until=now + timedelta(days=14),
        )
        grace_snapshot = SimpleNamespace(
            status="GRACE",
            paid_until=now - timedelta(days=1),
            grace_until=now,
        )
        suspended_snapshot = SimpleNamespace(
            status="SUSPENDED",
            paid_until=now - timedelta(days=10),
            grace_until=now - timedelta(days=1),
        )

        with (
            patch.object(process_billing_jobs, "_utc_now", return_value=now),
            patch.object(process_billing_jobs, "SessionLocal", return_value=_session_context(db)),
            patch.object(process_billing_jobs, "expire_stale_pending_checkouts", return_value=(1, [stale_event])),
            patch.object(
                process_billing_jobs,
                "list_pending_external_refund_transactions",
                return_value=[missing_request, failed_refund, completed_refund],
            ),
            patch.object(
                process_billing_jobs,
                "get_refund_request_state",
                side_effect=[RuntimeError("provider unavailable"), {"label": "succeeded"}],
            ),
            patch.object(
                process_billing_jobs,
                "sync_external_refund_transaction_state",
                return_value=(completed_refund_result, refund_event),
            ) as sync_refund,
            patch.object(
                process_billing_jobs,
                "sync_billing_state",
                side_effect=[
                    (active, None, None),
                    (grace, None, grace_event),
                    (suspended, None, suspended_event),
                ],
            ),
            patch.object(
                process_billing_jobs,
                "get_billing_snapshot_for_state",
                side_effect=[active_snapshot, grace_snapshot, suspended_snapshot],
            ),
            patch.object(process_billing_jobs, "send_owner_billing_notification_once", return_value=1) as owner_notify,
            patch.object(process_billing_jobs, "send_super_admin_billing_alert_once", return_value=1) as admin_notify,
            patch.object(process_billing_jobs, "sync_billing_reconciliation_issues") as sync_reconciliation,
            patch.object(process_billing_jobs, "get_billing_health_summary") as health,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                result = process_billing_jobs.main()

        self.assertEqual(result, 0)
        self.assertIn("changed_states=2", output.getvalue())
        self.assertIn("sent_notifications=5", output.getvalue())
        self.assertIn("expired_checkouts=1", output.getvalue())
        self.assertIn("sent_admin_alerts=3", output.getvalue())
        self.assertEqual(sync_refund.call_count, 1)
        self.assertEqual(owner_notify.call_count, 5)
        self.assertEqual(admin_notify.call_count, 3)
        sync_reconciliation.assert_called_once_with(db)
        health.assert_called_once_with(db)
        self.assertGreaterEqual(db.commit.call_count, 8)

        self.assertEqual(process_billing_jobs._fmt_date(None), "—")
        self.assertEqual(process_billing_jobs._fmt_date(now), "24.09.2026")
        self.assertIsNone(process_billing_jobs._days_until(None, now))
        self.assertEqual(process_billing_jobs._days_until(now + timedelta(days=3), now), 3)

    def test_payroll_draft_generator_processes_due_windows_and_isolates_failures(self):
        db = MagicMock()
        skipped = SimpleNamespace(venue_id=1)
        due = SimpleNamespace(venue_id=2)
        broken = SimpleNamespace(venue_id=3)
        query = MagicMock()
        query.scalars.return_value.all.return_value = [skipped, due, broken]
        db.execute.return_value = query

        target = date(2026, 9, 25)
        non_due_window = SimpleNamespace(payment_date=date(2026, 9, 26))
        due_window = SimpleNamespace(payment_date=target)
        generated = {
            "created": 2,
            "updated": 1,
            "items": [
                {"payment_date": target, "expense_id": 501, "status": "DRAFT", "amount_minor": 345_600},
                {"payment_date": target, "expense_id": None, "status": "DRAFT", "amount_minor": 1},
                {"payment_date": target, "expense_id": 502, "status": "CONFIRMED", "amount_minor": 1},
            ],
        }

        with (
            patch.object(generate_payroll_payment_drafts, "SessionLocal", return_value=_session_context(db)),
            patch.object(
                generate_payroll_payment_drafts,
                "payment_windows_for_settings",
                side_effect=[[non_due_window], [due_window], RuntimeError("bad venue")],
            ),
            patch.object(
                generate_payroll_payment_drafts,
                "generate_payroll_draft_expenses",
                return_value=generated,
            ) as generate,
            patch.object(
                generate_payroll_payment_drafts,
                "send_payroll_window_notifications",
                return_value={"managers_sent": 2, "employees_sent": 2},
            ) as notify,
        ):
            result = generate_payroll_payment_drafts.main(today=date(2026, 9, 24))

        self.assertEqual(result, 7)
        generate.assert_called_once_with(
            db,
            settings=due,
            schedule_month=date(2026, 9, 1),
            only_payment_date=target,
        )
        notify.assert_called_once_with(
            db,
            settings_row=due,
            window=due_window,
            amount_minor=345_600,
        )
        db.rollback.assert_called_once()

    def test_notification_runner_sums_successes_and_survives_each_optional_failure(self):
        db = MagicMock()
        with (
            patch.object(process_notification_jobs, "SessionLocal", return_value=_session_context(db)),
            patch.object(process_notification_jobs, "generate_payroll_payment_drafts_once", return_value=2),
            patch.object(process_notification_jobs, "send_due_draft_expense_reminders_once", return_value=3),
            patch.object(process_notification_jobs, "process_pending_notification_jobs_once", return_value=4) as jobs,
            patch.object(process_notification_jobs, "send_shift_reminders_once", return_value=5),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                result = process_notification_jobs.main()

        self.assertEqual(result, 14)
        self.assertIn("shift_reminders=5", output.getvalue())
        jobs.assert_called_once_with(50)

        with (
            patch.object(process_notification_jobs, "SessionLocal", return_value=_session_context(db)),
            patch.object(
                process_notification_jobs,
                "generate_payroll_payment_drafts_once",
                side_effect=RuntimeError("draft generation failed"),
            ),
            patch.object(
                process_notification_jobs,
                "send_due_draft_expense_reminders_once",
                side_effect=RuntimeError("draft reminder failed"),
            ),
            patch.object(process_notification_jobs, "process_pending_notification_jobs_once", return_value=4),
            patch.object(
                process_notification_jobs,
                "send_shift_reminders_once",
                side_effect=RuntimeError("shift reminder failed"),
            ),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                result = process_notification_jobs.main()

        self.assertEqual(result, 4)
        self.assertIn("shift_reminders_error=shift reminder failed", output.getvalue())

    def test_operational_snapshot_reports_all_financial_failure_counters(self):
        db = MagicMock()
        results = []
        for value in (2, 3, 4, 5):
            query = MagicMock()
            query.scalar_one.return_value = value
            results.append(query)
        db.execute.side_effect = results

        with patch.object(operational_snapshot, "SessionLocal", return_value=_session_context(db)):
            self.assertEqual(
                operational_snapshot.build_snapshot(),
                {
                    "failed_payments_24h": 2,
                    "open_reconciliation_high": 3,
                    "failed_notification_jobs_24h": 4,
                    "stale_notification_jobs": 5,
                },
            )

        with patch.object(
            operational_snapshot,
            "build_snapshot",
            return_value={"failed_payments_24h": 2, "stale_notification_jobs": 5},
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(operational_snapshot.main(), 0)
            self.assertEqual(output.getvalue().strip(), '{"failed_payments_24h":2,"stale_notification_jobs":5}')

    def test_notification_log_cleanup_preserves_sent_by_default_and_can_remove_it(self):
        db = MagicMock()
        delete_result = SimpleNamespace(rowcount=6)
        db.execute.return_value = delete_result

        with (
            patch.object(cleanup_notification_delivery_logs, "SessionLocal", return_value=_session_context(db)),
            patch.object(cleanup_notification_delivery_logs, "CLEAN_SENT", False),
        ):
            self.assertEqual(cleanup_notification_delivery_logs.main(), 6)
        db.commit.assert_called_once()

        db.reset_mock()
        db.execute.return_value = SimpleNamespace(rowcount=None)
        with (
            patch.object(cleanup_notification_delivery_logs, "SessionLocal", return_value=_session_context(db)),
            patch.object(cleanup_notification_delivery_logs, "CLEAN_SENT", True),
        ):
            self.assertEqual(cleanup_notification_delivery_logs.main(), 0)
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
