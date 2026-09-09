from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

from app.integrations.base import POSProviderCode, ProviderRecord


@dataclass(frozen=True)
class NormalizationContext:
    integration_connection_id: int
    venue_id: int
    provider: POSProviderCode
    normalization_version: str
    timezone: str = "Europe/Moscow"
    business_day_cutoff_hour: int = 0

    def __post_init__(self) -> None:
        if self.integration_connection_id <= 0:
            raise ValueError("Integration connection id must be positive")
        if self.venue_id <= 0:
            raise ValueError("Venue id must be positive")
        if not str(self.normalization_version or "").strip():
            raise ValueError("Normalization version is required")
        if not str(self.timezone or "").strip():
            raise ValueError("Normalization timezone is required")
        if not 0 <= int(self.business_day_cutoff_hour) <= 23:
            raise ValueError("Business day cutoff hour must be between 0 and 23")


class POSNormalizer(ABC):
    """Transforms provider DTOs into canonical model objects without persistence."""

    entity_type: str

    @abstractmethod
    def normalize(
        self,
        record: ProviderRecord,
        *,
        context: NormalizationContext,
    ) -> Sequence[Any]:
        """Return canonical objects; transaction handling belongs to the sync service."""
