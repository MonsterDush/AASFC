from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Iterable, Mapping

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
from app.integrations.base.errors import POSCapabilityUnavailableError
from app.integrations.providers.iiko.client import IikoAuthenticationError, IikoClient, IikoConfig, IikoError
from app.models.integration_connection import IntegrationConnection


_EXTENDED_EXPORTS: dict[POSCapability, tuple[tuple[str, ...], str]] = {
    POSCapability.RECIPES: (("recipes", "items"), "recipe"),
    POSCapability.WAREHOUSES: (("warehouses", "stores", "items"), "warehouse"),
    POSCapability.STOCK_BALANCES: (("stockBalances", "balances", "items"), "stock-balance"),
    POSCapability.STOCK_MOVEMENTS: (("stockMovements", "movements", "items"), "stock-movement"),
    POSCapability.SUPPLIERS: (("suppliers", "items"), "supplier"),
    POSCapability.PURCHASES: (("purchases", "documents", "items"), "purchase"),
    POSCapability.WRITEOFFS: (("writeoffs", "documents", "items"), "writeoff"),
    POSCapability.INVENTORY: (("inventories", "documents", "items"), "inventory"),
    POSCapability.EMPLOYEE_ATTENDANCE: (("attendance", "sessions", "items"), "attendance"),
}


