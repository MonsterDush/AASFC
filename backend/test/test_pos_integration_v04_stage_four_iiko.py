from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.base.credentials import ProviderCredentials
from app.integrations.providers.iiko.master_data_sync import (
    NORMALIZATION_VERSION,
    replay_iiko_master_data_raw,
    sync_iiko_master_data,
)
from app.integrations.providers.iiko.provider import (
    IIKOProviderAdapter,
    register_iiko_provider,
)
from app.integrations.raw.storage import load_raw_payload
from app.integrations.registry import ProviderRegistry
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.pos_canonical import (
    POSModifier,
    POSModifierGroup,
    POSOrganization,
    POSPaymentType,
    POSProduct,
    POSProductGroup,
    POSProductModifierRule,
    POSProductVariant,
    POSRestaurantSection,
    POSStopListEntry,
    POSTable,
    POSTerminalGroup,
    POSVenue,
)
from app.services.integrations.iiko import IIKOClient, IIKOConfig


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "iiko" / "stage4_master_data.json"
_API_MATRIX_PATH = Path(__file__).parents[1] / "docs" / "integrations" / "iiko-api-matrix.md"


class _Response:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = int(status_code)
        self._payload = payload

    def json(self):
        return deepcopy(self._payload)


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **deepcopy(kwargs)})
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class _StageFourClient:
    def __init__(self) -> None:
        self.fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        self.config = SimpleNamespace(timeout_seconds=20.0)
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def organizations(self, *, include_disabled=False):
        del include_disabled
        return deepcopy(self.fixture["organizations"])

    def terminal_groups(self, organization_ids, *, include_disabled=False):
        del include_disabled
        self._assert_organizations(organization_ids)
        return deepcopy(self.fixture["terminal_groups"])

    def terminal_groups_alive(self, organization_ids, terminal_group_ids):
        self._assert_organizations(organization_ids)
        self._assert_terminal_groups(terminal_group_ids)
        return deepcopy(self.fixture["terminal_groups_alive"])

    def nomenclature(self, organization_id, *, start_revision=0):
        self._assert_organizations([organization_id])
        self._assert_equal(start_revision, 0)
        return deepcopy(self.fixture["nomenclature"])

    def payment_types(self, organization_ids):
        self._assert_organizations(organization_ids)
        return deepcopy(self.fixture["payment_types"])

    def order_types(self, organization_ids):
        self._assert_organizations(organization_ids)
        return [{"id": "order-type-1", "name": "В зале"}]

    def discounts(self, organization_ids):
        self._assert_organizations(organization_ids)
        return [{"id": "discount-1", "name": "Скидка 10%"}]

    def cancel_causes(self, organization_ids):
        self._assert_organizations(organization_ids)
        return [{"id": "cancel-1", "name": "Отмена гостем"}]

    def removal_types(self, organization_ids):
        self._assert_organizations(organization_ids)
        return [{"id": "removal-1", "name": "Ошибка ввода"}]

    def tips_types(self):
        return [{"id": "tips-1", "name": "Чаевые"}]

    def marketing_sources(self, organization_ids):
        self._assert_organizations(organization_ids)
        return [{"id": "marketing-1", "name": "Сайт"}]

    def stop_lists(self, organization_ids, *, terminal_group_ids=(), return_size=True):
        self._assert_organizations(organization_ids)
        if terminal_group_ids:
            self._assert_terminal_groups(terminal_group_ids)
        self._assert_equal(return_size, True)
        return deepcopy(self.fixture["stop_lists"])

    def restaurant_sections(self, terminal_group_ids, *, revision=None, return_schema=False):
        self._assert_terminal_groups(terminal_group_ids)
        self._assert_equal(revision, None)
        self._assert_equal(return_schema, False)
        return deepcopy(self.fixture["restaurant_sections"])

    @staticmethod
    def _assert_organizations(values):
        if list(values) != ["org-1"]:
            raise AssertionError(values)

    @staticmethod
    def _assert_terminal_groups(values):
        if list(values) != ["tg-1"]:
            raise AssertionError(values)

    @staticmethod
    def _assert_equal(actual, expected):
        if actual != expected:
            raise AssertionError((actual, expected))


