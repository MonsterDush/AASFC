from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration_raw_object import IntegrationRawObject


class RawObjectStorageError(ValueError):
    """Raised when a provider payload cannot be stored losslessly as JSON."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_payload_json(payload: dict[str, Any] | list[Any]) -> tuple[dict[str, Any] | list[Any], str]:
    if not isinstance(payload, (dict, list)):
        raise RawObjectStorageError("Integration raw payload must be a JSON object or array")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        canonical = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RawObjectStorageError("Integration raw payload is not valid lossless JSON") from exc
    return canonical, hashlib.sha256(encoded).hexdigest()


def store_raw_object(
    db: Session,
    *,
    integration_connection_id: int,
    entity_type: str,
    external_id: str,
    payload: dict[str, Any] | list[Any],
    source_updated_at: datetime | None = None,
    received_at: datetime | None = None,
) -> tuple[IntegrationRawObject, bool]:
    connection_id = int(integration_connection_id)
    normalized_type = str(entity_type or "").strip().upper()
    normalized_external_id = str(external_id or "").strip()
    if connection_id <= 0:
        raise RawObjectStorageError("Integration connection id must be positive")
    if not normalized_type or len(normalized_type) > 64:
        raise RawObjectStorageError("Integration raw entity_type is invalid")
    if not normalized_external_id or len(normalized_external_id) > 255:
        raise RawObjectStorageError("Integration raw external_id is invalid")
    if source_updated_at is not None and (source_updated_at.tzinfo is None or source_updated_at.utcoffset() is None):
        raise RawObjectStorageError("Integration raw source_updated_at must be timezone-aware")
    observed_at = received_at or _utcnow()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise RawObjectStorageError("Integration raw received_at must be timezone-aware")

    canonical, payload_hash = canonical_payload_json(payload)
    row = db.execute(
        select(IntegrationRawObject).where(
            IntegrationRawObject.integration_connection_id == connection_id,
            IntegrationRawObject.entity_type == normalized_type,
            IntegrationRawObject.external_id == normalized_external_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationRawObject(
            integration_connection_id=connection_id,
            entity_type=normalized_type,
            external_id=normalized_external_id,
            payload_json=canonical,
            payload_hash=payload_hash,
            source_updated_at=source_updated_at,
            received_at=observed_at,
        )
        db.add(row)
        db.flush()
        return row, True

    changed = row.payload_hash != payload_hash
    row.received_at = observed_at
    if changed:
        row.payload_json = canonical
        row.payload_hash = payload_hash
        row.source_updated_at = source_updated_at
        row.normalized_at = None
        row.normalization_version = None
    elif source_updated_at is not None:
        row.source_updated_at = source_updated_at
    db.flush()
    return row, changed


def mark_raw_object_normalized(
    row: IntegrationRawObject,
    *,
    normalization_version: str,
    normalized_at: datetime | None = None,
) -> None:
    version = str(normalization_version or "").strip()
    if not version or len(version) > 64:
        raise RawObjectStorageError("Normalization version is invalid")
    completed_at = normalized_at or _utcnow()
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise RawObjectStorageError("Integration raw normalized_at must be timezone-aware")
    row.normalization_version = version
    row.normalized_at = completed_at
