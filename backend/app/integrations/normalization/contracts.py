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

    def __post_init__(self) -> None:
        if self.integration_connection_id <= 0:
            raise ValueError("Integration connection id must be positive")
        if self.venue_id <= 0:
            raise ValueError("Venue id must be positive")
        if not str(self.normalization_version or "").strip():
            raise ValueError("Normalization version is required")


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
