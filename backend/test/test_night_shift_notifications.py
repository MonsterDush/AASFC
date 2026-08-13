from __future__ import annotations

import json
from datetime import date, datetime, time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.routers import (
    venue_economics_notifications,
    venue_notification_common,
    venue_shift_notifications,
)
from app.schemas.venue_shifts import (
    ShiftCreateIn,
    ShiftScheduleTemplateItemIn,
    ShiftUpdateIn,
)
from app.scripts.send_shift_reminders import (
    _build_shift_reminder_text,
    _shift_start_naive,
)


class NightShiftNotificationJobTests(TestCase):
    def _enqueue(self, enqueue, *, shift_slot: str, event_key: str):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        job = enqueue(
            db,
            venue_id=5,
            target_date=date(2026, 7, 29),
            shift_slot=shift_slot,
            event_key=event_key,
        )
        return job

    def test_report_notification_jobs_are_separated_by_slot_and_close_event(self):
        enqueue_functions = (
            venue_economics_notifications._enqueue_day_economics_summary_job,
            venue_economics_notifications._enqueue_salary_day_breakdown_job,
            venue_economics_notifications._enqueue_soft_alerts_job,
        )

        for enqueue in enqueue_functions:
            with self.subTest(enqueue=enqueue.__name__):
                day_job = self._enqueue(enqueue, shift_slot="DAY", event_key="close-1")
                night_job = self._enqueue(enqueue, shift_slot="NIGHT", event_key="close-1")
                night_reclose_job = self._enqueue(enqueue, shift_slot="NIGHT", event_key="close-2")

                self.assertNotEqual(day_job.idempotency_key, night_job.idempotency_key)
                self.assertNotEqual(night_job.idempotency_key, night_reclose_job.idempotency_key)
                payload = json.loads(night_job.payload_json)
                self.assertEqual(payload["shift_slot"], "NIGHT")
                self.assertEqual(payload["event_key"], "close-1")

    def test_salary_recipient_queries_are_limited_to_requested_slot(self):
        assignment_result = Mock()
        assignment_result.all.return_value = [(11,)]
        tip_result = Mock()
        tip_result.all.return_value = [(12,)]
        db = Mock()
        db.execute.side_effect = [assignment_result, tip_result]

        result = venue_economics_notifications._collect_salary_day_notification_user_ids(
            db,
            venue_id=5,
            target_date=date(2026, 7, 29),
            shift_slot="NIGHT",
        )

        self.assertEqual(result, [11, 12])
        self.assertEqual(db.execute.call_count, 2)
        assignment_sql = str(
            db.execute.call_args_list[0]
            .args[0]
            .compile(
                compile_kwargs={"literal_binds": True},
            )
        )
        tips_sql = str(
            db.execute.call_args_list[1]
            .args[0]
            .compile(
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("shifts.shift_slot = 'NIGHT'", assignment_sql)
        self.assertIn("daily_reports.shift_slot = 'NIGHT'", tips_sql)
        self.assertNotIn("adjustments", assignment_sql + tips_sql)


class NightShiftNotificationContentTests(TestCase):
    def test_shift_start_uses_the_stored_calendar_date_without_night_offset(self):
        self.assertEqual(
            _shift_start_naive(date(2026, 7, 29), time(12, 0)),
            datetime(2026, 7, 29, 12, 0),
        )
        self.assertEqual(
            _shift_start_naive(date(2026, 7, 30), time(4, 0)),
            datetime(2026, 7, 30, 4, 0),
        )

    def test_notification_links_open_the_exact_night_slot(self):
        with patch.object(
            venue_notification_common,
            "_frontend_base_url",
            return_value="https://example.test",
        ):
            economics_link = venue_notification_common._build_owner_day_economics_link(
                venue_id=5,
                target_date=date(2026, 7, 29),
                shift_slot="NIGHT",
            )
            salary_link = venue_notification_common._build_staff_salary_day_link(
                venue_id=5,
                target_date=date(2026, 7, 29),
                shift_slot="NIGHT",
            )

        self.assertIn("shift_slot=NIGHT", economics_link)
        self.assertIn("shift_slot=NIGHT", salary_link)

    def test_report_notification_texts_name_the_night_slot(self):
        economics = {"summary": {}}
        day_text = venue_economics_notifications._build_day_economics_notification_text(
            venue_name="Тест",
            target_date=date(2026, 7, 29),
            economics=economics,
            detail_level="short",
            shift_slot="NIGHT",
        )
        salary_text = venue_economics_notifications._build_salary_day_breakdown_text(
            venue_name="Тест",
            target_date=date(2026, 7, 29),
            breakdown={"summary": {}},
            detail_level="short",
            shift_slot="NIGHT",
        )
        alerts_text = venue_economics_notifications._build_soft_alerts_notification_text(
            venue_name="Тест",
            target_date=date(2026, 7, 29),
            economics={"summary": {}, "metrics": {}, "rules": {}},
            alerts=[{"code": "TEST", "severity": "WARN", "title": "Проверка"}],
            detail_level="short",
            shift_slot="NIGHT",
        )

        for text_value in (day_text, salary_text, alerts_text):
            self.assertIn("Слот: Ночь", text_value)

    def test_report_notification_texts_support_english_recipients(self):
        day_text = venue_economics_notifications._build_day_economics_notification_text(
            venue_name="North Bar",
            target_date=date(2026, 7, 29),
            economics={"summary": {}},
            detail_level="short",
            shift_slot="NIGHT",
            locale="en",
        )
        salary_text = venue_economics_notifications._build_salary_day_breakdown_text(
            venue_name="North Bar",
            target_date=date(2026, 7, 29),
            breakdown={"summary": {}},
            detail_level="short",
            shift_slot="NIGHT",
            locale="en",
        )
        alerts_text = venue_economics_notifications._build_soft_alerts_notification_text(
            venue_name="North Bar",
            target_date=date(2026, 7, 29),
            economics={"summary": {}, "metrics": {}, "rules": {}},
            alerts=[{"code": "LOSS_DAY", "severity": "CRITICAL", "title": "День убыточный"}],
            detail_level="short",
            shift_slot="NIGHT",
            locale="en",
        )

        for text_value in (day_text, salary_text, alerts_text):
            self.assertIn("Shift: Night", text_value)
            self.assertNotRegex(text_value, r"[А-Яа-яЁё]")

    def test_shift_comment_link_and_label_preserve_night_context(self):
        shift = SimpleNamespace(
            id=41,
            date=date(2026, 7, 29),
            shift_slot="NIGHT",
        )
        interval = SimpleNamespace(start_time=time(23, 30))
        with patch.object(
            venue_shift_notifications,
            "_frontend_base_url",
            return_value="https://example.test",
        ):
            link = venue_shift_notifications._shift_comment_link(
                venue_id=5,
                shift=shift,
                comment_id=9,
            )

        label = venue_shift_notifications._shift_date_label(shift, interval)
        self.assertIn("shift_slot=NIGHT", link)
        self.assertIn("Ночь", label)
        self.assertIn("23:30", label)

    def test_shift_reminder_names_a_night_shift(self):
        text_value = _build_shift_reminder_text(
            shift=SimpleNamespace(date=date(2026, 7, 30), shift_slot="NIGHT"),
            interval=SimpleNamespace(start_time=time(4, 0)),
            venue=SimpleNamespace(name="Тест"),
        )

        self.assertIn("ночная смена", text_value)
        self.assertIn("30 июля", text_value)
        self.assertIn("04:00", text_value)


class NightShiftSlotValidationTests(TestCase):
    def test_shift_mutation_payloads_reject_unknown_slots(self):
        invalid_payloads = (
            lambda: ShiftCreateIn(
                date=date(2026, 7, 29),
                interval_id=1,
                shift_slot="NIGTH",
            ),
            lambda: ShiftUpdateIn(shift_slot="night"),
            lambda: ShiftScheduleTemplateItemIn(
                weekday=2,
                interval_id=1,
                shift_slot="EVENING",
            ),
        )

        for build_payload in invalid_payloads:
            with self.subTest(payload=build_payload):
                with self.assertRaises(ValidationError):
                    build_payload()
