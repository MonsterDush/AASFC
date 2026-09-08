from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.integrations.base import (
    CapabilityAuditResult,
    POSCapability,
    POSCapabilityStatus,
    POSCapabilityUnavailableError,
    POSProvider,
    POSProviderCode,
    POSProviderRegistrationError,
    ProviderHealth,
    ProviderPage,
    ProviderRecord,
    decrypt_credentials,
    encrypt_credentials,
    serialize_capability_audit,
)
from app.integrations.normalization import NormalizationContext
from app.integrations.raw import mark_raw_object_normalized, store_raw_object
from app.integrations.registry import POSProviderRegistry
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.pos_canonical import (
    POSOrder,
    POSOrderItem,
    POSPayment,
    POSProduct,
    POSRefund,
)
from app.models.venue import Venue
from app.services.integrations import credentials as legacy_credentials


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class FakeProvider(POSProvider):
    provider_code = POSProviderCode.QUICK_RESTO

    def __init__(self, connection):
        self.connection = connection

    def authenticate(self) -> None:
        return None

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, checked_at=datetime.now(timezone.utc))

    def detect_capabilities(self):
        checked_at = datetime.now(timezone.utc)
        return {
            POSCapability.SALES: CapabilityAuditResult(
                capability=POSCapability.SALES,
                status=POSCapabilityStatus.AVAILABLE,
                checked_at=checked_at,
            )
        }

    def get_orders(self, *, updated_since=None, cursor=None) -> ProviderPage:
        return ProviderPage(records=(ProviderRecord(external_id="order-1", payload={"total": 100}),))


class POSIntegrationContractTests(unittest.TestCase):
    def test_registry_normalizes_alias_and_does_not_overwrite_provider(self):
        registry = POSProviderRegistry()
        registry.register("quickresto", FakeProvider)

        provider = registry.create("QUICK_RESTO", connection={"id": 1})

        self.assertIsInstance(provider, FakeProvider)
        self.assertEqual(provider.get_orders().records[0].external_id, "order-1")
        with self.assertRaises(POSCapabilityUnavailableError):
            provider.get_products()
        with self.assertRaises(POSProviderRegistrationError):
            registry.register(POSProviderCode.QUICK_RESTO, FakeProvider)

    def test_capability_audit_is_explicit_and_serializable(self):
        checked_at = datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc)
        result = CapabilityAuditResult(
            capability=POSCapability.PAYMENTS,
            status=POSCapabilityStatus.DEGRADED,
            checked_at=checked_at,
            details={"missing": ["refund_reason"]},
        )

        serialized = serialize_capability_audit({POSCapability.PAYMENTS: result})

        self.assertTrue(result.available)
        self.assertEqual(serialized["PAYMENTS"]["status"], "DEGRADED")
        with self.assertRaises(TypeError):
            result.details["unexpected"] = True
        with self.assertRaises(ValueError):
            CapabilityAuditResult(
                capability=POSCapability.SALES,
                status=POSCapabilityStatus.AVAILABLE,
                checked_at=datetime(2030, 1, 2),
            )

    def test_credential_bundle_is_encrypted_and_round_trips(self):
        source = {"login": "api-user", "password": "not-plaintext", "cloud": "example"}
        with patch.object(legacy_credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "k" * 48):
            encrypted = encrypt_credentials(source)
            restored = decrypt_credentials(encrypted)

        self.assertTrue(encrypted.startswith("v1:"))
        self.assertNotIn("not-plaintext", encrypted)
        self.assertEqual(restored, source)

    def test_normalization_context_rejects_ambiguous_scope(self):
        context = NormalizationContext(
            integration_connection_id=10,
            venue_id=20,
            provider=POSProviderCode.IIKO,
            normalization_version="iiko-orders-v1",
        )
        self.assertEqual(context.provider, POSProviderCode.IIKO)
        with self.assertRaises(ValueError):
            NormalizationContext(
                integration_connection_id=0,
                venue_id=20,
                provider=POSProviderCode.IIKO,
                normalization_version="v1",
            )


class POSIntegrationPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                Venue.__table__,
                IntegrationConnection.__table__,
                IntegrationRawObject.__table__,
                POSProduct.__table__,
                POSOrder.__table__,
                POSOrderItem.__table__,
                POSPayment.__table__,
                POSRefund.__table__,
            ],
        )
        self.db = Session(self.engine)
        venue = Venue(id=1, name="Foundation test", timezone="Europe/Moscow")
        connection = IntegrationConnection(
            id=1,
            venue_id=1,
            provider="QUICK_RESTO",
            status="ACTIVE",
        )
        self.db.add_all([venue, connection])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_raw_storage_is_lossless_idempotent_and_reopens_changed_payload(self):
        observed_at = datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc)
        first, changed = store_raw_object(
            self.db,
            integration_connection_id=1,
            entity_type="order",
            external_id="42",
            payload={"total": "123.45", "items": [{"id": 1}]},
            received_at=observed_at,
        )
        self.assertTrue(changed)
        mark_raw_object_normalized(first, normalization_version="orders-v1", normalized_at=observed_at)
        self.db.commit()

        same, changed = store_raw_object(
            self.db,
            integration_connection_id=1,
            entity_type="ORDER",
            external_id="42",
            payload={"items": [{"id": 1}], "total": "123.45"},
            received_at=observed_at,
        )
        self.assertFalse(changed)
        self.assertEqual(same.id, first.id)
        self.assertEqual(same.normalization_version, "orders-v1")

        changed_row, changed = store_raw_object(
            self.db,
            integration_connection_id=1,
            entity_type="ORDER",
            external_id="42",
            payload={"items": [{"id": 1}], "total": "124.00"},
            received_at=observed_at,
        )
        self.assertTrue(changed)
        self.assertIsNone(changed_row.normalized_at)
        self.assertIsNone(changed_row.normalization_version)
        self.assertEqual(changed_row.payload_json["total"], "124.00")

    def test_p0_sales_entities_preserve_decimal_values_and_refunds(self):
        product = POSProduct(
            connection_id=1,
            external_id="product-1",
            name="Coffee",
            type="DISH",
        )
        order = POSOrder(
            venue_id=1,
            source="QUICK_RESTO",
            connection_id=1,
            external_id="order-1",
            business_date=date(2030, 1, 2),
            calendar_date=date(2030, 1, 2),
            status="PARTIALLY_REFUNDED",
            subtotal=Decimal("250.100000"),
            discount_amount=Decimal("0"),
            service_charge=Decimal("0"),
            delivery_fee=Decimal("0"),
            total_amount=Decimal("250.100000"),
            refund_amount=Decimal("50.050000"),
            synced_at=datetime.now(timezone.utc),
        )
        self.db.add_all([product, order])
        self.db.flush()
        self.db.add_all(
            [
                POSOrderItem(
                    order_id=order.id,
                    external_id="item-1",
                    product_id=product.id,
                    product_name_snapshot="Coffee",
                    quantity=Decimal("1.500000000"),
                    base_price=Decimal("166.733333"),
                    final_price=Decimal("166.733333"),
                    gross_amount=Decimal("250.100000"),
                    discount_amount=Decimal("0"),
                    net_amount=Decimal("250.100000"),
                ),
                POSPayment(
                    order_id=order.id,
                    external_id="payment-1",
                    canonical_type="CARD",
                    amount=Decimal("250.100000"),
                ),
                POSRefund(
                    order_id=order.id,
                    external_id="refund-1",
                    amount=Decimal("50.050000"),
                    reason="Guest request",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(order)

        self.assertEqual(order.total_amount, Decimal("250.100000"))
        self.assertEqual(order.refunds[0].amount, Decimal("50.050000"))


if __name__ == "__main__":
    unittest.main()
