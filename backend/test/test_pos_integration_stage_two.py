from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.integrations.base import (
    POSCapability,
    POSProvider,
    POSProviderCode,
    ProviderHealth,
    ProviderPage,
    ProviderRecord,
    decrypt_credentials,
)
from app.integrations.normalization import IikoP0Normalizer, NormalizationContext, QuickRestoP0Normalizer
from app.integrations.employee_mapping import suggest_employee_mappings
from app.integrations.providers.iiko import IikoClient, IikoConfig, IikoPOSProvider
from app.integrations.providers.quick_resto import QuickRestoPOSProvider
from app.integrations.providers.register import register_p0_providers
from app.integrations.registry import POSProviderRegistry
from app.integrations.reconciliation import (
    CanonicalReadSwitchError,
    canonical_metrics,
    enable_canonical_reads,
    reconcile_connection,
    rollback_to_legacy_reads,
)
from app.integrations.sync import synchronize_capability
from app.models.integration_connection import IntegrationConnection
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.pos_canonical import (
    POSEmployee,
    POSEmployeeMapping,
    POSOrder,
    POSOrderDiscount,
    POSOrderEvent,
    POSOrderItem,
    POSPayment,
    POSProduct,
    POSProductGroup,
    POSRefund,
)
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.models.venue_pos_integration_selection import VenuePOSIntegrationSelection
from app.routers.venue_pos_integrations import confirm_pos_employee_mapping, put_iiko_connection
from app.schemas.pos_integrations import IikoConnectionUpsertIn, POSEmployeeMappingConfirmIn
from app.services.integrations.pos_provider_selection import active_pos_provider


