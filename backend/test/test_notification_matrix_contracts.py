from __future__ import annotations

from pathlib import Path
from unittest import TestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP = PROJECT_ROOT / "backend" / "app"


def _source(relative_path: str) -> str:
    return (APP / relative_path).read_text(encoding="utf-8")


class NotificationTriggerMatrixContractTests(TestCase):
    def test_report_close_enqueues_every_day_close_notification(self):
        source = _source("routers/venue_reports.py")

        for enqueue_call in (
            "_enqueue_day_economics_summary_job",
            "_enqueue_salary_day_breakdown_job",
            "_enqueue_soft_alerts_job",
        ):
            self.assertIn(f"{enqueue_call}(db, venue_id=venue_id, target_date=report_date)", source)
        self.assertIn("background_tasks.add_task(process_pending_notification_jobs_once, 10)", source)

    def test_adjustment_mutations_enqueue_assignment_and_dispute_events(self):
        source = _source("routers/venue_adjustments.py")

        self.assertIn("_enqueue_adjustment_assigned_job(db, venue_id=venue_id, adjustment_id=int(obj.id))", source)
        self.assertEqual(source.count("_enqueue_adjustment_dispute_event_job("), 2)
        self.assertIn('event_kind="opened" if created_new else "comment"', source)
        self.assertIn('event_kind="comment"', source)

    def test_notification_job_dispatch_covers_the_complete_queue(self):
        constants = _source("routers/venue_common.py")
        worker = _source("routers/venue_economics_notifications.py")
        adjustment_worker = _source("routers/venue_adjustment_notifications.py")
        expected_job_types = (
            "day_economics_summary",
            "salary_day_breakdown",
            "soft_alerts",
            "adjustment_assigned",
            "adjustment_dispute_event",
        )

        for job_type in expected_job_types:
            self.assertIn(f'= "{job_type}"', constants)
            delivery_source = adjustment_worker if job_type.startswith("adjustment_") else worker
            self.assertIn(f'notification_type="{job_type}"', delivery_source)
        self.assertIn("from app.services.finance.day_economics import get_day_economics", worker)

    def test_shift_worker_covers_due_reminders_comments_and_deduplication(self):
        source = _source("scripts/send_shift_reminders.py")

        self.assertIn('notification_type="shift_reminder"', source)
        self.assertIn('notification_type="shift_comment"', source)
        self.assertIn("if now < planned_at - timedelta(minutes=WINDOW_MINUTES):", source)
        self.assertIn("if now >= start_dt:", source)
        self.assertIn("ShiftComment.created_at <= now_utc", source)
        self.assertIn("notification_delivery_exists", source)
        self.assertIn("sa.reminder_sent_at = sent_at", source)

        demo_bootstrap = _source("services/demo/bootstrap.py")
        self.assertIn("created_at=datetime.combine(day, time(hour=9), tzinfo=timezone.utc)", demo_bootstrap)

    def test_billing_worker_covers_every_scheduled_owner_and_admin_scenario(self):
        source = _source("scripts/process_billing_jobs.py")
        scheduled_types = (
            "stale_pending",
            "refund_state_error",
            "refund_finished",
            "grace_started",
            "suspended",
            "grace_ends_today",
            "failed_threshold_24h",
        )

        for notification_type in scheduled_types:
            self.assertIn(f'notification_type="{notification_type}"', source)
        self.assertIn('{7: "7d", 3: "3d", 1: "1d", 0: "due_today"}', source)
        self.assertIn('notification_type=f"reminder_{reminder_codes[int(days_to_paid_end)]}"', source)

    def test_immediate_and_account_notification_triggers_remain_registered(self):
        expected = {
            "routers/billing.py": ("payment_success",),
            "routers/admin_billing.py": ("manual_extend", "manual_set_paid_until"),
            "routers/venue_core.py": ("self_service_trial_created",),
            "routers/auth_common.py": ("phone_link_reminder",),
        }

        for relative_path, notification_types in expected.items():
            source = _source(relative_path)
            for notification_type in notification_types:
                self.assertIn(notification_type, source)

        public_leads = _source("routers/public_leads.py")
        self.assertIn("tg_notify.notify_result(", public_leads)
        self.assertIn('parse_mode="HTML"', public_leads)
