from __future__ import annotations

from unittest import TestCase

from app.routers.me import NotificationSettingsIn
from app.scripts.send_shift_reminders import _normalize_lead_hours


class NotificationSettingsTests(TestCase):
    def test_notification_settings_accepts_known_values(self):
        payload = NotificationSettingsIn(
            notify_enabled=True,
            notify_shifts=True,
            notify_shift_comments=True,
            shift_reminder_lead_time_hours=6,
            notification_detail_level="detailed",
        )
        self.assertEqual(payload.shift_reminder_lead_time_hours, 6)
        self.assertTrue(payload.notify_shift_comments)
        self.assertEqual(payload.notification_detail_level, "detailed")

    def test_notification_settings_rejects_unknown_lead_time(self):
        with self.assertRaisesRegex(ValueError, "shift_reminder_lead_time_hours"):
            NotificationSettingsIn(shift_reminder_lead_time_hours=5)

    def test_notification_settings_normalizes_detail_level(self):
        payload = NotificationSettingsIn(notification_detail_level="STANDARD")
        self.assertEqual(payload.notification_detail_level, "standard")

    def test_normalize_lead_hours_falls_back_to_default_for_bad_values(self):
        self.assertEqual(_normalize_lead_hours(None), 18)
        self.assertEqual(_normalize_lead_hours(0), 18)
        self.assertEqual(_normalize_lead_hours(24), 24)
