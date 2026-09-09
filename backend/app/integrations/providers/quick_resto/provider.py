from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Mapping

from app.integrations.base import (
    CapabilityAuditResult,
    POSAuthenticationError,
    POSCapability,
    POSCapabilityStatus,
    POSProvider,
    POSProviderCode,
    ProviderHealth,
    ProviderPage,
    ProviderRecord,
    decrypt_credentials,
)
from app.models.integration_connection import IntegrationConnection
from app.services.integrations.quickresto import (
    QUICKRESTO_OBJECT_TYPES,
    QuickRestoAuthenticationError,
    QuickRestoClient,
    QuickRestoConfig,
    QuickRestoError,
)


_P0_OBJECT_TYPES = {
    **QUICKRESTO_OBJECT_TYPES,
    "products": (
        "warehouse.nomenclature.dish",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.dish.Dish",
    ),
    "employees": (
        "personnel.employee",
        "ru.edgex.quickresto.modules.personnel.employee.Employee",
    ),
}

_EXTENDED_CAPABILITIES = {
    POSCapability.RECIPES,
    POSCapability.WAREHOUSES,
    POSCapability.STOCK_BALANCES,
    POSCapability.STOCK_MOVEMENTS,
    POSCapability.SUPPLIERS,
    POSCapability.PURCHASES,
    POSCapability.WRITEOFFS,
    POSCapability.INVENTORY,
    POSCapability.EMPLOYEE_ATTENDANCE,
}


