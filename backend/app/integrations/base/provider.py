from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

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
    external_venues: tuple[ProviderRecord, ...] = ()
    sale_places: tuple[ProviderRecord, ...] = ()
    terminals: tuple[ProviderRecord, ...] = ()
    stores: tuple[ProviderRecord, ...] = ()


class ProviderAdapter(Protocol):
    provider_code: str

    def health_check(self) -> ProviderHealth: ...

    def get_capabilities(self) -> Mapping[Capability, CapabilityProbe]: ...

    def get_limits(self) -> ProviderLimits: ...

    def discover_scope(self) -> ProviderScope: ...

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

    def iter_inventory(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]: ...
