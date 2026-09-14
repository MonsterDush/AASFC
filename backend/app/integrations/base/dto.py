from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    external_id: str
    payload: Mapping[str, Any]
    source_version: str | None = None
    source_updated_at: datetime | None = None
    cursor_token: str | None = None

    def __post_init__(self) -> None:
        external_id = str(self.external_id or "").strip()
        if not external_id:
            raise ValueError("ProviderRecord.external_id is required")
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.source_updated_at is not None and self.source_updated_at.tzinfo is None:
            raise ValueError("ProviderRecord.source_updated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CanonicalDTO:
    entity_type: str
    external_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    source_version: str | None = None
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not str(self.entity_type or "").strip():
            raise ValueError("CanonicalDTO.entity_type is required")
        if not str(self.external_id or "").strip():
            raise ValueError("CanonicalDTO.external_id is required")
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
