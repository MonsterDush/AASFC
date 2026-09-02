from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.finance_entry import FinanceEntry
from app.models.payment_method import PaymentMethod
from app.models.payroll_run import PayrollRun
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
from app.services.integrations.quickresto_scope_reconciliation import (
    QuickRestoSyncError,
    confirm_quickresto_historical_scope_reconciliation,
    preview_quickresto_historical_scope_reconciliation,
)
from app.services.integrations.quickresto_sync import (
    _rebuild_imported_report_keys,
    _sync_previous_scope_mismatch_issue,
)


TARGET_DATE = date(2030, 1, 15)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class QuickRestoScopePreviewTests(unittest.TestCase):
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
                FinanceEntry.__table__,
                PayrollRun.__table__,
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
            ],
        )
        self.db = Session(self.engine)
        self.db.add(User(id=1, system_role="NONE"))
        self.db.add(Venue(id=1, name="Source"))
        payment = PaymentMethod(venue_id=1, code="cash", title="Наличные", is_active=True, sort_order=1)
        department = Department(venue_id=1, code="bar", title="Бар", is_active=True, sort_order=1)
        self.db.add_all([payment, department])
        self.db.flush()
        self.connection = QuickRestoConnection(
            venue_id=1,
            cloud="preview-test",
            api_login_encrypted="v1:unused",
            api_password_encrypted="v1:unused",
            is_active=True,
            auto_sync_enabled=False,
            report_import_mode="DRAFT",
            created_by_user_id=1,
            external_venue_id=501,
            external_venue_name="Source QR",
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
        self.shifts = [self._add_shift("legacy-1", 1, 100), self._add_shift("legacy-2", 2, 200)]
        run = QuickRestoSyncRun(
            connection_id=self.connection.id,
            requested_by_user_id=1,
            trigger="TEST",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(run)
        self.db.flush()
        _rebuild_imported_report_keys(
            self.db,
            connection=self.connection,
            run=run,
            actor_user_id=1,
            affected_keys={(TARGET_DATE, "DAY")},
        )
        run.status = "SUCCEEDED"
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.issue = _sync_previous_scope_mismatch_issue(
            self.db,
            connection=self.connection,
            run=run,
            mismatch_external_ids={"legacy-1", "legacy-2"},
        )
        self.db.commit()

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
            "local_closed_at": f"{TARGET_DATE.isoformat()}T18:00:00",
            "payments_external": {"1": revenue},
            "departments_external": {"1": revenue},
            "writeoff_departments_external": {},
            "revenue_total": revenue,
            "writeoff_total": 0,
            "discount_total": 0,
            "orders_count": 1,
            "returned_orders_count": 0,
            "payload_hash": (str(external_pk) * 64)[:64],
        }
        row = QuickRestoShiftImport(
            connection_id=self.connection.id,
            external_shift_id=external_id,
            external_shift_pk=external_pk,
            source_version=1,
            business_date=TARGET_DATE,
            shift_slot="DAY",
            local_closed_at=datetime(2030, 1, 15, 18, 0),
            payload_hash=normalized["payload_hash"],
            normalized_json=normalized,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _decisions(self) -> dict[int, str]:
        return {
            int(self.shifts[0].id): "KEEP_CURRENT",
            int(self.shifts[1].id): "EXCLUDE_CURRENT",
        }

    def test_preview_is_read_only_and_confirm_applies_exact_plan(self):
        preview = preview_quickresto_historical_scope_reconciliation(
            self.db,
            connection=self.connection,
            issue_id=int(self.issue.id),
            decisions=self._decisions(),
            note="Проверенный перенос области.",
            requested_by_user_id=1,
            allowed_target_venue_ids=set(),
        )
        self.assertTrue(preview["requires_explicit_confirmation"])
        self.assertEqual(preview["summary"]["shifts_kept"], 1)
        self.assertEqual(preview["summary"]["shifts_excluded"], 1)
        self.assertEqual(preview["summary"]["revenue_delta"], -200)
        self.assertEqual(self.db.execute(select(DailyReport)).scalar_one().revenue_total, 300)
        self.assertTrue(
            all(self.db.get(QuickRestoShiftImport, row.id).scope_resolution_action is None for row in self.shifts)
        )

        run = confirm_quickresto_historical_scope_reconciliation(
            self.db,
            connection=self.connection,
            issue_id=int(self.issue.id),
            decisions=self._decisions(),
            note="Проверенный перенос области.",
            preview_token=preview["preview_token"],
            requested_by_user_id=1,
            allowed_target_venue_ids=set(),
        )
        self.assertEqual(run.status, "SUCCEEDED")
        self.assertEqual(run.summary_json["plan_hash"], preview["plan_hash"])
        self.assertEqual(self.db.execute(select(DailyReport)).scalar_one().revenue_total, 100)
        self.assertEqual(self.db.get(QuickRestoImportIssue, self.issue.id).status, "RESOLVED")

    def test_confirm_rejects_report_change_after_preview(self):
        preview = preview_quickresto_historical_scope_reconciliation(
            self.db,
            connection=self.connection,
            issue_id=int(self.issue.id),
            decisions=self._decisions(),
            note="Проверяем state hash.",
            requested_by_user_id=1,
            allowed_target_venue_ids=set(),
        )
        report = self.db.execute(select(DailyReport)).scalar_one()
        report.revenue_total = 999
        report.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        with self.assertRaises(QuickRestoSyncError):
            confirm_quickresto_historical_scope_reconciliation(
                self.db,
                connection=self.connection,
                issue_id=int(self.issue.id),
                decisions=self._decisions(),
                note="Проверяем state hash.",
                preview_token=preview["preview_token"],
                requested_by_user_id=1,
                allowed_target_venue_ids=set(),
            )
        self.assertEqual(self.db.get(DailyReport, report.id).revenue_total, 999)
        self.assertTrue(
            all(self.db.get(QuickRestoShiftImport, row.id).scope_resolution_action is None for row in self.shifts)
        )

    def test_confirm_rejects_token_when_decisions_change(self):
        preview = preview_quickresto_historical_scope_reconciliation(
            self.db,
            connection=self.connection,
            issue_id=int(self.issue.id),
            decisions=self._decisions(),
            note="Исходный набор решений.",
            requested_by_user_id=1,
            allowed_target_venue_ids=set(),
        )
        changed = {int(row.id): "KEEP_CURRENT" for row in self.shifts}
        with self.assertRaises(QuickRestoSyncError):
            confirm_quickresto_historical_scope_reconciliation(
                self.db,
                connection=self.connection,
                issue_id=int(self.issue.id),
                decisions=changed,
                note="Исходный набор решений.",
                preview_token=preview["preview_token"],
                requested_by_user_id=1,
                allowed_target_venue_ids=set(),
            )

    def test_move_clears_previous_target_exclusion_and_rebuilds_both_venues(self):
        self.db.add(Venue(id=2, name="Target"))
        target_payment = PaymentMethod(venue_id=2, code="cash", title="Наличные", is_active=True, sort_order=1)
        target_department = Department(venue_id=2, code="bar", title="Бар", is_active=True, sort_order=1)
        self.db.add_all([target_payment, target_department])
        self.db.flush()
        target = QuickRestoConnection(
            venue_id=2,
            cloud=self.connection.cloud,
            api_login_encrypted="v1:unused",
            api_password_encrypted="v1:unused",
            is_active=True,
            auto_sync_enabled=False,
            report_import_mode="DRAFT",
            created_by_user_id=1,
            external_venue_id=777,
            external_venue_name="Target QR",
            scope_status="READY",
            scope_generation=4,
        )
        self.db.add(target)
        self.db.flush()
        self.db.add_all(
            [
                QuickRestoPaymentMapping(
                    connection_id=target.id,
                    external_id=1,
                    external_name="Наличные",
                    operation_type="payment",
                    payment_method_id=target_payment.id,
                    excluded_from_revenue=False,
                    is_applicable=True,
                    is_available=True,
                ),
                QuickRestoDepartmentMapping(
                    connection_id=target.id,
                    external_id=1,
                    external_name="Бар",
                    department_id=target_department.id,
                ),
            ]
        )
        source_shift = self.shifts[1]
        target_shift = QuickRestoShiftImport(
            connection_id=target.id,
            external_shift_id=source_shift.external_shift_id,
            external_shift_pk=source_shift.external_shift_pk,
            source_version=source_shift.source_version,
            business_date=source_shift.business_date,
            shift_slot=source_shift.shift_slot,
            local_closed_at=source_shift.local_closed_at,
            payload_hash=source_shift.payload_hash,
            normalized_json=dict(source_shift.normalized_json),
            scope_resolution_action="EXCLUDE_CURRENT",
            scope_resolution_generation=4,
            scope_resolved_by_user_id=1,
            scope_resolved_at=datetime.now(timezone.utc),
            scope_resolution_note="Старое исключение target",
        )
        self.db.add(target_shift)
        snapshot = QuickRestoSourceSnapshot(
            connection_id=self.connection.id,
            source_fingerprint="a" * 64,
            payload_hash="b" * 64,
            encrypted_payload="v1:test-fixture",
            encryption_key_version="v1",
            external_shift_id=source_shift.external_shift_id,
            external_shift_pk=source_shift.external_shift_pk,
            source_version=source_shift.source_version,
            business_date=source_shift.business_date,
            shift_slot=source_shift.shift_slot,
            local_closed_at=source_shift.local_closed_at,
            retention_expires_at=datetime(2031, 1, 1, tzinfo=timezone.utc),
        )
        self.db.add(snapshot)
        self.db.flush()
        issue_item = self.db.execute(
            select(QuickRestoImportIssueShift).where(
                QuickRestoImportIssueShift.issue_id == self.issue.id,
                QuickRestoImportIssueShift.shift_import_id == source_shift.id,
            )
        ).scalar_one()
        issue_item.source_snapshot_id = snapshot.id
        self.db.commit()

        decisions = {
            int(self.shifts[0].id): "KEEP_CURRENT",
            int(source_shift.id): "MOVE_TO_CONNECTED",
        }
        normalized_target = dict(source_shift.normalized_json)
        with (
            patch(
                "app.services.integrations.quickresto_scope_reconciliation._matching_move_destinations",
                return_value=[target],
            ),
            patch(
                "app.services.integrations.quickresto_scope_reconciliation.open_source_snapshot",
                return_value={"shift": {}, "orders": []},
            ),
            patch(
                "app.services.integrations.quickresto_scope_reconciliation._target_normalized_payload",
                return_value=normalized_target,
            ),
        ):
            preview = preview_quickresto_historical_scope_reconciliation(
                self.db,
                connection=self.connection,
                issue_id=int(self.issue.id),
                decisions=decisions,
                note="Переносим смену во второе подключение.",
                requested_by_user_id=1,
                allowed_target_venue_ids={2},
            )
            self.assertEqual(preview["summary"]["shifts_moved"], 1)
            moved_preview = next(row for row in preview["shifts"] if row["action"] == "MOVE_TO_CONNECTED")
            self.assertEqual(moved_preview["target_state_before"]["scope_resolution_action"], "EXCLUDE_CURRENT")

            confirm_quickresto_historical_scope_reconciliation(
                self.db,
                connection=self.connection,
                issue_id=int(self.issue.id),
                decisions=decisions,
                note="Переносим смену во второе подключение.",
                preview_token=preview["preview_token"],
                requested_by_user_id=1,
                allowed_target_venue_ids={2},
            )

        self.db.refresh(source_shift)
        self.db.refresh(target_shift)
        self.assertEqual(source_shift.scope_resolution_action, "MOVE_TO_CONNECTED")
        self.assertIsNone(source_shift.daily_report_id)
        self.assertIsNone(target_shift.scope_resolution_action)
        self.assertIsNone(target_shift.scope_resolution_generation)
        self.assertIsNotNone(target_shift.daily_report_id)
        source_report = self.db.execute(select(DailyReport).where(DailyReport.venue_id == 1)).scalar_one()
        target_report = self.db.execute(select(DailyReport).where(DailyReport.venue_id == 2)).scalar_one()
        self.assertEqual(source_report.revenue_total, 100)
        self.assertEqual(target_report.revenue_total, 200)


if __name__ == "__main__":
    unittest.main()
