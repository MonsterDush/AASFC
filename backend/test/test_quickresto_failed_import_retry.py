from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
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
from app.models.notification_job import NotificationJob
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_external_venue import QuickRestoExternalVenue
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_audit import QuickRestoImportIssueAudit
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_sale_place_scope import QuickRestoSalePlaceScope
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.quickresto_store_scope import QuickRestoStoreScope
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations import credentials
from app.services.integrations.quickresto_issues import transition_issue
from app.services.integrations.quickresto_sync import (
    retry_quickresto_import_issue,
    sync_quickresto_connection,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class CountingQuickRestoClient:
    def __init__(self) -> None:
        self.calls = 0
        self.shift = {
            "id": 101,
            "frontId": "retry-shift-101",
            "version": 1,
            "status": "CLOSED",
            "localOpenedTime": "2030-01-15T10:00:00",
            "localClosedTime": "2030-01-15T18:00:00",
            "ordersCount": 1,
            "returnOrdersCount": 0,
            "totalCash": 0,
            "totalCard": 100.75,
            "totalBonuses": 0,
            "totalReturnCash": 0,
            "totalReturnCard": 0,
            "totalReturnBonuses": 0,
            "writeOffTotalCash": 0,
            "writeOffTotalCard": 0,
            "writeOffTotalBonuses": 0,
            "tableScheme": {"id": 501, "name": "Тестовое заведение"},
            "salePlace": {"id": 601, "title": "Основная касса"},
            "createTerminalSalePlace": {"id": 601, "title": "Основная касса"},
        }
        self.order = {
            "id": 201,
            "version": 1,
            "shiftId": "retry-shift-101",
            "returned": False,
            "frontTotalPrice": 100.75,
            "frontTotalAbsoluteDiscount": 0,
            "payments": [
                {
                    "amount": 100.75,
                    "paymentType": {"id": 1, "operationType": "payment"},
                }
            ],
            "orderItemList": [
                {
                    "amount": 1,
                    "totalPrice": 100.75,
                    "totalAbsoluteDiscount": 0,
                    "totalAbsoluteCharge": 0,
                    "product": {"id": 11, "parentId": 6},
                }
            ],
        }

    def list_all_objects(self, *, module_name, class_name):
        del module_name
        self.calls += 1
        if class_name.endswith("PaymentType"):
            return [
                {
                    "id": 1,
                    "name": "Карта",
                    "operationType": "payment",
                    "allowedSalePlacesWeb": [],
                }
            ]
        if class_name.endswith("DishCategory"):
            return [{"id": 6, "name": "Бар"}]
        if class_name.endswith("Shift"):
            return [deepcopy(self.shift)]
        if class_name.endswith("OrderInfo"):
            return [deepcopy(self.order)]
        if class_name.endswith("TableScheme"):
            return [{"id": 501, "name": "Тестовое заведение", "address": {}}]
        if class_name.endswith("SalePlace"):
            return [
                {
                    "id": 601,
                    "title": "Основная касса",
                    "tableScheme": {"id": 501},
                    "defaultCookingPlace": {"id": 701},
                }
            ]
        if class_name.endswith("CookingPlace"):
            return [{"id": 701, "title": "Основное производство", "store": {"id": 801}}]
        if class_name.endswith("Store"):
            return [{"id": 801, "title": "Основной склад"}]
        raise AssertionError(f"Unexpected QuickResto class: {class_name}")

    def read_object(self, *, module_name, class_name, object_id):
        del module_name, class_name
        self.calls += 1
        self.assert_object_id = int(object_id)
        return deepcopy(self.order)


class QuickRestoFailedImportRetryTests(unittest.TestCase):
    def test_mapping_failure_is_durable_atomic_and_retries_without_remote_api(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Venue.__table__,
                PaymentMethod.__table__,
                Department.__table__,
                DailyReport.__table__,
                DailyReportValue.__table__,
                QuickRestoConnection.__table__,
                QuickRestoExternalVenue.__table__,
                QuickRestoSalePlaceScope.__table__,
                QuickRestoStoreScope.__table__,
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
        client = CountingQuickRestoClient()
        with (
            Session(engine) as db,
            patch.object(
                credentials.settings,
                "INTEGRATION_ENCRYPTION_KEY",
                "s" * 48,
            ),
        ):
            db.add(User(id=1, system_role="NONE"))
            db.add(Venue(id=1, name="QuickResto retry test"))
            # Duplicate active titles deliberately prevent an unsafe automatic
            # choice while also preventing creation of a third catalog item.
            payment_a = PaymentMethod(
                venue_id=1,
                code="card-a",
                title="Карта",
                is_active=True,
                sort_order=1,
            )
            payment_b = PaymentMethod(
                venue_id=1,
                code="card-b",
                title="Карта",
                is_active=True,
                sort_order=2,
            )
            department = Department(
                venue_id=1,
                code="bar",
                title="Бар",
                is_active=True,
                sort_order=1,
            )
            db.add_all([payment_a, payment_b, department])
            connection = QuickRestoConnection(
                venue_id=1,
                cloud="fixture",
                api_login_encrypted="v1:unused",
                api_password_encrypted="v1:unused",
                is_active=True,
                report_import_mode="DRAFT",
                business_day_cutoff_hour=0,
                sync_from_date=date(2030, 1, 15),
                created_by_user_id=1,
                external_venue_id=501,
                external_venue_name="Тестовое заведение",
                scope_status="READY",
            )
            db.add(connection)
            db.flush()
            db.add(
                QuickRestoSalePlaceScope(
                    connection_id=connection.id,
                    external_id=601,
                    external_name="Основная касса",
                    external_venue_id=501,
                    default_cooking_place_id=701,
                    is_selected=True,
                    is_confirmed=True,
                    is_available=True,
                    last_seen_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            db.refresh(connection)

            first = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=1,
                trigger="TEST",
                client=client,
            )

            self.assertEqual(first.status, "PARTIAL")
            self.assertEqual(first.shifts_imported, 0)
            self.assertEqual(db.execute(select(DailyReport)).scalars().all(), [])
            self.assertEqual(db.execute(select(QuickRestoShiftImport)).scalars().all(), [])
            snapshot = db.execute(select(QuickRestoSourceSnapshot)).scalar_one()
            self.assertNotIn("retry-shift-101", snapshot.encrypted_payload)
            issue = db.execute(select(QuickRestoImportIssue)).scalar_one()
            self.assertEqual(issue.status, "OPEN")
            self.assertEqual(issue.error_code, "MAPPING_INCOMPLETE")
            self.assertEqual(issue.details_json["missing_payment_type_ids"], [1])
            self.assertEqual(len(issue.shifts), 1)
            self.assertEqual(issue.shifts[0].source_snapshot_id, snapshot.id)

            initial_attempt_count = issue.attempt_count
            transition_issue(
                db,
                issue=issue,
                status="IGNORED",
                event_type="USER_IGNORED",
                actor_user_id=1,
                resolution_code="USER_IGNORED",
                resolution_note="Проверено вручную, пока не импортировать.",
            )
            db.commit()

            unchanged = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=1,
                trigger="TEST",
                client=client,
            )
            self.assertEqual(unchanged.status, "SUCCEEDED")
            self.assertEqual(unchanged.summary_json["ignored_groups"], 1)
            self.assertEqual(unchanged.shifts_imported, 0)
            db.refresh(issue)
            self.assertEqual(issue.status, "IGNORED")
            self.assertEqual(issue.attempt_count, initial_attempt_count)
            self.assertEqual(db.execute(select(DailyReport)).scalars().all(), [])

            # A changed remote payload invalidates the explicit ignore decision
            # and must reopen the durable issue instead of disappearing.
            client.shift["totalCard"] = 120.25
            client.order["frontTotalPrice"] = 120.25
            client.order["payments"][0]["amount"] = 120.25
            client.order["orderItemList"][0]["totalPrice"] = 120.25
            changed = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=1,
                trigger="TEST",
                client=client,
            )
            self.assertEqual(changed.status, "PARTIAL")
            db.refresh(issue)
            self.assertEqual(issue.status, "OPEN")
            self.assertEqual(issue.generation, 2)
            self.assertEqual(issue.attempt_count, initial_attempt_count + 1)
            remote_calls_before_retry = client.calls

            mapping = db.execute(select(QuickRestoPaymentMapping)).scalar_one()
            mapping.payment_method_id = payment_a.id
            stale_at = datetime.now(timezone.utc) - timedelta(minutes=31)
            stale_run = QuickRestoSyncRun(
                connection_id=connection.id,
                requested_by_user_id=1,
                trigger="ISSUE_RETRY",
                status="RUNNING",
                started_at=stale_at,
            )
            db.add(stale_run)
            db.flush()
            transition_issue(
                db,
                issue=issue,
                status="PROCESSING",
                event_type="USER_RETRY_STARTED",
                actor_user_id=1,
                sync_run_id=int(stale_run.id),
            )
            issue.processing_started_at = stale_at
            connection.last_sync_status = "RUNNING"
            connection.last_sync_started_at = stale_at
            db.commit()
            retried = retry_quickresto_import_issue(
                db,
                connection=connection,
                issue_id=int(issue.id),
                requested_by_user_id=1,
            )

            self.assertEqual(client.calls, remote_calls_before_retry)
            self.assertEqual(retried.status, "SUCCEEDED")
            db.refresh(stale_run)
            self.assertEqual(stale_run.status, "FAILED")
            self.assertIn("автоматически восстановлен", stale_run.error_message)
            report = db.execute(select(DailyReport)).scalar_one()
            self.assertEqual(report.status, "DRAFT")
            self.assertEqual(report.revenue_total, 120)
            self.assertEqual(db.execute(select(QuickRestoShiftImport)).scalar_one().daily_report_id, report.id)
            db.refresh(issue)
            self.assertEqual(issue.status, "RESOLVED")

            # An unexpected report-writer defect must roll back the whole
            # report group, persist a retryable issue with its source snapshot,
            # and report the defect to Sentry instead of losing the shift.
            client.shift["totalCard"] = 130.25
            client.order["frontTotalPrice"] = 130.25
            client.order["payments"][0]["amount"] = 130.25
            client.order["orderItemList"][0]["totalPrice"] = 130.25
            with (
                patch(
                    "app.services.integrations.quickresto_sync._upsert_draft_report",
                    side_effect=RuntimeError("unexpected report writer failure"),
                ),
                patch("sentry_sdk.capture_exception", return_value="qr-runtime-correlation") as capture,
            ):
                internal_failure = sync_quickresto_connection(
                    db,
                    connection=connection,
                    requested_by_user_id=1,
                    trigger="TEST",
                    client=client,
                )

            self.assertEqual(internal_failure.status, "PARTIAL")
            capture.assert_called_once()
            db.refresh(report)
            self.assertEqual(report.revenue_total, 120)
            imported_shift = db.execute(select(QuickRestoShiftImport)).scalar_one()
            self.assertEqual(imported_shift.normalized_json["revenue_total_minor"], 12025)
            db.refresh(issue)
            self.assertEqual(issue.status, "OPEN")
            self.assertEqual(issue.error_code, "INTERNAL_ERROR")
            self.assertEqual(issue.generation, 3)
            self.assertEqual(len(issue.shifts), 1)
            remote_calls_before_internal_retry = client.calls

            recovered = retry_quickresto_import_issue(
                db,
                connection=connection,
                issue_id=int(issue.id),
                requested_by_user_id=1,
            )
            self.assertEqual(client.calls, remote_calls_before_internal_retry)
            self.assertEqual(recovered.status, "SUCCEEDED")
            db.refresh(report)
            self.assertEqual(report.revenue_total, 130)
            db.refresh(issue)
            self.assertEqual(issue.status, "RESOLVED")
            self.assertEqual(len(db.execute(select(NotificationJob)).scalars().all()), 5)

        engine.dispose()


if __name__ == "__main__":
    unittest.main()