class QuickRestoPOSProvider(POSProvider):
    provider_code = POSProviderCode.QUICK_RESTO

    def __init__(
        self,
        connection: IntegrationConnection | Mapping[str, Any],
        *,
        client: QuickRestoClient | None = None,
        page_size: int = 500,
    ) -> None:
        self.connection = connection
        self.page_size = max(1, min(int(page_size), 1000))
        credentials = self._credentials(connection)
        self.credentials = credentials
        self._extended_object_types = self._validate_extended_object_types(credentials.get("object_types") or {})
        self._client = client or QuickRestoClient(
            QuickRestoConfig(
                cloud=str(credentials.get("cloud") or ""),
                login=str(credentials.get("login") or ""),
                password=str(credentials.get("password") or ""),
                timeout_seconds=float(credentials.get("timeout_seconds") or 20),
            )
        )

    @staticmethod
    def _credentials(connection: IntegrationConnection | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(connection, Mapping):
            if isinstance(connection.get("credentials"), Mapping):
                return dict(connection["credentials"])
            return dict(connection)
        if not connection.credentials_encrypted:
            raise POSAuthenticationError("QuickResto credentials are missing")
        return decrypt_credentials(connection.credentials_encrypted)

    def authenticate(self) -> None:
        try:
            self._probe_object_type("venues")
        except QuickRestoAuthenticationError as exc:
            raise POSAuthenticationError("QuickResto rejected the credentials") from exc

    def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        checked_at = datetime.now(timezone.utc)
        try:
            self.authenticate()
            return ProviderHealth(ok=True, checked_at=checked_at, latency_ms=int((time.monotonic() - started) * 1000))
        except (QuickRestoError, POSAuthenticationError, ValueError) as exc:
            return ProviderHealth(
                ok=False,
                checked_at=checked_at,
                latency_ms=int((time.monotonic() - started) * 1000),
                message=type(exc).__name__,
            )

    def detect_capabilities(self):
        checked_at = datetime.now(timezone.utc)
        output = {
            capability: CapabilityAuditResult(
                capability=capability,
                status=POSCapabilityStatus.UNAVAILABLE,
                checked_at=checked_at,
                details={"adapter": "quickresto-p0-v1", "reason": "not_supported_by_p0_adapter"},
            )
            for capability in POSCapability
        }
        try:
            self.authenticate()
        except (QuickRestoError, POSAuthenticationError, ValueError) as exc:
            reason = type(exc).__name__
            return {
                capability: CapabilityAuditResult(
                    capability=capability,
                    status=POSCapabilityStatus.UNAVAILABLE,
                    checked_at=checked_at,
                    details={"adapter": "quickresto-p0-v1", "reason": reason},
                )
                for capability in POSCapability
            }
        for capability in (POSCapability.ORGANIZATIONS, POSCapability.VENUES):
            output[capability] = CapabilityAuditResult(
                capability=capability,
                status=POSCapabilityStatus.AVAILABLE,
                checked_at=checked_at,
                details={"adapter": "quickresto-p0-v1"},
            )
        checks = (
            ("sale_places", (POSCapability.TERMINALS,)),
            ("employees", (POSCapability.EMPLOYEES,)),
            ("products", (POSCapability.PRODUCTS,)),
            ("dish_categories", (POSCapability.PRODUCT_GROUPS,)),
            (
                "orders",
                (
                    POSCapability.SALES,
                    POSCapability.ORDER_ITEMS,
                    POSCapability.ORDER_EVENTS,
                    POSCapability.PAYMENTS,
                    POSCapability.DISCOUNTS,
                    POSCapability.REFUNDS,
                    POSCapability.GUEST_COUNT,
                    POSCapability.MODIFIERS,
                ),
            ),
        )
        for key, capabilities in checks:
            try:
                self._probe_object_type(key)
                available = True
                reason = None
            except (QuickRestoError, ValueError, KeyError, TypeError) as exc:
                available = False
                reason = type(exc).__name__
            for capability in capabilities:
                output[capability] = CapabilityAuditResult(
                    capability=capability,
                    status=POSCapabilityStatus.AVAILABLE if available else POSCapabilityStatus.UNAVAILABLE,
                    checked_at=checked_at,
                    details={"adapter": "quickresto-p0-v1", **({"reason": reason} if reason else {})},
                )
        for capability in _EXTENDED_CAPABILITIES:
            if capability.value not in self._extended_object_types:
                reason = "object_type_not_configured"
                available = False
            else:
                try:
                    self._probe_extended_capability(capability)
                    available = True
                    reason = None
                except (QuickRestoError, ValueError, KeyError, TypeError) as exc:
                    available = False
                    reason = type(exc).__name__
            output[capability] = CapabilityAuditResult(
                capability=capability,
                status=POSCapabilityStatus.AVAILABLE if available else POSCapabilityStatus.UNAVAILABLE,
                checked_at=checked_at,
                details={"adapter": "quickresto-p0-p2-v2", **({"reason": reason} if reason else {})},
            )
        return output

    def get_organizations(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("venues", cursor=cursor)

    def get_venues(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("venues", cursor=cursor)

    def get_terminals(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("sale_places", cursor=cursor)

    def get_employees(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("employees", cursor=cursor)

    def get_products(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("products", cursor=cursor)

    def get_product_groups(self, *, cursor: str | None = None) -> ProviderPage:
        return self._page("dish_categories", cursor=cursor)

    def get_orders(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        filters = None
        if updated_since is not None:
            filters = ({"field": "updated", "operation": "gte", "value": self._format_datetime(updated_since)},)
        page = self._page("orders", cursor=cursor, filters=filters, read_details=True)
        return page

    def get_payments(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._nested_order_page("payments", updated_since=updated_since, cursor=cursor)

    def get_refunds(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._nested_order_page("refunds", updated_since=updated_since, cursor=cursor)

    def get_discounts(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._nested_order_page("discounts", updated_since=updated_since, cursor=cursor)

    def get_recipes(self, *, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.RECIPES, cursor=cursor)

    def get_warehouses(self, *, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.WAREHOUSES, cursor=cursor)

    def get_stock_balances(self, *, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.STOCK_BALANCES, cursor=cursor)

    def get_stock_movements(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.STOCK_MOVEMENTS, cursor=cursor, updated_since=updated_since)

    def get_suppliers(self, *, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.SUPPLIERS, cursor=cursor)

    def get_purchases(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.PURCHASES, cursor=cursor, updated_since=updated_since)

    def get_writeoffs(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.WRITEOFFS, cursor=cursor, updated_since=updated_since)

    def get_inventories(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.INVENTORY, cursor=cursor, updated_since=updated_since)

    def get_attendance(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.EMPLOYEE_ATTENDANCE, cursor=cursor, updated_since=updated_since)

    def _page(self, key: str, *, cursor: str | None, filters=None, read_details: bool = False) -> ProviderPage:
        module_name, class_name = _P0_OBJECT_TYPES[key]
        offset = int(cursor or 0)
        if offset < 0:
            raise ValueError("QuickResto cursor must be non-negative")
        rows = self._client.list_objects(
            module_name=module_name,
            class_name=class_name,
            limit=self.page_size,
            offset=offset,
            filters=filters,
            sort_fields=("id",),
            sort_orders=("asc",),
        )
        if read_details:
            rows = [
                self._client.read_object(module_name=module_name, class_name=class_name, object_id=int(row["id"]))
                if int(row.get("id") or 0) > 0
                else row
                for row in rows
            ]
        records = tuple(self._record(row, fallback=f"{key}:{offset + index}") for index, row in enumerate(rows))
        next_cursor = str(offset + len(rows)) if len(rows) == self.page_size else None
        return ProviderPage(records=records, next_cursor=next_cursor)

    def _probe_object_type(self, key: str) -> None:
        module_name, class_name = _P0_OBJECT_TYPES[key]
        self._client.list_objects(
            module_name=module_name,
            class_name=class_name,
            limit=1,
            offset=0,
            sort_fields=("id",),
            sort_orders=("asc",),
        )

    def _probe_extended_capability(self, capability: POSCapability) -> None:
        module_name, class_name = self._extended_object_types[capability.value]
        self._client.list_objects(
            module_name=module_name,
            class_name=class_name,
            limit=1,
            offset=0,
            sort_fields=("id",),
            sort_orders=("asc",),
        )

    def _extended_page(
        self,
        capability: POSCapability,
        *,
        cursor: str | None,
        updated_since: datetime | None = None,
    ) -> ProviderPage:
        object_type = self._extended_object_types.get(capability.value)
        if object_type is None:
            from app.integrations.base.errors import POSCapabilityUnavailableError

            raise POSCapabilityUnavailableError(f"QuickResto {capability.value} object type is not configured")
        module_name, class_name = object_type
        offset = int(cursor or 0)
        filters = None
        if updated_since is not None:
            filters = ({"field": "updated", "operation": "gte", "value": self._format_datetime(updated_since)},)
        rows = self._client.list_objects(
            module_name=module_name,
            class_name=class_name,
            limit=self.page_size,
            offset=offset,
            filters=filters,
            sort_fields=("id",),
            sort_orders=("asc",),
        )
        # QuickResto list responses are summaries for several document types.
        # Persist the full document so recipes and inventory line items are not
        # silently dropped from the Raw Layer.
        rows = [
            self._client.read_object(
                module_name=module_name,
                class_name=class_name,
                object_id=int(row["id"]),
            )
            if int(row.get("id") or 0) > 0
            else row
            for row in rows
        ]
        records = tuple(
            self._record(row, fallback=f"{capability.value.lower()}:{offset + index}")
            for index, row in enumerate(rows)
        )
        return ProviderPage(
            records=records,
            next_cursor=str(offset + len(rows)) if len(rows) == self.page_size else None,
        )

    @staticmethod
    def _validate_extended_object_types(value: Any) -> dict[str, tuple[str, str]]:
        if not isinstance(value, Mapping):
            raise ValueError("QuickResto object_types must be a mapping")
        output: dict[str, tuple[str, str]] = {}
        allowed = {capability.value for capability in _EXTENDED_CAPABILITIES}
        for raw_capability, raw_spec in value.items():
            capability = str(raw_capability or "").strip().upper()
            if capability not in allowed or not isinstance(raw_spec, Mapping):
                raise ValueError("QuickResto object_types contains an unsupported capability")
            module_name = str(raw_spec.get("module_name") or "").strip()
            class_name = str(raw_spec.get("class_name") or "").strip()
            if not module_name or not class_name or len(module_name) > 255 or len(class_name) > 500:
                raise ValueError("QuickResto object type requires module_name and class_name")
            output[capability] = (module_name, class_name)
        return output

    def _nested_order_page(self, key: str, *, updated_since: datetime | None, cursor: str | None) -> ProviderPage:
        orders = self.get_orders(updated_since=updated_since, cursor=cursor)
        records = []
        for order in orders.records:
            for index, raw in enumerate(order.payload.get(key) or ()):
                if not isinstance(raw, Mapping):
                    continue
                payload = dict(raw)
                payload["orderId"] = order.external_id
                records.append(self._record(payload, fallback=f"{order.external_id}:{key}:{index}"))
        return ProviderPage(records=tuple(records), next_cursor=orders.next_cursor)

    @staticmethod
    def _record(payload: Mapping[str, Any], *, fallback: str) -> ProviderRecord:
        external_id = str(payload.get("frontId") or payload.get("_id") or payload.get("id") or fallback)
        updated = None
        for key in ("updated", "updatedAt", "closed", "localClosedTime"):
            raw = str(payload.get(key) or "").strip()
            if not raw:
                continue
            try:
                updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        return ProviderRecord(external_id=external_id, payload=payload, source_updated_at=updated)

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
