from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register complete metadata
from app.core.config import settings
from app.core.db import Base
from app.integrations.canonical.order_items import attribution_minor_for_item
from app.integrations.canonical.composite_payloads import normalize_iiko_composite, normalize_quickresto_composite
from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.base.dto import CanonicalDTO
from app.integrations.base.errors import ProviderCapabilityError
from app.integrations.providers.quickresto.provider import QuickRestoProviderAdapter
from app.integrations.quality import assess_capability_freshness, validate_and_quarantine, validate_canonical_dto
from app.models import (
    DailyReport,
    DailyReportValue,
    IntegrationCapabilityState,
    IntegrationConnection,
    IntegrationQuarantine,
    POSReportProjection,
    ReportValueContribution,
    User,
    Venue,
)
from app.services.integrations.report_facts import (
    MANUAL,
    POS_CANONICAL,
    load_report_facts,
    sync_manual_report_contributions,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pos"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class POSIntegrationStageThreeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all(
            [
                User(id=1, system_role="NONE"),
                Venue(id=1, name="Stage three", timezone="Europe/Moscow"),
            ]
        )
        self.db.flush()
        self.report = DailyReport(
            id=1,
            venue_id=1,
            date=date(2031, 3, 10),
            shift_slot="DAY",
            revenue_total=1_000,
            unallocated_revenue_total=100,
            status="CLOSED",
            created_by_user_id=1,
        )
        self.connection = IntegrationConnection(
            id=1,
            venue_id=1,
            provider="QUICKRESTO",
            status="ACTIVE",
            read_mode="LEGACY",
            shadow_sync_enabled=True,
            coverage_start=date(2031, 3, 1),
            coverage_end_exclusive=date(2031, 4, 1),
        )
        self.db.add_all([self.report, self.connection])
        self.db.flush()
        self.db.add(DailyReportValue(report_id=1, kind="DEPT", ref_id=10, value_numeric=900))
        self.db.flush()
        sync_manual_report_contributions(self.db, report=self.report)
        self.projection = POSReportProjection(
            daily_report_id=1,
            connection_id=1,
            business_date=self.report.date,
            shift_slot="DAY",
            aggregate_hash="a" * 64,
            mapping_version=1,
            policy_version=1,
            shift_count=1,
            canonical_coverage_hash="b" * 64,
            status="MATCHED",
            summary_json={},
        )
        self.db.add(self.projection)
        self.db.flush()
        self.db.add_all(
            [
                ReportValueContribution(
                    report_id=1,
                    kind="REVENUE",
                    ref_id=0,
                    source_type="POS",
                    source_id="projection:1:revenue",
                    value_numeric=Decimal("1200"),
                    source_hash="c" * 64,
                ),
                ReportValueContribution(
                    report_id=1,
                    kind="UNALLOCATED_REVENUE",
                    ref_id=0,
                    source_type="POS",
                    source_id="projection:1:unallocated",
                    value_numeric=Decimal("50"),
                    source_hash="d" * 64,
                ),
                ReportValueContribution(
                    report_id=1,
                    kind="DEPT",
                    ref_id=10,
                    source_type="POS",
                    source_id="projection:1:dept:10",
                    value_numeric=Decimal("1150"),
                    source_hash="e" * 64,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _enabled_flags(self):
        return (
            patch.object(settings, "POS_INTEGRATION_PROVIDER_ROLLOUT", "QUICKRESTO"),
            patch.object(settings, "POS_INTEGRATION_CANONICAL_READ_ENABLED", True),
        )

    def test_source_is_resolved_automatically_without_user_policy(self):
        manual = load_report_facts(self.db, report=self.report)
        self.assertEqual(manual.source_mode, MANUAL)
        self.assertEqual(manual.revenue_total, 1_000)

        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)
            self.connection.read_mode = POS_CANONICAL
            self.db.flush()
            canonical = load_report_facts(self.db, report=self.report)
            self.assertEqual(canonical.source_mode, POS_CANONICAL)
            self.assertEqual(canonical.revenue_total, 1_200)
            self.assertEqual(canonical.values_for("DEPT")[0].value_numeric, 1_150)

        # The global flag is the instant rollback gate; MANUAL contributions
        # remained intact while canonical reads were enabled.
        fallback = load_report_facts(self.db, report=self.report)
        self.assertEqual(fallback.source_mode, MANUAL)
        self.assertEqual(fallback.revenue_total, 1_000)

    def test_unmatched_or_incomplete_projection_falls_back_to_manual(self):
        self.connection.read_mode = POS_CANONICAL
        self.projection.status = "MISMATCH"
        self.db.flush()
        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)

        self.projection.status = "MATCHED"
        self.db.execute(
            ReportValueContribution.__table__.delete().where(
                ReportValueContribution.report_id == 1,
                ReportValueContribution.source_type == "POS",
            )
        )
        self.db.flush()
        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)

    def test_manual_edit_replaces_only_manual_contributions(self):
        self.report.revenue_total = 1_050
        sync_manual_report_contributions(self.db, report=self.report)
        rows = list(
            self.db.execute(select(ReportValueContribution).where(ReportValueContribution.report_id == 1)).scalars()
        )
        self.assertTrue(any(row.source_type == "POS" for row in rows))
        manual_revenue = next(row for row in rows if row.source_type == "MANUAL" and row.kind == "REVENUE")
        self.assertEqual(int(manual_revenue.value_numeric), 1_050)

    def test_composite_item_attribution_never_double_counts_parent_charge(self):
        parent = SimpleNamespace(
            parent_item_id=None,
            included_in_parent=False,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("0"),
        )
        primary = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("700"),
        )
        secondary = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("300"),
        )
        self.assertEqual(
            sum(attribution_minor_for_item(item) for item in (parent, primary, secondary)),
            100_000,
        )
        unresolved_component = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=None,
        )
        fallback_parent = SimpleNamespace(
            parent_item_id=None,
            included_in_parent=False,
            net_amount=Decimal("1000"),
            attributed_net_amount=None,
        )
        self.assertEqual(attribution_minor_for_item(unresolved_component), 0)
        self.assertEqual(attribution_minor_for_item(fallback_parent), 100_000)

    def test_provider_neutral_validation_reopens_the_same_quarantine_issue(self):
        dto = CanonicalDTO(
            entity_type="PURCHASE",
            external_id="purchase-1",
            attributes={"supplier_external_id": "supplier-1", "supplier_id": None},
        )
        first = validate_and_quarantine(
            self.db,
            connection_id=1,
            dto=dto,
            affected_report_keys=("2031-03-10:DAY",),
        )
        self.db.flush()
        first[0].status = "RESOLVED"
        self.db.flush()
        second = validate_and_quarantine(self.db, connection_id=1, dto=dto)
        self.db.flush()
        self.assertEqual(first[0].id, second[0].id)
        self.assertEqual(second[0].status, "OPEN")

    def test_quality_summary_surfaces_stale_capability_and_critical_issue(self):
        from app.routers.pos_integrations import get_pos_integration_quality_summary

        self.db.add_all(
            [
                IntegrationCapabilityState(
                    connection_id=1,
                    capability="ORDERS",
                    state="SUPPORTED",
                    last_success_at=datetime.now(timezone.utc) - timedelta(hours=8),
                ),
                IntegrationQuarantine(
                    connection_id=1,
                    issue_key="critical-1",
                    entity_type="ORDER",
                    external_id="order-1",
                    error_class="VALIDATION",
                    error_code="CLOSED_ORDER_WITHOUT_PAYMENT",
                    severity="CRITICAL",
                    status="OPEN",
                    user_summary="Closed order has no positive payment",
                ),
            ]
        )
        self.db.commit()
        with patch("app.routers.pos_integrations._require_view"):
            result = get_pos_integration_quality_summary(
                1,
                stale_after_seconds=3600,
                db=self.db,
                user=SimpleNamespace(id=1),
            )
        self.assertEqual(result["health"], "FAILED")
        self.assertEqual(result["critical_issue_count"], 1)
        self.assertEqual(result["stale_capability_count"], 1)


