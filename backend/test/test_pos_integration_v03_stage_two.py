from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register the complete metadata graph
from app.core.config import settings
from app.core.db import Base
from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.base.dto import ProviderRecord
from app.integrations.base.errors import ProviderAuthenticationError, ProviderValidationError
from app.integrations.canonical.report_projector import ReportProjector, ShadowProjectionCandidate
from app.integrations.providers.quickresto.canonical_sync import (
    ensure_quickresto_import_job,
    ensure_quickresto_integration_connection,
)
from app.integrations.providers.quickresto.provider import QuickRestoProviderAdapter
from app.integrations.raw.storage import load_raw_payload, record_raw_object
from app.integrations.registry import provider_registry
from app.models.daily_report import DailyReport
from app.models.department import Department
from app.models.integration_connection import IntegrationConnection
from app.models.integration_import_batch import IntegrationImportBatch
from app.models.integration_import_chunk import IntegrationImportChunk
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_sync_job import IntegrationSyncJob
from app.models.integration_sync_run import IntegrationSyncRun
from app.models.payment_method import PaymentMethod
from app.models.pos_canonical import POSBusinessShift, POSOrder, POSOrderItem, POSPayment
from app.models.pos_report_projection import POSReportProjection
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_batch import QuickRestoImportBatch
from app.models.quickresto_external_venue import QuickRestoExternalVenue
from app.models.quickresto_sale_place_scope import QuickRestoSalePlaceScope
from app.models.quickresto_store_scope import QuickRestoStoreScope
from app.models.report_value_contribution import ReportValueContribution
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations.quickresto_import_batches import process_quickresto_import_batch
from app.services.integrations.quickresto_import_batches import retry_quickresto_import_batch
from app.services.integrations.quickresto import QuickRestoError, QuickRestoHTTPError
from app.services.integrations.quickresto_sync import sync_quickresto_connection


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


TARGET_DATE = date(2031, 2, 15)


class FixtureQuickRestoClient:
    def __init__(self, fixture: dict):
        self.fixture = deepcopy(fixture)
        self.orders_by_id = {int(row["id"]): row for row in self.fixture["orders"]}
        self._fallback_diagnostics = []

    def clear_fallback_diagnostics(self):
        self._fallback_diagnostics.clear()

    def fallback_diagnostics(self):
        return tuple(self._fallback_diagnostics)

    def record_business_date_filter_result(self, **_kwargs):
        return None

    def list_all_objects(self, *, module_name, class_name):
        del module_name
        if class_name.endswith("PaymentType"):
            rows = deepcopy(self.fixture["payment_types"])
            for row in rows:
                row["allowedSalePlacesWeb"] = [{"id": 601}]
            return rows
        if class_name.endswith("DishCategory"):
            return deepcopy(self.fixture["dish_categories"])
        if class_name.endswith("Shift"):
            return [deepcopy(self.fixture["shift"])]
        if class_name.endswith("OrderInfo"):
            return deepcopy(self.fixture["orders"])
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
            return [{"id": 701, "title": "Кухня", "store": {"id": 801}}]
        if class_name.endswith("Store"):
            return [{"id": 801, "title": "Основной склад"}]
        raise AssertionError(class_name)

    def read_object(self, *, module_name, class_name, object_id):
        del module_name
        if class_name.endswith("DishCategory"):
            return next(row for row in self.fixture["dish_categories"] if int(row["id"]) == int(object_id))
        return deepcopy(self.orders_by_id[int(object_id)])


class ProbeClient:
    class Config:
        timeout_seconds = 20

    config = Config()

    def __init__(self):
        self._fallback = []

    def list_objects(self, **_kwargs):
        return []

    def fallback_diagnostics(self):
        return tuple(self._fallback)

    def close(self):
        return None


class FailingShiftClient(FixtureQuickRestoClient):
    def list_all_objects(self, *, module_name, class_name):
        if class_name.endswith("Shift"):
            raise QuickRestoError("temporary shift fetch failure")
        return super().list_all_objects(module_name=module_name, class_name=class_name)


class POSIntegrationStageTwoTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "basic_closed_shift.json"
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shift = self.fixture["shift"]
        shift.update(
            {
                "version": 3,
                "localOpenedTime": f"{TARGET_DATE.isoformat()}T09:00:00",
                "localClosedTime": f"{TARGET_DATE.isoformat()}T23:00:00",
                "closed": f"{TARGET_DATE.isoformat()}T20:00:00Z",
                "tableScheme": {"id": 501, "name": "Тестовое заведение"},
                "salePlace": {"id": 601, "title": "Основная касса"},
                "createTerminalSalePlace": {"id": 601, "title": "Основная касса"},
            }
        )
        for order in self.fixture["orders"]:
            order["version"] = 1

        self.db.add_all(
            [
                User(id=1, system_role="NONE"),
                Venue(id=1, name="Stage two", timezone="Europe/Moscow"),
                PaymentMethod(id=1, venue_id=1, code="cash", title="Наличные"),
                PaymentMethod(id=2, venue_id=1, code="cashless", title="Безналичные"),
                Department(id=6, venue_id=1, code="hookah", title="Кальянный бар"),
                Department(id=7, venue_id=1, code="bar", title="Бар"),
            ]
        )
        self.db.flush()
        self.connection = QuickRestoConnection(
            id=1,
            venue_id=1,
            cloud="test",
            api_login_encrypted="unused",
            api_password_encrypted="unused",
            external_venue_id=501,
            external_venue_name="Тестовое заведение",
            scope_status="READY",
            is_active=True,
            report_import_mode="DRAFT",
            business_day_cutoff_hour=5,
            sync_from_date=TARGET_DATE,
            created_by_user_id=1,
        )
        self.db.add(self.connection)
        self.db.flush()
        now = datetime.now(timezone.utc)
        self.db.add_all(
            [
                QuickRestoExternalVenue(
                    connection_id=1,
                    external_id=501,
                    external_name="Тестовое заведение",
                    is_available=True,
                    last_seen_at=now,
                ),
                QuickRestoSalePlaceScope(
                    connection_id=1,
                    external_id=601,
                    external_name="Основная касса",
                    external_venue_id=501,
                    default_cooking_place_id=701,
                    is_selected=True,
                    is_confirmed=True,
                    is_available=True,
                    last_seen_at=now,
                ),
                QuickRestoStoreScope(
                    connection_id=1,
                    external_id=801,
                    external_name="Основной склад",
                    is_selected=True,
                    is_available=True,
                    last_seen_at=now,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _flags(self):
        return (
            patch.object(settings, "POS_INTEGRATION_PROVIDER_ROLLOUT", "QUICKRESTO"),
            patch.object(settings, "POS_INTEGRATION_SHADOW_WRITE_ENABLED", True),
            patch.object(settings, "POS_INTEGRATION_CANONICAL_READ_ENABLED", False),
            patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 48),
        )

    def _shadow_candidate(
        self,
        *,
        report_id: int,
        connection_id: int,
        sync_run_id: int,
        status: str,
        aggregate_hash: str,
    ) -> ShadowProjectionCandidate:
        return ShadowProjectionCandidate(
            daily_report_id=report_id,
            connection_id=connection_id,
            business_date=TARGET_DATE,
            shift_slot="DAY",
            sync_run_id=sync_run_id,
            status=status,
            aggregate_hash=aggregate_hash,
            canonical_coverage_hash="c" * 64,
            shift_count=1,
            mapping_version=1,
            policy_version=1,
            summary_json={"state": status.lower()},
            facts={
                "revenue_total": 100,
                "unallocated_revenue_total": 0,
                "writeoff_total": 0,
                "refund_total": 0,
                "discount_total": 0,
                "payments_internal": {1: 100},
                "departments_internal": {6: 100},
                "kpis_internal": {},
            },
        )

    def _shadow_projection_setup(self):
        canonical_connection = ensure_quickresto_integration_connection(
            self.db,
            connection=self.connection,
        )
        report = DailyReport(
            venue_id=1,
            date=TARGET_DATE,
            shift_slot="DAY",
            status="DRAFT",
            created_by_user_id=1,
        )
        sync_run = IntegrationSyncRun(
            connection_id=int(canonical_connection.id),
            capability="REPORT_FACTS",
            trigger="TEST",
            status="RUNNING",
        )
        self.db.add_all([report, sync_run])
        self.db.flush()
        return canonical_connection, report, sync_run

    def test_shadow_projection_updates_matched_to_mismatch(self):
        canonical_connection, report, sync_run = self._shadow_projection_setup()
        projector = ReportProjector()

        first = projector.persist_shadow(
            self.db,
            candidate=self._shadow_candidate(
                report_id=int(report.id),
                connection_id=int(canonical_connection.id),
                sync_run_id=int(sync_run.id),
                status="MATCHED",
                aggregate_hash="a" * 64,
            ),
        )
        self.assertTrue(first.updated)
        self.assertEqual(first.projection.status, "MATCHED")
        self.assertEqual(first.projection.aggregate_hash, "a" * 64)

        second = projector.persist_shadow(
            self.db,
            candidate=self._shadow_candidate(
                report_id=int(report.id),
                connection_id=int(canonical_connection.id),
                sync_run_id=int(sync_run.id),
                status="MISMATCH",
                aggregate_hash="b" * 64,
            ),
        )

        self.assertTrue(second.updated)
        self.assertEqual(second.projection.status, "MISMATCH")
        self.assertEqual(second.projection.aggregate_hash, "b" * 64)
        self.assertEqual(second.projection.summary_json, {"state": "mismatch"})

    def test_shadow_projection_preserves_matched_on_failed_candidate(self):
        canonical_connection, report, sync_run = self._shadow_projection_setup()
        projector = ReportProjector()

        first = projector.persist_shadow(
            self.db,
            candidate=self._shadow_candidate(
                report_id=int(report.id),
                connection_id=int(canonical_connection.id),
                sync_run_id=int(sync_run.id),
                status="MATCHED",
                aggregate_hash="a" * 64,
            ),
        )
        self.assertTrue(first.updated)
        self.assertEqual(first.projection.status, "MATCHED")

        second = projector.persist_shadow(
            self.db,
            candidate=self._shadow_candidate(
                report_id=int(report.id),
                connection_id=int(canonical_connection.id),
                sync_run_id=int(sync_run.id),
                status="FAILED",
                aggregate_hash="f" * 64,
            ),
        )

        self.assertFalse(second.updated)
        self.assertEqual(second.projection.status, "MATCHED")
        self.assertEqual(second.projection.aggregate_hash, "a" * 64)
        self.assertEqual(second.projection.summary_json, {"state": "matched"})

    def test_adapter_marks_supported_only_after_real_list_probe(self):
        self.assertIn("QUICKRESTO", provider_registry.registered_providers())
        adapter = QuickRestoProviderAdapter(ProbeClient())
        capabilities = adapter.get_capabilities()
        self.assertEqual(capabilities[Capability.BUSINESS_SHIFTS].state, CapabilityState.SUPPORTED)
        self.assertTrue(capabilities[Capability.BUSINESS_SHIFTS].evidence_summary)
        self.assertEqual(capabilities[Capability.EMPLOYEES].state, CapabilityState.UNAVAILABLE)
        self.assertIsInstance(
            adapter._translate_error(QuickRestoHTTPError("forbidden", status_code=403)),
            ProviderAuthenticationError,
        )
        self.assertIsInstance(
            adapter._translate_error(QuickRestoHTTPError("bad request", status_code=400)),
            ProviderValidationError,
        )

    def test_raw_storage_preserves_distinct_source_versions_for_replay(self):
        flag_patches = self._flags()
        with flag_patches[0], flag_patches[3]:
            canonical_connection = ensure_quickresto_integration_connection(
                self.db,
                connection=self.connection,
            )
            first = record_raw_object(
                self.db,
                connection_id=int(canonical_connection.id),
                entity_type="ORDER",
                record=ProviderRecord(external_id="order-1", source_version="1", payload={"total": "10.00"}),
                allowed_fields={"total"},
            )
            second = record_raw_object(
                self.db,
                connection_id=int(canonical_connection.id),
                entity_type="ORDER",
                record=ProviderRecord(external_id="order-1", source_version="2", payload={"total": "12.00"}),
                allowed_fields={"total"},
            )
            repeated = record_raw_object(
                self.db,
                connection_id=int(canonical_connection.id),
                entity_type="ORDER",
                record=ProviderRecord(external_id="order-1", source_version="2", payload={"total": "12.00"}),
                allowed_fields={"total"},
            )

            self.assertNotEqual(first.id, second.id)
            self.assertEqual(second.id, repeated.id)
            self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 2)
            self.assertEqual(load_raw_payload(first), {"total": "10.00"})
            self.assertEqual(load_raw_payload(second), {"total": "12.00"})

    def test_monthly_batch_reuses_one_canonical_job(self):
        batch = QuickRestoImportBatch(
            connection_id=1,
            requested_by_user_id=1,
            trigger="FULL",
            force_full=True,
            status="PENDING",
            period_start=TARGET_DATE,
            period_end_exclusive=date(2031, 5, 1),
            next_period_start=TARGET_DATE,
            total_periods=3,
        )
        self.db.add(batch)
        self.db.flush()
        with self._flags()[0], self._flags()[1], self._flags()[2]:
            first = ensure_quickresto_import_job(self.db, connection=self.connection, batch=batch)
            second = ensure_quickresto_import_job(self.db, connection=self.connection, batch=batch)
        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.job_payload_json["queue_owner"], "quickresto_import_batches")
        self.assertEqual(self.db.scalar(select(func.count(IntegrationSyncJob.id))), 1)
        canonical_batch = self.db.scalar(select(IntegrationImportBatch))
        self.assertEqual(batch.integration_import_batch_id, canonical_batch.id)
        self.assertEqual(canonical_batch.sync_job_id, first.id)
        chunks = list(
            self.db.execute(select(IntegrationImportChunk).order_by(IntegrationImportChunk.sequence)).scalars()
        )
        self.assertEqual(
            [(row.period_start, row.period_end_exclusive) for row in chunks],
            [
                (date(2031, 2, 15), date(2031, 3, 1)),
                (date(2031, 3, 1), date(2031, 4, 1)),
                (date(2031, 4, 1), date(2031, 5, 1)),
            ],
        )

    def test_shadow_write_is_idempotent_and_does_not_switch_report_reads(self):
        client = FixtureQuickRestoClient(self.fixture)
        flag_patches = self._flags()
        with flag_patches[0], flag_patches[1], flag_patches[2], flag_patches[3]:
            first = sync_quickresto_connection(
                self.db,
                connection=self.connection,
                requested_by_user_id=1,
                trigger="TEST",
                client=client,
                force_full=True,
                period_start=TARGET_DATE,
                period_end_exclusive=date(2031, 2, 16),
            )
            counts_after_first = {
                model.__tablename__: self.db.scalar(select(func.count(model.id)))
                for model in (
                    IntegrationRawObject,
                    POSBusinessShift,
                    POSOrder,
                    POSOrderItem,
                    POSPayment,
                    POSReportProjection,
                )
            }
            pos_contributions_after_first = self.db.scalar(
                select(func.count(ReportValueContribution.id)).where(ReportValueContribution.source_type == "POS")
            )
            report = self.db.scalar(select(DailyReport).where(DailyReport.date == TARGET_DATE))
            self.db.add(
                ReportValueContribution(
                    report_id=int(report.id),
                    kind="KPI",
                    ref_id=999,
                    source_type="MANUAL",
                    source_id="test:manual-kpi",
                    value_numeric=7,
                    source_hash="a" * 64,
                )
            )
            self.db.commit()
            second = sync_quickresto_connection(
                self.db,
                connection=self.connection,
                requested_by_user_id=1,
                trigger="TEST",
                client=client,
                force_full=True,
                period_start=TARGET_DATE,
                period_end_exclusive=date(2031, 2, 16),
            )

        self.assertEqual(first.status, "SUCCEEDED", first.summary_json)
        self.assertEqual(second.status, "SUCCEEDED")
        self.assertEqual(first.summary_json["canonical"]["groups"][0]["status"], "MATCHED")
        self.assertEqual(
            counts_after_first,
            {
                model.__tablename__: self.db.scalar(select(func.count(model.id)))
                for model in (
                    IntegrationRawObject,
                    POSBusinessShift,
                    POSOrder,
                    POSOrderItem,
                    POSPayment,
                    POSReportProjection,
                )
            },
        )
        self.assertEqual(
            pos_contributions_after_first,
            self.db.scalar(
                select(func.count(ReportValueContribution.id)).where(ReportValueContribution.source_type == "POS")
            ),
        )
        manual_contribution = self.db.scalar(
            select(ReportValueContribution).where(ReportValueContribution.source_type == "MANUAL")
        )
        self.assertEqual(int(manual_contribution.value_numeric), 7)
        canonical_connection = self.db.scalar(select(IntegrationConnection))
        self.assertEqual(canonical_connection.read_mode, "LEGACY")
        self.assertFalse(settings.POS_INTEGRATION_CANONICAL_READ_ENABLED)
        self.assertIsNotNone(self.db.scalar(select(DailyReport).where(DailyReport.date == TARGET_DATE)))
        self.assertEqual(self.db.scalar(select(func.count(IntegrationSyncRun.id))), 2)

    def test_monthly_worker_persists_canonical_chunk_progress_and_provenance(self):
        batch = QuickRestoImportBatch(
            connection_id=1,
            requested_by_user_id=1,
            trigger="FULL",
            force_full=True,
            status="PENDING",
            period_start=TARGET_DATE,
            period_end_exclusive=date(2031, 2, 16),
            next_period_start=TARGET_DATE,
            total_periods=1,
            completed_periods=0,
            partial_periods=0,
            retry_count=0,
            summary_json={"totals": {}, "periods": [], "issue_ids": []},
        )
        self.db.add(batch)
        self.db.commit()

        flag_patches = self._flags()
        with flag_patches[0], flag_patches[1], flag_patches[2], flag_patches[3]:
            result = process_quickresto_import_batch(
                self.db,
                batch_id=int(batch.id),
                client=FixtureQuickRestoClient(self.fixture),
            )

        canonical_batch = self.db.get(IntegrationImportBatch, int(result.integration_import_batch_id))
        chunk = self.db.scalar(
            select(IntegrationImportChunk).where(IntegrationImportChunk.batch_id == int(canonical_batch.id))
        )
        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(canonical_batch.status, "SUCCEEDED")
        self.assertIsNone(canonical_batch.active_guard)
        self.assertEqual(canonical_batch.completed_chunks, 1)
        self.assertEqual(chunk.status, "SUCCEEDED")
        self.assertEqual(chunk.attempts, 1)
        self.assertEqual(chunk.sync_run_id, canonical_batch.last_sync_run_id)
        self.assertTrue(chunk.provenance_json["reconciliation_ids"])
        self.assertEqual(canonical_batch.sync_job.status, "SUCCEEDED")

    def test_failed_monthly_chunk_retries_the_exact_same_range(self):
        batch = QuickRestoImportBatch(
            connection_id=1,
            requested_by_user_id=1,
            trigger="FULL",
            force_full=True,
            status="PENDING",
            period_start=TARGET_DATE,
            period_end_exclusive=date(2031, 2, 16),
            next_period_start=TARGET_DATE,
            total_periods=1,
            completed_periods=0,
            partial_periods=0,
            retry_count=0,
            summary_json={"totals": {}, "periods": [], "issue_ids": []},
        )
        self.db.add(batch)
        self.db.commit()

        flag_patches = self._flags()
        with flag_patches[0], flag_patches[1], flag_patches[2], flag_patches[3]:
            failed = process_quickresto_import_batch(
                self.db,
                batch_id=int(batch.id),
                client=FailingShiftClient(self.fixture),
            )
            failed_chunk = self.db.scalar(select(IntegrationImportChunk))
            self.assertEqual(failed.status, "FAILED")
            self.assertEqual(failed.next_period_start, TARGET_DATE)
            self.assertEqual(failed_chunk.status, "FAILED")
            self.assertEqual(failed_chunk.attempts, 1)

            queued = retry_quickresto_import_batch(self.db, batch=failed)
            completed = process_quickresto_import_batch(
                self.db,
                batch_id=int(queued.id),
                client=FixtureQuickRestoClient(self.fixture),
            )

        chunk = self.db.get(IntegrationImportChunk, int(failed_chunk.id))
        canonical_batch = self.db.get(IntegrationImportBatch, int(completed.integration_import_batch_id))
        self.assertEqual(completed.status, "SUCCEEDED")
        self.assertEqual(chunk.period_start, TARGET_DATE)
        self.assertEqual(chunk.period_end_exclusive, date(2031, 2, 16))
        self.assertEqual(chunk.status, "SUCCEEDED")
        self.assertEqual(chunk.attempts, 2)
        self.assertEqual(canonical_batch.completed_chunks, 1)
        self.assertEqual(canonical_batch.retry_count, 1)


if __name__ == "__main__":
    unittest.main()
