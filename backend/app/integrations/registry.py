from __future__ import annotations

from collections.abc import Callable

from .base.credentials import ProviderCredentials
from .base.provider import ProviderAdapter


ProviderFactory = Callable[[ProviderCredentials], ProviderAdapter]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    @staticmethod
    def normalize_provider_code(provider_code: str) -> str:
        normalized = str(provider_code or "").strip().upper()
        if not normalized:
            raise ValueError("Provider code is required")
        return normalized

    def register(self, provider_code: str, factory: ProviderFactory) -> None:
        normalized = self.normalize_provider_code(provider_code)
        if normalized in self._factories:
            raise ValueError(f"Provider is already registered: {normalized}")
        self._factories[normalized] = factory

    def build(self, provider_code: str, credentials: ProviderCredentials) -> ProviderAdapter:
        normalized = self.normalize_provider_code(provider_code)
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            raise LookupError(f"Provider is not registered: {normalized}") from exc
        adapter = factory(credentials)
        if self.normalize_provider_code(adapter.provider_code) != normalized:
            raise ValueError("Provider factory returned an adapter for a different provider")
        return adapter

    def registered_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


provider_registry = ProviderRegistry()
