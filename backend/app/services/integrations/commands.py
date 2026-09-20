from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntegrationCommand
from app.services.integrations.credentials import encrypt_command_payload


FINAL_COMMAND_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
COMMAND_TRANSITIONS = {
    "PENDING": frozenset({"SUBMITTING", "CANCELLED"}),
    "SUBMITTING": frozenset({"ACCEPTED", "IN_PROGRESS", "SUCCEEDED", "FAILED", "UNKNOWN"}),
    "ACCEPTED": frozenset({"IN_PROGRESS", "SUCCEEDED", "FAILED", "UNKNOWN"}),
    "IN_PROGRESS": frozenset({"SUCCEEDED", "FAILED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"ACCEPTED", "IN_PROGRESS", "SUCCEEDED", "FAILED", "CANCELLED"}),
}


def create_command(
    db: Session,
    *,
    connection_id: int,
    venue_id: int,
    provider: str,
    command_type: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    target_external_id: str | None = None,
) -> tuple[IntegrationCommand, bool]:
    serialized = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    request_identity = json.dumps(
        {
            "provider": provider.strip().upper(),
            "command_type": command_type,
            "target_external_id": target_external_id,
            "payload": dict(payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    request_hash = hashlib.sha256(request_identity.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(IntegrationCommand).where(
            IntegrationCommand.connection_id == connection_id,
            IntegrationCommand.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("Command idempotency key was reused with a different payload")
        return existing, False

    command = IntegrationCommand(
        connection_id=connection_id,
        venue_id=venue_id,
        provider=provider.strip().upper(),
        command_type=command_type,
        target_external_id=target_external_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        encrypted_request=encrypt_command_payload(serialized),
    )
    db.add(command)
    db.flush()
    return command, True


def transition_command(
    command: IntegrationCommand,
    status: str,
    *,
    response: Mapping[str, Any] | None = None,
    external_command_id: str | None = None,
    provider_correlation_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    target = status.strip().upper()
    allowed = COMMAND_TRANSITIONS.get(command.status, frozenset())
    if target != command.status and target not in allowed:
        raise ValueError(f"Invalid command transition: {command.status} -> {target}")

    now = datetime.now(timezone.utc)
    command.status = target
    if target == "SUBMITTING":
        command.submitted_at = command.submitted_at or now
        command.attempts += 1
    if target in FINAL_COMMAND_STATUSES:
        command.completed_at = now
    if external_command_id is not None:
        command.external_command_id = external_command_id
    if provider_correlation_id is not None:
        command.provider_correlation_id = provider_correlation_id
    if response is not None:
        serialized = json.dumps(dict(response), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        command.encrypted_response = encrypt_command_payload(serialized)
    command.last_error_code = error_code
    command.last_error_message = error_message
