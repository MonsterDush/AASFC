from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.integrations.base.errors import ProviderCapabilityError
from app.integrations.base.credentials import ProviderCredentials
from app.integrations.registry import ProviderRegistry
from app.integrations.providers.quickresto.expanded_sync import (
    NORMALIZATION_VERSION,
    replay_quickresto_expanded_raw,
    sync_quickresto_expanded_capabilities,
)
from app.integrations.providers.quickresto.provider import QuickRestoProviderAdapter
from app.integrations.raw.storage import load_raw_payload
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.pos_canonical import (
    POSBusinessShift,
    POSEmployee,
    POSInventoryDocument,
    POSInventoryItem,
    POSProduct,
    POSPurchaseDocument,
    POSPurchaseItem,
    POSRestaurantSection,
    POSStockMovement,
    POSSupplier,
    POSTable,
    POSWarehouse,
    POSWriteoff,
    POSWriteoffItem,
)
from app.models.pos_operational_snapshot import POSOperationalSnapshot
from app.services.integrations.quickresto import QUICKRESTO_OBJECT_TYPES


class _StageThreeClient:
    def __init__(self) -> None:
        self.by_class = {class_name: key for key, (_, class_name) in QUICKRESTO_OBJECT_TYPES.items()}
        self.lists = {
            "shifts": [
                {
                    "id": 1,
                    "version": 2,
                    "status": "CLOSED",
                    "localOpenedTime": "2026-09-20T10:00:00",
                    "tableScheme": {"id": 100},
                },
                {
                    "id": 2,
                    "version": 3,
                    "status": "OPENED",
                    "localOpenedTime": "2026-09-21T10:00:00",
                    "opened": "2026-09-21T10:00:00",
                    "ordersCount": 4,
                    "tableScheme": {"id": 100},
                },
                {
                    "id": 3,
                    "status": "OPENED",
                    "localOpenedTime": "2026-09-21T11:00:00",
                    "tableScheme": {"id": 999},
                },
            ],
            "venues": [{"id": 100, "name": "Scheme"}],
            "employees": [
                {
                    "id": 30,
                    "version": 1,
                    "fullName": "Иванов Иван",
                    "firstName": "Иван",
                    "lastName": "Иванов",
                    "blocked": False,
                    "position": {"name": "Официант"},
                    "user": {"login": "ivan", "tokens": [{"token": "must-not-be-stored"}]},
                }
            ],
            "inventory_documents": [{"id": 40, "invoiceDate": "2026-09-21", "processed": True, "store": {"id": 10}}],
            "incoming_invoices": [{"id": 41, "invoiceDate": "2026-09-21", "processed": True, "store": {"id": 10}}],
            # Numeric ids are not assumed global across document classes.
            "discard_invoices": [{"id": 41, "invoiceDate": "2026-09-21", "processed": True, "store": {"id": 10}}],
            "outgoing_invoices": [],
            "exchange_invoices": [
                {
                    "id": 42,
                    "invoiceDate": "2026-09-21",
                    "processed": True,
                    "fromStore": {"id": 10},
                    "store": {"id": 11},
                }
            ],
            "cooking_invoices": [],
            "decomposition_invoices": [],
            "processing_invoices": [
                {
                    "id": 43,
                    "invoiceDate": "2026-09-21",
                    "processed": True,
                    "fromStore": {"id": 10},
                    "store": {"id": 11},
                }
            ],
        }
        self.details = {
            ("venues", 100): {
                "id": 100,
                "webHalls": [
                    {
                        "id": 200,
                        "title": "Основной зал",
                        "tables": [
                            {"id": 201, "title": "Стол 1", "maxCapacity": 4, "deleted": False},
                            {"id": 202, "itemTitle": "Бар", "maxCapacity": 2, "deleted": False},
                        ],
                    }
                ],
                "tables": [{"id": 201, "title": "Стол 1", "maxCapacity": 4, "deleted": False}],
            },
            ("inventory_documents", 40): {
                "id": 40,
                "version": 5,
                "invoiceDate": "2026-09-21",
                "processed": True,
                "store": {"id": 10},
                "shortfallSum": "15.00",
                "surplusSum": "0",
            },
            ("incoming_invoices", 41): {
                "id": 41,
                "version": 2,
                "invoiceDate": "2026-09-21",
                "processed": True,
                "store": {"id": 10},
                "provider": {"id": 50, "name": "Поставщик"},
                "totalSum": "30",
                "invoiceItems": [
                    {
                        "id": 410,
                        "product": {"id": 20},
                        "actualAmount": "3",
                        "measureUnit": {"shortName": "kg"},
                        "price": "10",
                        "calculatedTotalSum": "30",
                    }
                ],
            },
            ("discard_invoices", 41): {
                "id": 41,
                "version": 4,
                "invoiceDate": "2026-09-21",
                "processed": True,
                "store": {"id": 10},
                "discardReason": {"id": 70, "title": "Порча"},
                "totalSum": "5",
                "invoiceItems": [
                    {
                        "id": 420,
                        "product": {"id": 20},
                        "actualAmount": "0.5",
                        "measureUnit": {"shortName": "kg"},
                        "calculatedTotalSum": "5",
                    }
                ],
            },
            ("exchange_invoices", 42): {
                "id": 42,
                "invoiceDate": "2026-09-21",
                "processed": True,
                "fromStore": {"id": 10},
                "store": {"id": 11},
                "invoiceItems": [
                    {
                        "id": 430,
                        "product": {"id": 20},
                        "actualAmount": "2",
                        "measureUnit": {"shortName": "kg"},
                        "costPriceSum": "20",
                    }
                ],
            },
            ("processing_invoices", 43): {
                "id": 43,
                "invoiceDate": "2026-09-21",
                "processed": True,
                "fromStore": {"id": 10},
                "store": {"id": 11},
                "sourceItems": [
                    {
                        "id": 440,
                        "product": {"id": 20},
                        "actualAmount": "1",
                        "measureUnit": {"shortName": "kg"},
                    }
                ],
                "resultComponents": [
                    {
                        "id": 441,
                        "product": {"id": 20},
                        "actualAmount": "0.8",
                        "measureUnit": {"shortName": "kg"},
                    }
                ],
            },
        }

    def list_all_objects(self, *, class_name, **_kwargs):
        return deepcopy(self.lists.get(self.by_class[class_name], []))

    def read_object(self, *, class_name, object_id, **_kwargs):
        return deepcopy(self.details[(self.by_class[class_name], int(object_id))])


class QuickRestoStageThreeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = QuickRestoProviderAdapter(_StageThreeClient())

    def test_operational_adapter_filters_shift_locally_and_flattens_scheme(self):
        shift = self.adapter.get_current_business_shift(external_venue_id="100")
        sections = list(self.adapter.iter_restaurant_sections(external_venue_id="100"))
        tables = list(self.adapter.iter_tables(external_venue_id="100"))

        self.assertEqual(shift.external_id, "2")
        self.assertEqual([item.external_id for item in sections], ["200"])
        self.assertEqual([item.external_id for item in tables], ["201", "202"])
        self.assertEqual(tables[0].payload["restaurantSectionId"], "200")

    def test_unverified_open_orders_remain_hard_blocked(self):
        with self.assertRaisesRegex(ProviderCapabilityError, "not verified"):
            tuple(self.adapter.iter_open_orders(external_venue_id="100"))
        with self.assertRaisesRegex(ProviderCapabilityError, "not verified"):
            self.adapter.get_open_order(external_venue_id="100", external_order_id="1")

    def test_registry_exposes_quickresto_operational_contract_without_breaking_legacy_build(self):
        registry = ProviderRegistry()
        registry.register("QUICKRESTO", lambda _credentials: self.adapter)
        credentials = ProviderCredentials({"fixture": "value"})

        self.assertIs(registry.build("QUICKRESTO", credentials), self.adapter)
        bundle = registry.build_adapters("QUICKRESTO", credentials)
        self.assertIs(bundle.reader, self.adapter)
        self.assertIs(bundle.operational, self.adapter)

    def test_document_period_is_filtered_locally_and_detail_is_retained(self):
        records = list(
            self.adapter.iter_purchases(
                period_start=date(2026, 9, 21),
                period_end_exclusive=date(2026, 9, 22),
            )
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].external_id, "incoming_invoices:41")
        self.assertEqual(records[0].payload["documentSurface"], "incoming_invoices")
        self.assertEqual(records[0].payload["invoiceItems"][0]["actualAmount"], "3")


class QuickRestoStageThreeCanonicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE venues (id INTEGER PRIMARY KEY, name VARCHAR(200), timezone VARCHAR(64) NOT NULL)"
            )
        Base.metadata.create_all(
            self.engine,
            tables=[
                IntegrationConnection.__table__,
                IntegrationRawObject.__table__,
                POSOperationalSnapshot.__table__,
                POSRestaurantSection.__table__,
                POSTable.__table__,
                POSEmployee.__table__,
                POSWarehouse.__table__,
                POSProduct.__table__,
                POSBusinessShift.__table__,
                POSSupplier.__table__,
                POSInventoryDocument.__table__,
                POSInventoryItem.__table__,
                POSPurchaseDocument.__table__,
                POSPurchaseItem.__table__,
                POSWriteoff.__table__,
                POSWriteoffItem.__table__,
                POSStockMovement.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.connection().exec_driver_sql(
            "INSERT INTO venues (id, name, timezone) VALUES (21, 'Venue 21', 'Europe/Moscow')"
        )
        self.connection = IntegrationConnection(
            venue_id=21,
            provider="QUICKRESTO",
            status="ACTIVE",
            external_venue_id="100",
            read_mode="LEGACY",
        )
        self.db.add(self.connection)
        self.db.flush()
        self.db.add_all(
            [
                POSWarehouse(
                    connection_id=self.connection.id,
                    external_id="10",
                    venue_id=21,
                    name="Основной склад",
                    is_active=True,
                ),
                POSWarehouse(
                    connection_id=self.connection.id,
                    external_id="11",
                    venue_id=21,
                    name="Производственный склад",
                    is_active=True,
                ),
                POSProduct(
                    connection_id=self.connection.id,
                    external_id="20",
                    name="Товар",
                    unit="kg",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 32)
    def test_raw_first_sync_is_idempotent_and_replayable(self):
        adapter = QuickRestoProviderAdapter(_StageThreeClient())
        first = sync_quickresto_expanded_capabilities(
            self.db,
            connection=self.connection,
            adapter=adapter,
            period_start=date(2026, 9, 21),
            period_end_exclusive=date(2026, 9, 22),
            timezone_name="Europe/Moscow",
            observed_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )
        second = sync_quickresto_expanded_capabilities(
            self.db,
            connection=self.connection,
            adapter=QuickRestoProviderAdapter(_StageThreeClient()),
            period_start=date(2026, 9, 21),
            period_end_exclusive=date(2026, 9, 22),
            timezone_name="Europe/Moscow",
            observed_at=datetime(2026, 9, 21, 12, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(first.counts["current_business_shifts"], 1)
        self.assertEqual(first.counts["stock_movements"], 6)
        self.assertEqual(second.counts, first.counts)
        self.assertEqual(self.db.scalar(select(func.count(POSBusinessShift.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSRestaurantSection.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSTable.id))), 2)
        self.assertEqual(self.db.scalar(select(func.count(POSEmployee.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSInventoryDocument.id))), 5)
        self.assertEqual(self.db.scalar(select(func.count(POSInventoryItem.id))), 5)
        self.assertEqual(self.db.scalar(select(func.count(POSPurchaseDocument.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSWriteoff.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(POSStockMovement.id))), 6)
        self.assertEqual(self.db.scalar(select(func.count(POSOperationalSnapshot.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 10)

        shift = self.db.scalar(select(POSBusinessShift))
        self.assertEqual(shift.status, "OPEN")
        self.assertEqual(shift.revenue_amount, Decimal("0.0000"))
        self.assertEqual(self.connection.read_mode, "LEGACY")
        movements = list(self.db.scalars(select(POSStockMovement).order_by(POSStockMovement.external_id)))
        self.assertEqual(
            sorted(item.quantity for item in movements),
            [
                Decimal("-2.000000"),
                Decimal("-1.000000"),
                Decimal("-0.500000"),
                Decimal("0.800000"),
                Decimal("2.000000"),
                Decimal("3.000000"),
            ],
        )

        employee_raw = self.db.scalar(
            select(IntegrationRawObject).where(IntegrationRawObject.entity_type == "QR_EMPLOYEE")
        )
        self.assertNotIn("user", load_raw_payload(employee_raw))
        self.db.execute(POSEmployee.__table__.delete().where(POSEmployee.connection_id == self.connection.id))
        replayed = replay_quickresto_expanded_raw(
            self.db,
            raw=employee_raw,
            venue_id=21,
            timezone_name="Europe/Moscow",
        )
        self.db.commit()
        self.assertEqual(replayed.name, "Иванов Иван")
        self.assertEqual(employee_raw.normalization_version, NORMALIZATION_VERSION)
        self.assertTrue(str(employee_raw.canonical_identity).startswith("POSEmployee:"))


if __name__ == "__main__":
    unittest.main()
