from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.integrations.base import POSCapability, POSProvider, POSProviderCode, ProviderHealth, ProviderPage, ProviderRecord
from app.integrations.canonical import (
    CanonicalOrder,
    CanonicalOrderItem,
    CanonicalPayment,
    CanonicalProduct,
    CanonicalPurchase,
    CanonicalPurchaseItem,
    CanonicalRecipe,
    CanonicalRecipeItem,
    CanonicalSupplier,
    CanonicalWarehouse,
    canonical_sales_metrics,
    persist_canonical_batch,
)
from app.integrations.freshness import capability_freshness
from app.integrations.normalization import IikoP0Normalizer, NormalizationContext, QuickRestoP0Normalizer
from app.integrations.providers.iiko import IikoPOSProvider
from app.integrations.providers.quick_resto import QuickRestoPOSProvider
from app.integrations.sync import synchronize_capability
from app.integrations.sync.jobs import enqueue_due_jobs, requeue_stale_jobs
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_connection import IntegrationConnection
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.integration_sync_job import IntegrationSyncJob
from app.models.pos_canonical import (
    POSEmployee,
    POSOrder,
    POSOrderDiscount,
    POSOrderEvent,
    POSOrderItem,
    POSPayment,
    POSProduct,
    POSProductGroup,
    POSRefund,
)
from app.models.pos_inventory import (
    POSAttendance,
    POSCustomerIdentity,
    POSInventoryDocument,
    POSInventoryItem,
    POSPurchaseDocument,
    POSPurchaseItem,
    POSRecipe,
    POSRecipeItem,
    POSStockMovement,
    POSStockSnapshot,
    POSSupplier,
    POSWarehouse,
    POSWriteoff,
    POSWriteoffItem,
)
from app.models.venue import Venue


FIXTURES = Path(__file__).parent / "fixtures" / "pos"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class _PurchaseProvider(POSProvider):
    provider_code = POSProviderCode.QUICK_RESTO

    def authenticate(self) -> None:
        return None

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, checked_at=datetime.now(timezone.utc))

    def detect_capabilities(self):
        return {}

    def get_purchases(self, *, updated_since=None, cursor=None) -> ProviderPage:
        del updated_since, cursor
        observed_at = datetime(2030, 1, 3, 10, tzinfo=timezone.utc)
        return ProviderPage(
            records=(
                ProviderRecord(
                    external_id="bad-purchase",
                    payload={"date": "2030-01-03", "items": []},
                    source_updated_at=observed_at,
                ),
                ProviderRecord(
                    external_id="good-purchase",
                    payload={
                        "date": "2030-01-03",
                        "supplierId": "supplier-1",
                        "warehouseId": "warehouse-1",
                        "items": [
                            {
                                "id": "purchase-item-1",
                                "productId": "product-1",
                                "quantity": "2.5",
                                "price": "40",
                                "sum": "100",
                            }
                        ],
                    },
                    source_updated_at=observed_at,
                ),
            )
        )


class StageThreeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                Venue.__table__,
                IntegrationConnection.__table__,
                IntegrationCapabilityState.__table__,
                IntegrationRawObject.__table__,
                IntegrationSyncCursor.__table__,
                IntegrationReconciliationRun.__table__,
                IntegrationQuarantine.__table__,
                IntegrationSyncJob.__table__,
                POSEmployee.__table__,
                POSProductGroup.__table__,
                POSProduct.__table__,
                POSOrder.__table__,
                POSOrderItem.__table__,
                POSOrderEvent.__table__,
                POSPayment.__table__,
                POSRefund.__table__,
                POSOrderDiscount.__table__,
                POSRecipe.__table__,
                POSRecipeItem.__table__,
                POSWarehouse.__table__,
                POSStockSnapshot.__table__,
                POSStockMovement.__table__,
                POSSupplier.__table__,
                POSPurchaseDocument.__table__,
                POSPurchaseItem.__table__,
                POSWriteoff.__table__,
                POSWriteoffItem.__table__,
                POSInventoryDocument.__table__,
                POSInventoryItem.__table__,
                POSAttendance.__table__,
                POSCustomerIdentity.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.add(Venue(id=1, name="Test", timezone="Europe/Moscow"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _connection(self, connection_id: int = 1, *, provider: str = "QUICK_RESTO", read_mode: str = "LEGACY"):
        row = IntegrationConnection(
            id=connection_id,
            venue_id=1,
            provider=provider,
            status="ACTIVE",
            read_mode=read_mode,
            credentials_encrypted=b"opaque-test-credentials",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _context(self, connection_id: int = 1, *, provider: POSProviderCode = POSProviderCode.QUICK_RESTO):
        return NormalizationContext(
            integration_connection_id=connection_id,
            venue_id=1,
            provider=provider,
            normalization_version="stage-three-test",
        )

    def test_extended_entities_are_decimal_idempotent_and_keep_recipe_versions(self):
        self._connection()
        context = self._context()
        persist_canonical_batch(
            self.db,
            (
                CanonicalProduct(external_id="dish-1", name="Dish"),
                CanonicalProduct(external_id="ingredient-1", name="Ingredient", type="INGREDIENT"),
                CanonicalWarehouse(external_id="warehouse-1", name="Main"),
                CanonicalSupplier(external_id="supplier-1", name="Supplier"),
            ),
            context=context,
        )
        recipe = CanonicalRecipe(
            external_id="recipe-1:v1",
            product_external_id="dish-1",
            valid_from=datetime(2030, 1, 1, tzinfo=timezone.utc),
            valid_to=None,
            yield_quantity=Decimal("1.000"),
            yield_unit="kg",
            items=(CanonicalRecipeItem("ingredient-row-1", "ingredient-1", Decimal("0.250"), "kg"),),
        )
        purchase = CanonicalPurchase(
            external_id="purchase-1",
            supplier_external_id="supplier-1",
            warehouse_external_id="warehouse-1",
            document_date=date(2030, 1, 2),
            total_amount=Decimal("123.450000"),
            status="POSTED",
            items=(CanonicalPurchaseItem("line-1", "ingredient-1", Decimal("2.5"), Decimal("49.38"), Decimal("123.45"), "kg"),),
        )
        persist_canonical_batch(self.db, (recipe, purchase), context=context)
        persist_canonical_batch(self.db, (recipe, purchase), context=context)
        self.db.commit()

        self.assertEqual(self.db.scalar(select(func.count(POSRecipe.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSRecipeItem.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSPurchaseDocument.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSPurchaseItem.id))), 1)
        self.assertEqual(self.db.scalar(select(POSPurchaseDocument.total_amount)), Decimal("123.450000"))

    def test_quickresto_and_iiko_golden_purchases_produce_the_same_acdm(self):
        updated_at = datetime(2030, 1, 2, 8, tzinfo=timezone.utc)
        quickresto_payload = json.loads(
            (FIXTURES / "quickresto_purchase_golden.json").read_text(encoding="utf-8")
        )
        iiko_payload = json.loads(
            (FIXTURES / "iiko_purchase_golden.json").read_text(encoding="utf-8")
        )

        quick = QuickRestoP0Normalizer().normalize_purchases(
            ProviderRecord("purchase-1", quickresto_payload, updated_at),
            context=self._context(),
        )[0]
        iiko = IikoP0Normalizer().normalize_purchases(
            ProviderRecord("purchase-1", iiko_payload, updated_at),
            context=self._context(2, provider=POSProviderCode.IIKO),
        )[0]

        self.assertEqual(asdict(quick), asdict(iiko))
        self.assertEqual(quick.total_amount, Decimal("123.45"))

    def test_bad_record_is_quarantined_without_losing_valid_record(self):
        connection = self._connection()
        context = self._context()
        persist_canonical_batch(
            self.db,
            (
                CanonicalProduct(external_id="product-1", name="Product"),
                CanonicalWarehouse(external_id="warehouse-1", name="Main"),
                CanonicalSupplier(external_id="supplier-1", name="Supplier"),
            ),
            context=context,
        )
        self.db.commit()

        result = synchronize_capability(
            self.db,
            connection=connection,
            provider=_PurchaseProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.PURCHASES,
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.quarantined_records, 1)
        self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 2)
        self.assertEqual(self.db.scalar(select(func.count(POSPurchaseDocument.id))), 1)
        issue = self.db.scalar(select(IntegrationQuarantine))
        self.assertEqual(issue.error_code, "purchase_without_supplier")
        self.assertEqual(self.db.scalar(select(IntegrationSyncCursor)).status, "PARTIAL")
        self.assertEqual(connection.status, "DEGRADED")

    def test_freshness_uses_data_timestamp_not_capability_probe_timestamp(self):
        self._connection()
        observed_at = datetime(2030, 1, 3, 12, tzinfo=timezone.utc)
        self.db.add_all(
            [
                IntegrationCapabilityState(
                    integration_connection_id=1,
                    capability="SALES",
                    status="AVAILABLE",
                    last_updated_at=observed_at,
                    details_json={"last_data_at": (observed_at - timedelta(minutes=16)).isoformat()},
                ),
                IntegrationCapabilityState(
                    integration_connection_id=1,
                    capability="RECIPES",
                    status="UNAVAILABLE",
                    last_updated_at=observed_at,
                    details_json={},
                ),
            ]
        )
        self.db.commit()

        freshness = capability_freshness(self.db, connection_id=1, now=observed_at)

        self.assertEqual(freshness["SALES"]["status"], "STALE")
        self.assertEqual(freshness["RECIPES"]["status"], "UNAVAILABLE")
        self.assertEqual(freshness["PURCHASES"]["status"], "UNKNOWN")

    def test_scheduler_separates_critical_normal_and_bulk_queues_idempotently(self):
        connection = self._connection()
        connection.capabilities = {
            "SALES": {"status": "AVAILABLE"},
            "STOCK_BALANCES": {"status": "AVAILABLE"},
        }
        observed_at = datetime(2030, 1, 3, 12, tzinfo=timezone.utc)

        first = enqueue_due_jobs(self.db, now=observed_at)
        second = enqueue_due_jobs(self.db, now=observed_at)
        queues = set(self.db.scalars(select(IntegrationSyncJob.queue)))

        self.assertEqual(first, 4)
        self.assertEqual(second, 0)
        self.assertEqual(queues, {"CRITICAL", "NORMAL", "BULK"})

    def test_scheduler_releases_jobs_left_running_by_a_crashed_worker(self):
        self._connection()
        observed_at = datetime(2030, 1, 3, 12, tzinfo=timezone.utc)
        job = IntegrationSyncJob(
            integration_connection_id=1,
            job_type="CAPABILITY_SYNC",
            queue="CRITICAL",
            capability="SALES",
            payload_json={},
            idempotency_key="stale-job",
            status="RUNNING",
            run_after=observed_at - timedelta(hours=1),
            attempts=1,
            locked_at=observed_at - timedelta(minutes=31),
        )
        self.db.add(job)
        self.db.commit()

        released = requeue_stale_jobs(self.db, now=observed_at)

        self.assertEqual(released, 1)
        self.assertEqual(job.status, "PENDING")
        self.assertIsNone(job.locked_at)
        self.assertEqual(job.run_after.replace(tzinfo=timezone.utc), observed_at)
        self.assertEqual(job.last_error, "worker_lease_expired")

    def test_provider_extensions_are_available_only_after_configured_live_probe(self):
        client = Mock()
        client.organizations.return_value = {"organizations": [{"id": "org-1"}]}
        client.terminal_groups.return_value = {"terminalGroups": []}
        client.nomenclature.return_value = {"products": [], "groups": []}
        client.extended_export.return_value = {"recipes": []}
        provider = IikoPOSProvider(
            {
                "api_login": "login",
                "organization_id": "org-1",
                "extended_endpoints": {"RECIPES": "/api/1/export/recipes"},
            },
            client=client,
        )

        capabilities = provider.detect_capabilities()

        self.assertTrue(capabilities[POSCapability.RECIPES].available)
        self.assertFalse(capabilities[POSCapability.PURCHASES].available)
        client.extended_export.assert_called_once()
        with self.assertRaises(ValueError):
            QuickRestoPOSProvider(
                {"cloud": "unused", "object_types": {"SALES": {"module_name": "x", "class_name": "y"}}},
                client=Mock(),
            )

    def test_quickresto_extended_documents_load_full_details(self):
        client = Mock()
        client.list_objects.return_value = [{"id": 7, "number": "PN-7"}]
        client.read_object.return_value = {
            "id": 7,
            "number": "PN-7",
            "items": [{"id": 70, "productId": "product-1"}],
        }
        provider = QuickRestoPOSProvider(
            {
                "cloud": "unused",
                "object_types": {
                    "PURCHASES": {
                        "module_name": "warehouse.purchase",
                        "class_name": "example.Purchase",
                    }
                },
            },
            client=client,
        )

        page = provider.get_purchases()

        self.assertEqual(page.records[0].payload["items"][0]["id"], 70)
        client.read_object.assert_called_once_with(
            module_name="warehouse.purchase",
            class_name="example.Purchase",
            object_id=7,
        )

    def test_canonical_analytics_spans_provider_history_and_matches_golden_metrics(self):
        self._connection(1, provider="QUICK_RESTO", read_mode="CANONICAL")
        self._connection(2, provider="IIKO", read_mode="CANONICAL")
        contexts = (self._context(1), self._context(2, provider=POSProviderCode.IIKO))
        for index, (context, total, refund, guests, cost) in enumerate(
            (
                (contexts[0], Decimal("60000"), Decimal("0"), 20, Decimal("15000")),
                (contexts[1], Decimal("40000"), Decimal("5000"), 20, Decimal("13500")),
            ),
            start=1,
        ):
            persist_canonical_batch(
                self.db,
                (
                    CanonicalOrder(
                        external_id=f"order-{index}",
                        business_date=date(2030, 1, index),
                        calendar_date=date(2030, 1, index),
                        status="PARTIALLY_REFUNDED" if refund else "CLOSED",
                        subtotal=total,
                        discount_amount=0,
                        service_charge=0,
                        delivery_fee=0,
                        total_amount=total,
                        refund_amount=refund,
                        guest_count=guests,
                        items=(
                            CanonicalOrderItem(
                                external_id=f"item-{index}",
                                product_external_id=None,
                                product_name="Dish",
                                quantity=1,
                                base_price=total,
                                final_price=total,
                                gross_amount=total,
                                discount_amount=0,
                                net_amount=total,
                                cost_amount=cost,
                            ),
                        ),
                        payments=(CanonicalPayment(f"payment-{index}", "CARD", total),),
                    ),
                ),
                context=context,
            )
        self.db.commit()

        metrics = canonical_sales_metrics(
            self.db,
            venue_id=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
        )

        self.assertEqual(metrics["gross_revenue"], Decimal("100000"))
        self.assertEqual(metrics["refunds"], Decimal("5000"))
        self.assertEqual(metrics["net_revenue"], Decimal("95000"))
        self.assertEqual(metrics["food_cost_percent"], Decimal("30.00"))
        self.assertEqual(metrics["average_guest_spend"], Decimal("2375.00"))


if __name__ == "__main__":
    unittest.main()
