from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ProviderRecord:
    """One provider-specific DTO before normalization into ACDM."""

    external_id: str
    payload: Mapping[str, Any]
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        external_id = str(self.external_id or "").strip()
        if not external_id:
            raise ValueError("Provider record external_id is required")
        if self.source_updated_at is not None and (
            self.source_updated_at.tzinfo is None or self.source_updated_at.utcoffset() is None
        ):
            raise ValueError("Provider record source_updated_at must be timezone-aware")
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class ProviderPage:
    records: Sequence[ProviderRecord] = field(default_factory=tuple)
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        cursor = str(self.next_cursor or "").strip() or None
        object.__setattr__(self, "next_cursor", cursor)


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    checked_at: datetime
    latency_ms: int | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("Provider health timestamps must be timezone-aware")
        if self.latency_ms is not None and int(self.latency_ms) < 0:
            raise ValueError("Provider health latency cannot be negative")
