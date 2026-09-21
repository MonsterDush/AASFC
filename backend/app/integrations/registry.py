from __future__ import annotations

from collections.abc import Callable

from .base.credentials import ProviderCredentials
from .base.provider import ProviderAdapter, ProviderAdapters, ProviderOperationalAdapter


ProviderFactory = Callable[[ProviderCredentials], ProviderAdapter | ProviderAdapters]


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

    def _build_product(
        self, provider_code: str, credentials: ProviderCredentials
    ) -> tuple[str, ProviderAdapter | ProviderAdapters]:
        normalized = self.normalize_provider_code(provider_code)
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            raise LookupError(f"Provider is not registered: {normalized}") from exc
        return normalized, factory(credentials)

    def build(self, provider_code: str, credentials: ProviderCredentials) -> ProviderAdapter:
        normalized, product = self._build_product(provider_code, credentials)
        if isinstance(product, ProviderAdapters):
            raise TypeError("Focused provider bundle has no legacy composite; use build_adapters()")
        if self.normalize_provider_code(product.provider_code) != normalized:
            raise ValueError("Provider factory returned an adapter for a different provider")
        return product

    def build_adapters(self, provider_code: str, credentials: ProviderCredentials) -> ProviderAdapters:
        """Build focused contracts while keeping legacy adapters fully usable."""

        normalized, product = self._build_product(provider_code, credentials)
        bundle = (
            product
            if isinstance(product, ProviderAdapters)
            else ProviderAdapters(
                discovery=product,
                reader=product,
                operational=product if isinstance(product, ProviderOperationalAdapter) else None,
            )
        )
        adapters = (
            bundle.discovery,
            bundle.reader,
            bundle.operational,
            bundle.commands,
            bundle.webhooks,
            bundle.loyalty,
        )
        if any(
            adapter is not None and self.normalize_provider_code(adapter.provider_code) != normalized
            for adapter in adapters
        ):
            raise ValueError("Provider factory returned an adapter for a different provider")
        return bundle

    def registered_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


provider_registry = ProviderRegistry()
