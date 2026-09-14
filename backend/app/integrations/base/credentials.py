from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.services.integrations.credentials import decrypt_credential, encrypt_credential


@dataclass(frozen=True, slots=True)
class ProviderCredentials:
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        normalized = {str(key): str(value) for key, value in self.values.items() if str(value)}
        if not normalized:
            raise ValueError("Provider credentials cannot be empty")
        object.__setattr__(self, "values", MappingProxyType(normalized))

    def require(self, key: str) -> str:
        value = self.values.get(key)
        if not value:
            raise KeyError(f"Required provider credential is missing: {key}")
        return value


__all__ = ["ProviderCredentials", "decrypt_credential", "encrypt_credential"]
