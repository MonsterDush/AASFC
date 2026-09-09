"""Provider adapters are registered here during stage two."""
from app.integrations.providers.iiko import IikoPOSProvider
from app.integrations.providers.quick_resto import QuickRestoPOSProvider
from app.integrations.providers.register import register_p0_providers

__all__ = ["IikoPOSProvider", "QuickRestoPOSProvider", "register_p0_providers"]
