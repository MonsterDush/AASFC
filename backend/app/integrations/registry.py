from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.integrations.base.capabilities import POSProviderCode, normalize_provider_code
from app.integrations.base.errors import POSProviderNotRegisteredError, POSProviderRegistrationError
from app.integrations.base.provider import POSProvider


ProviderFactory = Callable[[Any], POSProvider]


class POSProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[POSProviderCode, ProviderFactory] = {}

    def register(
        self,
        provider: str | POSProviderCode,
        factory: ProviderFactory,
        *,
        replace: bool = False,
    ) -> None:
        code = normalize_provider_code(provider)
        if code in self._factories and not replace:
            raise POSProviderRegistrationError(f"POS provider {code.value} is already registered")
        self._factories[code] = factory

    def create(self, provider: str | POSProviderCode, connection: Any) -> POSProvider:
        code = normalize_provider_code(provider)
        factory = self._factories.get(code)
        if factory is None:
            raise POSProviderNotRegisteredError(f"POS provider {code.value} is not registered")
        adapter = factory(connection)
        if adapter.provider_code != code:
            raise POSProviderRegistrationError(
                f"POS provider factory for {code.value} returned {adapter.provider_code.value}"
            )
        return adapter

    def registered_codes(self) -> tuple[POSProviderCode, ...]:
        return tuple(sorted(self._factories, key=lambda item: item.value))


provider_registry = POSProviderRegistry()
