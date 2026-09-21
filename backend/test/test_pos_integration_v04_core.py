from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.integrations.base import Capability, ProviderAdapters, ProviderCredentials
from app.integrations.registry import ProviderRegistry
from app.models import (
    IntegrationCommand,
    IntegrationConnection,
    IntegrationSyncJob,
    IntegrationWebhookEvent,
    POSOperationalSnapshot,
)
from app.models.pos_canonical import (
    POSModifier,
    POSOrder,
    POSOrderItemModifier,
    POSProductVariant,
    POSProductVariantOption,
    POSRestaurantSection,
    POSStopListEntry,
    POSTable,
    POSTerminalGroup,
)
from app.services.integrations.commands import create_command, transition_command
from app.services.integrations.credentials import decrypt_command_payload, decrypt_event_payload
from app.services.integrations.operational import store_operational_snapshot
from app.services.integrations.sync_coordinator import (
    IntegrationSyncCoordinator,
    SyncQueue,
    SyncRequest,
    SyncStrategy,
    schedule_sync,
)
from app.services.integrations.webhooks import store_webhook_event


class _LegacyAdapter:
    provider_code = "LEGACY"


class POSIntegrationV04CoreTests(unittest.TestCase):
    def test_capability_catalog_covers_realtime_commands_and_iiko_scope(self):
        expected = {
            "CURRENT_BUSINESS_SHIFT",
            "OPEN_ORDERS",
            "TABLES",
            "RESTAURANT_SECTIONS",
            "PRODUCT_VARIANTS",
            "STOP_LISTS",
            "COMMANDS",
            "WEBHOOKS",
            "REVISION_SYNC",
        }
        self.assertTrue(expected.issubset({capability.value for capability in Capability}))

    def test_registry_wraps_legacy_adapter_without_granting_write_contract(self):
        registry = ProviderRegistry()
        adapter = _LegacyAdapter()
        registry.register("legacy", lambda _credentials: adapter)
        bundle = registry.build_adapters("LEGACY", ProviderCredentials({"token": "secret"}))
        self.assertIs(bundle.discovery, adapter)
        self.assertIs(bundle.reader, adapter)
        self.assertIsNone(bundle.commands)
        self.assertIsNone(bundle.webhooks)

        focused_registry = ProviderRegistry()
        focused_registry.register("legacy", lambda _credentials: ProviderAdapters(discovery=adapter))
        focused_bundle = focused_registry.build_adapters("LEGACY", ProviderCredentials({"token": "secret"}))
        self.assertIs(focused_bundle.discovery, adapter)
        self.assertIsNone(focused_bundle.reader)
        with self.assertRaisesRegex(TypeError, "build_adapters"):
            focused_registry.build("LEGACY", ProviderCredentials({"token": "secret"}))

    def test_canonical_schema_has_operational_and_composite_entities(self):
        self.assertEqual(POSTerminalGroup.__tablename__, "pos_terminal_groups")
        self.assertEqual(POSRestaurantSection.__tablename__, "pos_restaurant_sections")
        self.assertEqual(POSTable.__tablename__, "pos_tables")
        self.assertEqual(POSProductVariant.__tablename__, "pos_product_variants")
        self.assertEqual(POSProductVariantOption.__tablename__, "pos_product_variant_options")
        self.assertEqual(POSModifier.__tablename__, "pos_modifiers")
        self.assertEqual(POSOrderItemModifier.__tablename__, "pos_order_item_modifiers")
        self.assertEqual(POSStopListEntry.__tablename__, "pos_stop_list_entries")
        self.assertIn("current_amount", POSOrder.__table__.c)
        self.assertIn("is_final", POSOrder.__table__.c)
        open_order = POSOrder(
            connection_id=1,
            external_id="open-order",
            venue_id=1,
            business_date=date(2026, 9, 21),
            status="OPEN",
            current_amount=Decimal("8400.00"),
            net_amount=Decimal("0"),
            is_final=False,
            currency="RUB",
        )
        self.assertEqual(open_order.current_amount, Decimal("8400.00"))
        self.assertEqual(open_order.net_amount, Decimal("0"))
        self.assertFalse(open_order.is_final)

    def test_ledgers_are_encrypted_idempotent_and_operational_state_is_compacted(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE venues (id INTEGER PRIMARY KEY, name VARCHAR(200), timezone VARCHAR(64) NOT NULL)"
            )
        Base.metadata.create_all(
            engine,
            tables=[
                IntegrationConnection.__table__,
                IntegrationCommand.__table__,
                IntegrationWebhookEvent.__table__,
                POSOperationalSnapshot.__table__,
                IntegrationSyncJob.__table__,
            ],
        )
        try:
            with Session(engine) as db, patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "v" * 32):
                db.connection().exec_driver_sql(
                    "INSERT INTO venues (id, name, timezone) VALUES (1, 'iiko multi-scope', 'Europe/Moscow')"
                )
                connection = IntegrationConnection(venue_id=1, provider="IIKO", external_organization_id="org-1")
                db.add(connection)
                db.flush()

                command, created = create_command(
                    db,
                    connection_id=connection.id,
                    venue_id=1,
                    provider="IIKO",
                    command_type="ORDER_CREATE",
                    idempotency_key="order-create-1",
                    payload={"secret": "not-plaintext"},
                )
                duplicate, duplicate_created = create_command(
                    db,
                    connection_id=connection.id,
                    venue_id=1,
                    provider="IIKO",
                    command_type="ORDER_CREATE",
                    idempotency_key="order-create-1",
                    payload={"secret": "not-plaintext"},
                )
                self.assertTrue(created)
                self.assertFalse(duplicate_created)
                self.assertEqual(duplicate.id, command.id)
                with self.assertRaisesRegex(ValueError, "different payload"):
                    create_command(
                        db,
                        connection_id=connection.id,
                        venue_id=1,
                        provider="IIKO",
                        command_type="ORDER_CREATE",
                        idempotency_key="order-create-1",
                        payload={"secret": "changed"},
                    )
                self.assertNotIn("not-plaintext", command.encrypted_request)
                self.assertIn("not-plaintext", decrypt_command_payload(command.encrypted_request))
                transition_command(command, "SUBMITTING")
                transition_command(command, "ACCEPTED", external_command_id="iiko-command-1")

                event, event_created = store_webhook_event(
                    db,
                    connection_id=connection.id,
                    provider="IIKO",
                    event_type="ORDER_UPDATED",
                    external_event_id="event-1",
                    payload={"order": "sensitive-order"},
                )
                same_event, same_event_created = store_webhook_event(
                    db,
                    connection_id=connection.id,
                    provider="IIKO",
                    event_type="ORDER_UPDATED",
                    external_event_id="event-1",
                    payload={"order": "sensitive-order"},
                )
                self.assertTrue(event_created)
                self.assertFalse(same_event_created)
                self.assertEqual(same_event.id, event.id)
                self.assertNotIn("sensitive-order", event.payload_encrypted)
                self.assertIn("sensitive-order", decrypt_event_payload(event.payload_encrypted))

                observed_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
                snapshot, snapshot_created = store_operational_snapshot(
                    db,
                    connection_id=connection.id,
                    venue_id=1,
                    object_type="ORDER",
                    external_id="order-1",
                    payload={"status": "OPEN", "amount": "100.00"},
                    observed_at=observed_at,
                    source_status="OPEN",
                    current_amount=Decimal("100.00"),
                )
                same_snapshot, same_snapshot_created = store_operational_snapshot(
                    db,
                    connection_id=connection.id,
                    venue_id=1,
                    object_type="ORDER",
                    external_id="order-1",
                    payload={"status": "OPEN", "amount": "100.00"},
                    observed_at=datetime(2026, 9, 21, 12, 1, tzinfo=timezone.utc),
                    source_status="OPEN",
                    current_amount=Decimal("100.00"),
                )
                self.assertTrue(snapshot_created)
                self.assertFalse(same_snapshot_created)
                self.assertEqual(same_snapshot.id, snapshot.id)
                self.assertEqual(snapshot.current_amount, Decimal("100.00"))

                request = SyncRequest(
                    connection_id=connection.id,
                    capability="ORDERS",
                    strategy=SyncStrategy.DATE_RANGE,
                    queue=SyncQueue.BULK,
                    period_start=date(2026, 9, 1),
                    period_end_exclusive=date(2026, 9, 22),
                    scope={"external_organization_id": "org-1", "external_venue_id": "venue-2"},
                )
                job, job_created = schedule_sync(db, request)
                coordinator = IntegrationSyncCoordinator(db)
                same_job, same_job_created = coordinator.schedule(request)
                self.assertTrue(job_created)
                self.assertFalse(same_job_created)
                self.assertEqual(same_job.id, job.id)
                self.assertEqual(job.queue, "bulk")
                self.assertEqual(job.priority, 200)
                self.assertEqual(
                    coordinator.plan(["RECONCILIATION", "TABLES"]),
                    ("ORDERS", "PAYMENTS", "RECONCILIATION", "EXTERNAL_VENUES", "TERMINALS", "TABLES"),
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
