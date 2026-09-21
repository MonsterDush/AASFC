from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.providers.quickresto.provider import QuickRestoProviderAdapter
from app.services.integrations.quickresto import QUICKRESTO_OBJECT_TYPES, QuickRestoError
from app.services.integrations.quickresto_discovery import discover_quickresto_capabilities


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "quickresto" / "capability_discovery.json"


class _FixtureClient:
    def __init__(
        self,
        fixture: dict,
        *,
        failures: set[str] | None = None,
    ) -> None:
        self.fixture = deepcopy(fixture)
        self.failures = set(failures or ())
        self.calls: list[tuple[str, tuple[dict, ...]]] = []
        self._by_class = {class_name: object_type for object_type, (_, class_name) in QUICKRESTO_OBJECT_TYPES.items()}

    def list_objects(self, *, class_name, filters=(), **_kwargs):
        object_type = self._by_class[class_name]
        self.calls.append((object_type, tuple(filters)))
        if object_type in self.failures:
            raise QuickRestoError("fixture failure containing values that must not leak")
        return deepcopy(self.fixture["lists"].get(object_type, []))

    def read_object(self, *, class_name, **_kwargs):
        object_type = self._by_class[class_name]
        if object_type in self.failures:
            raise QuickRestoError("fixture detail failure containing values that must not leak")
        return deepcopy(self.fixture["details"].get(object_type, {}))

    def fallback_diagnostics(self):
        return ()


class QuickRestoCapabilityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_discovers_only_structurally_evidenced_capabilities(self):
        client = _FixtureClient(self.fixture)

        report = discover_quickresto_capabilities(client, sample_limit=5)

        expected_supported = {
            Capability.CURRENT_BUSINESS_SHIFT,
            Capability.OPEN_ORDERS,
            Capability.TABLES,
            Capability.RESTAURANT_SECTIONS,
            Capability.MODIFIERS,
            Capability.PRODUCT_VARIANTS,
            Capability.EMPLOYEES,
            Capability.INVENTORY,
            Capability.PURCHASES,
            Capability.WRITEOFFS,
        }
        for capability in expected_supported:
            self.assertEqual(report.capabilities[capability].state, CapabilityState.SUPPORTED)
        self.assertEqual(report.capabilities[Capability.CURRENT_ORDER_TOTAL].state, CapabilityState.DERIVED)
        self.assertEqual(report.capabilities[Capability.STOCK_MOVEMENTS].state, CapabilityState.DERIVED)
        self.assertEqual(report.capabilities[Capability.STOCK_BALANCES].state, CapabilityState.UNKNOWN)
        self.assertEqual(report.capabilities[Capability.STOP_LISTS].state, CapabilityState.UNKNOWN)

        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertNotIn("PrivateFixtureName", payload)
        self.assertNotIn("private@example.invalid", payload)
        self.assertNotIn("1234.56", payload)
        self.assertNotIn("fixture failure containing values", payload)
        self.assertIn("frontTotalPrice", payload)
        self.assertFalse(report.to_dict()["contains_payload_values"])
        self.assertTrue(
            any(
                object_type == "orders" and filters[0]["value"] == "OPEN"
                for object_type, filters in client.calls
                if filters
            )
        )

    def test_failed_surface_is_degraded_without_aborting_other_probes(self):
        report = discover_quickresto_capabilities(
            _FixtureClient(self.fixture, failures={"modifiers"}),
            sample_limit=3,
        )

        self.assertEqual(report.capabilities[Capability.MODIFIERS].state, CapabilityState.DEGRADED)
        self.assertEqual(report.capabilities[Capability.EMPLOYEES].state, CapabilityState.SUPPORTED)
        self.assertEqual(report.capabilities[Capability.INVENTORY].state, CapabilityState.SUPPORTED)
        modifier_surface = next(surface for surface in report.surfaces if surface.surface == "modifiers")
        self.assertEqual(modifier_surface.error_code, "PROVIDER_REQUEST")
        self.assertNotIn("fixture failure", json.dumps(report.to_dict()))

    def test_global_transport_failure_opens_circuit_without_losing_matrix_rows(self):
        class _TimeoutClient(_FixtureClient):
            def list_objects(self, **kwargs):
                self.calls.append(("global-timeout", ()))
                try:
                    raise TimeoutError("private transport detail")
                except TimeoutError as exc:
                    raise QuickRestoError("safe wrapper") from exc

        client = _TimeoutClient(self.fixture)

        report = discover_quickresto_capabilities(client)

        self.assertEqual(len(client.calls), 1)
        self.assertGreaterEqual(len(report.surfaces), 10)
        self.assertTrue(all(surface.error_code == "TIMEOUT" for surface in report.surfaces))
        self.assertEqual(report.capabilities[Capability.EMPLOYEES].state, CapabilityState.DEGRADED)
        self.assertEqual(report.capabilities[Capability.STOP_LISTS].state, CapabilityState.UNKNOWN)
        payload = json.dumps(report.to_dict())
        self.assertNotIn("private transport detail", payload)
        self.assertNotIn("Employee read-only endpoint responded", payload)
        self.assertNotIn("inventory_documents read-only endpoint responded", payload)

    def test_open_status_filter_mismatch_is_not_reported_supported(self):
        fixture = deepcopy(self.fixture)
        fixture["lists"]["shifts"][0]["status"] = "CLOSED"
        fixture["lists"]["orders"][0]["status"] = "CLOSED"

        report = discover_quickresto_capabilities(_FixtureClient(fixture))

        self.assertEqual(report.capabilities[Capability.CURRENT_BUSINESS_SHIFT].state, CapabilityState.DEGRADED)
        self.assertEqual(report.capabilities[Capability.OPEN_ORDERS].state, CapabilityState.DEGRADED)
        self.assertEqual(report.capabilities[Capability.CURRENT_ORDER_TOTAL].state, CapabilityState.DEGRADED)
        self.assertEqual(
            report.capabilities[Capability.OPEN_ORDERS].last_error_code,
            "FILTER_NOT_VERIFIED",
        )

    def test_adapter_caches_extended_probe_without_changing_legacy_reader(self):
        adapter = QuickRestoProviderAdapter(_FixtureClient(self.fixture))

        health = adapter.verify_credentials()
        report = adapter.probe_extended_capabilities(sample_limit=2)
        capabilities = adapter.get_capabilities()

        self.assertTrue(health.healthy)
        self.assertEqual(capabilities[Capability.TABLES].state, CapabilityState.SUPPORTED)
        self.assertEqual(capabilities[Capability.STOP_LISTS].state, CapabilityState.UNKNOWN)
        self.assertEqual(capabilities[Capability.TABLES], report.capabilities[Capability.TABLES])

    def test_official_api_292_object_type_names_are_pinned(self):
        expected = {
            "employees": ("personnel.employee", "Employee"),
            "modifier_groups": ("warehouse.nomenclature.mods", "ModifierGroup"),
            "modifiers": ("warehouse.nomenclature.mods", "Modifier"),
            "inventory_documents": ("warehouse.inventory.document.v2", "InventoryDocument2"),
            "incoming_invoices": ("warehouse.documents.incoming", "IncomingInvoice"),
            "discard_invoices": ("warehouse.documents.discard", "DiscardInvoice"),
        }
        for object_type, (module_name, class_suffix) in expected.items():
            actual_module, actual_class = QUICKRESTO_OBJECT_TYPES[object_type]
            self.assertEqual(actual_module, module_name)
            self.assertTrue(actual_class.endswith(class_suffix))


if __name__ == "__main__":
    unittest.main()
