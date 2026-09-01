from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.venue_pos_integration_selection import VenuePOSIntegrationSelection


class POSProviderSelectionError(ValueError):
    """Raised when a venue already uses another active POS provider."""


def normalize_pos_provider(value: str) -> str:
    provider = str(value or "").strip().upper()
    if not provider or len(provider) > 32:
        raise ValueError("Unsupported POS integration provider")
    return provider


def active_pos_provider(db: Session, *, venue_id: int) -> str | None:
    value = db.execute(
        select(VenuePOSIntegrationSelection.provider).where(VenuePOSIntegrationSelection.venue_id == int(venue_id))
    ).scalar_one_or_none()
    return str(value).upper() if value else None


def acquire_pos_provider(
    db: Session,
    *,
    venue_id: int,
    provider: str,
) -> VenuePOSIntegrationSelection:
    normalized = normalize_pos_provider(provider)
    selection = db.execute(
        select(VenuePOSIntegrationSelection)
        .where(VenuePOSIntegrationSelection.venue_id == int(venue_id))
        .with_for_update()
    ).scalar_one_or_none()
    if selection is not None and str(selection.provider).upper() != normalized:
        raise POSProviderSelectionError(
            "Для заведения уже активна другая POS-интеграция. Сначала отключите её, затем подключите новую."
        )
    if selection is None:
        selection = VenuePOSIntegrationSelection(
            venue_id=int(venue_id),
            provider=normalized,
            selected_at=datetime.now(timezone.utc),
        )
        db.add(selection)
    else:
        selection.updated_at = datetime.now(timezone.utc)
    db.flush()
    return selection


def release_pos_provider(db: Session, *, venue_id: int, provider: str) -> bool:
    normalized = normalize_pos_provider(provider)
    result = db.execute(
        delete(VenuePOSIntegrationSelection).where(
            VenuePOSIntegrationSelection.venue_id == int(venue_id),
            VenuePOSIntegrationSelection.provider == normalized,
        )
    )
    return bool(result.rowcount)