class StageThreeNotificationRegressionTests(unittest.TestCase):
    def test_successful_auto_import_does_not_enqueue_user_notification(self):
        from app.services.integrations.quickresto_sync import _enqueue_sync_notification_safely

        db = Mock()
        _enqueue_sync_notification_safely(
            db,
            connection=SimpleNamespace(venue_id=1, id=1),
            run=SimpleNamespace(
                id=2,
                status="SUCCEEDED",
                trigger="SCHEDULED",
                shifts_seen=1,
                shifts_imported=1,
                reports_created=0,
                reports_updated=1,
                reports_unchanged=0,
            ),
            issue_count=0,
            force=True,
        )
        db.commit.assert_not_called()
        db.add.assert_not_called()

    def test_shift_backed_salary_component_is_available_for_slot_notification(self):
        from app.services.payroll.day_breakdown import DayAllocationContext, _component_allocation_for_day

        target = date(2031, 3, 10)
        context = DayAllocationContext(
            shift_slot="DAY",
            month_dates=[target],
            worked_dates=[target],
            minutes_by_date={target: 480},
            shifts_by_date={target: 1},
            revenue_by_date_minor={target: 0},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        item = _component_allocation_for_day(
            component={
                "component_type": "SALARY_PER_SHIFT",
                "amount_minor": 300_000,
                "shift_rows": [
                    {
                        "date": target.isoformat(),
                        "shift_slot": "DAY",
                        "amount_minor": 300_000,
                        "applied_rate_minor": 300_000,
                    },
                    {
                        "date": target.isoformat(),
                        "shift_slot": "NIGHT",
                        "amount_minor": 400_000,
                        "applied_rate_minor": 400_000,
                    },
                ],
            },
            target_date=target,
            context=context,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["amount_minor"], 300_000)


class StageThreeOperationalDepthTests(unittest.TestCase):
    def test_operational_models_are_registered_with_expected_decimal_precision(self):
        expected_tables = {
            "pos_recipes",
            "pos_recipe_items",
            "pos_stock_snapshots",
            "pos_stock_movements",
            "pos_purchase_documents",
            "pos_purchase_items",
            "pos_writeoffs",
            "pos_writeoff_items",
            "pos_inventory_documents",
            "pos_inventory_items",
            "pos_employee_attendance",
        }
        self.assertTrue(expected_tables.issubset(Base.metadata.tables))
        self.assertEqual(Base.metadata.tables["pos_stock_snapshots"].c.quantity.type.scale, 6)
        self.assertEqual(Base.metadata.tables["pos_purchase_documents"].c.total_amount.type.scale, 4)

    def test_provider_neutral_quality_rules_cover_stage_three_entities(self):
        order = CanonicalDTO(
            entity_type="ORDER",
            external_id="order-1",
            attributes={
                "status": "CLOSED",
                "net_amount": "-10.00",
                "payment_amount": "0",
                "items_count": 0,
                "employee_external_id": "employee-1",
                "employee_id": None,
            },
        )
        self.assertEqual(
            {issue.code for issue in validate_canonical_dto(order)},
            {"NEGATIVE_REVENUE", "CLOSED_ORDER_WITHOUT_PAYMENT", "ORDER_WITHOUT_ITEMS", "UNKNOWN_EMPLOYEE"},
        )
        purchase = CanonicalDTO(
            entity_type="PURCHASE",
            external_id="purchase-1",
            attributes={"supplier_external_id": "supplier-1", "supplier_id": None},
        )
        self.assertEqual([issue.code for issue in validate_canonical_dto(purchase)], ["PURCHASE_WITHOUT_SUPPLIER"])
        inventory_item = CanonicalDTO(
            entity_type="INVENTORY_ITEM",
            external_id="inventory-item-1",
            attributes={"product_external_id": "product-1", "product_id": None},
        )
        self.assertEqual(
            [issue.code for issue in validate_canonical_dto(inventory_item)],
            ["INVENTORY_UNKNOWN_PRODUCT"],
        )

    def test_freshness_distinguishes_stale_missing_and_unavailable_capabilities(self):
        now = datetime(2031, 3, 10, 12, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(capability="ORDERS", state="SUPPORTED", last_success_at=now - timedelta(minutes=5)),
            SimpleNamespace(capability="PRODUCTS", state="SUPPORTED", last_success_at=now - timedelta(hours=8)),
            SimpleNamespace(capability="PURCHASES", state="UNKNOWN", last_success_at=None),
            SimpleNamespace(capability="RECIPES", state="UNAVAILABLE", last_success_at=None),
        ]
        result = {
            item.capability: item.freshness
            for item in assess_capability_freshness(rows, stale_after_seconds=3600, now=now)
        }
        self.assertEqual(
            result,
            {"ORDERS": "FRESH", "PRODUCTS": "STALE", "PURCHASES": "NO_DATA", "RECIPES": "NOT_APPLICABLE"},
        )

    def test_iiko_and_quickresto_compounds_share_one_canonical_financial_shape(self):
        quickresto = normalize_quickresto_composite(
            json.loads((FIXTURES_DIR / "quickresto_compound_order_item.json").read_text(encoding="utf-8"))
        )
        iiko = normalize_iiko_composite(
            json.loads((FIXTURES_DIR / "iiko_compound_order_item.json").read_text(encoding="utf-8"))
        )

        def signature(lines):
            return [
                (
                    line.external_id,
                    line.parent_external_id,
                    line.item_role,
                    line.component_role,
                    line.product_external_id,
                    line.quantity,
                    line.net_amount,
                    line.attributed_net_amount,
                    line.included_in_parent,
                )
                for line in lines
            ]

        self.assertEqual(signature(quickresto), signature(iiko))
        self.assertEqual(sum(line.attributed_net_amount or 0 for line in iiko), Decimal("750.00"))

    def test_quickresto_stage_three_capabilities_are_truthful(self):
        class Client:
            def list_objects(self, **_kwargs):
                return []

            def list_all_objects(self, *, class_name, **_kwargs):
                if class_name.endswith(".Store"):
                    return [{"id": 7, "name": "Main store"}]
                return []

            def fallback_diagnostics(self):
                return []

        adapter = QuickRestoProviderAdapter(Client())
        capabilities = adapter.get_capabilities()
        self.assertEqual(capabilities[Capability.WAREHOUSES].state, CapabilityState.DERIVED)
        self.assertEqual(capabilities[Capability.WRITEOFFS].state, CapabilityState.UNAVAILABLE)
        self.assertEqual([row.external_id for row in adapter.iter_warehouses()], ["7"])
        with self.assertRaises(ProviderCapabilityError):
            adapter.iter_recipes()
