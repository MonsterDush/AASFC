from __future__ import annotations

from typing import Protocol

from app.integrations.base.dto import CanonicalDTO, ProviderRecord


class Normalizer(Protocol):
    provider_code: str
    normalization_version: str

    def normalize(self, *, entity_type: str, record: ProviderRecord) -> CanonicalDTO: ...