class IIKOClientTests(unittest.TestCase):
    def test_token_is_cached_and_never_added_to_request_body(self):
        session = _Session(
            [
                _Response(200, {"correlationId": "c-auth", "token": "secret-token"}),
                _Response(200, {"correlationId": "c-org-1", "organizations": []}),
                _Response(200, {"correlationId": "c-org-2", "organizations": []}),
            ]
        )
        client = IIKOClient(
            IIKOConfig(api_login="secret-api-login"),
            session=session,
            monotonic=lambda: 100.0,
        )

        self.assertEqual(client.organizations(), [])
        self.assertEqual(client.organizations(), [])

        self.assertEqual(len(session.calls), 3)
        self.assertTrue(session.calls[0]["url"].endswith("/api/1/access_token"))
        self.assertEqual(session.calls[0]["json"], {"apiLogin": "secret-api-login"})
        self.assertEqual(session.calls[1]["headers"]["Authorization"], "Bearer secret-token")
        self.assertNotIn("secret-token", json.dumps(session.calls[1]["json"]))
        self.assertEqual(session.calls[2]["headers"]["Authorization"], "Bearer secret-token")

    def test_expired_bearer_is_refreshed_once(self):
        session = _Session(
            [
                _Response(200, {"correlationId": "c-auth-1", "token": "old-token"}),
                _Response(401, {"error": "expired"}),
                _Response(200, {"correlationId": "c-auth-2", "token": "new-token"}),
                _Response(200, {"correlationId": "c-org", "organizations": []}),
            ]
        )
        client = IIKOClient(IIKOConfig(api_login="api-login"), session=session)

        self.assertEqual(client.organizations(), [])
        self.assertEqual(session.calls[-1]["headers"]["Authorization"], "Bearer new-token")

    def test_modern_v2_credentials_use_the_v2_authorization_contract(self):
        session = _Session(
            [
                _Response(200, {"correlationId": "c-auth", "token": "v2-token"}),
                _Response(200, {"correlationId": "c-org", "organizations": []}),
            ]
        )
        client = IIKOClient(
            IIKOConfig(
                api_key="saved-api-key",
                app_id="saved-app-id",
                client_secret="saved-client-secret",
            ),
            session=session,
        )

        self.assertEqual(client.organizations(), [])

        self.assertEqual(client.config.auth_version, "v2")
        self.assertTrue(session.calls[0]["url"].endswith("/api/v2/access_token"))
        self.assertEqual(
            session.calls[0]["json"],
            {
                "apiKey": "saved-api-key",
                "appId": "saved-app-id",
                "clientSecret": "saved-client-secret",
            },
        )
        self.assertEqual(session.calls[1]["headers"]["Authorization"], "Bearer v2-token")
        self.assertNotIn("saved-client-secret", json.dumps(session.calls[1]["json"]))

    def test_partial_v2_credentials_are_rejected_without_disabling_v1(self):
        with self.assertRaisesRegex(ValueError, "api_key, app_id and client_secret"):
            IIKOConfig(api_key="api-key", app_id="app-id")

        self.assertEqual(IIKOConfig(api_login="legacy-login").auth_version, "v1")


class IIKOStageFourProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _StageFourClient()
        self.adapter = IIKOProviderAdapter(
            self.client,
            organization_id="org-1",
            terminal_group_ids=("tg-1",),
        )

    def test_discovery_preserves_multi_scope_and_alive_state(self):
        scope = self.adapter.discover_scope()

        self.assertEqual([item.external_id for item in scope.organizations], ["org-1"])
        self.assertEqual([item.external_id for item in scope.external_venues], ["org-1"])
        self.assertEqual([item.external_id for item in scope.terminal_groups], ["tg-1"])
        self.assertIs(scope.terminal_groups[0].payload["isAlive"], True)

    def test_master_data_is_exposed_as_provider_neutral_records(self):
        groups = tuple(self.adapter.iter_product_groups())
        products = tuple(self.adapter.iter_products())
        variants = tuple(self.adapter.iter_product_variants())
        modifier_groups = tuple(self.adapter.iter_modifier_groups())
        modifiers = tuple(self.adapter.iter_modifiers())
        rules = tuple(self.adapter.iter_product_modifier_rules())
        sections = tuple(self.adapter.iter_restaurant_sections(external_venue_id="org-1"))
        tables = tuple(self.adapter.iter_tables(external_venue_id="org-1"))
        stop_entries = tuple(self.adapter.iter_stop_list_entries())

        self.assertEqual([item.payload["canonicalKind"] for item in groups], ["GROUP", "CATEGORY"])
        self.assertEqual([item.external_id for item in products], ["product-latte"])
        self.assertEqual([item.external_id for item in variants], ["product-latte:size-large"])
        self.assertEqual([item.external_id for item in modifier_groups], ["modifier-group-milk"])
        self.assertEqual(
            [item.external_id for item in modifiers],
            ["modifier-syrup", "modifier-oat"],
        )
        self.assertEqual(len(rules), 2)
        self.assertTrue(all(item.source_version == "17" for item in products + variants + modifiers))
        self.assertEqual([item.external_id for item in sections], ["section-main"])
        self.assertEqual(tables[0].payload["restaurantSectionId"], "section-main")
        self.assertEqual(stop_entries[0].external_id, "tg-1:product-latte:size-large")

    def test_capabilities_require_successful_calls_and_future_stages_remain_unknown(self):
        capabilities = self.adapter.get_capabilities()

        for capability in (
            Capability.EXTERNAL_VENUES,
            Capability.PRODUCTS,
            Capability.PRODUCT_GROUPS,
            Capability.PRODUCT_VARIANTS,
            Capability.MODIFIERS,
            Capability.PAYMENTS,
            Capability.STOP_LISTS,
            Capability.RESTAURANT_SECTIONS,
            Capability.TABLES,
            Capability.REVISION_SYNC,
        ):
            self.assertEqual(capabilities[capability].state, CapabilityState.SUPPORTED)
        self.assertEqual(capabilities[Capability.TERMINALS].state, CapabilityState.DERIVED)
        self.assertEqual(capabilities[Capability.OPEN_ORDERS].state, CapabilityState.UNKNOWN)
        self.assertEqual(capabilities[Capability.ORDER_CREATE].state, CapabilityState.UNKNOWN)

    def test_dictionaries_are_kept_separate_from_orders(self):
        dictionaries = self.adapter.iter_dictionaries()

        self.assertEqual(
            set(dictionaries),
            {
                "payment_types",
                "order_types",
                "discounts",
                "cancel_causes",
                "removal_types",
                "tips_types",
                "marketing_sources",
            },
        )
        self.assertEqual(dictionaries["payment_types"][0].external_id, "payment-card")

    def test_registry_builds_focused_iiko_bundle(self):
        registry = ProviderRegistry()
        register_iiko_provider(registry)

        modern_bundle = registry.build_adapters(
            "IIKO",
            ProviderCredentials(
                {
                    "api_key": "not-used-api-key",
                    "app_id": "not-used-app-id",
                    "client_secret": "not-used-client-secret",
                    "organization_id": "org-1",
                    "terminal_group_ids": "tg-1",
                }
            ),
        )
        legacy_bundle = registry.build_adapters(
            "IIKO",
            ProviderCredentials(
                {
                    "api_login": "not-used-legacy-login",
                    "organization_id": "org-1",
                    "terminal_group_ids": "tg-1",
                }
            ),
        )

        self.assertEqual(modern_bundle.discovery.provider_code, "IIKO")
        self.assertIs(modern_bundle.discovery, modern_bundle.reader)
        self.assertIs(modern_bundle.discovery, modern_bundle.operational)
        self.assertEqual(modern_bundle.discovery.client.config.auth_version, "v2")
        self.assertEqual(legacy_bundle.discovery.client.config.auth_version, "v1")

    def test_official_endpoint_matrix_is_complete_and_conservative(self):
        matrix = _API_MATRIX_PATH.read_text(encoding="utf-8")
        operation_rows = [line for line in matrix.splitlines() if line.startswith("| `")]

        self.assertEqual(len(operation_rows), 328)
        self.assertIn("Operations inventoried: **328** across **327** paths.", matrix)
        self.assertIn("`/api/1/nomenclature`", matrix)
        self.assertIn("`/api/1/stop_lists`", matrix)
        self.assertNotIn("| `SUPPORTED` |", matrix)


