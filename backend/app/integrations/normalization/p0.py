from __future__ import annotations

from typing import Protocol, Sequence

from app.integrations.base import ProviderRecord
from app.integrations.canonical import (
    CanonicalEmployee,
    CanonicalOrder,
    CanonicalProduct,
    CanonicalProductGroup,
    CanonicalTerminal,
    CanonicalVenue,
)
from app.integrations.normalization.contracts import NormalizationContext


class P0Normalizer(Protocol):
    def normalize_venues(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalVenue]: ...

    def normalize_terminals(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalTerminal]: ...

    def normalize_employees(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalEmployee]: ...

    def normalize_product_groups(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalProductGroup]: ...

    def normalize_products(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalProduct]: ...

    def normalize_orders(
        self, record: ProviderRecord, *, context: NormalizationContext
    ) -> Sequence[CanonicalOrder]: ...
