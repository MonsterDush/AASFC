"""Provider-neutral POS integration layer.

Business modules must consume ACDM projections, never provider clients or raw
payloads. Stage 1 intentionally exposes no operational provider wiring.
"""

from .registry import ProviderRegistry, provider_registry

__all__ = ["ProviderRegistry", "provider_registry"]
from .quality import DataQualityIssue, assess_capability_freshness, validate_and_quarantine, validate_canonical_dto

__all__ = [
    "DataQualityIssue",
    "assess_capability_freshness",
    "validate_and_quarantine",
    "validate_canonical_dto",
]
