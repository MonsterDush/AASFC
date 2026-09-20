"""Canonical ACDM persistence namespace."""

from .report_projector import ReportProjector, ShadowProjectionCandidate, ShadowProjectionResult

__all__ = ["ReportProjector", "ShadowProjectionCandidate", "ShadowProjectionResult"]
from .composite_payloads import (
    CanonicalCompositeLine,
    normalize_iiko_composite,
    normalize_quickresto_composite,
)

__all__ = [
    "CanonicalCompositeLine",
    "normalize_iiko_composite",
    "normalize_quickresto_composite",
]
