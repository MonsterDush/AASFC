from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.daily_report import DailyReport
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.daily_report_audit import DailyReportAudit
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.notification_job import NotificationJob
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_audit import QuickRestoImportIssueAudit
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations.quickresto_issues import serialize_issue
from app.services.integrations.quickresto_sync import (
    QuickRestoSyncError,
    _rebuild_imported_report_keys,
    _sync_previous_scope_mismatch_issue,
    reconcile_quickresto_historical_scope_issue,
)


TARGET_DATE = date(2030, 1, 15)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class QuickRestoHistoricalScopeReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Venue.__table__,
                PaymentMethod.__table__,
                Department.__table__,
                DailyReport.__table__,
                DailyReportValue.__table__,
                DailyReportAttachment.__table__,
                DailyReportAudit.__table__,
                DailyReportTipAllocation.__table__,
                QuickRestoConnection.__table__,
                QuickRestoPaymentMapping.__table__,
                QuickRestoDepartmentMapping.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoShiftImport.__table__,
                QuickRestoReportImport.__table__,
                QuickRestoSourceSnapshot.__table__,
                QuickRestoImportIssue.__table__,
                QuickRestoImportIssueShift.__table__,
                QuickRestoImportIssueAudit.__table__,
                NotificationJob.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.add(User(id=1, system_role="NONE"))
        self.db.add(Venue(id=1, name="Historical scope test"))
        payment = PaymentMethod(
            venue_id=1,
            code="cash",
            title="Наличные",
            is_active=True,
            sort_order=1,
        )
        department = Department(
            venue_id=1,
            code="bar",
            title="Бар",
            is_active=True,
            sort_order=1,
        )
        self.db.add_all([payment, department])
        self.db.flush()
        self.connection = QuickRestoConnection(
            venue_id=1,
            cloud="historical",
            api_login_encrypted="v1:unused",
            api_password_encrypted="v1:unused",
            is_active=True,
            auto_sync_enabled=False,
            report_import_mode="DRAFT",
            created_by_user_id=1,
            external_venue_id=501,
            external_venue_name="Old venue",
            scope_status="READY",
            scope_generation=2,
        )
        self.db.add(self.connection)
        self.db.flush()
        self.db.add_all(
            [
                QuickRestoPaymentMapping(
                    connection_id=self.connection.id,
                    external_id=1,
                    external_name="Наличные",
                    operation_type="payment",
                    payment_method_id=payment.id,
                    excluded_from_revenue=False,
                    is_applicable=True,
                    is_available=True,
                ),
                QuickRestoDepartmentMapping(
                    connection_id=self.connection.id,
                    external_id=1,
                    external_name="Бар",
                    department_id=department.id,
                ),
            ]
        )
        self.db.flush()
        self.shifts = [self._add_shift("legacy-1", 1, 100), self._add_shift("legacy-2", 2, 200)]
        initial_run = QuickRestoSyncRun(
            connection_id=self.connection.id,
            requested_by_user_id=1,
            trigger="TEST",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(initial_run)
        self.db.flush()
        counts, report_ids = _rebuild_imported_report_keys(
            self.db,
            connection=self.connection,
            run=initial_run,
            actor_user_id=1,
            affected_keys={(TARGET_DATE, "DAY")},
        )
        self.assertEqual(counts["created"], 1)
        self.assertEqual(len(report_ids), 1)
        initial_run.status = "SUCCEEDED"
        initial_run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(self.connection)
        self.issue = _sync_previous_scope_mismatch_issue(
            self.db,
            connection=self.connection,
            run=initial_run,
            mismatch_external_ids={"legacy-1", "legacy-2"},
        )
        self.db.commit()
        self.db.refresh(self.issue)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_shift(self, external_id: str, external_pk: int, revenue: int) -> QuickRestoShiftImport:
        normalized = {
            "external_shift_id": external_id,
            "external_shift_pk": external_pk,
            "source_version": 1,
            "business_date": TARGET_DATE.isoformat(),
            "shift_slot": "DAY",
            "local_opened_at": f"{TARGET_DATE.isoformat()}T09:00:00",
            "local_closed_at": f"{TARGET_DATE.isoformat()}T18:00:00",
            "payments_external": {"1": revenue},
            "departments_external": {"1": revenue},
            "writeoff_departments_external": {},
            "revenue_total": revenue,
            "writeoff_total": 0,
            "discount_total": 0,
            "orders_count": 1,
            "returned_orders_count": 0,
        }
        row = QuickRestoShiftImport(
            connection_id=self.connection.id,
            external_shift_id=external_id,
            external_shift_pk=external_pk,
            source_version=1,
            business_date=TARGET_DATE,
            shift_slot="DAY",
            local_closed_at=datetime(2030, 1, 15, 18, 0),
            payload_hash=str(external_pk) * 64,
            normalized_json=normalized,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def test_issue_exposes_concrete_historical_shifts_and_atomic_decisions_rebuild_report(self):
        payload = serialize_issue(self.issue, include_shifts=True)
        self.assertTrue(payload["can_reconcile_scope"])
        self.assertFalse(payload["can_retry"])
        self.assertFalse(payload["can_ignore"])
        self.assertEqual({item["shift_import_id"] for item in payload["shifts"]}, {row.id for row in self.shifts})
        self.assertTrue(all(item["daily_report_id"] for item in payload["shifts"]))

        run = reconcile_quickresto_historical_scope_issue(
            self.db,
            connection=self.connection,
            issue_id=self.issue.id,
            decisions={
                self.shifts[0].id: "KEEP_CURRENT",
                self.shifts[1].id: "EXCLUDE_CURRENT",
            },
            note="Первая смена относится к заведению, вторая — к филиалу.",
            requested_by_user_id=1,
        )

        self.assertEqual(run.status, "SUCCEEDED")
        self.assertEqual(run.summary_json["shifts_kept"], 1)
        self.assertEqual(run.summary_json["shifts_excluded"], 1)
        report = self.db.execute(select(DailyReport)).scalar_one()
        source = self.db.execute(select(QuickRestoReportImport)).scalar_one()
        self.assertEqual(report.revenue_total, 100)
        self.assertEqual(source.shift_count, 1)
        self.db.refresh(self.shifts[0])
        self.db.refresh(self.shifts[1])
        self.assertEqual(self.shifts[0].scope_resolution_action, "KEEP_CURRENT")
        self.assertEqual(self.shifts[1].scope_resolution_action, "EXCLUDE_CURRENT")
        self.assertEqual(self.shifts[0].scope_resolution_generation, 2)
        self.assertIsNone(self.shifts[1].daily_report_id)
        self.db.refresh(self.issue)
        self.assertEqual(self.issue.status, "RESOLVED")

    def test_excluding_every_shift_removes_integration_owned_report(self):
        run = reconcile_quickresto_historical_scope_issue(
            self.db,
            connection=self.connection,
            issue_id=self.issue.id,
            decisions={row.id: "EXCLUDE_CURRENT" for row in self.shifts},
            note="Обе смены принадлежат другому заведению.",
            requested_by_user_id=1,
        )

        self.assertEqual(run.summary_json["reports_removed"], 1)
        self.assertIsNone(self.db.execute(select(DailyReport)).scalar_one_or_none())
        self.assertIsNone(self.db.execute(select(QuickRestoReportImport)).scalar_one_or_none())

    def test_manual_report_edit_rolls_back_all_shift_decisions(self):
        report = self.db.execute(select(DailyReport)).scalar_one()
        report.revenue_total = 999
        self.db.commit()

        with self.assertRaises(QuickRestoSyncError):
            reconcile_quickresto_historical_scope_issue(
                self.db,
                connection=self.connection,
                issue_id=self.issue.id,
                decisions={
                    self.shifts[0].id: "KEEP_CURRENT",
                    self.shifts[1].id: "EXCLUDE_CURRENT",
                },
                note="Проверяем безопасный откат.",
                requested_by_user_id=1,
            )

        for shift_id in (self.shifts[0].id, self.shifts[1].id):
            shift = self.db.get(QuickRestoShiftImport, shift_id)
            self.assertIsNone(shift.scope_resolution_action)
            self.assertIsNotNone(shift.daily_report_id)
        self.assertEqual(self.db.get(DailyReport, report.id).revenue_total, 999)
        self.assertEqual(self.db.get(QuickRestoImportIssue, self.issue.id).status, "OPEN")

    def test_recorded_decisions_are_not_reopened_by_the_same_scope_mismatch(self):
        reconcile_quickresto_historical_scope_issue(
            self.db,
            connection=self.connection,
            issue_id=self.issue.id,
            decisions={row.id: "KEEP_CURRENT" for row in self.shifts},
            note="Подтверждаем обе смены как исторические.",
            requested_by_user_id=1,
        )
        follow_up_run = QuickRestoSyncRun(
            connection_id=self.connection.id,
            requested_by_user_id=1,
            trigger="TEST",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(follow_up_run)
        self.db.flush()

        issue = _sync_previous_scope_mismatch_issue(
            self.db,
            connection=self.connection,
            run=follow_up_run,
            mismatch_external_ids={"legacy-1", "legacy-2"},
        )

        self.assertIsNone(issue)
        self.assertEqual(self.db.get(QuickRestoImportIssue, self.issue.id).status, "RESOLVED")

    def test_recorded_decisions_must_be_reviewed_again_for_a_new_scope_generation(self):
        reconcile_quickresto_historical_scope_issue(
            self.db,
            connection=self.connection,
            issue_id=self.issue.id,
            decisions={row.id: "KEEP_CURRENT" for row in self.shifts},
            note="Подтверждаем решения для второй версии области.",
            requested_by_user_id=1,
        )
        self.connection.scope_generation = 3
        self.db.commit()
        follow_up_run = QuickRestoSyncRun(
            connection_id=self.connection.id,
            requested_by_user_id=1,
            trigger="TEST",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(follow_up_run)
        self.db.flush()

        issue = _sync_previous_scope_mismatch_issue(
            self.db,
            connection=self.connection,
            run=follow_up_run,
            mismatch_external_ids={"legacy-1", "legacy-2"},
            scope_generation=3,
        )

        self.assertIsNotNone(issue)
        payload = serialize_issue(issue, include_shifts=True)
        self.assertEqual(payload["details"]["scope_generation"], 3)
        self.assertTrue(payload["can_reconcile_scope"])
        self.assertEqual(
            {item["scope_resolution_generation"] for item in payload["shifts"]},
            {2},
        )