FIXTURES = Path(__file__).parent / "fixtures" / "pos"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class ProviderAdapterTests(unittest.TestCase):
    def test_stage_two_registers_both_p0_adapters(self):
        registry = register_p0_providers(POSProviderRegistry())

        self.assertEqual(registry.registered_codes(), (POSProviderCode.IIKO, POSProviderCode.QUICK_RESTO))

    def test_quickresto_adapter_uses_offset_cursor_and_reads_order_details(self):
        client = Mock()
        client.list_objects.return_value = [{"id": 7, "frontId": "order-7"}]
        client.read_object.return_value = {
            "id": 7,
            "frontId": "order-7",
            "status": "CLOSED",
            "updated": "2030-01-02T11:00:00Z",
        }
        provider = QuickRestoPOSProvider({"cloud": "unused"}, client=client, page_size=1)

        page = provider.get_orders(cursor="5")

        self.assertEqual(page.records[0].external_id, "order-7")
        self.assertEqual(page.next_cursor, "6")
        self.assertEqual(page.records[0].source_updated_at, datetime(2030, 1, 2, 11, tzinfo=timezone.utc))
        self.assertEqual(client.list_objects.call_args.kwargs["offset"], 5)
        client.read_object.assert_called_once()

    def test_iiko_client_uses_official_auth_and_organization_paths(self):
        token_response = Mock(status_code=200)
        token_response.json.return_value = {"token": "secret-token"}
        organizations_response = Mock(status_code=200)
        organizations_response.json.return_value = {"organizations": [{"id": "org-1", "name": "Cafe"}]}
        session = Mock()
        session.headers = {}
        session.post.side_effect = [token_response, organizations_response]
        client = IikoClient(IikoConfig(api_login="login"), session=session)

        result = client.organizations()

        self.assertEqual(result["organizations"][0]["id"], "org-1")
        self.assertTrue(session.post.call_args_list[0].args[0].endswith("/api/1/access_token"))
        self.assertTrue(session.post.call_args_list[1].args[0].endswith("/api/1/organizations"))
        self.assertEqual(session.post.call_args_list[1].kwargs["headers"], {"Authorization": "Bearer secret-token"})

    def test_iiko_config_rejects_external_or_traversing_export_endpoints(self):
        for endpoint in ("https://example.com/api/1/sales", "/api/1/../access_token", "/api/1/sales?all=1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                IikoConfig(api_login="login", sales_endpoint=endpoint)

    def test_iiko_capabilities_do_not_claim_sales_without_export_endpoint(self):
        provider = IikoPOSProvider({"api_login": "login", "organization_id": "org-1"}, client=Mock())

        capabilities = provider.detect_capabilities()

        self.assertTrue(capabilities[POSCapability.PRODUCTS].available)
        self.assertFalse(capabilities[POSCapability.SALES].available)
        self.assertEqual(
            capabilities[POSCapability.SALES].details["reason"],
            "sales_endpoint_not_configured",
        )


class ProviderGoldenNormalizationTests(unittest.TestCase):
    def test_quickresto_and_iiko_golden_orders_produce_the_same_acdm(self):
        quickresto_payload = json.loads((FIXTURES / "quickresto_golden.json").read_text(encoding="utf-8"))
        iiko_payload = json.loads((FIXTURES / "iiko_golden.json").read_text(encoding="utf-8"))
        updated_at = datetime(2030, 1, 2, 8, tzinfo=timezone.utc)
        quick_context = NormalizationContext(
            integration_connection_id=1,
            venue_id=1,
            provider=POSProviderCode.QUICK_RESTO,
            normalization_version="quickresto-p0-v1",
        )
        iiko_context = NormalizationContext(
            integration_connection_id=2,
            venue_id=1,
            provider=POSProviderCode.IIKO,
            normalization_version="iiko-p0-v1",
        )

        quick = QuickRestoP0Normalizer().normalize_orders(
            ProviderRecord(external_id="order-1", payload=quickresto_payload, source_updated_at=updated_at),
            context=quick_context,
        )[0]
        iiko = IikoP0Normalizer().normalize_orders(
            ProviderRecord(external_id="order-1", payload=iiko_payload, source_updated_at=updated_at),
            context=iiko_context,
        )[0]

        self.assertEqual(asdict(quick), asdict(iiko))
        self.assertEqual(len(quick.items), 3)
        self.assertEqual(sum(not item.is_modifier for item in quick.items), 2)
        self.assertEqual(sum(item.is_modifier for item in quick.items), 1)
        self.assertEqual(len(quick.discounts), 1)
        self.assertEqual(len(quick.payments), 2)
        self.assertEqual(quick.waiter_external_id, "employee-1")


class _PagedOrderProvider(POSProvider):
    provider_code = POSProviderCode.QUICK_RESTO

    def authenticate(self) -> None:
        return None

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, checked_at=datetime.now(timezone.utc))

    def detect_capabilities(self):
        return {}

    def get_orders(self, *, updated_since=None, cursor=None) -> ProviderPage:
        del updated_since
        payload = json.loads((FIXTURES / "quickresto_golden.json").read_text(encoding="utf-8"))
        if cursor is None:
            payload["id"] = payload["frontId"] = "order-1"
            return ProviderPage(
                records=(
                    ProviderRecord(
                        external_id="order-1",
                        payload=payload,
                        source_updated_at=datetime(2030, 1, 2, 8, tzinfo=timezone.utc),
                    ),
                ),
                next_cursor="page-2",
            )
        if cursor == "page-2":
            payload["id"] = payload["frontId"] = "order-2"
            return ProviderPage(
                records=(
                    ProviderRecord(
                        external_id="order-2",
                        payload=payload,
                        source_updated_at=datetime(2030, 1, 2, 9, tzinfo=timezone.utc),
                    ),
                )
            )
        raise AssertionError(cursor)


class _UpdatedOrderProvider(_PagedOrderProvider):
    def get_orders(self, *, updated_since=None, cursor=None) -> ProviderPage:
        del updated_since
        if cursor is not None:
            raise AssertionError(cursor)
        payload = json.loads((FIXTURES / "quickresto_golden.json").read_text(encoding="utf-8"))
        payload["payments"] = payload["payments"][:1]
        payload["orderItemList"] = payload["orderItemList"][:1]
        return ProviderPage(
            records=(
                ProviderRecord(
                    external_id="order-1",
                    payload=payload,
                    source_updated_at=datetime(2030, 1, 2, 10, tzinfo=timezone.utc),
                ),
            )
        )


class StageTwoPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Venue.__table__,
                VenueMember.__table__,
                VenuePOSIntegrationSelection.__table__,
                IntegrationConnection.__table__,
                IntegrationCapabilityState.__table__,
                IntegrationRawObject.__table__,
                IntegrationQuarantine.__table__,
                IntegrationSyncCursor.__table__,
                IntegrationReconciliationRun.__table__,
                POSEmployee.__table__,
                POSEmployeeMapping.__table__,
                POSProductGroup.__table__,
                POSProduct.__table__,
                POSOrder.__table__,
                POSOrderItem.__table__,
                POSOrderEvent.__table__,
                POSPayment.__table__,
                POSRefund.__table__,
                POSOrderDiscount.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.connection = IntegrationConnection(
            id=1,
            venue_id=1,
            provider="QUICK_RESTO",
            status="ACTIVE",
        )
        self.db.add_all([Venue(id=1, name="Test", timezone="Europe/Moscow"), self.connection])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_paginated_sync_is_idempotent_and_persists_cursor_watermark_and_raw_payloads(self):
        result = synchronize_capability(
            self.db,
            connection=self.connection,
            provider=_PagedOrderProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.SALES,
        )

        self.assertEqual(result.pages, 2)
        self.assertEqual(result.records_seen, 2)
        self.assertEqual(self.db.scalar(select(func.count(POSOrder.id))), 2)
        self.assertEqual(self.db.scalar(select(func.count(IntegrationRawObject.id))), 2)
        cursor = self.db.scalar(select(IntegrationSyncCursor))
        self.assertEqual(cursor.status, "SUCCEEDED")
        self.assertIsNone(cursor.cursor)
        self.assertEqual(cursor.watermark_at.replace(tzinfo=timezone.utc), datetime(2030, 1, 2, 9, tzinfo=timezone.utc))

        second = synchronize_capability(
            self.db,
            connection=self.connection,
            provider=_PagedOrderProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.SALES,
        )
        self.assertEqual(second.records_changed, 0)
        self.assertEqual(self.db.scalar(select(func.count(POSOrder.id))), 2)

    def test_order_snapshot_removes_stale_items_and_payments(self):
        synchronize_capability(
            self.db,
            connection=self.connection,
            provider=_PagedOrderProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.SALES,
        )

        synchronize_capability(
            self.db,
            connection=self.connection,
            provider=_UpdatedOrderProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.SALES,
        )

        order = self.db.scalar(select(POSOrder).where(POSOrder.external_id == "order-1"))
        self.assertEqual(
            self.db.scalar(select(func.count(POSOrderItem.id)).where(POSOrderItem.order_id == order.id)),
            2,
        )
        self.assertEqual(
            self.db.scalar(select(func.count(POSPayment.id)).where(POSPayment.order_id == order.id)),
            1,
        )

    def test_read_switch_requires_green_reconciliation_and_has_immediate_rollback(self):
        synchronize_capability(
            self.db,
            connection=self.connection,
            provider=_PagedOrderProvider(),
            normalizer=QuickRestoP0Normalizer(),
            capability=POSCapability.SALES,
        )
        with self.assertRaises(CanonicalReadSwitchError):
            enable_canonical_reads(self.db, connection=self.connection)

        metrics = canonical_metrics(
            self.db,
            connection_id=1,
            period_start=date(2030, 1, 2),
            period_end=date(2030, 1, 2),
        )
        run = reconcile_connection(
            self.db,
            connection=self.connection,
            period_start=date(2030, 1, 2),
            period_end=date(2030, 1, 2),
            source=metrics,
        )
        self.assertEqual(run.status, "OK")
        self.connection.historical_sync_status = "COMPLETED"
        self.connection.coverage_start = date(2030, 1, 2)
        self.connection.coverage_end = date(2030, 1, 2)

        member_user = User(id=3, full_name="Мария Орлова", system_role="NONE")
        member = VenueMember(id=3, venue_id=1, user_id=3, venue_role="STAFF", is_active=True)
        employee = POSEmployee(
            connection_id=1,
            external_id="employee-maria",
            name="Мария Орлова",
            active=True,
        )
        self.db.add_all([member_user, member, employee])
        self.db.flush()
        order = self.db.scalar(select(POSOrder).where(POSOrder.external_id == "order-1"))
        order.waiter_pos_employee_id = employee.id
        mapping = POSEmployeeMapping(
            pos_employee_id=employee.id,
            venue_member_id=member.id,
            match_type="EXACT_NAME",
            confidence=1,
            confirmed=False,
        )
        self.db.add(mapping)
        self.db.flush()
        with self.assertRaises(CanonicalReadSwitchError):
            enable_canonical_reads(self.db, connection=self.connection)

        mapping.confirmed = True
        self.db.flush()
        enable_canonical_reads(self.db, connection=self.connection)
        self.assertEqual(self.connection.read_mode, "CANONICAL")
        rollback_to_legacy_reads(self.connection)
        self.assertEqual(self.connection.read_mode, "LEGACY")
        self.assertIsNone(self.connection.canonical_read_enabled_at)

    def test_employee_mapping_is_suggested_but_never_auto_confirmed(self):
        member_user = User(id=2, full_name="Анна Смирнова", system_role="SUPER_ADMIN")
        self.db.add_all(
            [
                member_user,
                VenueMember(id=2, venue_id=1, user_id=2, venue_role="STAFF", is_active=True),
                POSEmployee(
                    connection_id=1,
                    external_id="employee-anna",
                    name="Анна Смирнова",
                    active=True,
                ),
            ]
        )
        self.db.commit()

        suggested = suggest_employee_mappings(self.db, connection_id=1, venue_id=1)
        mapping = self.db.scalar(select(POSEmployeeMapping))

        self.assertEqual(suggested, 1)
        self.assertEqual(mapping.venue_member_id, 2)
        self.assertEqual(mapping.match_type, "EXACT_NAME")
        self.assertFalse(mapping.confirmed)

        response = confirm_pos_employee_mapping(
            1,
            "quickresto",
            mapping.pos_employee_id,
            POSEmployeeMappingConfirmIn(venue_member_id=2),
            db=self.db,
            user=member_user,
        )
        self.assertTrue(response["mapping"]["confirmed"])
        self.assertEqual(mapping.match_type, "MANUAL")

    def test_iiko_management_api_encrypts_secrets_and_preserves_omitted_endpoints(self):
        self.db.add(Venue(id=2, name="iiko", timezone="Europe/Moscow"))
        self.db.commit()
        user = User(id=99, system_role="SUPER_ADMIN")

        created = put_iiko_connection(
            2,
            IikoConnectionUpsertIn(
                api_login="secret-login",
                organization_id="org-1",
                sales_endpoint="/api/1/export/sales",
                employees_endpoint="/api/1/export/employees",
                is_active=True,
            ),
            db=self.db,
            user=user,
        )

        connection = self.db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.venue_id == 2,
                IntegrationConnection.provider == "IIKO",
            )
        )
        self.assertEqual(created["active_pos_provider"], "IIKO")
        self.assertEqual(active_pos_provider(self.db, venue_id=2), "IIKO")
        self.assertNotIn("secret-login", connection.credentials_encrypted)
        self.assertNotIn("credentials_encrypted", created["connection"])

        updated = put_iiko_connection(
            2,
            IikoConnectionUpsertIn(organization_id="org-2", is_active=True),
            db=self.db,
            user=user,
        )
        restored = decrypt_credentials(connection.credentials_encrypted)
        self.assertEqual(restored["api_login"], "secret-login")
        self.assertEqual(restored["sales_endpoint"], "/api/1/export/sales")
        self.assertEqual(restored["employees_endpoint"], "/api/1/export/employees")
        self.assertEqual(updated["connection"]["external_organization_id"], "org-2")


if __name__ == "__main__":
    unittest.main()
