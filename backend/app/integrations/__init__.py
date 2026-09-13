"""Provider-neutral POS integration layer.

Business modules must consume ACDM projections, never provider clients or raw
payloads. Stage 1 intentionally exposes no operational provider wiring.
"""

from .registry import ProviderRegistry, provider_registry

__all__ = ["ProviderRegistry", "provider_registry"]
