from __future__ import annotations

from app.integrations.base import POSProviderCode
from app.integrations.providers.iiko import IikoPOSProvider
from app.integrations.providers.quick_resto import QuickRestoPOSProvider
from app.integrations.registry import POSProviderRegistry, provider_registry


def register_p0_providers(registry: POSProviderRegistry = provider_registry) -> POSProviderRegistry:
    registered = set(registry.registered_codes())
    if POSProviderCode.QUICK_RESTO not in registered:
        registry.register(POSProviderCode.QUICK_RESTO, QuickRestoPOSProvider)
    if POSProviderCode.IIKO not in registered:
        registry.register(POSProviderCode.IIKO, IikoPOSProvider)
    return registry
