from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.models.notification_job import NotificationJob
from app.routers import venue_economics_notifications
from app.services.integrations import quickresto_notifications


def _safe_payload(**overrides):
    payload = {
        "venue_id": 7,
        "connection_id": 11,
        "run_id": 13,
        "status": "PARTIAL",
        "shifts_seen": 5,
        "shifts_imported": 4,
        "reports_created": 2,
        "reports_updated": 1,
        "reports_unchanged": 1,
        "issue_count": 1,
        "report_import_mode": "DRAFT",
        "technical_summary": "One mapping is missing",
        "correlation_id": "qr-sync-13",
    }
    payload.update(overrides)
    return payload


class QuickRestoNotificationQueueTests(TestCase):
    def test_enqueue_is_per_run_and_payload_is_a_redacted_allowlist(self):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        technical_summary = (
            "QuickResto returned 401; login=owner@example.test password=top-secret "
            "token=abc123 https://api-user:api-pass@cloud.example/api?api_login=raw-user"
        )

        with patch.object(quickresto_notifications, "lock_notification_idempotency_key"):
            job = quickresto_notifications.enqueue_quickresto_import_notification(
                db,
                venue_id=7,
                connection_id=11,
                run_id=13,
                status="FAILED",
                shifts_seen=3,
                issue_count=1,
                report_import_mode="CLOSED",
                technical_summary=technical_summary,
                correlation_id="unsafe correlation token=do-not-store",
            )

        self.assertEqual(job.job_type, "quickresto_import")
        self.assertEqual(job.idempotency_key, "job:quickresto_import:run:13")
        payload = json.loads(job.payload_json)
        self.assertEqual(
            set(payload),
            {
                "venue_id",
                "connection_id",
                "run_id",
                "status",
                "shifts_seen",
                "shifts_imported",
                "reports_created",
                "reports_updated",
                "reports_unchanged",
                "issue_count",
                "report_import_mode",
                "technical_summary",
                "correlation_id",
            },
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in ("top-secret", "abc123", "api-user", "api-pass", "raw-user", "do-not-store"):
            self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", payload["technical_summary"])
        self.assertRegex(payload["correlation_id"], r"^redacted-[0-9a-f]{16}$")
        db.add.assert_called_once_with(job)
        db.flush.assert_called_once_with()

    def test_enqueue_returns_the_existing_job_for_any_terminal_state(self):
        existing = NotificationJob(
            id=91,
            job_type="quickresto_import",
            status="failed",
            idempotency_key="job:quickresto_import:run:13",
        )
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = existing

        with patch.object(quickresto_notifications, "lock_notification_idempotency_key"):
            result = quickresto_notifications.enqueue_quickresto_import_notification(
                db,
                **_safe_payload(),
            )

        self.assertIs(result, existing)
        db.add.assert_not_called()


class QuickRestoNotificationContentTests(TestCase):
    def test_business_message_is_aggregated_and_localized(self):
        ru = quickresto_notifications.build_quickresto_import_text(
            venue_name="Бар Север",
            payload=_safe_payload(),
            locale="ru",
        )
        en = quickresto_notifications.build_quickresto_import_text(
            venue_name="North Bar",
            payload=_safe_payload(),
            locale="en",
        )

        self.assertIn("Смены: найдено 5 · импортировано 4", ru)
        self.assertIn("Отчёты: создано 2 · обновлено 1 · без изменений 1", ru)
        self.assertIn("Проблемы: 1", ru)
        self.assertIn("Shifts: 5 found · 4 imported", en)
        self.assertIn("Reports: 2 created · 1 updated · 1 unchanged", en)
        self.assertIn("Issues: 1", en)
        self.assertNotRegex(en, r"[А-Яа-яЁё]")

    def test_admin_message_never_exposes_credentials_or_raw_payload(self):
        text = quickresto_notifications.build_quickresto_admin_text(
            payload=_safe_payload(
                technical_summary='{"orders": [{"password": "raw-secret"}]}',
                correlation_id="correlation with password=raw-secret",
            ),
            locale="en",
        )

        self.assertIn("Run ID: 13", text)
        self.assertIn("Connection ID: 11", text)
        self.assertIn("[structured detail redacted]", text)
        self.assertNotIn("raw-secret", text)
        self.assertNotIn("orders", text)

    def test_deep_link_opens_quickresto_issues(self):
        with patch.object(quickresto_notifications, "_frontend_base_url", return_value="https://app.test"):
            value = quickresto_notifications._integration_open_url(venue_id=7, show_issues=True)
        self.assertEqual(value, "https://app.test/owner-quickresto.html?venue_id=7&issues=1")


class QuickRestoNotificationRecipientTests(TestCase):
    def test_business_recipients_are_active_owners_or_integration_managers_with_preferences(self):
        owner = SimpleNamespace(
            id=1,
            tg_user_id=101,
            notify_enabled=True,
            notify_integrations=True,
            system_role="NONE",
        )
        manager = SimpleNamespace(
            id=2,
            tg_user_id=102,
            notify_enabled=True,
            notify_integrations=True,
            system_role="NONE",
        )
        denied = SimpleNamespace(
            id=3,
            tg_user_id=103,
            notify_enabled=True,
            notify_integrations=True,
            system_role="NONE",
        )
        muted = SimpleNamespace(
            id=4,
            tg_user_id=104,
            notify_enabled=True,
            notify_integrations=False,
            system_role="NONE",
        )
        db = Mock()
        db.execute.return_value.all.return_value = [
            (owner, "OWNER"),
            (manager, "STAFF"),
            (denied, "STAFF"),
            (muted, "OWNER"),
        ]

        with patch.object(
            quickresto_notifications,
            "has_venue_permission",
            side_effect=lambda _db, *, user, **_kwargs: user.id == manager.id,
        ) as has_permission:
            result = quickresto_notifications._business_recipients(db, venue_id=7)

        self.assertEqual(result, [owner, manager])
        has_permission.assert_any_call(
            db,
            venue_id=7,
            user=manager,
            permission_code="INTEGRATIONS_MANAGE",
        )
        sql = str(db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("venue_members.is_active IS true", sql)
        self.assertIn("users.tg_user_id IS NOT NULL", sql)

    def test_admin_recipients_union_system_role_and_configured_ids_without_bypassing_user_mute(self):
        system_admin = SimpleNamespace(
            id=1,
            tg_user_id=101,
            preferred_locale="en",
            notify_enabled=True,
            notify_integrations=True,
        )
        muted_configured_user = SimpleNamespace(
            id=2,
            tg_user_id=202,
            preferred_locale="ru",
            notify_enabled=False,
            notify_integrations=True,
        )
        result_proxy = Mock()
        result_proxy.scalars.return_value.all.return_value = [system_admin, muted_configured_user]
        db = Mock()
        db.execute.return_value = result_proxy

        with patch.object(quickresto_notifications, "_configured_super_admin_ids", return_value={202, 999}):
            recipients = quickresto_notifications._admin_recipients(db)

        self.assertEqual([item.chat_id for item in recipients], [101, 999])
        self.assertEqual(recipients[0].locale, "en")
        self.assertIsNone(recipients[1].user_id)


class QuickRestoNotificationDeliveryTests(TestCase):
    def test_success_notifies_business_recipients_only_and_opens_integration_root(self):
        business_user = SimpleNamespace(id=1, tg_user_id=101, preferred_locale="ru")
        with (
            patch.object(quickresto_notifications, "_venue_name", return_value="Test"),
            patch.object(
                quickresto_notifications,
                "_integration_open_url",
                return_value="https://app.test/qr",
            ) as integration_url,
            patch.object(
                quickresto_notifications,
                "_business_recipients",
                return_value=[business_user],
            ),
            patch.object(quickresto_notifications, "_admin_recipients") as admin_recipients,
            patch.object(
                quickresto_notifications,
                "_deliver_once",
                return_value=(True, False, False),
            ) as deliver,
        ):
            result = quickresto_notifications.send_quickresto_import_notifications(
                Mock(),
                payload=_safe_payload(
                    status="SUCCEEDED",
                    issue_count=0,
                    technical_summary=None,
                    correlation_id=None,
                ),
            )

        self.assertEqual(result, {"business_sent": 1, "admin_sent": 0})
        integration_url.assert_called_once_with(venue_id=7, show_issues=False)
        admin_recipients.assert_not_called()
        self.assertEqual(deliver.call_count, 1)
        self.assertEqual(deliver.call_args.kwargs["recipient_kind"], "business")

    def test_delivery_log_idempotency_is_scoped_by_recipient_run_and_kind(self):
        db = Mock()
        entry = SimpleNamespace(status=None, sent_at=None, error_text=None)
        with (
            patch.object(quickresto_notifications, "lock_notification_idempotency_key") as lock_key,
            patch.object(quickresto_notifications, "notification_delivery_exists", return_value=False),
            patch.object(quickresto_notifications, "_pending_delivery", return_value=None),
            patch.object(quickresto_notifications, "log_notification_attempt", return_value=entry) as log_attempt,
            patch.object(
                quickresto_notifications.tg_notify,
                "notify_result",
                return_value={"ok": True, "retryable": False},
            ) as notify,
        ):
            result = quickresto_notifications._deliver_once(
                db,
                recipient_kind="business",
                chat_id=101,
                user_id=1,
                venue_id=7,
                run_id=13,
                text="safe aggregate",
                url="https://app.test/owner-quickresto.html?venue_id=7&issues=1",
                button_text="Open",
            )

        key = "quickresto_import:business:run:13:tg:101"
        self.assertEqual(result, (True, False, False))
        lock_key.assert_called_once_with(db, key)
        self.assertEqual(log_attempt.call_args.kwargs["idempotency_key"], key)
        self.assertEqual(log_attempt.call_args.kwargs["notification_type"], "quickresto_import_business")
        notify.assert_called_once()
        self.assertEqual(entry.status, "sent")

    def test_fresh_pending_delivery_keeps_concurrent_send_blocked_and_job_retryable(self):
        db = Mock()
        pending = SimpleNamespace(planned_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        with (
            patch.object(quickresto_notifications, "lock_notification_idempotency_key"),
            patch.object(quickresto_notifications, "notification_delivery_exists", return_value=False),
            patch.object(quickresto_notifications, "_pending_delivery", return_value=pending),
            patch.object(quickresto_notifications, "log_notification_attempt") as log_attempt,
            patch.object(quickresto_notifications.tg_notify, "notify_result") as notify,
        ):
            result = quickresto_notifications._deliver_once(
                db,
                recipient_kind="business",
                chat_id=101,
                user_id=1,
                venue_id=7,
                run_id=13,
                text="safe aggregate",
                url="https://app.test/owner-quickresto.html?venue_id=7&issues=1",
                button_text="Open",
            )

        self.assertEqual(result, (False, True, True))
        log_attempt.assert_not_called()
        notify.assert_not_called()
        db.commit.assert_not_called()

    def test_stale_pending_delivery_is_reclaimed_after_worker_crash(self):
        db = Mock()
        old_planned_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        pending = SimpleNamespace(
            notification_type="quickresto_import_business",
            status="pending",
            user_id=1,
            venue_id=7,
            planned_at=old_planned_at,
            sent_at=None,
            error_text=None,
            payload_preview="old preview",
        )
        with (
            patch.object(quickresto_notifications, "lock_notification_idempotency_key"),
            patch.object(quickresto_notifications, "notification_delivery_exists", return_value=False),
            patch.object(quickresto_notifications, "_pending_delivery", return_value=pending),
            patch.object(quickresto_notifications, "log_notification_attempt") as log_attempt,
            patch.object(
                quickresto_notifications.tg_notify,
                "notify_result",
                return_value={"ok": True, "retryable": False},
            ) as notify,
        ):
            result = quickresto_notifications._deliver_once(
                db,
                recipient_kind="business",
                chat_id=101,
                user_id=1,
                venue_id=7,
                run_id=13,
                text="safe aggregate",
                url="https://app.test/owner-quickresto.html?venue_id=7&issues=1",
                button_text="Open",
            )

        self.assertEqual(result, (True, False, False))
        self.assertEqual(pending.status, "sent")
        self.assertGreater(pending.planned_at, old_planned_at)
        log_attempt.assert_not_called()
        notify.assert_called_once()
        self.assertEqual(db.commit.call_count, 2)

    def test_existing_delivery_skips_network(self):
        db = Mock()
        with (
            patch.object(quickresto_notifications, "lock_notification_idempotency_key"),
            patch.object(quickresto_notifications, "notification_delivery_exists", return_value=True),
            patch.object(quickresto_notifications.tg_notify, "notify_result") as notify,
        ):
            result = quickresto_notifications._deliver_once(
                db,
                recipient_kind="admin",
                chat_id=999,
                user_id=None,
                venue_id=7,
                run_id=13,
                text="safe technical summary",
                url="https://app.test/owner-quickresto.html?venue_id=7&issues=1",
                button_text="Open",
            )

        self.assertEqual(result, (False, False, False))
        notify.assert_not_called()

    def test_aggregate_and_admin_failures_keep_retryability(self):
        business_user = SimpleNamespace(id=1, tg_user_id=101, preferred_locale="ru")
        admin_user = SimpleNamespace(id=2, tg_user_id=102, preferred_locale="en")
        with (
            patch.object(quickresto_notifications, "_venue_name", return_value="Test"),
            patch.object(quickresto_notifications, "_integration_open_url", return_value="https://app.test/qr"),
            patch.object(quickresto_notifications, "_business_recipients", return_value=[business_user]),
            patch.object(
                quickresto_notifications,
                "_admin_recipients",
                return_value=[quickresto_notifications._AdminRecipient(chat_id=102, user=admin_user)],
            ),
            patch.object(
                quickresto_notifications,
                "_deliver_once",
                side_effect=[(True, False, False), (False, True, True)],
            ) as deliver,
        ):
            with self.assertRaises(quickresto_notifications.QuickRestoNotificationDeliveryError) as raised:
                quickresto_notifications.send_quickresto_import_notifications(
                    Mock(),
                    payload=_safe_payload(),
                )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(deliver.call_count, 2)
        self.assertEqual(deliver.call_args_list[0].kwargs["recipient_kind"], "business")
        self.assertEqual(deliver.call_args_list[1].kwargs["recipient_kind"], "admin")


class QuickRestoNotificationWorkerTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=[NotificationJob.__table__])
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _add_job(self) -> int:
        with Session(self.engine) as db:
            job = NotificationJob(
                job_type="quickresto_import",
                status="pending",
                payload_json=json.dumps(_safe_payload()),
                attempts=0,
                max_attempts=3,
                run_after=datetime.utcnow(),
                idempotency_key="job:quickresto_import:run:13",
            )
            db.add(job)
            db.commit()
            return int(job.id)

    def test_shared_worker_dispatches_quickresto_job(self):
        job_id = self._add_job()
        with (
            patch.object(venue_economics_notifications, "SessionLocal", self.SessionLocal),
            patch.object(venue_economics_notifications, "send_quickresto_import_notifications") as send,
        ):
            processed = venue_economics_notifications.process_pending_notification_jobs_once(limit=1)

        self.assertEqual(processed, 1)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["payload"]["run_id"], 13)
        with Session(self.engine) as db:
            self.assertEqual(db.get(NotificationJob, job_id).status, "sent")

    def test_shared_worker_keeps_retry_semantics_for_transient_delivery_failure(self):
        job_id = self._add_job()
        error = quickresto_notifications.QuickRestoNotificationDeliveryError(
            "temporary Telegram failure",
            retryable=True,
        )
        with (
            patch.object(venue_economics_notifications, "SessionLocal", self.SessionLocal),
            patch.object(
                venue_economics_notifications,
                "send_quickresto_import_notifications",
                side_effect=error,
            ),
            patch.object(venue_economics_notifications.log, "exception"),
        ):
            processed = venue_economics_notifications.process_pending_notification_jobs_once(limit=1)

        self.assertEqual(processed, 1)
        with Session(self.engine) as db:
            job = db.get(NotificationJob, job_id)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempts, 1)
            self.assertEqual(job.last_error, "temporary Telegram failure")
            self.assertIsNone(job.locked_at)
