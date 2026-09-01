from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.daily_report import DailyReport
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_audit import QuickRestoImportIssueAudit
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.schemas.quickresto import QuickRestoIssueResolveIn


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class QuickRestoIssueModelTests(unittest.TestCase):
    def test_ignore_resolution_note_is_trimmed_and_cannot_be_whitespace(self):
        parsed = QuickRestoIssueResolveIn(action="IGNORE", note="  проверено  ")
        self.assertEqual(parsed.note, "проверено")

        with self.assertRaises(ValidationError):
            QuickRestoIssueResolveIn(action="IGNORE", note="   ")

    def test_issue_group_snapshot_items_and_audit_persist_on_sqlite(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Venue.__table__,
                DailyReport.__table__,
                QuickRestoConnection.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoShiftImport.__table__,
                QuickRestoSourceSnapshot.__table__,
                QuickRestoImportIssue.__table__,
                QuickRestoImportIssueShift.__table__,
                QuickRestoImportIssueAudit.__table__,
            ],
        )

        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            user = User(system_role="NONE")
            venue = Venue(name="QuickResto durable issue test")
            db.add_all([user, venue])
            db.flush()
            connection = QuickRestoConnection(
                venue_id=venue.id,
                cloud="fixture",
                api_login_encrypted="v1:login",
                api_password_encrypted="v1:password",
                created_by_user_id=user.id,
            )
            db.add(connection)
            db.flush()
            run = QuickRestoSyncRun(
                connection_id=connection.id,
                requested_by_user_id=user.id,
                trigger="TEST",
                status="PARTIAL",
                started_at=now,
            )
            db.add(run)
            db.flush()
            snapshot = QuickRestoSourceSnapshot(
                connection_id=connection.id,
                sync_run_id=run.id,
                source_fingerprint="a" * 64,
                payload_hash="b" * 64,
                encrypted_payload="v1:encrypted",
                encryption_key_version="v1",
                external_shift_id="fixture-shift-1",
                external_shift_pk=101,
                source_version=2,
                business_date=date(2030, 1, 15),
                shift_slot="DAY",
                local_opened_at=datetime(2030, 1, 15, 10),
                local_closed_at=datetime(2030, 1, 15, 18),
                retention_expires_at=now + timedelta(days=30),
                created_at=now,
                updated_at=now,
            )
            db.add(snapshot)
            db.flush()
            issue = QuickRestoImportIssue(
                connection_id=connection.id,
                last_sync_run_id=run.id,
                group_key="report:2030-01-15:DAY",
                business_date=date(2030, 1, 15),
                shift_slot="DAY",
                status="OPEN",
                error_code="MAPPING_REQUIRED",
                error_category="ACTION_REQUIRED",
                user_summary="Нужно сопоставить способ оплаты.",
                details_json={"missing_payment_type_ids": [7]},
                failure_fingerprint="c" * 64,
                correlation_id="qr-test-correlation",
                first_failed_at=now,
                last_failed_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(issue)
            db.flush()
            issue.shifts.append(
                QuickRestoImportIssueShift(
                    source_snapshot_id=snapshot.id,
                    source_key="external:fixture-shift-1",
                    external_shift_id="fixture-shift-1",
                    external_shift_pk=101,
                    source_version=2,
                    source_fingerprint=snapshot.source_fingerprint,
                    item_status="FAILED",
                    error_code="MAPPING_REQUIRED",
                    user_summary="Не сопоставлен способ оплаты.",
                    created_at=now,
                    updated_at=now,
                )
            )
            issue.audits.append(
                QuickRestoImportIssueAudit(
                    actor_user_id=user.id,
                    sync_run_id=run.id,
                    event_type="OPENED",
                    to_status="OPEN",
                    reason_code="MAPPING_REQUIRED",
                    correlation_id=issue.correlation_id,
                    metadata_json={"missing_payment_type_ids": [7]},
                    created_at=now,
                )
            )
            db.commit()

            db.refresh(issue)
            self.assertEqual(issue.status, "OPEN")
            self.assertEqual(issue.details_json, {"missing_payment_type_ids": [7]})
            self.assertEqual(len(issue.shifts), 1)
            self.assertEqual(issue.shifts[0].source_snapshot_id, snapshot.id)
            self.assertEqual(len(issue.audits), 1)
            self.assertTrue(user.notify_integrations)


if __name__ == "__main__":
    unittest.main()