class IIKOStageFourCanonicalTests(unittest.TestCase):
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
                POSOrganization.__table__,
                POSVenue.__table__,
                POSTerminalGroup.__table__,
                POSProductGroup.__table__,
                POSProduct.__table__,
                POSProductVariant.__table__,
                POSModifierGroup.__table__,
                POSModifier.__table__,
                POSProductModifierRule.__table__,
                POSPaymentType.__table__,
                POSRestaurantSection.__table__,
                POSTable.__table__,
                POSStopListEntry.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.connection().exec_driver_sql(
            "INSERT INTO venues (id, name, timezone) VALUES (21, 'Venue 21', 'Europe/Moscow')"
        )
        self.connection = IntegrationConnection(
            venue_id=21,
            provider="IIKO",
            status="ACTIVE",
            external_organization_id="org-1",
            external_venue_id="org-1",
            read_mode="LEGACY",
        )
        self.db.add(self.connection)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _adapter(self) -> IIKOProviderAdapter:
        return IIKOProviderAdapter(
            _StageFourClient(),
            organization_id="org-1",
            terminal_group_ids=("tg-1",),
        )

    @patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 32)
    def test_raw_first_sync_is_idempotent_linked_and_replayable(self):
        first = sync_iiko_master_data(
            self.db,
            connection=self.connection,
            adapter=self._adapter(),
        )
        second = sync_iiko_master_data(
            self.db,
            connection=self.connection,
            adapter=self._adapter(),
        )

        expected_counts = {
            "organizations": 1,
            "terminal_groups": 1,
            "product_groups": 2,
            "products": 1,
            "product_variants": 1,
            "modifier_groups": 1,
            "modifiers": 2,
            "modifier_rules": 2,
            "payment_types": 1,
            "restaurant_sections": 1,
            "tables": 1,
            "stop_list_entries": 1,
        }
        self.assertEqual(first.counts, expected_counts)
        self.assertEqual(second.counts, expected_counts)
        self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 15)
        for model, expected in (
            (POSOrganization, 1),
            (POSVenue, 1),
            (POSTerminalGroup, 1),
            (POSProductGroup, 2),
            (POSProduct, 1),
            (POSProductVariant, 1),
            (POSModifierGroup, 1),
            (POSModifier, 2),
            (POSProductModifierRule, 2),
            (POSPaymentType, 1),
            (POSRestaurantSection, 1),
            (POSTable, 1),
            (POSStopListEntry, 1),
        ):
            self.assertEqual(self.db.scalar(select(func.count(model.id))), expected)

        product = self.db.scalar(select(POSProduct))
        variant = self.db.scalar(select(POSProductVariant))
        modifier_group = self.db.scalar(select(POSModifierGroup))
        stop_entry = self.db.scalar(select(POSStopListEntry))
        self.assertIsNotNone(product.group_id)
        self.assertIsNotNone(product.category_id)
        self.assertEqual(variant.product_id, product.id)
        self.assertEqual(stop_entry.product_id, product.id)
        self.assertEqual(stop_entry.variant_id, variant.id)
        self.assertEqual(
            self.db.scalar(
                select(func.count(POSModifier.id)).where(POSModifier.modifier_group_id == modifier_group.id)
            ),
            1,
        )
        self.assertEqual(self.connection.read_mode, "LEGACY")

        raw_payment = self.db.scalar(
            select(IntegrationRawObject).where(IntegrationRawObject.entity_type == "IIKO_PAYMENT_TYPE")
        )
        raw_payload = load_raw_payload(raw_payment)
        self.assertNotIn("apiLogin", raw_payload)
        self.assertNotIn("apiKey", raw_payload)
        self.assertNotIn("clientSecret", raw_payload)
        self.assertNotIn("token", json.dumps(raw_payload).lower())

        payment = self.db.scalar(select(POSPaymentType))
        self.db.delete(payment)
        self.db.commit()
        replayed = replay_iiko_master_data_raw(
            self.db,
            raw=raw_payment,
            venue_id=21,
        )
        self.db.commit()
        self.assertEqual(replayed.external_id, "payment-card")
        self.assertEqual(raw_payment.normalization_version, NORMALIZATION_VERSION)
        self.assertIn("POSPaymentType:", raw_payment.canonical_identity)

    @patch.object(settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 32)
    def test_sync_rejects_mismatched_organization_scope(self):
        self.connection.external_organization_id = "org-other"
        self.connection.external_venue_id = "org-other"
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "organization scopes do not match"):
            sync_iiko_master_data(
                self.db,
                connection=self.connection,
                adapter=self._adapter(),
            )

        self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 0)


if __name__ == "__main__":
    unittest.main()
