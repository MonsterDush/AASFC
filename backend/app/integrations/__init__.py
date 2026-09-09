"""Provider-neutral POS integration contracts.

The legacy QuickResto report flow remains the default while stage two mirrors
its source payloads into the canonical model behind venue-level switches.
"""

from app.integrations.reconciliation import (
    CanonicalReadSwitchError,
    SourceReconciliationMetrics,
    enable_canonical_reads,
    reconcile_connection,
    rollback_to_legacy_reads,
)

__all__ = [
    "CanonicalReadSwitchError",
    "SourceReconciliationMetrics",
    "enable_canonical_reads",
    "reconcile_connection",
    "rollback_to_legacy_reads",
]
