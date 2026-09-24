from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from .capabilities import Capability, CapabilityProbe
from .dto import ProviderRecord


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    healthy: bool
    checked_at: datetime
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderLimits:
    max_page_size: int | None = None
    max_pages: int | None = None
    max_range_days: int | None = None
    rate_limit_per_minute: int | None = None
    timeout_seconds: float | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderScope:
    organizations: tuple[ProviderRecord, ...] = ()
    external_venues: tuple[ProviderRecord, ...] = ()
    terminal_groups: tuple[ProviderRecord, ...] = ()
    sale_places: tuple[ProviderRecord, ...] = ()
    terminals: tuple[ProviderRecord, ...] = ()
    stores: tuple[ProviderRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    command_type: str
    idempotency_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderCommandResult:
    external_command_id: str | None
    status: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderWebhookEvent:
    event_type: str
    external_event_id: str | None
    occurred_at: datetime | None
    payload: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProviderDiscoveryAdapter(Protocol):
    provider_code: str

    def health_check(self) -> ProviderHealth: ...

    def verify_credentials(self) -> ProviderHealth: ...

    def get_capabilities(self) -> Mapping[Capability, CapabilityProbe]: ...

    def get_limits(self) -> ProviderLimits: ...

    def discover_scope(self) -> ProviderScope: ...


@runtime_checkable
class ProviderReadAdapter(Protocol):
    provider_code: str

    def iter_business_shifts(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...

    def iter_orders(
        self,
        *,
        business_shift_ids: Iterable[str],
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]: ...

    def iter_payment_types(self) -> Iterable[ProviderRecord]: ...

    def iter_products(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_product_groups(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_employees(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_recipes(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_warehouses(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_stock_balances(self, *, at: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_stock_movements(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...

    def iter_suppliers(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_purchases(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...

    def iter_writeoffs(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...

    def iter_inventory(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...

    def iter_attendance(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...


@runtime_checkable
class ProviderOperationalAdapter(Protocol):
    provider_code: str

    def get_current_business_shift(self, *, external_venue_id: str) -> ProviderRecord | None: ...

    def iter_open_orders(self, *, external_venue_id: str) -> Iterable[ProviderRecord]: ...

    def get_open_order(self, *, external_venue_id: str, external_order_id: str) -> ProviderRecord | None: ...

    def iter_tables(self, *, external_venue_id: str) -> Iterable[ProviderRecord]: ...

    def iter_restaurant_sections(self, *, external_venue_id: str) -> Iterable[ProviderRecord]: ...


@runtime_checkable
class ProviderCommandAdapter(Protocol):
    provider_code: str

    def submit_command(self, command: ProviderCommand) -> ProviderCommandResult: ...

    def get_command_status(self, *, external_command_id: str) -> ProviderCommandResult: ...


@runtime_checkable
class ProviderWebhookAdapter(Protocol):
    provider_code: str

    def verify_event(self, *, headers: Mapping[str, str], body: bytes) -> bool: ...

    def event_identity(self, *, headers: Mapping[str, str], body: bytes) -> str | None: ...

    def parse_event(self, *, headers: Mapping[str, str], body: bytes) -> ProviderWebhookEvent: ...


@runtime_checkable
class ProviderLoyaltyAdapter(Protocol):
    provider_code: str

    def iter_loyalty_programs(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_loyalty_accounts(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_customers(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_wallets(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def iter_coupons(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]: ...

    def calculate_loyalty(self, payload: Mapping[str, Any]) -> ProviderRecord: ...


class ProviderAdapter(ProviderDiscoveryAdapter, ProviderReadAdapter, Protocol):
    """Backward-compatible historical adapter contract.

    Providers may migrate to focused contracts independently. Existing adapters
    remain valid discovery/read adapters without gaining write permissions.
    """


@dataclass(frozen=True, slots=True)
class ProviderAdapters:
    discovery: ProviderDiscoveryAdapter
    reader: ProviderReadAdapter | None = None
    operational: ProviderOperationalAdapter | None = None
    commands: ProviderCommandAdapter | None = None
    webhooks: ProviderWebhookAdapter | None = None
    loyalty: ProviderLoyaltyAdapter | None = None
