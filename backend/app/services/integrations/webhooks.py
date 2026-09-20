from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntegrationWebhookEvent
from app.services.integrations.credentials import encrypt_event_payload


def _serialize(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def store_webhook_event(
    db: Session,
    *,
    connection_id: int,
    provider: str,
    event_type: str,
    payload: Mapping[str, Any],
    external_event_id: str | None = None,
    occurred_at: datetime | None = None,
    received_at: datetime | None = None,
    fallback_bucket_seconds: int = 300,
) -> tuple[IntegrationWebhookEvent, bool]:
    if fallback_bucket_seconds <= 0:
        raise ValueError("Webhook fallback bucket must be positive")
    serialized = _serialize(payload)
    payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    received = received_at or datetime.now(timezone.utc)
    identity = external_event_id or f"{payload_hash}:{int(received.timestamp()) // fallback_bucket_seconds}"
    deduplication_key = hashlib.sha256(f"{provider}:{event_type}:{identity}".encode()).hexdigest()

    existing = db.scalar(
        select(IntegrationWebhookEvent).where(
            IntegrationWebhookEvent.connection_id == connection_id,
            IntegrationWebhookEvent.deduplication_key == deduplication_key,
        )
    )
    if existing is not None:
        return existing, False

    event = IntegrationWebhookEvent(
        connection_id=connection_id,
        provider=provider.strip().upper(),
        event_type=event_type,
        external_event_id=external_event_id,
        deduplication_key=deduplication_key,
        payload_hash=payload_hash,
        payload_encrypted=encrypt_event_payload(serialized),
        occurred_at=occurred_at,
        received_at=received,
    )
    db.add(event)
    db.flush()
    return event, True
