from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class POSIntegrationFeatureFlags:
    shadow_write_enabled: bool
    canonical_read_enabled: bool
    provider_rollout_enabled: bool


def _provider_rollout_codes() -> set[str]:
    raw = str(settings.POS_INTEGRATION_PROVIDER_ROLLOUT or "")
    return {item.strip().upper() for item in raw.replace(";", ",").replace("\n", ",").split(",") if item.strip()}


def feature_flags_for(provider_code: str | None = None) -> POSIntegrationFeatureFlags:
    provider = str(provider_code or "").strip().upper()
    rollout = _provider_rollout_codes()
    provider_enabled = bool(provider and (provider in rollout or "*" in rollout))
    return POSIntegrationFeatureFlags(
        shadow_write_enabled=bool(settings.POS_INTEGRATION_SHADOW_WRITE_ENABLED and provider_enabled),
        canonical_read_enabled=bool(settings.POS_INTEGRATION_CANONICAL_READ_ENABLED and provider_enabled),
        provider_rollout_enabled=provider_enabled,
    )
