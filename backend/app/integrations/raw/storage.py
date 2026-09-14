from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base.dto import ProviderRecord
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_common import utc_now
from app.services.integrations.credentials import (
    decrypt_raw_integration_payload,
    encrypt_raw_integration_payload,
)


ReplayResult = TypeVar("ReplayResult")


def _allowlisted_payload(payload: Mapping[str, Any], allowed_fields: Collection[str]) -> dict[str, Any]:
    allowlist = {str(field) for field in allowed_fields if str(field)}
    if not allowlist:
        raise ValueError("Raw payload allowlist cannot be empty")
    filtered = {str(key): value for key, value in payload.items() if str(key) in allowlist}
    _reject_secret_fields(filtered)
    return filtered


def _reject_secret_fields(value: Any, *, path: str = "payload") -> None:
    forbidden = {"authorization", "password", "token", "secret", "api_key", "apikey", "api-key"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in forbidden:
                raise ValueError(f"Raw payload contains a forbidden secret field at {path}.{key}")
            _reject_secret_fields(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secret_fields(child, path=f"{path}[{index}]")


def _serialize_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def record_raw_object(
    db: Session,
    *,
    connection_id: int,
    entity_type: str,
    record: ProviderRecord,
    allowed_fields: Collection[str],
    import_run_id: int | None = None,
    expires_at: datetime | None = None,
) -> IntegrationRawObject:
    """Persist encrypted provider input before normalization.

    This method owns its transaction boundary deliberately: returning means the
    raw object is durable, so a subsequent normalization failure can be replayed
    without another provider call.
    """

    normalized_entity_type = str(entity_type or "").strip().upper()
    if not normalized_entity_type:
        raise ValueError("Raw entity_type is required")
    payload = _allowlisted_payload(record.payload, allowed_fields)
    serialized = _serialize_payload(payload)
    payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    row = db.execute(
        select(IntegrationRawObject).where(
            IntegrationRawObject.integration_connection_id == int(connection_id),
            IntegrationRawObject.entity_type == normalized_entity_type,
            IntegrationRawObject.external_id == record.external_id,
            IntegrationRawObject.source_version == record.source_version,
            IntegrationRawObject.payload_hash == payload_hash,
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationRawObject(
            integration_connection_id=int(connection_id),
            entity_type=normalized_entity_type,
            external_id=record.external_id,
            source_version=record.source_version,
            payload_hash=payload_hash,
            encrypted_payload=encrypt_raw_integration_payload(serialized),
            source_updated_at=record.source_updated_at,
            import_run_id=import_run_id,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row.received_at = utc_now()
        row.import_run_id = import_run_id
        row.expires_at = expires_at
    db.commit()
    db.refresh(row)
    return row


def load_raw_payload(raw_object: IntegrationRawObject) -> dict[str, Any]:
    serialized = decrypt_raw_integration_payload(raw_object.encrypted_payload)
    payload = json.loads(serialized)
    if not isinstance(payload, dict):
        raise ValueError("Stored raw payload must be a JSON object")
    digest = hashlib.sha256(_serialize_payload(payload).encode("utf-8")).hexdigest()
    if digest != raw_object.payload_hash:
        raise ValueError("Stored raw payload hash mismatch")
    return payload


def replay_raw_object(
    raw_object: IntegrationRawObject,
    *,
    normalizer: Callable[[ProviderRecord], ReplayResult],
) -> ReplayResult:
    source_updated_at = raw_object.source_updated_at
    if source_updated_at is not None and source_updated_at.tzinfo is None:
        # SQLite fixtures lose the timezone marker; production stores UTC in a
        # timezone-aware column. Reconstruct that invariant before normalizing.
        source_updated_at = source_updated_at.replace(tzinfo=timezone.utc)
    record = ProviderRecord(
        external_id=raw_object.external_id,
        payload=load_raw_payload(raw_object),
        source_version=raw_object.source_version,
        source_updated_at=source_updated_at,
    )
    return normalizer(record)
