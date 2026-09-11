from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_batch import QuickRestoImportBatch
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations.quickresto_sync import QuickRestoSyncError
from app.services.integrations.quickresto_import_batches import (
    monthly_periods_count,
    process_quickresto_import_batch,
    retry_quickresto_import_batch,
)


class QuickRestoImportBatchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Venue.__table__,
                QuickRestoConnection.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoImportBatch.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.add(User(id=1, system_role="NONE"))
        self.db.add(Venue(id=1, name="Monthly QuickResto test"))
        self.db.add(
            QuickRestoConnection(
                id=1,
                venue_id=1,
                cloud="test",
                api_login_encrypted="login",
                api_password_encrypted="password",
                scope_status="READY",
                is_active=True,
                report_import_mode="CLOSED",
                sync_from_date=date(2024, 11, 15),
                created_by_user_id=1,
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_batch(self, *, period_end: date = date(2025, 2, 1)) -> QuickRestoImportBatch:
        batch = QuickRestoImportBatch(
            connection_id=1,
            requested_by_user_id=1,
            trigger="FULL",
            force_full=True,
            status="PENDING",
            period_start=date(2024, 11, 15),
            period_end_exclusive=period_end,
            next_period_start=date(2024, 11, 15),
            total_periods=monthly_periods_count(date(2024, 11, 15), period_end),
            completed_periods=0,
            partial_periods=0,
            retry_count=0,
            summary_json={"totals": {}, "periods": [], "issue_ids": []},
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def test_period_count_uses_calendar_month_boundaries(self):
        self.assertEqual(monthly_periods_count(date(2024, 11, 15), date(2025, 2, 1)), 3)
        self.assertEqual(monthly_periods_count(date(2025, 1, 1), date(2025, 1, 2)), 1)

    def test_batch_processes_months_sequentially_and_aggregates_result(self):
        batch = self.add_batch()
        observed_periods: list[tuple[date, date, bool]] = []

        def fake_sync(db, **kwargs):
            observed_periods.append(
                (
                    kwargs["period_start"],
                    kwargs["period_end_exclusive"],
                    kwargs["refresh_catalog"],
                )
            )
            run = QuickRestoSyncRun(
                connection_id=1,
                requested_by_user_id=1,
                trigger="MONTHLY_IMPORT",
                status="PARTIAL" if len(observed_periods) == 2 else "SUCCEEDED",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                shifts_seen=3,
                shifts_imported=2,
                reports_created=1,
                reports_updated=1,
                reports_unchanged=0,
                summary_json={"issue_count": 1 if len(observed_periods) == 2 else 0},
            )
            db.add(run)
            db.flush()
            return run

        with (
            patch(
                "app.services.integrations.quickresto_import_batches.sync_quickresto_connection",
                side_effect=fake_sync,
                autospec=True,
            ),
            patch("app.services.integrations.quickresto_import_batches.enqueue_quickresto_import_notification"),
        ):
            result = process_quickresto_import_batch(self.db, batch_id=batch.id, client=object())

        self.assertEqual(
            observed_periods,
            [
                (date(2024, 11, 15), date(2024, 12, 1), True),
                (date(2024, 12, 1), date(2025, 1, 1), False),
                (date(2025, 1, 1), date(2025, 2, 1), False),
            ],
        )
        self.assertEqual(result.status, "PARTIAL")
        self.assertEqual(result.completed_periods, 3)
        self.assertEqual(result.partial_periods, 1)
        self.assertEqual(result.next_period_start, date(2025, 2, 1))
        self.assertEqual(result.summary_json["totals"]["shifts_imported"], 6)
        self.assertEqual(len(result.summary_json["periods"]), 3)

    def test_failed_month_remains_cursor_and_can_be_retried(self):
        batch = self.add_batch()

        def failed_sync(db, **_kwargs):
            run = QuickRestoSyncRun(
                connection_id=1,
                requested_by_user_id=1,
                trigger="MONTHLY_IMPORT",
                status="FAILED",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                error_message="temporary provider failure",
                summary_json={"issue_count": 0},
            )
            db.add(run)
            db.commit()
            raise QuickRestoSyncError("temporary provider failure")

        with patch(
            "app.services.integrations.quickresto_import_batches.sync_quickresto_connection",
            side_effect=failed_sync,
            autospec=True,
        ):
            failed = process_quickresto_import_batch(self.db, batch_id=batch.id, client=object())

        self.assertEqual(failed.status, "FAILED")
        self.assertEqual(failed.completed_periods, 0)
        self.assertEqual(failed.next_period_start, date(2024, 11, 15))
        self.assertIsNotNone(failed.last_sync_run_id)

        retried = retry_quickresto_import_batch(self.db, batch=failed)
        self.assertEqual(retried.status, "PENDING")
        self.assertEqual(retried.retry_count, 1)
        self.assertEqual(retried.next_period_start, date(2024, 11, 15))


if __name__ == "__main__":
    unittest.main()
