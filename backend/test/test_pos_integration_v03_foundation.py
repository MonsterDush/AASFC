from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import Numeric, create_engine, event, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.integrations.base.capabilities import Capability, CapabilityProbe, CapabilityState
from app.integrations.base.credentials import ProviderCredentials
from app.integrations.base.dto import ProviderRecord
from app.integrations.base.errors import ProviderAuthenticationError
from app.integrations.feature_flags import feature_flags_for
from app.integrations.raw.storage import load_raw_payload, record_raw_object, replay_raw_object
from app.integrations.registry import ProviderRegistry
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_sync_run import IntegrationSyncRun
from app.models.pos_canonical import POSBusinessShift, POSOrder, POSOrderItem, POSPayment
from app.routers.pos_integrations import router as pos_integrations_router
from app.routers.pos_integrations import venue_router as venue_pos_integrations_router


class _FakeProvider:
    provider_code = "FAKE"


class POSIntegrationFoundationTests(unittest.TestCase):
    def test_capability_catalog_and_probe_contract(self):
        self.assertEqual(Capability.BUSINESS_SHIFTS.value, "BUSINESS_SHIFTS")
        self.assertEqual(Capability.EMPLOYEE_ATTENDANCE.value, "EMPLOYEE_ATTENDANCE")
        self.assertEqual(Capability.SERVER_TIME_FILTER.value, "SERVER_TIME_FILTER")
        self.assertEqual(
            {state.value for state in CapabilityState},
            {"SUPPORTED", "DERIVED", "UNAVAILABLE", "DEGRADED", "UNKNOWN"},
        )
        with self.assertRaisesRegex(ValueError, "probe evidence"):
            CapabilityProbe(
                capability=Capability.SALES,
                state=CapabilityState.SUPPORTED,
                checked_at=datetime.now(timezone.utc),
            )

    def test_provider_record_requires_timezone_aware_source_time(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ProviderRecord(
                external_id="order-1",
                payload={"amount": "12.34"},
                source_updated_at=datetime(2026, 9, 13, 12, 0),
            )

    def test_registry_builds_only_matching_registered_provider(self):
        registry = ProviderRegistry()
        credentials = ProviderCredentials({"token": "secret"})
        registry.register("fake", lambda _credentials: _FakeProvider())
        self.assertEqual(registry.registered_providers(), ("FAKE",))
        self.assertEqual(registry.build("FAKE", credentials).provider_code, "FAKE")
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("FAKE", lambda _credentials: _FakeProvider())

    def test_provider_errors_redact_secret_values(self):
        error = ProviderAuthenticationError("Authorization: Bearer-secret https://pos.invalid?q=visible")
        self.assertNotIn("Bearer-secret", str(error))
        self.assertNotIn("visible", str(error))
        self.assertIn("[REDACTED]", str(error))

    def test_disabled_feature_flags_preserve_legacy_behaviour(self):
        with (
            patch.object(settings, "POS_INTEGRATION_SHADOW_WRITE_ENABLED", False),
            patch.object(settings, "POS_INTEGRATION_CANONICAL_READ_ENABLED", False),
            patch.object(settings, "POS_INTEGRATION_PROVIDER_ROLLOUT", ""),
        ):
            flags = feature_flags_for("QUICKRESTO")
        self.assertFalse(flags.shadow_write_enabled)
        self.assertFalse(flags.canonical_read_enabled)
        self.assertFalse(flags.provider_rollout_enabled)

    def test_raw_storage_is_encrypted_idempotent_allowlisted_and_replayable(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE venues (id INTEGER PRIMARY KEY, name VARCHAR(200), timezone VARCHAR(64) NOT NULL)"
            )
        Base.metadata.create_all(
            engine,
            tables=[
                IntegrationConnection.__table__,
                IntegrationSyncRun.__table__,
                IntegrationRawObject.__table__,
            ],
        )
        try:
            with Session(engine) as db:
                db.connection().exec_driver_sql(
                    "INSERT INTO venues (id, name, timezone) VALUES (1, 'Raw storage', 'Europe/Moscow')"
                )
                connection = IntegrationConnection(venue_id=1, provider="FAKE")
                db.add(connection)
                db.commit()
                record = ProviderRecord(
                    external_id="order-1",
                    payload={"amount": "12.34", "authorization": "must-not-be-stored"},
                    source_version="7",
                    source_updated_at=datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc),
                )
                with patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "x" * 32):
                    first = record_raw_object(
                        db,
                        connection_id=connection.id,
                        entity_type="order",
                        record=record,
                        allowed_fields={"amount"},
                    )
                    first_id = first.id
                    self.assertNotIn("12.34", first.encrypted_payload)
                    self.assertNotIn("must-not-be-stored", first.encrypted_payload)
                    self.assertEqual(load_raw_payload(first), {"amount": "12.34"})
                    replayed = replay_raw_object(
                        first, normalizer=lambda replay_record: replay_record.payload["amount"]
                    )
                    second = record_raw_object(
                        db,
                        connection_id=connection.id,
                        entity_type="ORDER",
                        record=record,
                        allowed_fields={"amount"},
                    )
                self.assertEqual(second.id, first_id)
                self.assertEqual(
                    db.scalar(select(IntegrationRawObject).where(IntegrationRawObject.external_id == "order-1")).id,
                    first_id,
                )
                self.assertEqual(replayed, "12.34")
                with patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "x" * 32):
                    with self.assertRaisesRegex(ValueError, "forbidden secret field"):
                        record_raw_object(
                            db,
                            connection_id=connection.id,
                            entity_type="ORDER",
                            record=ProviderRecord(
                                external_id="order-2",
                                payload={"customer": {"token": "secret"}},
                            ),
                            allowed_fields={"customer"},
                        )
        finally:
            engine.dispose()

    def test_acdm_uses_decimal_money_and_separate_business_shifts(self):
        self.assertIsInstance(POSOrder.__table__.c.net_amount.type, Numeric)
        self.assertIsInstance(POSPayment.__table__.c.amount.type, Numeric)
        self.assertIsInstance(POSOrderItem.__table__.c.quantity.type, Numeric)
        self.assertEqual(POSOrder.__table__.c.net_amount.type.scale, 4)
        self.assertEqual(POSOrderItem.__table__.c.quantity.type.scale, 6)
        self.assertEqual(POSBusinessShift.__tablename__, "pos_business_shifts")
        order = POSOrder(
            connection_id=1,
            external_id="order",
            venue_id=1,
            business_date=datetime(2026, 9, 13, tzinfo=timezone.utc).date(),
            net_amount=Decimal("12.3400"),
            currency="RUB",
        )
        self.assertEqual(order.net_amount, Decimal("12.3400"))

    def test_minimal_read_only_routes_are_registered(self):
        venue_paths = {route.path for route in venue_pos_integrations_router.routes}
        integration_paths = {route.path for route in pos_integrations_router.routes}
        self.assertIn("/{venue_id}/pos-integrations", venue_paths)
        self.assertIn("/pos-integrations/{connection_id}/capabilities", integration_paths)


if __name__ == "__main__":
    unittest.main()
