from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Capability(str, Enum):
    SALES = "SALES"
    BUSINESS_SHIFTS = "BUSINESS_SHIFTS"
    ORDERS = "ORDERS"
    ORDER_ITEMS = "ORDER_ITEMS"
    ORDER_EVENTS = "ORDER_EVENTS"
    PAYMENTS = "PAYMENTS"
    RETURNS = "RETURNS"
    DISCOUNTS = "DISCOUNTS"
    GUEST_COUNT = "GUEST_COUNT"

    EMPLOYEES = "EMPLOYEES"
    EMPLOYEE_ATTENDANCE = "EMPLOYEE_ATTENDANCE"
    EMPLOYEE_ROLES = "EMPLOYEE_ROLES"

    PRODUCTS = "PRODUCTS"
    PRODUCT_GROUPS = "PRODUCT_GROUPS"
    PRODUCT_PRICES = "PRODUCT_PRICES"
    MODIFIERS = "MODIFIERS"
    RECIPES = "RECIPES"

    WAREHOUSES = "WAREHOUSES"
    STOCK_BALANCES = "STOCK_BALANCES"
    STOCK_MOVEMENTS = "STOCK_MOVEMENTS"
    SUPPLIERS = "SUPPLIERS"
    PURCHASES = "PURCHASES"
    WRITEOFFS = "WRITEOFFS"
    INVENTORY = "INVENTORY"

    EXTERNAL_VENUES = "EXTERNAL_VENUES"
    SALE_PLACES = "SALE_PLACES"
    TERMINALS = "TERMINALS"
    STORES = "STORES"

    PAGINATION = "PAGINATION"
    SERVER_TIME_FILTER = "SERVER_TIME_FILTER"
    SORTING = "SORTING"
    SOURCE_VERSION = "SOURCE_VERSION"
    UPDATED_SINCE = "UPDATED_SINCE"


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CapabilityProbe:
    capability: Capability
    state: CapabilityState
    checked_at: datetime
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    evidence_summary: str | None = None

    def __post_init__(self) -> None:
        if self.state is CapabilityState.SUPPORTED and not self.evidence_summary:
            raise ValueError("SUPPORTED capability requires probe evidence")