class IikoPOSProvider(POSProvider):
    provider_code = POSProviderCode.IIKO

    def __init__(
        self,
        connection: IntegrationConnection | Mapping[str, Any],
        *,
        client: IikoClient | None = None,
        page_size: int = 500,
    ) -> None:
        self.connection = connection
        self.page_size = max(1, min(int(page_size), 1000))
        self.credentials = self._credentials(connection)
        self.organization_id = str(
            self.credentials.get("organization_id")
            or getattr(connection, "external_organization_id", None)
            or ""
        ).strip()
        self._client = client or IikoClient(
            IikoConfig(
                api_login=str(self.credentials.get("api_login") or self.credentials.get("apiLogin") or ""),
                base_url=str(self.credentials.get("base_url") or "https://api-ru.iiko.services"),
                timeout_seconds=float(self.credentials.get("timeout_seconds") or 20),
                sales_endpoint=self.credentials.get("sales_endpoint"),
                employees_endpoint=self.credentials.get("employees_endpoint"),
                extended_endpoints=self.credentials.get("extended_endpoints") or {},
            )
        )

    @staticmethod
    def _credentials(connection: IntegrationConnection | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(connection, Mapping):
            if isinstance(connection.get("credentials"), Mapping):
                return dict(connection["credentials"])
            return dict(connection)
        if not connection.credentials_encrypted:
            raise POSAuthenticationError("iiko credentials are missing")
        return decrypt_credentials(connection.credentials_encrypted)

    def authenticate(self) -> None:
        try:
            self._client.authenticate()
        except IikoAuthenticationError as exc:
            raise POSAuthenticationError("iiko rejected the credentials") from exc

    def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        checked_at = datetime.now(timezone.utc)
        try:
            self.authenticate()
            return ProviderHealth(ok=True, checked_at=checked_at, latency_ms=int((time.monotonic() - started) * 1000))
        except (IikoError, POSAuthenticationError, ValueError) as exc:
            return ProviderHealth(
                ok=False,
                checked_at=checked_at,
                latency_ms=int((time.monotonic() - started) * 1000),
                message=type(exc).__name__,
            )

    def detect_capabilities(self):
        checked_at = datetime.now(timezone.utc)
        sales_capabilities = {
            POSCapability.SALES,
            POSCapability.ORDER_ITEMS,
            POSCapability.ORDER_EVENTS,
            POSCapability.PAYMENTS,
            POSCapability.DISCOUNTS,
            POSCapability.REFUNDS,
            POSCapability.GUEST_COUNT,
        }
        output = {
            capability: CapabilityAuditResult(
                capability=capability,
                status=POSCapabilityStatus.UNAVAILABLE,
                checked_at=checked_at,
                details={"adapter": "iiko-p0-v1", "reason": "not_supported_by_p0_adapter"},
            )
            for capability in POSCapability
        }

        def record(capabilities, *, available: bool, reason: str | None = None) -> None:
            for capability in capabilities:
                output[capability] = CapabilityAuditResult(
                    capability=capability,
                    status=POSCapabilityStatus.AVAILABLE if available else POSCapabilityStatus.UNAVAILABLE,
                    checked_at=checked_at,
                    details={"adapter": "iiko-p0-v1", **({"reason": reason} if reason else {})},
                )

        try:
            self.authenticate()
        except (IikoError, POSAuthenticationError, ValueError) as exc:
            record(tuple(POSCapability), available=False, reason=type(exc).__name__)
            return output

        organization_ids = [self.organization_id] if self.organization_id else []
        try:
            data = self._client.organizations()
            organizations = data.get("organizations") or ()
            if not organization_ids:
                organization_ids = [
                    str(row.get("id"))
                    for row in organizations
                    if isinstance(row, Mapping) and row.get("id")
                ]
            record((POSCapability.ORGANIZATIONS, POSCapability.VENUES), available=True)
        except (IikoError, ValueError, TypeError) as exc:
            record(
                (POSCapability.ORGANIZATIONS, POSCapability.VENUES),
                available=False,
                reason=type(exc).__name__,
            )

        if organization_ids:
            try:
                self._client.terminal_groups(organization_ids[:1])
                record((POSCapability.TERMINALS,), available=True)
            except (IikoError, ValueError, TypeError) as exc:
                record((POSCapability.TERMINALS,), available=False, reason=type(exc).__name__)
            try:
                self._client.nomenclature(organization_ids[0])
                record(
                    (POSCapability.PRODUCTS, POSCapability.PRODUCT_GROUPS, POSCapability.MODIFIERS),
                    available=True,
                )
            except (IikoError, ValueError, TypeError) as exc:
                record(
                    (POSCapability.PRODUCTS, POSCapability.PRODUCT_GROUPS, POSCapability.MODIFIERS),
                    available=False,
                    reason=type(exc).__name__,
                )
        else:
            record((POSCapability.TERMINALS,), available=False, reason="organization_not_resolved")
            record(
                (POSCapability.PRODUCTS, POSCapability.PRODUCT_GROUPS, POSCapability.MODIFIERS),
                available=False,
                reason="organization_not_resolved",
            )

        if self.credentials.get("sales_endpoint"):
            try:
                self._client.sales(self._page_body(cursor=None) | {"limit": 1})
                record(sales_capabilities, available=True)
            except (IikoError, ValueError, TypeError) as exc:
                record(sales_capabilities, available=False, reason=type(exc).__name__)
        else:
            record(sales_capabilities, available=False, reason="sales_endpoint_not_configured")

        if self.credentials.get("employees_endpoint"):
            try:
                self._client.employees(self._page_body(cursor=None) | {"limit": 1})
                record((POSCapability.EMPLOYEES,), available=True)
            except (IikoError, ValueError, TypeError) as exc:
                record((POSCapability.EMPLOYEES,), available=False, reason=type(exc).__name__)
        else:
            record((POSCapability.EMPLOYEES,), available=False, reason="employees_endpoint_not_configured")

        configured_extended = {
            str(key or "").strip().upper(): value
            for key, value in (self.credentials.get("extended_endpoints") or {}).items()
        }
        for capability in _EXTENDED_EXPORTS:
            if capability.value not in configured_extended:
                record((capability,), available=False, reason="endpoint_not_configured")
                continue
            try:
                self._client.extended_export(capability.value, self._page_body(cursor=None) | {"limit": 1})
                record((capability,), available=True)
            except (IikoError, ValueError, TypeError) as exc:
                record((capability,), available=False, reason=type(exc).__name__)

        return output

    def get_organizations(self, *, cursor: str | None = None) -> ProviderPage:
        if cursor:
            return ProviderPage()
        data = self._client.organizations()
        return ProviderPage(records=self._records(data.get("organizations") or (), prefix="organization"))

    def get_venues(self, *, cursor: str | None = None) -> ProviderPage:
        return self.get_organizations(cursor=cursor)

    def get_terminals(self, *, cursor: str | None = None) -> ProviderPage:
        if cursor:
            return ProviderPage()
        organization_ids = [self.organization_id] if self.organization_id else [
            row.external_id for row in self.get_organizations().records
        ]
        data = self._client.terminal_groups(organization_ids)
        rows = []
        for group in data.get("terminalGroups") or ():
            if not isinstance(group, Mapping):
                continue
            nested = group.get("items") if isinstance(group.get("items"), list) else (group,)
            rows.extend(item for item in nested if isinstance(item, Mapping))
        return ProviderPage(records=self._records(rows, prefix="terminal"))

    def get_employees(self, *, cursor: str | None = None) -> ProviderPage:
        if not self.credentials.get("employees_endpoint"):
            raise POSCapabilityUnavailableError("iiko employee export is unavailable for this connection")
        data = self._client.employees(self._page_body(cursor=cursor))
        return self._response_page(data, keys=("employees", "items"), prefix="employee")

    def get_products(self, *, cursor: str | None = None) -> ProviderPage:
        data = self._nomenclature(cursor)
        return ProviderPage(records=self._records(data.get("products") or (), prefix="product"))

    def get_product_groups(self, *, cursor: str | None = None) -> ProviderPage:
        data = self._nomenclature(cursor)
        return ProviderPage(records=self._records(data.get("groups") or (), prefix="group"))

    def get_orders(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        if not self.credentials.get("sales_endpoint"):
            raise POSCapabilityUnavailableError("iiko sales export is unavailable for this connection")
        body = self._page_body(cursor=cursor)
        if updated_since is not None:
            normalized = updated_since if updated_since.tzinfo is not None else updated_since.replace(tzinfo=timezone.utc)
            body["updatedSince"] = normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        data = self._client.sales(body)
        return self._response_page(data, keys=("orders", "items"), prefix="order")

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
        return self._extended_page(POSCapability.STOCK_MOVEMENTS, updated_since=updated_since, cursor=cursor)

    def get_suppliers(self, *, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.SUPPLIERS, cursor=cursor)

    def get_purchases(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.PURCHASES, updated_since=updated_since, cursor=cursor)

    def get_writeoffs(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.WRITEOFFS, updated_since=updated_since, cursor=cursor)

    def get_inventories(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.INVENTORY, updated_since=updated_since, cursor=cursor)

    def get_attendance(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._extended_page(POSCapability.EMPLOYEE_ATTENDANCE, updated_since=updated_since, cursor=cursor)

    def _extended_page(
        self,
        capability: POSCapability,
        *,
        cursor: str | None,
        updated_since: datetime | None = None,
    ) -> ProviderPage:
        if capability not in _EXTENDED_EXPORTS:
            raise POSCapabilityUnavailableError(f"iiko {capability.value} export is unavailable")
        body = self._page_body(cursor=cursor)
        if updated_since is not None:
            normalized = updated_since if updated_since.tzinfo is not None else updated_since.replace(tzinfo=timezone.utc)
            body["updatedSince"] = normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        data = self._client.extended_export(capability.value, body)
        keys, prefix = _EXTENDED_EXPORTS[capability]
        return self._response_page(data, keys=keys, prefix=prefix)

    def _nomenclature(self, cursor: str | None) -> dict[str, Any]:
        if cursor:
            return {}
        organization_id = self.organization_id
        if not organization_id:
            organizations = self.get_organizations().records
            if len(organizations) != 1:
                raise IikoError("iiko organization_id is required when multiple organizations are available")
            organization_id = organizations[0].external_id
        return self._client.nomenclature(organization_id)

    def _page_body(self, *, cursor: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"limit": self.page_size}
        if self.organization_id:
            body["organizationIds"] = [self.organization_id]
        if cursor:
            body["cursor"] = cursor
        return body

    def _response_page(self, data: Mapping[str, Any], *, keys: tuple[str, ...], prefix: str) -> ProviderPage:
        rows: Iterable[Any] = ()
        for key in keys:
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        cursor = str(data.get("nextCursor") or data.get("cursor") or "").strip() or None
        return ProviderPage(records=self._records(rows, prefix=prefix), next_cursor=cursor)

    def _nested_order_page(self, key: str, *, updated_since: datetime | None, cursor: str | None) -> ProviderPage:
        page = self.get_orders(updated_since=updated_since, cursor=cursor)
        records = []
        for order in page.records:
            for index, raw in enumerate(order.payload.get(key) or ()):
                if not isinstance(raw, Mapping):
                    continue
                payload = dict(raw)
                payload["orderId"] = order.external_id
                records.append(self._record(payload, fallback=f"{order.external_id}:{key}:{index}"))
        return ProviderPage(records=tuple(records), next_cursor=page.next_cursor)

    def _records(self, values: Iterable[Any], *, prefix: str) -> tuple[ProviderRecord, ...]:
        return tuple(
            self._record(row, fallback=f"{prefix}:{index}")
            for index, row in enumerate(values)
            if isinstance(row, Mapping)
        )

    @staticmethod
    def _record(payload: Mapping[str, Any], *, fallback: str) -> ProviderRecord:
        external_id = str(payload.get("id") or payload.get("externalId") or fallback)
        updated = None
        for key in ("updatedAt", "whenUpdated", "whenClosed", "createdAt"):
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
