from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.routers import venue_economics_notifications, venue_notification_common, venue_pay_profile_support
from app.services import tg_notify
from app.services.billing import promos


class _FlushSession:
    def __init__(self):
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1


class BillingPromoPatchRegressionTests(TestCase):
    def test_active_only_patch_preserves_percent_value(self):
        db = _FlushSession()
        promo = SimpleNamespace(
            id=7,
            code="SAVE15",
            title="15 percent",
            kind=promos.PROMO_KIND_PERCENT,
            percent_value=15,
            amount_minor=None,
            free_days=None,
            comment=None,
            is_active=True,
            updated_at=None,
        )

        with patch.object(promos, "get_promo_code_by_code", return_value=promo):
            result = promos.update_promo_code(db, promo=promo, is_active=False)

        self.assertIs(result, promo)
        self.assertFalse(promo.is_active)
        self.assertEqual(promo.percent_value, 15)
        self.assertIsNone(promo.amount_minor)
        self.assertIsNone(promo.free_days)
        self.assertEqual(db.flush_calls, 1)

    def test_changing_kind_still_requires_value_for_new_kind(self):
        db = _FlushSession()
        promo = SimpleNamespace(
            id=8,
            code="SAVE15",
            title=None,
            kind=promos.PROMO_KIND_PERCENT,
            percent_value=15,
            amount_minor=None,
            free_days=None,
            comment=None,
            is_active=True,
            updated_at=None,
        )

        with patch.object(promos, "get_promo_code_by_code", return_value=promo):
            with self.assertRaises(ValueError):
                promos.update_promo_code(db, promo=promo, kind=promos.PROMO_KIND_FIXED_MINOR)


class PayProfileAssignmentRegressionTests(TestCase):
    def test_phone_only_member_has_a_display_name(self):
        assignment = SimpleNamespace(
            id=31,
            pay_profile_id=7,
            member_user_id=17,
            start_date=None,
            end_date=None,
            is_active=True,
        )
        member = SimpleNamespace(
            id=17,
            tg_user_id=None,
            tg_username=None,
            full_name=None,
            short_name=None,
        )

        payload = venue_pay_profile_support._serialize_pay_profile_assignment(
            assignment,
            member=member,
            auth_snapshot={"phone": "+79990000999", "auth_methods": ["phone"]},
        )

        self.assertEqual(payload["member"]["phone"], "+79990000999")
        self.assertEqual(payload["member"]["display_name"], "+79990000999")


class TelegramNotificationRegressionTests(TestCase):
    def test_economics_notification_module_keeps_day_economics_dependency(self):
        self.assertTrue(callable(venue_economics_notifications.get_day_economics))

    def test_web_app_button_is_only_built_for_https(self):
        self.assertIsNone(
            tg_notify._reply_markup(
                url="http://127.0.0.1:8765/staff-adjustments.html",
                button_text="Открыть",
            )
        )
        self.assertEqual(
            tg_notify._reply_markup(
                url="https://app.axelio.example/staff-adjustments.html",
                button_text="Открыть",
            ),
            {
                "inline_keyboard": [[{
                    "text": "Открыть",
                    "web_app": {"url": "https://app.axelio.example/staff-adjustments.html"},
                }]],
            },
        )

    def test_existing_delivery_is_an_idempotent_success(self):
        recipient = SimpleNamespace(id=11, tg_user_id=416573580)
        with patch.object(venue_notification_common, "lock_notification_idempotency_key"), \
             patch.object(venue_notification_common, "notification_delivery_exists", return_value=True):
            result = venue_notification_common._deliver_user_notification(
                SimpleNamespace(),
                notification_type="adjustment_assigned",
                recipient=recipient,
                venue_id=1,
                idempotency_key="delivery:1",
                text="test",
            )
        self.assertEqual(result, (True, False))

    def test_master_and_category_notification_preferences_are_respected(self):
        user = SimpleNamespace(
            notify_enabled=True,
            notify_adjustments=True,
            notify_shifts=True,
            notify_shift_comments=True,
            notify_day_economics=True,
            notify_salary=True,
            notify_soft_alerts=True,
        )
        categories = {
            "adjustments": "notify_adjustments",
            "shifts": "notify_shifts",
            "shift_comments": "notify_shift_comments",
            "day_economics": "notify_day_economics",
            "salary": "notify_salary",
            "soft_alerts": "notify_soft_alerts",
        }

        for category, attribute in categories.items():
            self.assertTrue(venue_notification_common._should_notify_user(user, category))
            setattr(user, attribute, False)
            self.assertFalse(venue_notification_common._should_notify_user(user, category))
            setattr(user, attribute, True)

        user.notify_enabled = False
        for category in categories:
            self.assertFalse(venue_notification_common._should_notify_user(user, category))

    def test_terminal_delivery_error_marks_job_failed_without_retry(self):
        job = SimpleNamespace(
            attempts=1,
            max_attempts=3,
            status="PROCESSING",
            run_after=None,
            locked_at=object(),
            last_error=None,
            updated_at=None,
            processed_at=None,
        )

        venue_economics_notifications._complete_notification_job(
            SimpleNamespace(),
            job,
            status=venue_economics_notifications._NOTIFICATION_JOB_STATUS_FAILED,
            last_error="Telegram rejected payload",
            retryable=False,
        )

        self.assertEqual(job.status, venue_economics_notifications._NOTIFICATION_JOB_STATUS_FAILED)
        self.assertEqual(job.last_error, "Telegram rejected payload")
        self.assertIsNotNone(job.processed_at)
        self.assertIsNone(job.locked_at)

    def test_retryable_delivery_error_returns_job_to_pending(self):
        job = SimpleNamespace(
            attempts=1,
            max_attempts=3,
            status="PROCESSING",
            run_after=None,
            locked_at=object(),
            last_error=None,
            updated_at=None,
            processed_at=None,
        )

        venue_economics_notifications._complete_notification_job(
            SimpleNamespace(),
            job,
            status=venue_economics_notifications._NOTIFICATION_JOB_STATUS_FAILED,
            last_error="Telegram unavailable",
            retryable=True,
        )

        self.assertEqual(job.status, venue_economics_notifications._NOTIFICATION_JOB_STATUS_PENDING)
        self.assertEqual(job.last_error, "Telegram unavailable")
        self.assertIsNotNone(job.run_after)
        self.assertIsNone(job.locked_at)
        self.assertIsNone(job.processed_at)
