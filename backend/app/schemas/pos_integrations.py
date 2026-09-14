from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class POSIntegrationFeatureFlagsOut(BaseModel):
    shadow_write_enabled: bool
    canonical_read_enabled: bool
    provider_rollout_enabled: bool


class POSIntegrationConnectionOut(BaseModel):
    id: int
    venue_id: int
    provider: str
    status: str
    external_organization_id: str | None
    external_venue_id: str | None
    read_mode: str
    coverage_start: date | None
    coverage_end_exclusive: date | None
    last_sync_at: datetime | None
    last_successful_sync_at: datetime | None
    flags: POSIntegrationFeatureFlagsOut


class POSIntegrationCapabilityOut(BaseModel):
    capability: str
    state: str
    checked_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    evidence_summary: str | None
    freshness_seconds: int | None
