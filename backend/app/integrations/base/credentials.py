from __future__ import annotations

import json
from typing import Any, Mapping

from app.services.integrations.credentials import (
    IntegrationCredentialError,
    decrypt_credential,
    encrypt_credential,
)


def encrypt_credentials(credentials: Mapping[str, Any]) -> str:
    """Serialize and encrypt a provider credential bundle as one opaque value."""

    if not isinstance(credentials, Mapping) or not credentials:
        raise IntegrationCredentialError("Integration credentials must be a non-empty object")
    try:
        payload = json.dumps(
            dict(credentials),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise IntegrationCredentialError("Integration credentials must be valid JSON") from exc
    return encrypt_credential(payload)


def decrypt_credentials(value: str) -> dict[str, Any]:
    """Decrypt a credential bundle and reject legacy plaintext or non-object data."""

    try:
        payload = json.loads(decrypt_credential(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrationCredentialError("Integration credentials contain invalid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise IntegrationCredentialError("Integration credentials must contain a non-empty object")
    return payload
