from __future__ import annotations

import base64
import hashlib

from app.core.config import settings


class IntegrationCredentialError(RuntimeError):
    """Raised when stored integration credentials cannot be encrypted or decrypted."""


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise IntegrationCredentialError("Integration credential encryption is unavailable") from exc

    configured = str(settings.INTEGRATION_ENCRYPTION_KEY or settings.JWT_SECRET or "")
    if len(configured.encode("utf-8")) < 32:
        raise IntegrationCredentialError("Integration encryption key material is too short")
    digest = hashlib.sha256(b"axelio:integration-credentials:v1\x00" + configured.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credential(value: str) -> str:
    plaintext = str(value or "")
    if not plaintext:
        raise IntegrationCredentialError("Integration credential cannot be empty")
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"v1:{token}"


def decrypt_credential(value: str) -> str:
    stored = str(value or "")
    if not stored.startswith("v1:"):
        raise IntegrationCredentialError("Integration credential has an unsupported format")
    try:
        plaintext = _fernet().decrypt(stored[3:].encode("ascii"))
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise IntegrationCredentialError("Integration credential could not be decrypted") from exc
