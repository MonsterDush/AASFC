from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class POSProviderCode(str, Enum):
    IIKO = "IIKO"
    QUICK_RESTO = "QUICK_RESTO"
    R_KEEPER = "R_KEEPER"
    PALOMA = "PALOMA"
    SYRVE = "SYRVE"
    OTHER = "OTHER"


_PROVIDER_ALIASES = {
    "QUICKRESTO": POSProviderCode.QUICK_RESTO,
    "QUICK_RESTO": POSProviderCode.QUICK_RESTO,
}


def normalize_provider_code(value: str | POSProviderCode) -> POSProviderCode:
    if isinstance(value, POSProviderCode):
        return value
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[normalized]
    try:
        return POSProviderCode(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported POS provider: {value}") from exc


class POSCapability(str, Enum):
    ORGANIZATIONS = "ORGANIZATIONS"
    VENUES = "VENUES"
    TERMINALS = "TERMINALS"
    SALES = "SALES"
    ORDER_ITEMS = "ORDER_ITEMS"
    ORDER_EVENTS = "ORDER_EVENTS"
    PAYMENTS = "PAYMENTS"
    DISCOUNTS = "DISCOUNTS"
    REFUNDS = "REFUNDS"
    GUEST_COUNT = "GUEST_COUNT"
    EMPLOYEES = "EMPLOYEES"
    EMPLOYEE_ATTENDANCE = "EMPLOYEE_ATTENDANCE"
    PRODUCTS = "PRODUCTS"
    PRODUCT_GROUPS = "PRODUCT_GROUPS"
    MODIFIERS = "MODIFIERS"
    RECIPES = "RECIPES"
    WAREHOUSES = "WAREHOUSES"
    STOCK_BALANCES = "STOCK_BALANCES"
    STOCK_MOVEMENTS = "STOCK_MOVEMENTS"
    SUPPLIERS = "SUPPLIERS"
    PURCHASES = "PURCHASES"
    WRITEOFFS = "WRITEOFFS"
    INVENTORY = "INVENTORY"


class POSCapabilityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class CapabilityAuditResult:
    capability: POSCapability
    status: POSCapabilityStatus
    checked_at: datetime
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("Capability audit timestamps must be timezone-aware")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    @property
    def available(self) -> bool:
        return self.status in {POSCapabilityStatus.AVAILABLE, POSCapabilityStatus.DEGRADED}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "details": dict(self.details),
        }


def serialize_capability_audit(
    results: Mapping[POSCapability, CapabilityAuditResult],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for capability, result in results.items():
        if capability != result.capability:
            raise ValueError("Capability audit key does not match its result")
        output[capability.value] = result.as_dict()
    return dict(sorted(output.items()))
