from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Mapping

from app.integrations.base.capabilities import CapabilityAuditResult, POSCapability, POSProviderCode
from app.integrations.base.dto import ProviderHealth, ProviderPage
from app.integrations.base.errors import POSCapabilityUnavailableError


class POSProvider(ABC):
    """Provider boundary: fetch DTOs only, never calculate Axelio business metrics."""

    provider_code: POSProviderCode

    @abstractmethod
    def authenticate(self) -> None:
        """Validate credentials without mutating canonical data."""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Return the current connection health."""

    @abstractmethod
    def detect_capabilities(self) -> Mapping[POSCapability, CapabilityAuditResult]:
        """Audit capabilities using the active connection rather than provider marketing claims."""

    def get_organizations(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.ORGANIZATIONS)

    def get_venues(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.VENUES)

    def get_terminals(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.TERMINALS)

    def get_employees(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.EMPLOYEES)

    def get_orders(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.SALES)

    def get_products(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.PRODUCTS)

    def get_product_groups(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.PRODUCT_GROUPS)

    def get_recipes(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.RECIPES)

    def get_payments(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.PAYMENTS)

    def get_warehouses(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.WAREHOUSES)

    def get_stock_balances(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.STOCK_BALANCES)

    def get_stock_movements(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.STOCK_MOVEMENTS)

    def get_suppliers(self, *, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.SUPPLIERS)

    def get_purchases(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.PURCHASES)

    def get_writeoffs(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.WRITEOFFS)

    def get_inventories(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.INVENTORY)

    def get_attendance(self, *, updated_since: datetime | None = None, cursor: str | None = None) -> ProviderPage:
        return self._unavailable(POSCapability.EMPLOYEE_ATTENDANCE)

    @staticmethod
    def _unavailable(capability: POSCapability) -> ProviderPage:
        raise POSCapabilityUnavailableError(f"POS capability {capability.value} is unavailable")
